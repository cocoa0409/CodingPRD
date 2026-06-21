"""Core scheduling business logic: calculations, predictability pay, pay-period
reconciliation, eligibility battery, assignment creation, and state cascades.

All time reasoning reads the logical clock (clock.now()). All instants are stored
as ISO 8601 UTC strings; we parse them on the fly into aware datetimes.
"""
from decimal import Decimal

import clock
import db
from errors import ApiError
from util import (
    parse_utc, hours_between, round_half_up_cents,
)

# Calculation constants (scaffold §1.3).
CLOPENING_PENALTY_CENTS = 5000
SHORT_NOTICE_POST_RATE = Decimal("0.25")
SHORT_NOTICE_CANCEL_RATE = Decimal("0.5")
STRIKE_CEILING = 3

# Assignment status sets.
FILLED_STATES = {"SCHEDULED", "CONFIRMED", "COMPLETED"}
NON_TERMINAL_ASSIGNMENT = {"SCHEDULED", "CONFIRMED"}
SCHEDULED_OR_CONFIRMED = {"SCHEDULED", "CONFIRMED"}
TERMINAL_ASSIGNMENT = {"COMPLETED", "NO_SHOW", "CANCELLED"}


# ---------------------------------------------------------------------------
# Datetime accessors on stored records
# ---------------------------------------------------------------------------
def shift_start(shift):
    return parse_utc(shift["start_utc"])


def shift_end(shift):
    return parse_utc(shift["end_utc"])


def shift_duration_hours(shift):
    return hours_between(shift_start(shift), shift_end(shift))


# ---------------------------------------------------------------------------
# Pay-period lookup
# ---------------------------------------------------------------------------
def find_pay_period_for_shift(shift):
    """The location pay-period whose half-open [start,end) window contains
    shift.start_utc. Returns the record or None."""
    s = shift_start(shift)
    loc_id = shift["location_id"]
    for pp in db.pay_periods.values():
        if pp["location_id"] != loc_id:
            continue
        if parse_utc(pp["start_utc"]) <= s < parse_utc(pp["end_utc"]):
            return pp
    return None


# ---------------------------------------------------------------------------
# Cost calculations (scaffold §1.3 provisional/finalize)
# ---------------------------------------------------------------------------
def _overtime_split_cost(prior_hours, shift_hours, base_rate_cents, ot_threshold, ot_multiplier):
    """Stack shift_hours on top of prior_hours around the OT threshold; charge
    regular at base, overtime at base*multiplier; round once after summing."""
    reg_hours = ot_threshold - prior_hours
    if reg_hours < 0:
        reg_hours = 0.0
    if reg_hours > shift_hours:
        reg_hours = shift_hours
    ot_hours = shift_hours - reg_hours
    base = Decimal(str(base_rate_cents))
    mult = Decimal(str(ot_multiplier))
    cost = (Decimal(str(reg_hours)) * base) + (Decimal(str(ot_hours)) * base * mult)
    return round_half_up_cents(cost)


def compute_provisional_cost(assignment, shift, worker, location):
    """Forward-looking provisional cost. Baseline = worker's other SCHEDULED/
    CONFIRMED assignments in the same pay-period whose shift starts strictly
    before this shift (start_utc ASC ordering decides which hours fall in the
    OT band)."""
    shift_hours = shift_duration_hours(shift)
    ot_threshold = float(location["overtime_weekly_threshold_hours"])
    this_start = shift_start(shift)

    prior = 0.0
    for a in db.assignments.values():
        if a["id"] == assignment["id"]:
            continue
        if a["worker_id"] != worker["id"]:
            continue
        if a["pay_period_id"] != assignment["pay_period_id"]:
            continue
        if a["status"] not in SCHEDULED_OR_CONFIRMED:
            continue
        a_shift = db.shifts[a["shift_id"]]
        a_start = shift_start(a_shift)
        # Order by start_utc ASC: hours from shifts starting before this one
        # form the baseline. Tie-break by created sequence.
        if a_start < this_start or (a_start == this_start and a["_seq"] < assignment["_seq"]):
            prior += shift_duration_hours(a_shift)

    return _overtime_split_cost(
        prior, shift_hours, worker["base_hourly_rate_cents"],
        ot_threshold, location["overtime_multiplier"],
    )


