"""Domain logic: derived fields, cascades, allocation, rollup, serializers.

Consistency is immediate (PRD 2.9): derived values are recomputed as part of
the same operation, and every resource a recomputation touches has its
updated_at refreshed and version incremented.
"""
from datetime import timedelta
from decimal import Decimal

from http_util import ApiError
from state import (
    CLASS_CY,
    DB,
    EST_TONS,
    GRADE_A_THRESHOLD,
    GRADE_B_THRESHOLD,
    MIN_CLAIM_CY,
    NO_SHOW_LIMIT,
    PARTICIPANT_RESERVE_PCT,
    POSTURE_TICKET_THRESHOLD,
    STRIKE_THRESHOLD,
    YIELD_CY_PER_TON,
    YIELD_VARIANCE_THRESHOLD,
    clock_now,
    dec,
    fmt_dt,
    new_id,
    next_seq,
    num_out,
    r2,
    r3,
    r4,
    wall_now,
)


def get_or_404(collection, rid):
    e = DB[collection].get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist: %s" % rid)
    return e


def touch(entity):
    """Derived-field recomputation / mutation marker (PRD 2.5/2.9)."""
    entity["version"] += 1
    entity["updated_at"] = wall_now()


def common_new(entity):
    """Stamp system-managed common fields on a newly created entity."""
    now = wall_now()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def append_only_new(entity):
    """IntakeEvent / NotificationLog: only id and created_at (PRD 2.5)."""
    entity["created_at"] = wall_now()
    entity["_seq"] = next_seq()
    return entity


def notify(program_id, kind, household_id=None, zone_id=None, message=""):
    n = {
        "id": new_id(),
        "program_id": program_id,
        "kind": kind,
        "household_id": household_id,
        "zone_id": zone_id,
        "message": message,
    }
    append_only_new(n)
    DB["notifications"][n["id"]] = n
    return n


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def open_ticket_count(program_id):
    return sum(
        1 for t in DB["tickets"].values() if t["program_id"] == program_id and t["status"] == "OPEN"
    )


def program_posture(program_id):
    return "RESTRICTED" if open_ticket_count(program_id) >= POSTURE_TICKET_THRESHOLD else "NORMAL"


def participant_pool(program):
    return r2(PARTICIPANT_RESERVE_PCT * program["mulch_produced_cy"])


def tier_remaining(program, tier):
    produced = program["mulch_produced_cy"]
    ppool = participant_pool(program)
    if tier == "PARTICIPANT":
        return ppool - program["mulch_allocated_participant_cy"]
    return produced - ppool - program["mulch_allocated_general_cy"]


def booking_zone(booking):
    return DB["zones"].get(booking["zone_id"])


def booking_program(booking):
    z = booking_zone(booking)
    return DB["programs"].get(z["program_id"]) if z else None


def zone_reserved_trees(zone_id):
    return sum(
        b["tree_count"]
        for b in DB["bookings"].values()
        if b["zone_id"] == zone_id and b["status"] == "CONFIRMED"
    )


def _booking_est_tons(b):
    return dec(b["tree_count"]) * EST_TONS[b["size_class"]]


def zone_projected_tons_provisional(zone_id):
    total = Decimal("0")
    for b in DB["bookings"].values():
        if b["zone_id"] == zone_id and b["status"] == "CONFIRMED":
            total += _booking_est_tons(b)
    return r3(total)


def zone_collected_tons_actual(zone_id):
    total = Decimal("0")
    for b in DB["bookings"].values():
        if b["zone_id"] == zone_id and b["status"] == "SERVICED":
            total += b["actual_tons"] if b["actual_tons"] is not None else _booking_est_tons(b)
    return r3(total)


def site_stockpile_cy(site_id):
    total = Decimal("0")
    for e in DB["intake_events"].values():
        if e["site_id"] == site_id and e["status"] == "RECORDED":
            total += e["net_volume_cy"]
    for run in DB["runs"].values():
        if run["site_id"] == site_id and run["status"] == "COMPLETED":
            total -= run["input_cy"]
    return r2(total)


def derive_tier(household):
    """PARTICIPANT if the household has >=1 SERVICED booking in the program."""
    for b in DB["bookings"].values():
        if b["household_id"] == household["id"] and b["status"] == "SERVICED":
            return "PARTICIPANT"
    return "GENERAL"


def allocation_key(tier):
    return "mulch_allocated_participant_cy" if tier == "PARTICIPANT" else "mulch_allocated_general_cy"


