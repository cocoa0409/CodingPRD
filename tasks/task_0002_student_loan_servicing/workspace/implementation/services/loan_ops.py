"""Loan transitions, capitalization, delinquency, and PSLF recount logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import db
from services import calc, serializer


# ---------- Date helpers ----------


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---------- Capitalization ----------


def capitalize_interest(
    loan: dict,
    transition: str,
    effective_on: str,
    actor_user_id: str,
    reason_code: str = "OTHER",
) -> dict:
    """Per SCAFFOLD §1.3 capitalization_amount: compute capitalizable, add to principal,
    zero interest, bump loan version. Also creates a CAPITALIZATION ServicingEvent.

    Returns the created ServicingEvent.

    `transition` is one of: 'GRACE_TO_REPAYMENT', 'DEFERMENT_TO_REPAYMENT',
    'FORBEARANCE_TO_REPAYMENT', 'DELINQUENT_TO_DEFAULT', 'EXPLICIT'.
    """
    capitalizable = loan["accrued_interest_cents"]
    if transition == "DEFERMENT_TO_REPAYMENT" and loan["loan_type"] == "DIRECT_SUBSIDIZED":
        # Subsidy held throughout deferment for DIRECT_SUBSIDIZED → capitalizable is 0
        capitalizable = 0

    loan["outstanding_principal_cents"] += capitalizable
    loan["capitalized_interest_cents"] += capitalizable
    loan["accrued_interest_cents"] = 0
    # Note: the caller is responsible for the OUTER version bump tied to the transition.
    # Capitalization itself does not double-bump; PRD §2.7 says the cap step ends with
    # version increment, but the surrounding transition is the unit that bumps version.

    # Always emit a CAPITALIZATION ServicingEvent for the audit log
    eid = db.new_id()
    event = {
        "id": eid,
        "loan_id": loan["id"],
        "event_type": "CAPITALIZATION",
        "effective_on": effective_on,
        "reason_code": reason_code,
        "created_by_user_id": actor_user_id,
        "created_at": db.now_iso(),
    }
    db.servicing_events[eid] = event
    return event


# ---------- Loan transitions (the post-validation work) ----------


def transition_grace(loan: dict, effective_on: str, user_id: str) -> None:
    loan["status"] = "GRACE"
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_grace_to_repayment(loan: dict, effective_on: str, user_id: str) -> None:
    # First flip the status (so subsidy_active becomes false on subsidized loans BEFORE
    # capitalization fires the next steps); per §3.2 subsidy flips at REPAYMENT_BEGIN.
    loan["status"] = "REPAYMENT"
    capitalize_interest(loan, "GRACE_TO_REPAYMENT", effective_on, user_id, "GRACE_EXPIRY")
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_to_deferment(loan: dict, effective_on: str, user_id: str) -> None:
    loan["status"] = "DEFERMENT"
    loan["days_delinquent"] = 0
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_deferment_to_repayment(loan: dict, effective_on: str, user_id: str) -> None:
    loan["status"] = "REPAYMENT"
    capitalize_interest(loan, "DEFERMENT_TO_REPAYMENT", effective_on, user_id)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_to_forbearance(loan: dict, effective_on: str, user_id: str, reason_code: str) -> None:
    """REPAYMENT or DELINQUENT → FORBEARANCE."""
    was_delinquent = loan["status"] == "DELINQUENT"
    loan["status"] = "FORBEARANCE"
    loan["days_delinquent"] = 0
    if was_delinquent:
        # Close the open DelinquencyRecord with FORBORNE
        d = serializer.open_delinquency_for_loan(loan["id"])
        if d:
            d["closed_on"] = effective_on
            d["outcome"] = "FORBORNE"
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_forbearance_to_repayment(loan: dict, effective_on: str, user_id: str) -> None:
    loan["status"] = "REPAYMENT"
    capitalize_interest(loan, "FORBEARANCE_TO_REPAYMENT", effective_on, user_id)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_to_default(loan: dict, effective_on: str, user_id: str, reason_code: str = "MISSED_PAYMENTS_270D") -> None:
    """DELINQUENT → DEFAULT. Closes open delinquency, capitalizes, expires ACTIVE plan."""
    # Capitalize full interest
    capitalize_interest(loan, "DELINQUENT_TO_DEFAULT", effective_on, user_id, reason_code)
    loan["status"] = "DEFAULT"
    # Close open delinquency
    d = serializer.open_delinquency_for_loan(loan["id"])
    if d:
        d["closed_on"] = effective_on
        d["outcome"] = "DEFAULTED"
    # Expire any ACTIVE plan
    active = serializer.active_plan_for_loan(loan["id"])
    if active:
        active["status"] = "EXPIRED"
        active["terminated_on_clock"] = db.get_clock_date()
        serializer.bump_plan(active)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_to_paid_off(loan: dict, effective_on: str, user_id: str) -> None:
    """Cascade from a payment that zeroes out the loan."""
    loan["status"] = "PAID_OFF"
    loan["outstanding_principal_cents"] = 0
    loan["accrued_interest_cents"] = 0
    loan["days_delinquent"] = 0
    # Close any open delinquency
    d = serializer.open_delinquency_for_loan(loan["id"])
    if d:
        d["closed_on"] = effective_on
        d["outcome"] = "CURED"
    # Expire any ACTIVE plan
    active = serializer.active_plan_for_loan(loan["id"])
    if active:
        active["status"] = "EXPIRED"
        active["terminated_on_clock"] = db.get_clock_date()
        serializer.bump_plan(active)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_delinquent_to_repayment(loan: dict, effective_on: str, user_id: str) -> None:
    """Cure via payment that covers full arrears."""
    loan["status"] = "REPAYMENT"
    loan["days_delinquent"] = 0
    d = serializer.open_delinquency_for_loan(loan["id"])
    if d:
        d["closed_on"] = effective_on
        d["outcome"] = "CURED"
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


def transition_to_discharged(loan: dict, effective_on: str, user_id: str) -> None:
    """Cascade from approved DischargeApplication. Preserves balances per §3.2."""
    loan["status"] = "DISCHARGED"
    # Close any open delinquency with CURED
    d = serializer.open_delinquency_for_loan(loan["id"])
    if d:
        d["closed_on"] = effective_on
        d["outcome"] = "CURED"
    # Expire any ACTIVE plan
    active = serializer.active_plan_for_loan(loan["id"])
    if active:
        active["status"] = "EXPIRED"
        active["terminated_on_clock"] = db.get_clock_date()
        serializer.bump_plan(active)
    serializer.bump_loan(loan)
    serializer.recompute_borrower(loan["borrower_id"])


# ---------- PSLF Recount ----------


def _payment_in_cert_window(payment: dict, certs: list) -> bool:
    posted = payment["posted_on"]
    for c in certs:
        if c["status"] != "APPROVED":
            continue
        if not serializer.compute_pslf_qualifying_employer(c):
            continue
        if c["period_start_on"] <= posted <= c["period_end_on"]:
            return True
    return False


def _active_plan_on_date(loan_id: str, on_date: str):
    """Return the RepaymentPlan that was ACTIVE on the given simulation-clock date.

    Uses `activated_on_clock` (and `terminated_on_clock` when set) — these track
    plan activation in simulation-clock time, distinct from wall-clock created_at.
    A plan was active on `on_date` iff:
        activated_on_clock <= on_date AND (terminated_on_clock is None OR terminated_on_clock > on_date)
    """
    candidates = [p for p in db.repayment_plans.values() if p["loan_id"] == loan_id]
    for p in candidates:
        activated = p.get("activated_on_clock") or p["created_at"][:10]
        terminated = p.get("terminated_on_clock")
        if activated <= on_date and (terminated is None or terminated > on_date):
            return p
    return None


def _payment_qualifies_pslf(payment: dict, borrower_id: str) -> bool:
    """Per SCAFFOLD §1.3 pslf_qualifying_payment (relaxed lookback variant)."""
    if payment["status"] != "POSTED":
        return False

    # Find the loan + its borrower
    loan = db.loans.get(payment["loan_id"])
    if loan is None or loan["borrower_id"] != borrower_id:
        return False

    # (b) cert window
    certs = [c for c in db.employment_certifications.values() if c["borrower_id"] == borrower_id]
    if not _payment_in_cert_window(payment, certs):
        return False

    # (c) ACTIVE plan with eligible plan_type on posted_on
    plan = _active_plan_on_date(payment["loan_id"], payment["posted_on"])
    if plan is None:
        return False
    if plan["plan_type"] not in {"STANDARD_10YR", "IBR", "PAYE", "SAVE"}:
        return False

    # (d) amount >= monthly_payment_cents in force
    if payment["amount_cents"] < plan["monthly_payment_cents"]:
        return False

    # (e) on-time window: posted_on within [scheduled_due_date, scheduled_due_date + 15d]
    # We compute the "scheduled due date for the cycle containing posted_on" by walking
    # forward from the plan's creation date in monthly steps. The first due date is
    # plan_created + ~30 days; we approximate via month addition.
    if not _payment_on_time_for_cycle(payment["posted_on"], plan):
        return False

    return True


def _payment_on_time_for_cycle(posted_on_str: str, plan: dict) -> bool:
    """Returns True iff posted_on falls in [due_date, due_date + 15d] for the cycle
    that contains posted_on. Cycle due dates are monthly from plan activation date.
    """
    activation_str = plan.get("activated_on_clock") or plan["created_at"][:10]
    activation = parse_date(activation_str)
    posted = parse_date(posted_on_str)
    if posted < activation:
        return False
    # Find the most recent due date <= posted, with cycles every month from activation.
    # Use simple month-add: for month k after activation, due_date = activation + k months.
    months_since = (posted.year - activation.year) * 12 + (posted.month - activation.month)
    # Walk back/forward to find the cycle whose due_date <= posted < next_due_date
    def add_months(d: date, n: int) -> date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        # clamp day to valid month-end
        try:
            return date(y, m, d.day)
        except ValueError:
            # day out of range — clamp to last day of month
            if m == 12:
                next_first = date(y + 1, 1, 1)
            else:
                next_first = date(y, m + 1, 1)
            return next_first - timedelta(days=1)

    candidate = add_months(activation, months_since)
    if candidate > posted:
        months_since -= 1
        candidate = add_months(activation, months_since)
    # candidate is the cycle's due_date that contains posted_on
    delta = (posted - candidate).days
    return 0 <= delta <= 15


def recount_pslf_tracker(tracker: dict) -> None:
    """Recompute qualifying_payment_count for the borrower per SCAFFOLD §1.3.
    Flips status TRACKING → ELIGIBLE_FOR_FORGIVENESS at threshold, or back to
    TRACKING if previously ELIGIBLE and count drops below threshold.
    """
    borrower_id = tracker["borrower_id"]
    count = 0
    # Walk every Payment for every Loan of this borrower, set pslf_qualifying flag.
    loan_ids = {l["id"] for l in db.loans.values() if l["borrower_id"] == borrower_id}
    for payment in db.payments.values():
        if payment["loan_id"] not in loan_ids:
            continue
        q = _payment_qualifies_pslf(payment, borrower_id)
        payment["pslf_qualifying"] = q
        if q:
            count += 1

    tracker["qualifying_payment_count"] = count
    tracker["last_recount_on"] = db.get_clock_date()
    # Status transitions
    if tracker["status"] == "TRACKING":
        if count >= tracker["required_payment_count"]:
            tracker["status"] = "ELIGIBLE_FOR_FORGIVENESS"
    elif tracker["status"] == "ELIGIBLE_FOR_FORGIVENESS":
        if count < tracker["required_payment_count"]:
            tracker["status"] = "TRACKING"
    serializer.bump_tracker(tracker)


def maybe_recount_for_borrower(borrower_id: str) -> None:
    t = serializer.tracker_for_borrower(borrower_id)
    if t is None:
        return
    # Don't recount terminal states (FORGIVEN/DENIED)
    if t["status"] in {"FORGIVEN", "DENIED"}:
        return
    recount_pslf_tracker(t)


# ---------- Clock advance: delinquency and default ----------


def _generate_due_dates_for_loan(loan_id: str, plan: dict, up_to_date: date) -> list:
    """Compute monthly due dates from plan activation up to (inclusive) up_to_date.
    First due date = activation + 1 month.
    """
    activation_str = plan.get("activated_on_clock") or plan["created_at"][:10]
    activation = parse_date(activation_str)

    def add_months(d: date, n: int) -> date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        try:
            return date(y, m, d.day)
        except ValueError:
            if m == 12:
                next_first = date(y + 1, 1, 1)
            else:
                next_first = date(y, m + 1, 1)
            return next_first - timedelta(days=1)

    dates = []
    k = 1
    while True:
        d = add_months(activation, k)
        if d > up_to_date:
            break
        dates.append(d)
        k += 1
        if k > 600:  # safety guard
            break
    return dates


def _due_satisfied_by_payment(loan_id: str, due_date: date, monthly_cents: int) -> bool:
    """True if any POSTED payment with amount_cents >= monthly_cents has
    posted_on in [due_date, due_date + 15d]."""
    lo = due_date
    hi = due_date + timedelta(days=15)
    for p in db.payments.values():
        if p["loan_id"] != loan_id or p["status"] != "POSTED":
            continue
        if p["amount_cents"] < monthly_cents:
            continue
        posted = parse_date(p["posted_on"])
        if lo <= posted <= hi:
            return True
    return False


def advance_clock(target_iso_date: str) -> None:
    """Set the clock to target_iso_date and drive all elapsed-day side effects.

    target_iso_date is a YYYY-MM-DD string. The endpoint accepts ISO 8601 datetime,
    we normalize the date portion only.
    """
    target = parse_date(target_iso_date)
    current = parse_date(db.get_clock_date())
    if target <= current:
        # Caller should have validated; do nothing
        return

    # Iterate day-by-day so daily accrual fires per elapsed day in order.
    day = current
    while day < target:
        day += timedelta(days=1)
        # Daily accrual: every non-terminal loan with subsidy_active=false accrues.
        for loan in db.loans.values():
            if loan["status"] in {"PAID_OFF", "DISCHARGED"}:
                continue
            if serializer.compute_subsidy_active(loan):
                continue
            inc = calc.daily_interest_increment(loan["outstanding_principal_cents"], loan["interest_rate_bps"])
            if inc:
                loan["accrued_interest_cents"] += inc
                # Daily accrual itself does not bump version per §2.7 — interest accrual
                # is silent; only capitalization/transition steps bump version.

    # Now commit the clock
    db.set_clock_date(target_iso_date)

    # After clock advance, scan for delinquency transitions on REPAYMENT loans
    # We process each loan that has an ACTIVE plan with monthly_payment_cents > 0
    # and find the earliest missed due date.
    for loan in list(db.loans.values()):
        if loan["status"] != "REPAYMENT":
            continue
        plan = serializer.active_plan_for_loan(loan["id"])
        if plan is None or plan["monthly_payment_cents"] <= 0:
            continue
        due_dates = _generate_due_dates_for_loan(loan["id"], plan, target)
        for due in due_dates:
            if not _due_satisfied_by_payment(loan["id"], due, plan["monthly_payment_cents"]):
                # Crossed unsatisfied. Transition to DELINQUENT.
                loan["status"] = "DELINQUENT"
                loan["days_delinquent"] = (target - due).days
                # Open a new DelinquencyRecord
                did = db.new_id()
                rec = {
                    "id": did,
                    "loan_id": loan["id"],
                    "opened_on": fmt_date(due),
                    "closed_on": None,
                    "cumulative_days": (target - due).days,
                    "outcome": "OPEN",
                    "created_at": db.now_iso(),
                }
                db.delinquency_records[did] = rec
                serializer.bump_loan(loan)
                serializer.recompute_borrower(loan["borrower_id"])
                break  # only handle earliest missed due date

    # Update cumulative_days for all open delinquencies; if >= 270, default the loan
    for rec in list(db.delinquency_records.values()):
        if rec["outcome"] != "OPEN":
            continue
        opened = parse_date(rec["opened_on"])
        rec["cumulative_days"] = (target - opened).days
        if rec["cumulative_days"] >= 270:
            loan = db.loans.get(rec["loan_id"])
            if loan and loan["status"] == "DELINQUENT":
                transition_to_default(loan, target_iso_date, "system", "MISSED_PAYMENTS_270D")

    # Update days_delinquent on each currently-delinquent loan
    for loan in db.loans.values():
        if loan["status"] == "DELINQUENT":
            d = serializer.open_delinquency_for_loan(loan["id"])
            if d:
                loan["days_delinquent"] = d["cumulative_days"]


# ---------- Arrears check for cure ----------


def covered_missed_due_dates(loan_id: str, rec: dict, plan: dict) -> int:
    """Number of missed scheduled monthly payment due dates since rec.opened_on up to today's clock.
    Used to compute the arrears amount required for cure.
    """
    opened = parse_date(rec["opened_on"])
    today = parse_date(db.get_clock_date())
    # Build cycle due dates from plan activation; count those in [opened, today]
    candidates = _generate_due_dates_for_loan(loan_id, plan, today)
    return sum(1 for d in candidates if opened <= d <= today)


def payment_cures_arrears(loan: dict, payment_amount: int) -> bool:
    """A payment cures arrears iff amount_cents >= every missed scheduled monthly
    payment since DelinquencyRecord.opened_on (i.e., >= count_missed * monthly_payment_cents).
    """
    rec = serializer.open_delinquency_for_loan(loan["id"])
    if rec is None:
        return False
    plan = serializer.active_plan_for_loan(loan["id"])
    if plan is None or plan["monthly_payment_cents"] <= 0:
        return False
    missed = covered_missed_due_dates(loan["id"], rec, plan)
    if missed < 1:
        missed = 1
    arrears = missed * plan["monthly_payment_cents"]
    return payment_amount >= arrears
