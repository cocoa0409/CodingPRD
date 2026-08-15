"""Business logic: calculations (scaffold section 1.3), cascades, clock sweep."""
from datetime import timedelta
from fractions import Fraction

from db import STORE, logical_now, new_id, next_seq, wall_now
from domain import (
    ACTIVE_BOOKING_STATES,
    area_occupancy,
    call_bookings,
    reliability_of,
    required_union_slots,
    touch,
)

# Calculation constants (scaffold section 1.3)
MEAL_WINDOW_MINUTES = 360
MEAL_PENALTY_CAP = 3
REGULAR_MINUTES = 480
UNION_OT1_CAP_MINUTES = 120
UNION_OT2_FLOOR_MINUTES = 600
NONUNION_OT1_CAP_MINUTES = 240
NONUNION_OT2_FLOOR_MINUTES = 720
ASSUMED_MEAL_MINUTES = 30
TURNAROUND_MINUTES = 600
NO_SHOW_SUSPEND_THRESHOLD = 3
NO_SHOW_GRACE_MINUTES = 60
REPLACEMENT_DEADLINE_MINUTES = 120
NONCOMPLIANT_WRAP_PENALTY = 15
PUBLISH_GATE_MINIMUM = 30


def _rhu(fr):
    """Round a non-negative Fraction half up to an integer (per-component rounding)."""
    return (fr.numerator * 2 + fr.denominator) // (2 * fr.denominator)


# ---------------------------------------------------------------------------
# Event timeline replay (calculations.event_timeline_replay / net_work_minutes)
# ---------------------------------------------------------------------------

def effective_events(booking_id):
    """Effective event set: events superseded by a correction drop out; a
    correction is itself effective unless later corrected (chain substitution).
    Ordered by occurred_at ASC, tie-break creation order (created_at ASC)."""
    evs = [e for e in STORE.time_events.values() if e["booking_id"] == booking_id]
    corrected = {e["corrects_event_id"] for e in evs if e.get("corrects_event_id")}
    eff = [e for e in evs if e["id"] not in corrected]
    eff.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    return eff


def replay_timeline(eff):
    """check_in = first effective CHECK_IN; wrap_out = last effective WRAP_OUT;
    meals = consecutive (MEAL_OUT -> next MEAL_IN) pairs in the ordered stream."""
    check_in_at = None
    wrap_out_at = None
    meals = []
    open_meal_out = None
    for e in eff:
        t = e["event_type"]
        if t == "CHECK_IN":
            if check_in_at is None:
                check_in_at = e["occurred_at"]
        elif t == "WRAP_OUT":
            wrap_out_at = e["occurred_at"]
        elif t == "MEAL_OUT":
            open_meal_out = e["occurred_at"]
        elif t == "MEAL_IN":
            if open_meal_out is not None:
                meals.append((open_meal_out, e["occurred_at"]))
                open_meal_out = None
    return check_in_at, wrap_out_at, meals


