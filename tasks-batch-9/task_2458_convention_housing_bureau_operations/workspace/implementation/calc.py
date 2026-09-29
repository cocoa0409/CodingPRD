"""Derived values, pinned calculations and cascade helpers (PRD §2.6, §2.11, §3)."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import (
    STORE,
    clock_iso,
    date_shift,
    days_between,
    parse_iso_date,
    parse_iso_datetime,
    sort_created,
    touch,
)

getcontext().prec = 60

# ------------------------------------------------------------------ constants
PACE_TARGET_RATIO = Decimal("0.80")
ALLOWED_PICKUP_RATIO = Decimal("0.80")
NO_SHOW_BILLED_NIGHTS = 1
TIER_1_MAX_RATIO = Decimal("0.10")
TIER_1_PCT = Decimal("0.50")
TIER_2_MAX_RATIO = Decimal("0.25")
TIER_2_PCT = Decimal("0.70")
TIER_3_PCT = Decimal("0.90")
VARIANCE_FLOOR_CENTS = 5000
VARIANCE_PCT = Decimal("0.01")
BASE_SCORE = 10
PER_VERIFIED_INCIDENT = 25
PER_DISTINCT_CHANNEL = 15
PAYMENT_SOLICITATION_BONUS = 20
SCORE_FLOOR = 0
SCORE_CEILING = 100
VENDOR_REVIEW_SCORE_THRESHOLD = 60
HOUSING_RISK_WARNING_THRESHOLD = 2
MAX_NEGOTIATION_ROUNDS = 3
SHOULDER_BUFFER_DAYS = 1
SEGMENT_RANK = {"GENERAL": 1, "EXHIBITOR": 2, "STAFF": 3, "VIP": 4}


def D(value):
    """Decimal that preserves the decimal precision the value was supplied with."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round to a whole integer, half away from zero (PRD §2.6)."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------- navigation


def block_of_sub_block(sub_block):
    return STORE.hotel_blocks.get(sub_block["hotel_block_id"])


def event_of_block(block):
    return STORE.events.get(block["event_id"])


def sub_blocks_of_block(block_id):
    return [sb for sb in STORE.sub_blocks.values() if sb["hotel_block_id"] == block_id]


def reservations_of_sub_block(sub_block_id):
    return [r for r in STORE.reservations.values() if r["sub_block_id"] == sub_block_id]


def reservations_of_block(block_id):
    ids = {sb["id"] for sb in sub_blocks_of_block(block_id)}
    return [r for r in STORE.reservations.values() if r["sub_block_id"] in ids]


def blocks_of_event(event_id):
    return [b for b in STORE.hotel_blocks.values() if b["event_id"] == event_id]


def pickup_reports_of_block(block_id):
    reports = [p for p in STORE.pickup_reports.values() if p["hotel_block_id"] == block_id]
    return sorted(reports, key=lambda p: (p["as_of_date"], p["_seq"]))


def transmissions_of_block(block_id):
    batches = [t for t in STORE.transmissions.values() if t["hotel_block_id"] == block_id]
    return sorted(batches, key=lambda t: t["batch_seq"])


def reductions_of_block(block_id):
    rows = [r for r in STORE.reductions.values() if r["hotel_block_id"] == block_id]
    return sorted(rows, key=lambda r: (r["effective_date"], r["created_at"], r["_seq"]))


def invoices_of_block(block_id):
    return sort_created([i for i in STORE.invoices.values() if i["hotel_block_id"] == block_id])


def incidents_of_vendor(vendor_id):
    rows = [i for i in STORE.incidents.values() if i["rogue_vendor_id"] == vendor_id]
    return sorted(rows, key=incident_sort_key)


def incident_sort_key(incident):
    parsed = parse_iso_datetime(incident["occurred_at"])
    return (parsed, incident["contact_channel"], incident["_seq"])


# ------------------------------------------------- block room-night accounting


def block_contracted_room_nights(block):
    event = event_of_block(block)
    night_count = event["night_count"] if event else 0
    return block["contracted_rooms_per_night"] * night_count


# --------------------------------------- sub-block peak-night occupancy (§3.3)


def _stay_covers(reservation, day):
    check_in = parse_iso_date(reservation["check_in_date"])
    check_out = parse_iso_date(reservation["check_out_date"])
    return check_in <= day < check_out


def committed_on(sub_block_id, day, exclude_reservation_id=None):
    count = 0
    for reservation in STORE.reservations.values():
        if reservation["sub_block_id"] != sub_block_id:
            continue
        if reservation["id"] == exclude_reservation_id:
            continue
        if reservation["reservation_status"] != "CONFIRMED":
            continue
        if _stay_covers(reservation, day):
            count += 1
    return count


