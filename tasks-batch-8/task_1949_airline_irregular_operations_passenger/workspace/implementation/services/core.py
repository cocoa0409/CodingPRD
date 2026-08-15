"""Core shared services: common-field management, cost ledger, communications,
priority scoring, refund/credit computation, crew legality, event counters."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id, now, iso


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------

def stamp_new(row):
    ts = now()
    row["id"] = new_id()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    return row


def stamp_new_ledger(row):
    ts = now()
    row["id"] = new_id()
    row["created_at"] = ts
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] += 1


def round_half_up_cents(value):
    """Round a Decimal/numeric to integer cents, ROUND_HALF_UP."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Cost ledger (PRD §2.9)
# ---------------------------------------------------------------------------

def post_cost_entry(event_id, source_type, source_id, entry_kind, amount_cents, note=""):
    """Append a CostEntry. Zero-amount entries are not posted at all."""
    if amount_cents == 0:
        return None
    entry = stamp_new_ledger({
        "disruption_event_id": event_id,
        "source_type": source_type,
        "source_id": source_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "note": note,
    })
    db.cost_entries[entry["id"]] = entry
    recompute_event_cost_totals(event_id)
    return entry


def recompute_event_cost_totals(event_id):
    """accrual = sum(ACCRUAL) + sum(REVERSAL); settled = sum(SETTLEMENT).
    Reversals in this system always target accruals."""
    event = db.disruption_events.get(event_id)
    if event is None:
        return
    accrual = 0
    settled = 0
    for ce in db.cost_entries.values():
        if ce["disruption_event_id"] != event_id:
            continue
        if ce["entry_kind"] == "ACCRUAL":
            accrual += ce["amount_cents"]
        elif ce["entry_kind"] == "SETTLEMENT":
            settled += ce["amount_cents"]
        elif ce["entry_kind"] == "REVERSAL":
            accrual += ce["amount_cents"]
    event["accrual_total_cents"] = accrual
    event["settled_total_cents"] = settled
    event["updated_at"] = now()


def voucher_face_outstanding(event_id):
    total = 0
    for v in db.vouchers.values():
        if v["disruption_event_id"] == event_id and v["voucher_status"] == "ISSUED":
            total += v["face_value_cents"]
    return total


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------

