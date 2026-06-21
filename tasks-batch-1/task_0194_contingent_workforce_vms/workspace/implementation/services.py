"""Business-logic services: calculations, tenure rollups, time-gated sweeps, cascades."""
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import parse_iso, inclusive_days

OT_MULTIPLIER = Decimal("1.5")

EXPENSE_CAPS = {
    "TRAVEL": 50000,
    "LODGING": 30000,
    "MEALS": 7500,
    "EQUIPMENT": 100000,
    "OTHER": 20000,
}

SUBMITTAL_TERMINAL = {"HIRED", "REJECTED", "WITHDRAWN"}
DISTRIBUTION_TERMINAL = {"REVOKED"}


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- bill_rate_and_markup ---------------------------------------------------

def derive_bill_and_markup(program, pay_rate_cents, bill_rate_cents):
    """Returns (bill_rate_cents, effective_markup_pct).

    Step 1: if bill_rate supplied -> use verbatim; else derive from default markup.
    Step 2: effective_markup_pct = bill/pay - 1, kept as exact ratio (a float for JSON).
    """
    if bill_rate_cents is None:
        markup = Decimal(str(program["default_markup_pct"]))
        bill = round_half_up(Decimal(pay_rate_cents) * (Decimal(1) + markup))
    else:
        bill = int(bill_rate_cents)
    effective = (Decimal(bill) / Decimal(pay_rate_cents)) - Decimal(1)
    return bill, effective


def markup_as_number(effective_decimal):
    """Render the exact-ratio markup as a JSON number, trimming trailing zeros."""
    f = float(effective_decimal)
    return f


# --- timesheet_amounts ------------------------------------------------------

def timesheet_amounts(regular_hours, overtime_hours, pay_rate_cents, bill_rate_cents):
    reg = Decimal(str(regular_hours))
    ot = Decimal(str(overtime_hours))
    pay = Decimal(pay_rate_cents)
    bill = Decimal(bill_rate_cents)

    pay_regular = round_half_up(reg * pay)
    pay_ot = round_half_up(ot * pay * OT_MULTIPLIER)
    pay_amount = pay_regular + pay_ot

    bill_regular = round_half_up(reg * bill)
    bill_ot = round_half_up(ot * bill * OT_MULTIPLIER)
    bill_amount = bill_regular + bill_ot
    return pay_amount, bill_amount


# --- expense_reimbursement --------------------------------------------------

def expense_reimbursement(category, amount_cents):
    cap = EXPENSE_CAPS[category]
    return min(int(amount_cents), cap)


# --- worker_tenure_rollup ---------------------------------------------------

def compute_engaged_days(assignment, program):
    """Inclusive engaged-day count for one assignment relative to current clock or end."""
    start = parse_iso(assignment["start_date"], "start_date")
    if assignment["engagement_status"] == "ENDED" and assignment.get("actual_end_date"):
        end = parse_iso(assignment["actual_end_date"], "actual_end_date")
    else:
        end = parse_iso(program["current_clock"], "current_clock")
    days = inclusive_days(start, end)
    return days if days > 0 else 0


def worker_assignments(worker_id):
    out = [a for a in db.assignments.values() if a["worker_profile_id"] == worker_id]
    # Process in ascending start_date, then created_at (via _seq) order.
    out.sort(key=lambda a: (parse_iso(a["start_date"], "start_date"), a["_seq"]))
    return out


def derive_tenure_status(cumulative, program):
    if cumulative >= program["coemployment_tenure_limit_days"]:
        return "BREACH"
    if cumulative >= program["tenure_warning_threshold_days"]:
        return "WARNING"
    return "CLEAR"


def rollup_worker(worker, program):
    """Recompute a worker's cumulative_engaged_days and tenure_status. Mutates the worker."""
    total = 0
    for a in worker_assignments(worker["id"]):
        a_program = db.programs.get(a["program_id"], program)
        ed = compute_engaged_days(a, a_program)
        # Persist engaged_days on the assignment (frozen if ENDED).
        if a["engagement_status"] != "ENDED":
            a["engaged_days"] = ed
        total += a["engaged_days"]
    new_status = derive_tenure_status(total, program)
    changed = (worker.get("cumulative_engaged_days") != total
               or worker.get("tenure_status") != new_status)
    worker["cumulative_engaged_days"] = total
    worker["tenure_status"] = new_status
    if changed:
        db.touch(worker)
    return new_status


def offboard_rollup(assignment, program):
    """Recompute the affected worker after an offboard."""
    worker = db.workers.get(assignment["worker_profile_id"])
    if worker is not None:
        rollup_worker(worker, program)


# --- distribution_waterfall -------------------------------------------------

def compute_release_offsets(distinct_tiers, interval_hours):
    """Map each distinct tier -> release offset in hours (index * interval)."""
    sorted_tiers = sorted(set(distinct_tiers))
    return {tier: idx * interval_hours for idx, tier in enumerate(sorted_tiers)}


def add_hours_iso(base_iso, hours):
    from datetime import timedelta
    base = parse_iso(base_iso, "current_clock")
    result = base + timedelta(hours=hours)
    return result.strftime("%Y-%m-%dT%H:%M:%S.") + f"{result.microsecond // 1000:03d}Z"