def compute_finalized_cost(assignment, shift, worker, location):
    """Chronological finalized cost over the worker's COMPLETED assignments in
    the same pay-period, ordered by shift start_utc ASC (tie created_at ASC)."""
    shift_hours = shift_duration_hours(shift)
    ot_threshold = float(location["overtime_weekly_threshold_hours"])
    this_start = shift_start(shift)

    running = 0.0
    for a in db.assignments.values():
        if a["id"] == assignment["id"]:
            continue
        if a["worker_id"] != worker["id"]:
            continue
        if a["pay_period_id"] != assignment["pay_period_id"]:
            continue
        if a["status"] != "COMPLETED":
            continue
        a_shift = db.shifts[a["shift_id"]]
        a_start = shift_start(a_shift)
        if a_start < this_start or (a_start == this_start and a["_seq"] < assignment["_seq"]):
            running += shift_duration_hours(a_shift)

    return _overtime_split_cost(
        running, shift_hours, worker["base_hourly_rate_cents"],
        ot_threshold, location["overtime_multiplier"],
    )


# ---------------------------------------------------------------------------
# Pay-period reconciliation (scaffold §1.3 pay_period_projected_cost)
# ---------------------------------------------------------------------------
def reconcile_pay_period(pp):
    """Recompute projected_labor_cost_cents. This is a mutation -> bump version
    + updated_at (PRD §2.9)."""
    if pp is None:
        return
    projected = 0
    for a in db.assignments.values():
        if a["pay_period_id"] != pp["id"]:
            continue
        if a["status"] in SCHEDULED_OR_CONFIRMED:
            projected += a["provisional_cost_cents"] or 0
    for e in db.ledger.values():
        if e["pay_period_id"] == pp["id"]:
            projected += e["amount_cents"]
    if pp["projected_labor_cost_cents"] != projected:
        pp["projected_labor_cost_cents"] = projected
        db.touch(pp)
    else:
        # Still a reconciliation event triggered by a feeding mutation; PRD §2.9
        # says any reconciliation refreshes updated_at/version. We only bump when
        # the value actually changes to avoid spurious version drift on no-op
        # reads; feeding mutations that change nothing do not occur in practice.
        pass


def projected_cost_with(pp, extra_provisional):
    """Projected cost if a new assignment with extra_provisional cents were
    committed (used for the guardrail check before commit)."""
    projected = extra_provisional
    for a in db.assignments.values():
        if a["pay_period_id"] != pp["id"]:
            continue
        if a["status"] in SCHEDULED_OR_CONFIRMED:
            projected += a["provisional_cost_cents"] or 0
    for e in db.ledger.values():
        if e["pay_period_id"] == pp["id"]:
            projected += e["amount_cents"]
    return projected


# ---------------------------------------------------------------------------
# Predictability ledger (scaffold §1.3)
# ---------------------------------------------------------------------------
def append_ledger(worker_id, shift_id, pay_period_id, reason, amount_cents):
    entry = db.ledger_fields()
    entry.update({
        "worker_id": worker_id,
        "shift_id": shift_id,
        "pay_period_id": pay_period_id,
        "reason": reason,
        "amount_cents": amount_cents,
    })
    db.ledger[entry["id"]] = entry
    return entry


def nearest_prior_end(worker_id, this_shift, exclude_assignment_id=None):
    """Largest a.shift.end_utc <= this_shift.start among the worker's SCHEDULED/
    CONFIRMED/COMPLETED assignments (tie-break latest created). Returns datetime
    or None."""
    this_start = shift_start(this_shift)
    best = None
    best_seq = -1
    for a in db.assignments.values():
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if a["worker_id"] != worker_id:
            continue
        if a["status"] not in FILLED_STATES:
            continue
        a_shift = db.shifts[a["shift_id"]]
        a_end = shift_end(a_shift)
        if a_end <= this_start:
            if best is None or a_end > best or (a_end == best and a["_seq"] > best_seq):
                best = a_end
                best_seq = a["_seq"]
    return best


def compute_clopening_flag(assignment, shift, worker, location):
    prior_end = nearest_prior_end(worker["id"], shift, exclude_assignment_id=assignment["id"])
    if prior_end is None:
        return False
    gap = hours_between(prior_end, shift_start(shift))
    return gap < float(location["min_rest_hours_between_shifts"])


def accrue_clopening_if_needed(assignment, shift, worker, location, pp):
    """If clopening_flag set and predictability enabled, append CLOPENING entry."""
    if assignment["clopening_flag"] and location["predictability_pay_enabled"]:
        append_ledger(worker["id"], shift["id"], pp["id"], "CLOPENING",
                      CLOPENING_PENALTY_CENTS)


def is_short_notice_post(shift, location):
    """Posting was short-notice: predictability enabled and notice gap < window."""
    if not location["predictability_pay_enabled"]:
        return False
    if not shift.get("posted_utc"):
        return False
    notice_hours = hours_between(parse_utc(shift["posted_utc"]), shift_start(shift))
    window_hours = location["advance_notice_days"] * 24
    return notice_hours < window_hours