def try_allocate(program, event, tier, requested_cy):
    """mulch_claim_allocation: tier -> remaining -> min(...) -> threshold."""
    remaining = tier_remaining(program, tier)
    allocated = min(requested_cy, event["per_household_cap_cy"], remaining)
    if allocated >= MIN_CLAIM_CY:
        return allocated, "CONFIRMED"
    return Decimal("0"), "WAITLISTED"


def recompute_strikes(household):
    """strike_count = tickets linked to the household's bookings in
    UPHELD/UPHELD_FINAL; curbside_eligible = strike_count < 2."""
    count = 0
    for t in DB["tickets"].values():
        if t["booking_id"] and t["status"] in ("UPHELD", "UPHELD_FINAL"):
            b = DB["bookings"].get(t["booking_id"])
            if b and b["household_id"] == household["id"]:
                count += 1
    household["strike_count"] = count
    household["curbside_eligible"] = count < STRIKE_THRESHOLD


def promotion_sweep(program):
    """mulch_waitlist_promotion: WAITLISTED claims on the program's OPEN
    events, ascending created_at; no head-of-line blocking. Returns True if
    any claim was promoted."""
    pid = program["id"]
    candidates = []
    for c in DB["claims"].values():
        if c["status"] != "WAITLISTED":
            continue
        ev = DB["events"].get(c["event_id"])
        if ev and ev["program_id"] == pid and ev["status"] == "OPEN":
            candidates.append(c)
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    promoted = False
    for c in candidates:
        ev = DB["events"][c["event_id"]]
        household = DB["households"][c["household_id"]]
        tier = derive_tier(household)
        allocated, status = try_allocate(program, ev, tier, c["requested_cy"])
        if status == "CONFIRMED":
            c["tier"] = tier
            c["allocated_cy"] = allocated
            c["status"] = "CONFIRMED"
            touch(c)
            program[allocation_key(tier)] += allocated
            promoted = True
            notify(
                pid,
                "CLAIM_PROMOTED",
                household_id=c["household_id"],
                message="Mulch claim %s promoted from the waitlist with allocation %s cy."
                % (c["id"], allocated),
            )
    return promoted


def release_claim_allocation(program, claim):
    program[allocation_key(claim["tier"])] -= claim["allocated_cy"]


# ---------------------------------------------------------------------------
# Contamination adjudication cascades (PRD 3.4)
# ---------------------------------------------------------------------------
def adjudicate_upheld(ticket, adjudicator_id):
    program = DB["programs"][ticket["program_id"]]
    ticket["status"] = "UPHELD"
    ticket["adjudicated_by"] = adjudicator_id
    ticket["adjudicated_at"] = clock_now()
    ticket["appeal_deadline"] = clock_now() + timedelta(hours=72)
    touch(ticket)
    touch(program)  # open_ticket_count decremented; posture recomputed
    if not ticket["booking_id"]:
        return
    booking = DB["bookings"][ticket["booking_id"]]
    touched_zones = set()
    if booking["status"] == "CONFIRMED":
        booking["status"] = "REJECTED_CONTAMINATED"
        touch(booking)
        touched_zones.add(booking["zone_id"])  # route capacity released
    household = DB["households"][booking["household_id"]]
    was_eligible = household["curbside_eligible"]
    recompute_strikes(household)
    touch(household)
    if was_eligible and not household["curbside_eligible"]:
        # Bar cascade: every other CONFIRMED booking of the household is
        # auto-cancelled, with one notification per cancelled booking.
        for b in list(DB["bookings"].values()):
            if b["household_id"] == household["id"] and b["status"] == "CONFIRMED":
                b["status"] = "CANCELLED"
                touch(b)
                touched_zones.add(b["zone_id"])  # capacity released
                notify(
                    ticket["program_id"],
                    "BOOKING_AUTO_CANCELLED",
                    household_id=household["id"],
                    zone_id=b["zone_id"],
                    message="Booking %s was automatically cancelled: the household is barred "
                    "from curbside service." % b["id"],
                )
    for zid in touched_zones:
        touch(DB["zones"][zid])


def resolve_overturned(ticket, resolver_id):
    ticket["status"] = "OVERTURNED"
    ticket["resolved_by"] = resolver_id
    touch(ticket)
    if not ticket["booking_id"]:
        return
    booking = DB["bookings"][ticket["booking_id"]]
    household = DB["households"][booking["household_id"]]
    # Compensation: strike revoked, eligibility recomputed. Auto-cancelled
    # bookings are NOT resurrected.
    recompute_strikes(household)
    touch(household)
    if booking["status"] == "REJECTED_CONTAMINATED":
        zone = DB["zones"][booking["zone_id"]]
        booking["status"] = "CONFIRMED"
        # Capacity re-reserved unconditionally (documented exception);
        # service_date set to the zone's current collection_date.
        booking["service_date"] = zone["collection_date"]
        touch(booking)
        touch(zone)