def queue_comm(booking_id, event_id, template, channel="EMAIL", due_at=None):
    row = stamp_new_ledger({
        "booking_id": booking_id,
        "disruption_event_id": event_id,
        "template": template,
        "channel": channel,
        "due_at": due_at if due_at is not None else now(),
        "sent_at": None,
        "log_status": "QUEUED",
    })
    db.communication_logs[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Booking helpers
# ---------------------------------------------------------------------------

def booking_segments(booking_id):
    segs = [s for s in db.booking_segments.values() if s["booking_id"] == booking_id]
    segs.sort(key=lambda s: (s["created_at"], s["seq_no"]))
    return segs


def original_segments(booking_id):
    """Original segments are those created at booking time (no reaccommodation_case_id)."""
    segs = [s for s in db.booking_segments.values()
            if s["booking_id"] == booking_id and s["reaccommodation_case_id"] is None]
    segs.sort(key=lambda s: s["seq_no"])
    return segs


def itinerary_distance_km(booking_id):
    total = 0
    for seg in original_segments(booking_id):
        f = db.flights.get(seg["flight_id"])
        if f is not None:
            total += f["distance_km"]
    return total


def compensation_base_cents(booking_id):
    dist = itinerary_distance_km(booking_id)
    if dist <= 1500:
        return 25000
    if dist <= 3500:
        return 40000
    return 60000


def recompute_refund_credit(booking):
    """refund = fare - sum(round_half_up(fare * seg.distance / total_distance) for FLOWN
    original segments). credit = round_half_up(refund * 110/100)."""
    segs = original_segments(booking["id"])
    total_dist = 0
    for seg in segs:
        f = db.flights.get(seg["flight_id"])
        if f is not None:
            total_dist += f["distance_km"]
    flown_alloc = 0
    if total_dist > 0:
        for seg in segs:
            if seg["segment_status"] != "FLOWN":
                continue
            f = db.flights.get(seg["flight_id"])
            if f is None:
                continue
            alloc = (Decimal(booking["fare_cents"]) * Decimal(f["distance_km"])
                     / Decimal(total_dist)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            flown_alloc += int(alloc)
    booking["refund_amount_cents"] = booking["fare_cents"] - flown_alloc
    credit = (Decimal(booking["refund_amount_cents"]) * Decimal(110)
              / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    booking["credit_amount_cents"] = int(credit)
    booking["updated_at"] = now()


# ---------------------------------------------------------------------------
# Priority score (calculation reaccommodation_priority_score)
# ---------------------------------------------------------------------------

TIER_WEIGHT = {"NONE": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 4}
CABIN_WEIGHT = {"ECONOMY": 1, "PREMIUM": 2, "BUSINESS": 3, "FIRST": 4}
SSR_BONUS = {"UMNR": 300, "WCHR": 200, "PETC": 50}
SSR_CAP = 400
GROUP_PENALTY_PER_EXTRA = 50
GROUP_PENALTY_MAX_EXTRA = 4


def compute_priority_score(booking, passenger, disrupted_segment):
    score = 1000 * TIER_WEIGHT.get(passenger["loyalty_tier"], 0)
    score += 10 * CABIN_WEIGHT.get(booking["cabin"], 0)
    # urgency: minutes from case creation (now) to the disrupted segment's
    # originally scheduled departure (the flight's live sched_dep_utc at this moment)
    flight = db.flights.get(disrupted_segment["flight_id"]) if disrupted_segment else None
    if flight is not None:
        delta = flight["sched_dep_utc"] - now()
        minutes = int(delta.total_seconds() // 60)
    else:
        minutes = 10 ** 9
    if minutes < 120:
        score += 500
    elif minutes < 360:
        score += 250
    ssr_total = 0
    for code in passenger["special_service_codes"]:
        ssr_total += SSR_BONUS.get(code, 0)
    score += min(SSR_CAP, ssr_total)
    extra = min(booking["party_size"] - 1, GROUP_PENALTY_MAX_EXTRA)
    if extra < 0:
        extra = 0
    score -= GROUP_PENALTY_PER_EXTRA * extra
    return score


# ---------------------------------------------------------------------------
# Reaccommodation case creation (shared by cancel/misconnect cascades)
# ---------------------------------------------------------------------------

OPEN_CASE_STATES = {"QUEUED", "OFFERED", "ESCALATED"}


def booking_has_open_case(booking_id):
    for c in db.reaccommodation_cases.values():
        if c["booking_id"] == booking_id and c["case_status"] in OPEN_CASE_STATES:
            return True
    return False


def create_case_for_booking(booking, event_id, disrupted_segment):
    if booking_has_open_case(booking["id"]):
        return None
    passenger = db.passengers.get(booking["passenger_id"])
    score = compute_priority_score(booking, passenger, disrupted_segment)
    case = stamp_new({
        "booking_id": booking["id"],
        "disruption_event_id": event_id,
        "priority_score": score,
        "case_status": "QUEUED",
        "queued_at": now(),
        "committed_option_id": None,
    })
    db.reaccommodation_cases[case["id"]] = case
    return case


# ---------------------------------------------------------------------------
# Crew legality (calculation crew_legality_eval)
# ---------------------------------------------------------------------------

MAX_DUTY_HOURS = 14
POST_FLIGHT_BUFFER_MINUTES = 30
MIN_CONNECT_MINUTES = 45


def assignment_covers_flight(assignment, flight):
    if flight["sched_dep_utc"] is None or flight["sched_arr_utc"] is None:
        return True
    return (assignment["duty_start_utc"] <= flight["sched_dep_utc"]
            and flight["sched_arr_utc"] + timedelta(minutes=POST_FLIGHT_BUFFER_MINUTES)
            <= assignment["duty_end_utc"])


def recompute_crew_coverage(flight):
    """CREW_OK iff each of CAPTAIN, FIRST_OFFICER has >=1 non-RELEASED LEGAL assignment."""
    ok = True
    for role in ("CAPTAIN", "FIRST_OFFICER"):
        found = False
        for a in db.crew_assignments.values():
            if (a["flight_id"] == flight["id"] and a["crew_role"] == role
                    and a["assignment_status"] != "RELEASED"
                    and a["legality_status"] == "LEGAL"):
                found = True
                break
        if not found:
            ok = False
            break
    flight["crew_coverage_status"] = "CREW_OK" if ok else "CREW_SHORT"
    flight["updated_at"] = now()


def crew_legality_reeval(flight):
    """On retime: assignments whose duty window no longer covers
    [sched_dep, sched_arr + 30min] become FLAGGED_ILLEGAL; coverage recomputed."""
    for a in db.crew_assignments.values():
        if a["flight_id"] != flight["id"]:
            continue
        if a["assignment_status"] == "RELEASED":
            continue
        legal = assignment_covers_flight(a, flight)
        new_status = "LEGAL" if legal else "FLAGGED_ILLEGAL"
        if a["legality_status"] != new_status:
            a["legality_status"] = new_status
            a["updated_at"] = now()
            a["version"] += 1
    recompute_crew_coverage(flight)


# ---------------------------------------------------------------------------
# Event affected counters
# ---------------------------------------------------------------------------

def recompute_event_affected(event_id):
    event = db.disruption_events.get(event_id)
    if event is None:
        return
    count = 0
    pax = 0
    for b in db.bookings.values():
        if b["booking_status"] != "DISRUPTED":
            continue
        for seg in db.booking_segments.values():
            if seg["booking_id"] != b["id"]:
                continue
            f = db.flights.get(seg["flight_id"])
            if f is not None and f["disruption_event_id"] == event_id:
                count += 1
                pax += b["party_size"]
                break
    event["affected_booking_count"] = count
    event["affected_passenger_count"] = pax
    event["updated_at"] = now()


# ---------------------------------------------------------------------------
# Booking completion rollup
# ---------------------------------------------------------------------------

def booking_completion_rollup(booking):
    """A booking whose every segment is in {FLOWN, CANCELLED, REBOOKED} with at
    least one FLOWN and none DISRUPTED becomes COMPLETED."""
    if booking["booking_status"] in ("CANCELLED", "COMPLETED"):
        return
    segs = booking_segments(booking["id"])
    if not segs:
        return
    statuses = {s["segment_status"] for s in segs}
    if "DISRUPTED" in statuses or "CONFIRMED" in statuses:
        return
    if "FLOWN" not in statuses:
        return
    booking["booking_status"] = "COMPLETED"
    touch(booking)