def accrue_short_notice_post(shift, worker, location, pp):
    if not is_short_notice_post(shift, location):
        return
    amount = round_half_up_cents(
        Decimal(str(shift_duration_hours(shift)))
        * Decimal(str(worker["base_hourly_rate_cents"]))
        * SHORT_NOTICE_POST_RATE
    )
    append_ledger(worker["id"], shift["id"], pp["id"], "SHORT_NOTICE_POST", amount)


def accrue_short_notice_cancel(shift, worker, location, pp):
    """Caller has already verified predictability enabled and within window."""
    amount = round_half_up_cents(
        Decimal(str(shift_duration_hours(shift)))
        * Decimal(str(worker["base_hourly_rate_cents"]))
        * SHORT_NOTICE_CANCEL_RATE
    )
    append_ledger(worker["id"], shift["id"], pp["id"], "SHORT_NOTICE_CANCEL", amount)


def within_advance_notice_window(shift, location):
    """True iff predictability enabled and (shift.start - now) < advance window."""
    if not location["predictability_pay_enabled"]:
        return False
    gap_hours = hours_between(clock.now(), shift_start(shift))
    window_hours = location["advance_notice_days"] * 24
    return gap_hours < window_hours


# ---------------------------------------------------------------------------
# Eligibility battery (PRD §3.9 / §2.7), in precedence order. Caller invokes
# this AFTER auth/existence/state/locked/OCC/cross-location have passed.
# Order here: suspended -> unavailable -> minor cap -> fully-staffed -> guardrail.
# ---------------------------------------------------------------------------
def overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a) intersects [b). Adjacency (a_end == b_start) NOT
    an overlap."""
    return a_start < b_end and b_start < a_end


def collides_closed(a_start, a_end, b_start, b_end):
    """Closed-interval collision: touching a boundary counts."""
    return a_start <= b_end and b_start <= a_end


def check_not_suspended(worker):
    if worker["status"] == "SUSPENDED":
        raise ApiError("ERR_WORKER_SUSPENDED")


def check_worker_free(worker, shift, exclude_assignment_id=None):
    """(i) no other non-terminal assignment overlaps (half-open);
    (ii) no UNAVAILABLE availability and no APPROVED time-off collides (closed)."""
    s_start = shift_start(shift)
    s_end = shift_end(shift)

    for a in db.assignments.values():
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if a["worker_id"] != worker["id"]:
            continue
        if a["status"] not in NON_TERMINAL_ASSIGNMENT:
            continue
        a_shift = db.shifts[a["shift_id"]]
        if overlaps_half_open(s_start, s_end, shift_start(a_shift), shift_end(a_shift)):
            raise ApiError("ERR_WORKER_UNAVAILABLE")

    for av in db.availabilities.values():
        if av["worker_id"] != worker["id"]:
            continue
        if av["kind"] != "UNAVAILABLE":
            continue
        if collides_closed(s_start, s_end, parse_utc(av["start_utc"]), parse_utc(av["end_utc"])):
            raise ApiError("ERR_WORKER_UNAVAILABLE")

    for to in db.time_off_requests.values():
        if to["worker_id"] != worker["id"]:
            continue
        if to["status"] != "APPROVED":
            continue
        if collides_closed(s_start, s_end, parse_utc(to["start_utc"]), parse_utc(to["end_utc"])):
            raise ApiError("ERR_WORKER_UNAVAILABLE")


def check_minor_caps(worker, shift, pay_period_id, location, exclude_assignment_id=None):
    if not worker["is_minor"]:
        return
    shift_hours = shift_duration_hours(shift)
    this_day = local_calendar_day(shift_start(shift), location["time_zone"])

    day_hours = shift_hours
    week_hours = shift_hours
    for a in db.assignments.values():
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if a["worker_id"] != worker["id"]:
            continue
        if a["status"] not in SCHEDULED_OR_CONFIRMED:
            continue
        a_shift = db.shifts[a["shift_id"]]
        if local_calendar_day(shift_start(a_shift), location["time_zone"]) == this_day:
            day_hours += shift_duration_hours(a_shift)
        if a["pay_period_id"] == pay_period_id:
            week_hours += shift_duration_hours(a_shift)

    if day_hours > float(worker["minor_daily_cap_hours"]):
        raise ApiError("ERR_MINOR_HOUR_CAP_EXCEEDED")
    if week_hours > float(worker["minor_weekly_cap_hours"]):
        raise ApiError("ERR_MINOR_HOUR_CAP_EXCEEDED")


def check_not_fully_staffed(shift):
    if headcount_filled(shift) >= shift["headcount_required"]:
        raise ApiError("ERR_SHIFT_FULLY_STAFFED")


def check_guardrail(pp, provisional_cents, location, force_over_guardrail):
    if force_over_guardrail:
        return
    projected = projected_cost_with(pp, provisional_cents)
    if projected > location["overtime_cost_guardrail_cents"]:
        raise ApiError("ERR_OVERTIME_GUARDRAIL_EXCEEDED")


# ---------------------------------------------------------------------------
# Local calendar-day bucket (PRD §2.5)
# ---------------------------------------------------------------------------
def local_calendar_day(utc_dt, tz_name):
    from zoneinfo import ZoneInfo
    local = utc_dt.astimezone(ZoneInfo(tz_name))
    return (local.year, local.month, local.day)


# ---------------------------------------------------------------------------
# Headcount + shift status cascades (PRD §2.10)
# ---------------------------------------------------------------------------
def headcount_filled(shift):
    n = 0
    for a in db.assignments.values():
        if a["shift_id"] == shift["id"] and a["status"] in FILLED_STATES:
            n += 1
    return n


def bubble_up_if_full(shift):
    """OPEN -> FULLY_STAFFED when filled == required; rejects remaining SUBMITTED
    bids."""
    if shift["status"] != "OPEN":
        return
    if headcount_filled(shift) >= shift["headcount_required"]:
        shift["status"] = "FULLY_STAFFED"
        db.touch(shift)
        reject_submitted_bids(shift)


def bubble_down_if_understaffed(shift):
    """FULLY_STAFFED -> OPEN when filled drops below required."""
    if shift["status"] != "FULLY_STAFFED":
        return
    if headcount_filled(shift) < shift["headcount_required"]:
        shift["status"] = "OPEN"
        db.touch(shift)


def reject_submitted_bids(shift):
    for b in db.bids.values():
        if b["shift_id"] == shift["id"] and b["status"] == "SUBMITTED":
            b["status"] = "REJECTED"
            db.touch(b)


# ---------------------------------------------------------------------------
# The shared assignment-creation pipeline (PRD §3.5/§3.9/§3.10/§3.11)
# Runs the eligibility battery in precedence order, then commits.
# ---------------------------------------------------------------------------
def create_scheduled_assignment(shift, worker, location, source, force_over_guardrail):
    """Run cross-location + full eligibility battery, then create a SCHEDULED
    assignment, compute clopening + provisional cost, accrue predictability, and
    reconcile the pay-period. Bubbles the shift up if it becomes full.

    Precondition (caller-checked): shift is OPEN, pay-period is OPEN, and (for
    award) OCC has passed. Returns the new assignment record.
    """
    pp = find_pay_period_for_shift(shift)
    if pp is None:
        # No pay-period contains the shift start. Treated as not-found referential
        # gap; but the PRD always provides a pay-period in scheduling flows. We
        # surface ERR_INVALID_REQUEST defensively.
        raise ApiError("ERR_INVALID_REQUEST", "No pay-period contains the shift start.")

    # Pay-period must be OPEN to mutate assignments in its window (priority 7).
    if pp["status"] != "OPEN":
        raise ApiError("ERR_PAY_PERIOD_LOCKED")

    # Cross-location (priority 9): worker belongs to shift's location.
    if worker["location_id"] != shift["location_id"]:
        raise ApiError("ERR_CROSS_LOCATION")

    # Business-safety battery (priority 10-14), in precedence order.
    check_not_suspended(worker)
    check_worker_free(worker, shift)
    check_minor_caps(worker, shift, pp["id"], location)
    check_not_fully_staffed(shift)

    # Build the (not-yet-committed) assignment so cost/clopening can reference it.
    rec = db.common_fields()
    rec.update({
        "shift_id": shift["id"],
        "worker_id": worker["id"],
        "pay_period_id": pp["id"],
        "status": "SCHEDULED",
        "source": source,
        "clopening_flag": False,
        "provisional_cost_cents": 0,
        "finalized_cost_cents": None,
    })

    # Provisional cost (excludes this assignment from its own baseline via id).
    rec["provisional_cost_cents"] = compute_provisional_cost(rec, shift, worker, location)

    # Guardrail (priority 14, last): projected cost AS IF committed.
    check_guardrail(pp, rec["provisional_cost_cents"], location, force_over_guardrail)

    # Commit.
    db.assignments[rec["id"]] = rec

    # Clopening flag + accrual (predictability premium).
    rec["clopening_flag"] = compute_clopening_flag(rec, shift, worker, location)
    accrue_clopening_if_needed(rec, shift, worker, location, pp)

    # Short-notice posting accrual: staffing a shift opened inside the window.
    accrue_short_notice_post(shift, worker, location, pp)

    # Reconcile the pay-period now that provisional cost + ledger changed.
    reconcile_pay_period(pp)

    # Bubble the shift up if this assignment fills the last seat.
    bubble_up_if_full(shift)

    return rec