# ---------------------------------------------------------------------------
# Volunteer reliability (PRD 3.7)
# ---------------------------------------------------------------------------
def mark_no_show(shift):
    shift["status"] = "NO_SHOW"
    touch(shift)
    volunteer = DB["volunteers"][shift["volunteer_id"]]
    volunteer["no_show_count"] += 1
    if volunteer["no_show_count"] == NO_SHOW_LIMIT and volunteer["status"] == "APPROVED":
        volunteer["status"] = "SUSPENDED"
        now = clock_now()
        for s in DB["shifts"].values():
            if (
                s["volunteer_id"] == volunteer["id"]
                and s["status"] == "SIGNED_UP"
                and s["start_at"] > now
            ):
                s["status"] = "CANCELLED"
                touch(s)
    touch(volunteer)


def close_site_cascade(site):
    """-> CLOSING: SITE_CLOSING notification; future SIGNED_UP shifts cancel."""
    site["status"] = "CLOSING"
    touch(site)
    notify(
        site["program_id"],
        "SITE_CLOSING",
        message="Drop-off site %s is closing." % site["name"],
    )
    now = clock_now()
    for s in DB["shifts"].values():
        if s["site_id"] == site["id"] and s["status"] == "SIGNED_UP" and s["start_at"] > now:
            s["status"] = "CANCELLED"
            touch(s)


def expire_event_claims(event):
    """Event closure: CONFIRMED/WAITLISTED claims -> EXPIRED; confirmed
    allocations released. Returns True if any allocation was released."""
    program = DB["programs"][event["program_id"]]
    released = False
    for c in DB["claims"].values():
        if c["event_id"] == event["id"] and c["status"] in ("CONFIRMED", "WAITLISTED"):
            if c["status"] == "CONFIRMED":
                release_claim_allocation(program, c)
                released = True
            c["status"] = "EXPIRED"
            touch(c)
    return released


# ---------------------------------------------------------------------------
# Operational checkpoint (PRD 3.8): five reconciliations + posture recompute
# ---------------------------------------------------------------------------
def ops_run(program):
    now = clock_now()
    pid = program["id"]
    # 1. CONFIRMED bookings whose service_date has passed -> MISSED
    touched_zones = set()
    for b in list(DB["bookings"].values()):
        z = DB["zones"].get(b["zone_id"])
        if z is None or z["program_id"] != pid:
            continue
        if b["status"] == "CONFIRMED" and b["service_date"] < now:
            b["status"] = "MISSED"  # reserved capacity released (derived)
            touch(b)
            touched_zones.add(b["zone_id"])
    for zid in touched_zones:
        touch(DB["zones"][zid])
    # 2. SIGNED_UP shifts whose end_at has passed -> NO_SHOW (auto-suspend at 3)
    for s in list(DB["shifts"].values()):
        site = DB["sites"].get(s["site_id"])
        if site is None or site["program_id"] != pid:
            continue
        if s["status"] == "SIGNED_UP" and s["end_at"] < now:
            mark_no_show(s)
    # 3. OPEN sites whose close_date has passed -> CLOSING
    for site in list(DB["sites"].values()):
        if site["program_id"] == pid and site["status"] == "OPEN" and site["close_date"] < now:
            close_site_cascade(site)
    # 4. OPEN events whose pickup_end has passed -> CLOSED; claims expire
    pool_changed = False
    for ev in list(DB["events"].values()):
        if ev["program_id"] == pid and ev["status"] == "OPEN" and ev["pickup_end"] < now:
            ev["status"] = "CLOSED"
            touch(ev)
            if expire_event_claims(ev):
                pool_changed = True
    if promotion_sweep(program):
        pool_changed = True
    # 5. posture recomputed (derived on read; nothing to store)
    touch(program)  # the checkpoint always increments the program version
    return pool_changed