def event_window_nights(event):
    start = parse_iso_date(event["event_start_date"])
    end = parse_iso_date(event["event_end_date"])
    day = start
    nights = []
    while day < end:
        nights.append(day)
        day = date_shift(day, 1)
    return nights


def compute_committed_rooms(sub_block):
    """Peak-night committed rooms over the event housing window."""
    block = block_of_sub_block(sub_block)
    event = event_of_block(block) if block else None
    if event is None:
        return 0
    peak = 0
    for day in event_window_nights(event):
        peak = max(peak, committed_on(sub_block["id"], day))
    return peak


def derived_sub_block(sub_block):
    committed = compute_committed_rooms(sub_block)
    available = sub_block["allotted_rooms"] - committed
    inventory_status = "FULL" if available == 0 else "OPEN"
    return committed, available, inventory_status


def recompute_sub_block(sub_block):
    """Re-derive committed/available/inventory_status; a change is a mutation
    of the sub-block (PRD §2.4) so it refreshes updated_at and bumps version."""
    committed, available, inventory_status = derived_sub_block(sub_block)
    changed = (
        sub_block.get("committed_rooms") != committed
        or sub_block.get("available_rooms") != available
        or sub_block.get("inventory_status") != inventory_status
    )
    sub_block["committed_rooms"] = committed
    sub_block["available_rooms"] = available
    sub_block["inventory_status"] = inventory_status
    if changed:
        touch(sub_block)
    return changed


def sync_sub_block_quiet(sub_block):
    committed, available, inventory_status = derived_sub_block(sub_block)
    sub_block["committed_rooms"] = committed
    sub_block["available_rooms"] = available
    sub_block["inventory_status"] = inventory_status


def admits_stay(sub_block, check_in, check_out, exclude_reservation_id=None):
    """Night-capacity admission test over the candidate stay's own nights."""
    day = parse_iso_date(check_in)
    end = parse_iso_date(check_out)
    while day < end:
        if committed_on(sub_block["id"], day, exclude_reservation_id) + 1 > sub_block["allotted_rooms"]:
            return False
        day = date_shift(day, 1)
    return True


# ---------------------------------------------- attendee buffered overlap (§3.4)