# --- time-gated sweeps on advance_clock -------------------------------------

def advance_clock_sweeps(program):
    """Run release sweep, timesheet auto-approval, and tenure escalation in order."""
    clock = parse_iso(program["current_clock"], "current_clock")

    # 1) Release PENDING distributions whose released_at <= new clock.
    for dist in db.distributions.values():
        if dist["status"] == "PENDING":
            ra = parse_iso(dist["released_at"], "released_at")
            if ra <= clock:
                dist["status"] = "RELEASED"
                db.touch(dist)

    # 2) Auto-approve SUBMITTED timesheets past their approval window.
    window_days = program["timesheet_approval_window_days"]
    for ts in db.timesheets.values():
        assignment = db.assignments.get(ts["assignment_id"])
        if assignment is None or assignment["program_id"] != program["id"]:
            continue
        if ts["status"] == "SUBMITTED" and ts.get("submitted_at"):
            from datetime import timedelta
            submitted = parse_iso(ts["submitted_at"], "submitted_at")
            deadline = submitted + timedelta(days=window_days)
            if clock >= deadline:
                _approve_timesheet(ts, assignment)

    # 3) Recompute every non-ENDED worker's tenure, then escalate compliance.
    #    A worker is "non-ENDED" if it has at least one non-ENDED assignment OR
    #    we recompute all to keep cumulative accurate; PRD: recompute every
    #    non-ENDED worker. We iterate workers that have any non-ENDED assignment.
    workers_to_recompute = set()
    for a in db.assignments.values():
        if a["program_id"] != program["id"]:
            continue
        if a["engagement_status"] != "ENDED":
            workers_to_recompute.add(a["worker_profile_id"])

    for wid in workers_to_recompute:
        worker = db.workers.get(wid)
        if worker is None:
            continue
        rollup_worker(worker, program)

    # Escalate compliance on each non-ENDED assignment based on the worker's total.
    for a in db.assignments.values():
        if a["program_id"] != program["id"]:
            continue
        if a["engagement_status"] == "ENDED":
            continue
        worker = db.workers.get(a["worker_profile_id"])
        if worker is None:
            continue
        cumulative = worker["cumulative_engaged_days"]
        escalate_compliance(a, cumulative, program)


def escalate_compliance(assignment, cumulative, program):
    """Drive an assignment's compliance_status forward and apply the breach safety stop."""
    prior = assignment["compliance_status"]
    limit = program["coemployment_tenure_limit_days"]
    warn = program["tenure_warning_threshold_days"]

    new_compliance = prior
    if cumulative >= limit:
        new_compliance = "TENURE_BREACH"
    elif cumulative >= warn:
        if prior in ("CLEAR", "TENURE_WARNING"):
            new_compliance = "TENURE_WARNING"

    forced_hold = False
    if new_compliance == "TENURE_BREACH" and prior != "TENURE_BREACH":
        if assignment["engagement_status"] == "ACTIVE":
            assignment["engagement_status"] = "ON_HOLD"
            forced_hold = True

    if new_compliance != prior or forced_hold:
        assignment["compliance_status"] = new_compliance
        db.touch(assignment)


# --- timesheet approval (shared by manual + auto) ---------------------------

def _approve_timesheet(ts, assignment):
    pay, bill = timesheet_amounts(
        ts["regular_hours"], ts["overtime_hours"],
        assignment["pay_rate_cents"], assignment["bill_rate_cents"],
    )
    ts["pay_amount_cents"] = pay
    ts["bill_amount_cents"] = bill
    ts["status"] = "APPROVED"
    db.touch(ts)


# --- requisition fill cascade ----------------------------------------------

def fill_cascade(requisition):
    """Cascade for a requisition that has just FILLED: revoke distributions,
    reject sibling submittals.

    PRD §3.5: the requisition's own DISTRIBUTED -> FILLED transition and its
    single version bump are applied by the hire handler as part of the one hire
    mutation; this function only propagates to the *affected records*
    (distributions, sibling submittals), each of which gets its own version
    increment per §2.8.
    """
    for dist in db.distributions.values():
        if dist["requisition_id"] == requisition["id"] and dist["status"] in ("PENDING", "RELEASED"):
            dist["status"] = "REVOKED"
            db.touch(dist)
    for sub in db.submittals.values():
        if sub["requisition_id"] == requisition["id"] and sub["status"] not in SUBMITTAL_TERMINAL:
            sub["status"] = "REJECTED"
            db.touch(sub)


def revoke_and_reject(requisition):
    """Shared close/cancel cascade: revoke non-terminal distributions, reject non-terminal submittals."""
    for dist in db.distributions.values():
        if dist["requisition_id"] == requisition["id"] and dist["status"] not in DISTRIBUTION_TERMINAL:
            dist["status"] = "REVOKED"
            db.touch(dist)
    for sub in db.submittals.values():
        if sub["requisition_id"] == requisition["id"] and sub["status"] not in SUBMITTAL_TERMINAL:
            sub["status"] = "REJECTED"
            db.touch(sub)