# ---------------------------------------------------------------------------
# Diversion rollup (PRD 3.8): per-source rounding first, then sum
# ---------------------------------------------------------------------------
def diversion_rollup(program):
    pid = program["id"]
    collected = Decimal("0")
    for b in DB["bookings"].values():
        z = DB["zones"].get(b["zone_id"])
        if z is None or z["program_id"] != pid or b["status"] != "SERVICED":
            continue
        contrib = b["actual_tons"] if b["actual_tons"] is not None else _booking_est_tons(b)
        collected += r3(contrib)
    for e in DB["intake_events"].values():
        site = DB["sites"].get(e["site_id"])
        if site is None or site["program_id"] != pid or e["status"] != "RECORDED":
            continue
        collected += r3(e["report_tons"])
    diverted = Decimal("0")
    for run in DB["runs"].values():
        if run["program_id"] == pid and run["status"] == "COMPLETED":
            diverted += r3(run["measured_input_tons"] - run["contaminated_input_tons"])
    disposed = collected - diverted
    if collected == 0:
        rate = Decimal("0.0000")
        grade = "NO_DATA"
    else:
        rate = r4(diverted / collected)
        if rate >= GRADE_A_THRESHOLD:
            grade = "A"
        elif rate >= GRADE_B_THRESHOLD:
            grade = "B"
        else:
            grade = "C"
    below_target = rate < program["target_diversion_rate"]
    return {
        "collected_tons": collected,
        "diverted_tons": diverted,
        "disposed_tons": disposed,
        "diversion_rate": rate,
        "grade": grade,
        "below_target": below_target,
    }


# ---------------------------------------------------------------------------
# Chipping yield (PRD 3.5)
# ---------------------------------------------------------------------------
def compute_yield(material_class, measured_input_tons, contaminated_input_tons, measured_output_cy):
    fraction = contaminated_input_tons / measured_input_tons
    theoretical = r2(measured_input_tons * YIELD_CY_PER_TON[material_class] * (1 - fraction))
    if theoretical > 0:
        raw_variance = abs(measured_output_cy - theoretical) / theoretical
        variance_pct = r4(raw_variance)
    else:
        raw_variance = Decimal("0") if measured_output_cy == 0 else Decimal("1")
        variance_pct = r4(raw_variance)
    return theoretical, raw_variance, variance_pct