def attendee_stay_collides(attendee_id, check_in, check_out, exclude_reservation_id=None):
    candidate_in = parse_iso_date(check_in)
    candidate_out = parse_iso_date(check_out)
    for reservation in STORE.reservations.values():
        if reservation["attendee_id"] != attendee_id:
            continue
        if reservation["id"] == exclude_reservation_id:
            continue
        if reservation["reservation_status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        low = date_shift(reservation["check_in_date"], -SHOULDER_BUFFER_DAYS)
        high = date_shift(reservation["check_out_date"], SHOULDER_BUFFER_DAYS)
        if not (candidate_out < low or candidate_in > high):
            return True
    return False


# ------------------------------------------------- event posture / aggregates


def derived_event(event):
    blocks = blocks_of_event(event["id"])
    total_contracted = 0
    for block in blocks:
        if block["status"] in ("CONTRACTED", "OPEN", "CUTOFF_PASSED", "CLOSED"):
            total_contracted += block_contracted_room_nights(block)

    total_confirmed = 0
    commission_collected = 0
    open_blocks = []
    ended_blocks = []
    for block in blocks:
        if block["status"] == "OPEN":
            open_blocks.append(block)
        elif block["status"] in ("CUTOFF_PASSED", "CLOSED"):
            ended_blocks.append(block)
        for reservation in reservations_of_block(block["id"]):
            if reservation["reservation_status"] == "CONFIRMED":
                total_confirmed += reservation["room_nights"]
        for invoice in invoices_of_block(block["id"]):
            commission_collected += invoice["paid_cents"]

    available = 0
    for block in open_blocks:
        for sub_block in sub_blocks_of_block(block["id"]):
            if sub_block["approval_status"] == "APPROVED":
                _, sb_available, _ = derived_sub_block(sub_block)
                available += sb_available

    if not open_blocks and not ended_blocks:
        posture = "PLANNING"
    elif open_blocks and available > 0:
        posture = "OPEN"
    elif open_blocks and available == 0:
        posture = "RESTRICTED"
    else:
        posture = "CLOSED"

    return {
        "night_count": event["night_count"],
        "housing_posture": posture,
        "total_contracted_room_nights": total_contracted,
        "total_confirmed_room_nights": total_confirmed,
        "commission_collected_cents": commission_collected,
    }


def recompute_event(event):
    if event is None:
        return False
    derived = derived_event(event)
    changed = False
    for key in (
        "housing_posture",
        "total_contracted_room_nights",
        "total_confirmed_room_nights",
        "commission_collected_cents",
    ):
        if event.get(key) != derived[key]:
            changed = True
        event[key] = derived[key]
    if changed:
        touch(event)
    return changed


def recompute_event_of_block(block):
    recompute_event(event_of_block(block))


# ----------------------------------------------------- reservation money (§3.4)


def taxed_nightly_cents(reservation):
    """Taxed nightly amount rounded half up to whole cents FIRST."""
    return round_half_up(
        D(reservation["quoted_nightly_rate_cents"]) * (Decimal(1) + D(reservation["room_tax_pct_snapshot"]))
    )


def reservation_total_charge(reservation):
    return taxed_nightly_cents(reservation) * reservation["room_nights"]


def no_show_billing(reservation):
    return taxed_nightly_cents(reservation) * NO_SHOW_BILLED_NIGHTS


# -------------------------------------------------------- pickup pace (§3.6)


def block_pickup_pace(block):
    reports = pickup_reports_of_block(block["id"])
    report_count = len(reports)
    pace_target = round_half_up(D(block_contracted_room_nights(block)) * PACE_TARGET_RATIO)

    if report_count == 0:
        return {
            "hotel_block_id": block["id"],
            "report_count": 0,
            "latest_reported_room_nights": 0,
            "days_remaining_to_cutoff": 0,
            "forward_looking_projection_room_nights": 0,
            "chronological_run_rate_projection_room_nights": 0,
            "pace_variance_room_nights": 0,
            "pace_target_room_nights": pace_target,
            "on_pace": 0 >= pace_target,
        }

    last = reports[-1]
    latest_room_nights = last["reported_room_nights"]
    days_remaining = days_between(last["as_of_date"], block["cutoff_date"])

    if report_count < 2:
        forward = latest_room_nights
        run_rate = latest_room_nights
        variance = 0
    else:
        first = reports[0]
        previous = reports[-2]
        span_all = days_between(first["as_of_date"], last["as_of_date"])
        avg_daily = D(last["reported_room_nights"] - first["reported_room_nights"]) / D(span_all)
        forward = round_half_up(D(last["reported_room_nights"]) + avg_daily * D(days_remaining))
        span_last = days_between(previous["as_of_date"], last["as_of_date"])
        last_rate = D(last["reported_room_nights"] - previous["reported_room_nights"]) / D(span_last)
        run_rate = round_half_up(D(last["reported_room_nights"]) + last_rate * D(days_remaining))
        variance = run_rate - forward

    return {
        "hotel_block_id": block["id"],
        "report_count": report_count,
        "latest_reported_room_nights": latest_room_nights,
        "days_remaining_to_cutoff": days_remaining,
        "forward_looking_projection_room_nights": forward,
        "chronological_run_rate_projection_room_nights": run_rate,
        "pace_variance_room_nights": variance,
        "pace_target_room_nights": pace_target,
        "on_pace": forward >= pace_target,
    }


# ------------------------------------------------ reduction rights headroom


def reduction_rights_headroom(block):
    original = block.get("original_contracted_rooms_per_night") or 0
    cap = int(D(original) * D(block["reduction_rights_pct"]))
    consumed = 0
    for reduction in STORE.reductions.values():
        if reduction["hotel_block_id"] != block["id"]:
            continue
        if reduction["status"] in ("SUBMITTED", "APPROVED", "EXERCISED"):
            consumed += reduction["requested_reduction_rooms"]
    return cap - consumed


# ---------------------------------------------- attrition penalty exposure


def block_actual_room_nights(block):
    """CONFIRMED rows at full room_nights, NO_SHOW rows at one night each."""
    total = 0
    for reservation in reservations_of_block(block["id"]):
        if reservation["reservation_status"] == "CONFIRMED":
            total += reservation["room_nights"]
        elif reservation["reservation_status"] == "NO_SHOW":
            total += NO_SHOW_BILLED_NIGHTS
    return total


def attrition_penalty_exposure(block, contracted_rooms=None, actual_room_nights=None):
    event = event_of_block(block)
    night_count = event["night_count"] if event else 0
    rooms = block["contracted_rooms_per_night"] if contracted_rooms is None else contracted_rooms
    adjusted = rooms * night_count
    actual = block_actual_room_nights(block) if actual_room_nights is None else actual_room_nights
    protected = round_half_up(D(adjusted) * ALLOWED_PICKUP_RATIO)
    shortfall = max(0, protected - actual)
    ratio = Decimal(0) if adjusted == 0 else D(shortfall) / D(adjusted)
    if ratio <= TIER_1_MAX_RATIO:
        penalty_pct = TIER_1_PCT
    elif ratio <= TIER_2_MAX_RATIO:
        penalty_pct = TIER_2_PCT
    else:
        penalty_pct = TIER_3_PCT
    return round_half_up(D(shortfall) * D(block["negotiated_nightly_rate_cents"]) * penalty_pct)


# --------------------------------------------------------- commission (§3.9)


def commission_figures(block):
    bureau_room_nights = 0
    bureau_pre_tax = 0
    for reservation in reservations_of_block(block["id"]):
        if reservation["reservation_status"] == "CONFIRMED":
            bureau_room_nights += reservation["room_nights"]
            bureau_pre_tax += reservation["quoted_nightly_rate_cents"] * reservation["room_nights"]
        elif reservation["reservation_status"] == "NO_SHOW":
            bureau_room_nights += NO_SHOW_BILLED_NIGHTS
            bureau_pre_tax += reservation["quoted_nightly_rate_cents"] * NO_SHOW_BILLED_NIGHTS
    bureau_commission = round_half_up(D(bureau_pre_tax) * D(block["commission_pct"]))

    reports = pickup_reports_of_block(block["id"])
    latest = reports[-1] if reports else None
    if latest is None:
        hotel_commission = None
    else:
        hotel_commission = round_half_up(
            D(latest["reported_gross_revenue_cents"]) * D(block["commission_pct"])
        )
    return bureau_room_nights, bureau_commission, hotel_commission, latest


def commission_variance_tolerance(invoice):
    return max(
        VARIANCE_FLOOR_CENTS,
        round_half_up(D(invoice["bureau_confirmed_commission_cents"]) * VARIANCE_PCT),
    )


def invoice_outstanding(invoice):
    return invoice["commission_due_cents"] - invoice["paid_cents"] - invoice["written_off_cents"]


# ----------------------------------------------------- rogue vendor scoring


def vendor_counted_incidents(vendor_id):
    return [
        incident
        for incident in STORE.incidents.values()
        if incident["rogue_vendor_id"] == vendor_id
        and incident["verified"] is True
        and incident["status"] in ("RECORDED", "WARNING_ISSUED")
    ]


def vendor_derived(vendor):
    counted = vendor_counted_incidents(vendor["id"])
    verified_count = len(counted)
    distinct_channels = len({incident["contact_channel"] for incident in counted})
    payment_bonus = (
        PAYMENT_SOLICITATION_BONUS
        if any(incident["solicited_payment"] for incident in counted)
        else 0
    )
    raw = (
        BASE_SCORE
        + PER_VERIFIED_INCIDENT * verified_count
        + PER_DISTINCT_CHANNEL * distinct_channels
        + payment_bonus
    )
    score = min(SCORE_CEILING, max(SCORE_FLOOR, raw))
    return score, verified_count


# -------------------------------------------- rooming-list transmission set


def rooming_list_transmission_set(block):
    candidates = []
    for reservation in reservations_of_block(block["id"]):
        if reservation["transmission_status"] not in ("NOT_TRANSMITTED", "CHANGE_PENDING"):
            continue
        if reservation["reservation_status"] not in ("CONFIRMED", "CANCELLED", "NO_SHOW"):
            continue
        if (
            reservation["reservation_status"] in ("CANCELLED", "NO_SHOW")
            and reservation["transmission_status"] == "NOT_TRANSMITTED"
        ):
            continue
        candidates.append(reservation)
    candidates.sort(key=lambda r: (r["created_at"], r["intake_seq"]))
    return candidates


# ------------------------------------------------------ waitlist promotion


def promote_one_waitlisted(sub_block):
    """At most one promotion: lowest intake_seq among fully-fitting candidates."""
    candidates = [
        r
        for r in reservations_of_sub_block(sub_block["id"])
        if r["reservation_status"] == "WAITLISTED"
    ]
    candidates.sort(key=lambda r: r["intake_seq"])
    for candidate in candidates:
        if admits_stay(sub_block, candidate["check_in_date"], candidate["check_out_date"], candidate["id"]):
            candidate["reservation_status"] = "CONFIRMED"
            if candidate["transmission_status"] == "TRANSMITTED":
                candidate["transmission_status"] = "CHANGE_PENDING"
            touch(candidate)
            return candidate
    return None


def waitlist_overcommitment(sub_block):
    """LINK 3 — bump CONFIRMED reservations in intake_seq DESC order until the
    sub-block's committed_rooms is back at or below its allotted_rooms."""
    changed = []
    sync_sub_block_quiet(sub_block)
    guard = 0
    while sub_block["committed_rooms"] > sub_block["allotted_rooms"]:
        guard += 1
        if guard > 10000:
            break
        confirmed = [
            r
            for r in reservations_of_sub_block(sub_block["id"])
            if r["reservation_status"] == "CONFIRMED"
        ]
        if not confirmed:
            break
        victim = max(confirmed, key=lambda r: r["intake_seq"])
        victim["reservation_status"] = "WAITLISTED"
        if victim["transmission_status"] == "TRANSMITTED":
            victim["transmission_status"] = "CHANGE_PENDING"
        touch(victim)
        changed.append(victim)
        sync_sub_block_quiet(sub_block)
    return changed
