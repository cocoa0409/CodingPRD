"""Policy computed fields, loan interest, and clock-driven reconciliation.

These functions are pure with respect to the store: they read the policy's
children (premium payments, loans) and the logical clock and recompute the
derived figures the PRD §3.5/§3.6/§3.9 describe.
"""
import db
from clock import get_now, parse_iso, format_iso_millis
from helpers import round_half_up
from services import timecalc


def posted_payments(policy_id):
    return [
        p for p in db.premium_payments.values()
        if p["policy_id"] == policy_id and p["status"] == "POSTED"
    ]


def total_premiums_paid_cents(policy_id):
    """Sum of POSTED premium amounts minus reversed ones (conserved invariant)."""
    return sum(p["amount_cents"] for p in posted_payments(policy_id))


def compute_paid_through(policy):
    """The exclusive upper bound of contiguous covered coverage from issue_date.

    Equal to issue_date when no premium has yet posted. Walk POSTED payment
    intervals sorted by coverage_start, extending the contiguous frontier as
    long as the next interval starts at or before the current frontier.
    """
    issue = parse_iso(policy["issue_date"])
    frontier = issue
    pays = posted_payments(policy["id"])
    intervals = []
    for p in pays:
        cs = parse_iso(p["coverage_start"])
        ce = parse_iso(p["coverage_end"])
        if cs is not None and ce is not None:
            intervals.append((cs, ce))
    intervals.sort(key=lambda iv: iv[0])
    extended = True
    while extended:
        extended = False
        for cs, ce in intervals:
            if cs <= frontier and ce > frontier:
                frontier = ce
                extended = True
    return frontier


def gross_cash_value_cents(policy):
    """Guaranteed cash value from full policy-years in force past vesting (ignores loans)."""
    plan = db.product_plans.get(policy["product_plan_id"])
    if plan is None:
        return 0
    issue = parse_iso(policy["issue_date"])
    whole_years = timecalc.whole_years_between(issue, get_now())
    vested_years = max(0, whole_years - plan["cash_value_vesting_years"])
    face_units = policy["face_amount_cents"] / 100000
    return int(round(plan["cash_value_factor_per_1000_cents"] * face_units * vested_years))


def loan_balance_cents(loan):
    """Outstanding principal + accrued simple interest at loan_apr (PRD §3.9)."""
    plan = _plan_for_loan(loan)
    outstanding_principal = loan["principal_cents"] - loan["repaid_principal_cents"]
    accrued = accrued_interest_cents(loan, plan)
    return outstanding_principal + accrued


def accrued_interest_cents(loan, plan=None):
    if plan is None:
        plan = _plan_for_loan(loan)
    loan_apr = plan["loan_apr"] if plan else 0
    outstanding_principal = loan["principal_cents"] - loan["repaid_principal_cents"]
    disbursed = parse_iso(loan["disbursed_date"])
    days = timecalc.whole_days_between(disbursed, get_now())
    return round_half_up(outstanding_principal * loan_apr * days / 365)


def _plan_for_loan(loan):
    policy = db.policies.get(loan["policy_id"])
    if policy is None:
        return None
    return db.product_plans.get(policy["product_plan_id"])


def outstanding_loan_balance_cents(policy_id):
    """Sum of principal + accrued interest over all ACTIVE loans."""
    total = 0
    for loan in db.policy_loans.values():
        if loan["policy_id"] == policy_id and loan["status"] == "ACTIVE":
            total += loan_balance_cents(loan)
    return total


def net_cash_value_cents(policy):
    gross = gross_cash_value_cents(policy)
    outstanding = outstanding_loan_balance_cents(policy["id"])
    return max(0, gross - outstanding)


def recompute_policy(policy):
    """Refresh all computed figures on the policy in place (does not persist version)."""
    pt = compute_paid_through(policy)
    policy["paid_through_date"] = format_iso_millis(pt)
    policy["due_date"] = format_iso_millis(pt)
    policy["total_premiums_paid_cents"] = total_premiums_paid_cents(policy["id"])
    policy["gross_cash_value_cents"] = gross_cash_value_cents(policy)
    policy["outstanding_loan_balance_cents"] = outstanding_loan_balance_cents(policy["id"])
    policy["net_cash_value_cents"] = net_cash_value_cents(policy)
    return policy


def reconcile_payment_dimension(policy):
    """Apply clock-driven payment/coverage auto-transitions (PRD §2.4, §3.6, §3.7).

    Independent of coverage where possible:
      CURRENT  -> GRACE       when due_date < clock < due_date + grace
      GRACE    -> DELINQUENT  when clock >= due_date + grace (coverage stays ACTIVE)
      ACTIVE   -> LAPSED      (auto) when clock >= due_date + grace AND the policy
                              was ALREADY DELINQUENT before this advance.

    Per PRD §3.7 the automatic lapse path fires "on a policy that is DELINQUENT":
    the GRACE->DELINQUENT transition leaves coverage ACTIVE, and the auto-lapse
    fires on a *subsequent* clock advance once the policy is already DELINQUENT.
    A payment that restores paid_through past the clock returns to CURRENT.
    Only meaningful while coverage is ACTIVE.
    """
    plan = db.product_plans.get(policy["product_plan_id"])
    if plan is None:
        return
    # Capture the payment status as it stood BEFORE this reconciling advance, so
    # we can tell whether the policy was already DELINQUENT (gating auto-lapse).
    prior_payment_status = policy.get("payment_status")
    recompute_policy(policy)
    if policy["coverage_status"] != "ACTIVE":
        return

    from datetime import timedelta

    now = get_now()
    due = parse_iso(policy["due_date"])
    grace_days = plan["grace_period_days"]
    grace_end = due + timedelta(days=grace_days)

    # If coverage is fully paid past the clock, payment is CURRENT.
    if due > now:
        policy["payment_status"] = "CURRENT"
        return

    if now >= grace_end:
        policy["payment_status"] = "DELINQUENT"
        # Auto-lapse fires only if the policy was already DELINQUENT before this
        # advance (PRD §3.7: "on a policy that is DELINQUENT"). A single advance
        # from CURRENT/GRACE lands at DELINQUENT but leaves coverage ACTIVE.
        if prior_payment_status == "DELINQUENT":
            _auto_lapse(policy)
    elif now > due:
        policy["payment_status"] = "GRACE"
    else:
        # now == due (boundary): still CURRENT (grace runs strictly after due).
        policy["payment_status"] = "CURRENT"


def _auto_lapse(policy):
    """System lapse path on clock advance (PRD §3.7). Calls loans due."""
    from services import policy_ops
    policy_ops.do_lapse(policy, manual=False)