# ---------------------------------------------------------------------------
# Serializers (strip internal keys; Decimal -> number; datetime -> ISO)
# ---------------------------------------------------------------------------
def program_json(p):
    otc = open_ticket_count(p["id"])
    produced = p["mulch_produced_cy"]
    ppool = participant_pool(p)
    return {
        "id": p["id"],
        "name": p["name"],
        "season_label": p["season_label"],
        "window_start": fmt_dt(p["window_start"]),
        "window_end": fmt_dt(p["window_end"]),
        "target_diversion_rate": num_out(p["target_diversion_rate"]),
        "status": p["status"],
        "posture": "RESTRICTED" if otc >= POSTURE_TICKET_THRESHOLD else "NORMAL",
        "open_ticket_count": otc,
        "mulch_produced_cy": num_out(produced),
        "mulch_allocated_participant_cy": num_out(p["mulch_allocated_participant_cy"]),
        "mulch_allocated_general_cy": num_out(p["mulch_allocated_general_cy"]),
        "participant_remaining_cy": num_out(ppool - p["mulch_allocated_participant_cy"]),
        "general_remaining_cy": num_out(produced - ppool - p["mulch_allocated_general_cy"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def site_json(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "name": s["name"],
        "address": s["address"],
        "capacity_cy": num_out(s["capacity_cy"]),
        "open_date": fmt_dt(s["open_date"]),
        "close_date": fmt_dt(s["close_date"]),
        "volunteer_slots_per_role": s["volunteer_slots_per_role"],
        "status": s["status"],
        "stockpile_cy": num_out(site_stockpile_cy(s["id"])),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def zone_json(z):
    reserved = zone_reserved_trees(z["id"])
    return {
        "id": z["id"],
        "program_id": z["program_id"],
        "zone_code": z["zone_code"],
        "collection_date": fmt_dt(z["collection_date"]),
        "daily_tree_capacity": z["daily_tree_capacity"],
        "status": z["status"],
        "reserved_trees": reserved,
        "remaining_capacity": z["daily_tree_capacity"] - reserved,
        "projected_tons_provisional": num_out(zone_projected_tons_provisional(z["id"])),
        "collected_tons_actual": num_out(zone_collected_tons_actual(z["id"])),
        "created_at": fmt_dt(z["created_at"]),
        "updated_at": fmt_dt(z["updated_at"]),
        "version": z["version"],
    }


def household_json(h):
    return {
        "id": h["id"],
        "program_id": h["program_id"],
        "zone_id": h["zone_id"],
        "address": h["address"],
        "contact_email": h["contact_email"],
        "strike_count": h["strike_count"],
        "curbside_eligible": h["curbside_eligible"],
        "created_at": fmt_dt(h["created_at"]),
        "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def booking_json(b):
    return {
        "id": b["id"],
        "household_id": b["household_id"],
        "zone_id": b["zone_id"],
        "tree_count": b["tree_count"],
        "size_class": b["size_class"],
        "prep_attestation": b["prep_attestation"],
        "status": b["status"],
        "service_date": fmt_dt(b["service_date"]),
        "actual_tons": num_out(b["actual_tons"]),
        "estimated_tons": num_out(b["estimated_tons"]),
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def intake_json(e):
    return {
        "id": e["id"],
        "site_id": e["site_id"],
        "source_type": e["source_type"],
        "tree_count": e["tree_count"],
        "size_class": e["size_class"],
        "contaminated_cy": num_out(e["contaminated_cy"]),
        "gross_volume_cy": num_out(e["gross_volume_cy"]),
        "net_volume_cy": num_out(e["net_volume_cy"]),
        "weighed_tons": num_out(e["weighed_tons"]),
        "estimated_tons": num_out(e["estimated_tons"]),
        "report_tons": num_out(e["report_tons"]),
        "recorded_at": fmt_dt(e["recorded_at"]),
        "status": e["status"],
        "void_reason": e["void_reason"],
        "created_at": fmt_dt(e["created_at"]),
    }


def ticket_json(t):
    return {
        "id": t["id"],
        "program_id": t["program_id"],
        "booking_id": t["booking_id"],
        "site_id": t["site_id"],
        "category": t["category"],
        "notes": t["notes"],
        "reporter_user_id": t["reporter_user_id"],
        "reporter_role": t["reporter_role"],
        "status": t["status"],
        "adjudicated_by": t["adjudicated_by"],
        "adjudicated_at": fmt_dt(t["adjudicated_at"]),
        "appeal_deadline": fmt_dt(t["appeal_deadline"]),
        "resolved_by": t["resolved_by"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def run_json(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "site_id": r["site_id"],
        "scheduled_start": fmt_dt(r["scheduled_start"]),
        "scheduled_end": fmt_dt(r["scheduled_end"]),
        "material_class": r["material_class"],
        "status": r["status"],
        "input_cy": num_out(r["input_cy"]),
        "measured_input_tons": num_out(r["measured_input_tons"]),
        "contaminated_input_tons": num_out(r["contaminated_input_tons"]),
        "theoretical_output_cy": num_out(r["theoretical_output_cy"]),
        "measured_output_cy": num_out(r["measured_output_cy"]),
        "variance_pct": num_out(r["variance_pct"]),
        "yield_review_confirmed": r["yield_review_confirmed"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "program_id": e["program_id"],
        "name": e["name"],
        "claim_open_at": fmt_dt(e["claim_open_at"]),
        "claim_close_at": fmt_dt(e["claim_close_at"]),
        "pickup_start": fmt_dt(e["pickup_start"]),
        "pickup_end": fmt_dt(e["pickup_end"]),
        "per_household_cap_cy": num_out(e["per_household_cap_cy"]),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def claim_json(c):
    return {
        "id": c["id"],
        "event_id": c["event_id"],
        "household_id": c["household_id"],
        "requested_cy": num_out(c["requested_cy"]),
        "tier": c["tier"],
        "allocated_cy": num_out(c["allocated_cy"]),
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def volunteer_json(v):
    return {
        "id": v["id"],
        "program_id": v["program_id"],
        "full_name": v["full_name"],
        "email": v["email"],
        "status": v["status"],
        "no_show_count": v["no_show_count"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def shift_json(s):
    return {
        "id": s["id"],
        "volunteer_id": s["volunteer_id"],
        "site_id": s["site_id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "shift_role": s["shift_role"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def notification_json(n):
    return {
        "id": n["id"],
        "program_id": n["program_id"],
        "kind": n["kind"],
        "household_id": n["household_id"],
        "zone_id": n["zone_id"],
        "message": n["message"],
        "created_at": fmt_dt(n["created_at"]),
    }


def report_json(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "status": r["status"],
        "collected_tons": num_out(r["collected_tons"]),
        "diverted_tons": num_out(r["diverted_tons"]),
        "disposed_tons": num_out(r["disposed_tons"]),
        "diversion_rate": num_out(r["diversion_rate"]),
        "grade": r["grade"],
        "below_target": r["below_target"],
        "published_at": fmt_dt(r["published_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def sorted_asc(items):
    """Default list ordering: created_at ascending (PRD 2.3)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def sorted_desc(items):
    """Notification log ordering: newest first (PRD 2.3 exception)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]), reverse=True)