def _minutes(delta):
    return int(delta.total_seconds() // 60)


def compute_net_work(check_in_at, wrap_out_at, meals):
    """Pinned evaluation order: gross elapsed first; meal timeliness judged on
    GROSS elapsed anchors (check_in / previous meal_in), never on net; only
    TIMELY meal durations are deducted; penalty meals stay paid time."""
    gross_elapsed = _minutes(wrap_out_at - check_in_at)
    penalty_count = 0
    timely_deduction = 0
    anchor = check_in_at
    for meal_out, meal_in in meals:
        if _minutes(meal_out - anchor) <= MEAL_WINDOW_MINUTES:
            timely_deduction += _minutes(meal_in - meal_out)
        else:
            penalty_count += 1
        anchor = meal_in
    if gross_elapsed > MEAL_WINDOW_MINUTES and not meals:
        penalty_count += 1
    penalty_count = min(penalty_count, MEAL_PENALTY_CAP)
    net = gross_elapsed - timely_deduction
    return gross_elapsed, net, penalty_count


# ---------------------------------------------------------------------------
# Wage computation (calculations.voucher_gross_final / voucher_gross_estimate)
# ---------------------------------------------------------------------------

def ot_split(slot_type, n):
    reg = min(n, REGULAR_MINUTES)
    if slot_type == "UNION":
        ot1 = min(max(n - REGULAR_MINUTES, 0), UNION_OT1_CAP_MINUTES)
        ot2 = max(n - UNION_OT2_FLOOR_MINUTES, 0)
    else:
        ot1 = min(max(n - REGULAR_MINUTES, 0), NONUNION_OT1_CAP_MINUTES)
        ot2 = max(n - NONUNION_OT2_FLOOR_MINUTES, 0)
    return reg, ot1, ot2


def compute_wages(daily_rate_cents, slot_type, net_work_minutes, meal_penalty_count, bumps_total):
    """hourly = daily_rate / 8 (fractional cents mid-formula). Per-component
    round-half-up to whole cents, THEN sum — never sum-then-round."""
    hourly = Fraction(daily_rate_cents, 8)
    reg, ot1, ot2 = ot_split(slot_type, net_work_minutes)
    base = _rhu(Fraction(reg, 60) * hourly)
    ot_wages = _rhu(Fraction(ot1, 60) * hourly * Fraction(3, 2)) + _rhu(
        Fraction(ot2, 60) * hourly * 2
    )
    meal_penalty = _rhu(Fraction(1, 2) * hourly) * meal_penalty_count
    gross = base + ot_wages + meal_penalty + bumps_total
    return {
        "reg": reg,
        "ot1": ot1,
        "ot2": ot2,
        "base_wages_cents": base,
        "ot_wages_cents": ot_wages,
        "meal_penalty_cents": meal_penalty,
        "gross_total_cents": gross,
    }


def voucher_bumps(voucher_id, statuses):
    return sum(
        b["amount_cents"]
        for b in STORE.bump_adjustments.values()
        if b["voucher_id"] == voucher_id and b["status"] in statuses
    )


def compute_voucher_final(voucher):
    """voucher_gross_final: chronological replay of actual effective events,
    APPROVED bumps only. Stores all computed pay fields on the voucher."""
    from errors import ApiError, ERR_TIME_EVENT_INVALID

    booking = STORE.bookings[voucher["booking_id"]]
    eff = effective_events(booking["id"])
    check_in_at, wrap_out_at, meals = replay_timeline(eff)
    if check_in_at is None or wrap_out_at is None:
        raise ApiError(
            ERR_TIME_EVENT_INVALID,
            409,
            "Effective timeline lacks a check-in or wrap-out event",
        )
    gross_elapsed, net, penalty_count = compute_net_work(check_in_at, wrap_out_at, meals)
    bumps = voucher_bumps(voucher["id"], ("APPROVED",))
    w = compute_wages(booking["daily_rate_cents"], booking["slot_type"], net, penalty_count, bumps)
    voucher["check_in_at"] = check_in_at
    voucher["wrap_out_at"] = wrap_out_at
    voucher["gross_elapsed_minutes"] = gross_elapsed
    voucher["net_work_minutes"] = net
    voucher["ot_tier1_minutes"] = w["ot1"]
    voucher["ot_tier2_minutes"] = w["ot2"]
    voucher["meal_penalty_count"] = penalty_count
    voucher["base_wages_cents"] = w["base_wages_cents"]
    voucher["ot_wages_cents"] = w["ot_wages_cents"]
    voucher["meal_penalty_cents"] = w["meal_penalty_cents"]
    voucher["bumps_total_cents"] = bumps
    voucher["gross_total_cents"] = w["gross_total_cents"]


def compute_voucher_estimate(voucher):
    """voucher_gross_estimate: forward-looking — scheduled wrap, exactly one
    timely 30-minute meal assumed, PENDING + APPROVED bumps counted."""
    booking = STORE.bookings[voucher["booking_id"]]
    call = STORE.casting_calls[booking["casting_call_id"]]
    net = max(0, call["scheduled_duration_minutes"] - ASSUMED_MEAL_MINUTES)
    bumps = voucher_bumps(voucher["id"], ("PENDING", "APPROVED"))
    w = compute_wages(booking["daily_rate_cents"], booking["slot_type"], net, 0, bumps)
    return {
        "estimated_gross_cents": w["gross_total_cents"],
        "estimated_net_work_minutes": net,
        "bump_basis": "PENDING+APPROVED",
    }


# ---------------------------------------------------------------------------
# Turnaround (calculations.turnaround_conflict_check)
# ---------------------------------------------------------------------------

def check_turnaround(actor_id, new_call_time, new_expected_wrap):
    """Half-open windows with a mandatory >= 600-minute rest buffer in either
    direction; a gap of exactly 600 minutes is allowed. Comparison set: the
    actor's bookings in OFFERED|CONFIRMED|CHECKED_IN|WRAPPED across all calls;
    WRAPPED bookings use the voucher's wrap_out_at when present."""
    for b in STORE.bookings.values():
        if b["actor_id"] != actor_id or b["status"] not in ACTIVE_BOOKING_STATES:
            continue
        other_end = b["expected_wrap_time"]
        if b["status"] == "WRAPPED":
            voucher = voucher_of_booking(b["id"])
            if voucher is not None and voucher.get("wrap_out_at") is not None:
                other_end = voucher["wrap_out_at"]
        gap_after = (new_call_time - other_end).total_seconds() / 60
        gap_before = (b["call_time"] - new_expected_wrap).total_seconds() / 60
        if not (gap_after >= TURNAROUND_MINUTES or gap_before >= TURNAROUND_MINUTES):
            return False
    return True


def voucher_of_booking(booking_id):
    for v in STORE.vouchers.values():
        if v["booking_id"] == booking_id:
            return v
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def suspend_cascade(actor):
    """ELIGIBLE -> SUSPENDED cascade: OFFERED bookings -> EXPIRED, CONFIRMED ->
    CANCELLED (each releases its slot to its call), ACTIVE standby -> WITHDRAWN."""
    for b in STORE.bookings.values():
        if b["actor_id"] != actor["id"]:
            continue
        if b["status"] == "OFFERED":
            b["status"] = "EXPIRED"
            touch(b)
            touch(STORE.casting_calls[b["casting_call_id"]])
        elif b["status"] == "CONFIRMED":
            b["status"] = "CANCELLED"
            touch(b)
            touch(STORE.casting_calls[b["casting_call_id"]])
    for s in STORE.standby_entries.values():
        if s["actor_id"] == actor["id"] and s["status"] == "ACTIVE":
            s["status"] = "WITHDRAWN"
            touch(s)


def create_replacement_case(booking, reason):
    case = {
        "id": new_id(),
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
        "_seq": next_seq(),
        "casting_call_id": booking["casting_call_id"],
        "original_booking_id": booking["id"],
        "required_slot_type": booking["slot_type"],
        "reason": reason,
        "deadline_at": booking["call_time"] + timedelta(minutes=REPLACEMENT_DEADLINE_MINUTES),
        "excluded_actor_ids": [],
        "offered_booking_id": None,
        "offered_actor_id": None,
        "attempts_count": 0,
        "status": "OPEN",
    }
    STORE.replacement_cases[case["id"]] = case
    return case


def create_voucher(booking_id):
    voucher = {
        "id": new_id(),
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
        "_seq": next_seq(),
        "booking_id": booking_id,
        "payroll_batch_id": None,
        "status": "DRAFT",
        "check_in_at": None,
        "wrap_out_at": None,
        "gross_elapsed_minutes": None,
        "net_work_minutes": None,
        "ot_tier1_minutes": None,
        "ot_tier2_minutes": None,
        "meal_penalty_count": None,
        "base_wages_cents": None,
        "ot_wages_cents": None,
        "meal_penalty_cents": None,
        "bumps_total_cents": None,
        "gross_total_cents": None,
        "issued_by_user_id": None,
        "adjusted_by_user_id": None,
        "issued_at": None,
    }
    STORE.vouchers[voucher["id"]] = voucher
    return voucher


def append_time_event(booking_id, event_type, occurred_at, recorded_by, corrects_event_id=None):
    event = {
        "id": new_id(),
        "created_at": wall_now(),
        "_seq": next_seq(),
        "booking_id": booking_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "corrects_event_id": corrects_event_id,
        "recorded_by": recorded_by,
    }
    STORE.time_events[event["id"]] = event
    return event


def recompute_batch_and_exposure(batch):
    """Batch totals are derived at read; this bump pair is the version-level
    signal that the batch total changed (production version increments too)."""
    touch(batch)
    production = STORE.productions.get(batch["production_id"])
    if production is not None:
        touch(production)


def eject_voucher_from_open_batch(voucher):
    """Dispute cascade hop: remove the voucher from its OPEN batch, recompute
    batch totals and production exposure (each with its own version bump)."""
    batch_id = voucher.get("payroll_batch_id")
    if batch_id is None:
        return
    batch = STORE.payroll_batches.get(batch_id)
    voucher["payroll_batch_id"] = None
    if batch is not None and batch["status"] == "OPEN":
        recompute_batch_and_exposure(batch)


# ---------------------------------------------------------------------------
# Standby selection (calculations.standby_selection)
# ---------------------------------------------------------------------------

def select_standby_candidate(case):
    """Conjunctive eligibility filter; rank reliability_score DESC, then
    StandbyEntry creation order ASC (created_at ASC — never by id)."""
    candidates = []
    for entry in STORE.standby_entries.values():
        if entry["casting_call_id"] != case["casting_call_id"]:
            continue
        if entry["status"] != "ACTIVE":
            continue
        if entry["slot_type"] != case["required_slot_type"]:
            continue
        actor = STORE.actors.get(entry["actor_id"])
        if actor is None or actor["status"] != "ELIGIBLE":
            continue
        if actor["id"] in case["excluded_actor_ids"]:
            continue
        has_active_booking = any(
            b["actor_id"] == actor["id"]
            and b["casting_call_id"] == case["casting_call_id"]
            and b["status"] in ("OFFERED", "CONFIRMED", "CHECKED_IN")
            for b in STORE.bookings.values()
        )
        if has_active_booking:
            continue
        candidates.append((entry, actor))
    candidates.sort(key=lambda pair: (-reliability_of(pair[1]), pair[0]["_seq"]))
    return candidates[0] if candidates else None


def create_booking_record(call, actor, call_time, is_replacement=False, case=None, replaces=None):
    """booking_rate_snapshot: slot_type and daily_rate_cents snapshot the actor's
    union status and the call's rates at creation; later edits never retro-change."""
    slot_type = "UNION" if actor["union_status"] == "SAG_AFTRA" else "NONUNION"
    rate = call["union_rate_cents"] if slot_type == "UNION" else call["nonunion_rate_cents"]
    expected_wrap = call_time + timedelta(minutes=call["scheduled_duration_minutes"])
    if is_replacement:
        offer_expires = case["deadline_at"]
    else:
        offer_expires = call_time
    booking = {
        "id": new_id(),
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
        "_seq": next_seq(),
        "casting_call_id": call["id"],
        "actor_id": actor["id"],
        "replacement_case_id": case["id"] if case else None,
        "replaces_booking_id": replaces["id"] if replaces else None,
        "is_replacement": is_replacement,
        "slot_type": slot_type,
        "daily_rate_cents": rate,
        "call_time": call_time,
        "expected_wrap_time": expected_wrap,
        "offer_expires_at": offer_expires,
        "holding_area_id": None,
        "status": "OFFERED",
    }
    STORE.bookings[booking["id"]] = booking
    return booking


# ---------------------------------------------------------------------------
# Logical clock sweep (POST /_clock/set_current_utc side effects)
# ---------------------------------------------------------------------------

def sweep_clock():
    """Advancing the logical clock expires OFFERED bookings past offer_expires_at
    (slot released; replacement offers reopen or expire their case with the actor
    excluded) and expires OPEN/CANDIDATE_OFFERED replacement cases past deadline."""
    now = logical_now()
    for b in list(STORE.bookings.values()):
        if b["status"] == "OFFERED" and now > b["offer_expires_at"]:
            b["status"] = "EXPIRED"
            touch(b)
            touch(STORE.casting_calls[b["casting_call_id"]])
            if b["is_replacement"] and b["replacement_case_id"]:
                case = STORE.replacement_cases.get(b["replacement_case_id"])
                if case is not None and case["status"] == "CANDIDATE_OFFERED":
                    if b["actor_id"] not in case["excluded_actor_ids"]:
                        case["excluded_actor_ids"].append(b["actor_id"])
                    case["offered_booking_id"] = None
                    case["offered_actor_id"] = None
                    case["status"] = "OPEN" if now <= case["deadline_at"] else "EXPIRED"
                    touch(case)
    for case in list(STORE.replacement_cases.values()):
        if case["status"] in ("OPEN", "CANDIDATE_OFFERED") and now > case["deadline_at"]:
            if case["status"] == "CANDIDATE_OFFERED" and case["offered_booking_id"]:
                offer = STORE.bookings.get(case["offered_booking_id"])
                if offer is not None and offer["status"] == "OFFERED":
                    offer["status"] = "EXPIRED"
                    touch(offer)
                    touch(STORE.casting_calls[offer["casting_call_id"]])
                case["offered_booking_id"] = None
                case["offered_actor_id"] = None
            case["status"] = "EXPIRED"
            touch(case)
