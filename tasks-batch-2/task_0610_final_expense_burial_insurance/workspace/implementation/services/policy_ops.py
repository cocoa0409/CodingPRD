"""Policy state transitions and cascades (PRD §3.7, §3.10)."""
from datetime import timedelta

import db
from clock import get_now, parse_iso, format_iso_millis
from errors import err
from helpers import round_half_up
from services import policy_calc, ledger, timecalc

TERMINAL_COVERAGE = {"TERMINATED", "SURRENDERED", "RESCINDED"}


def do_lapse(policy, manual):
    """Lapse a policy: coverage LAPSED, payment DELINQUENT, call ACTIVE loans.

    Caller is responsible for the ACTIVE precondition and (for manual) the
    grace-expired precondition. Opens the reinstatement window from the lapse
    instant (recorded as _lapse_instant on the policy).
    """
    policy["coverage_status"] = "LAPSED"
    policy["payment_status"] = "DELINQUENT"
    policy["_lapse_instant"] = format_iso_millis(get_now())
    # CASCADE depth-3 step 2: each ACTIVE loan -> CALLED.
    for loan in db.policy_loans.values():
        if loan["policy_id"] == policy["id"] and loan["status"] == "ACTIVE":
            loan["status"] = "CALLED"
            db.touch(loan)
    db.touch(policy)


def manual_lapse(policy):
    plan = db.product_plans.get(policy["product_plan_id"])
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Policy is not ACTIVE")
    policy_calc.recompute_policy(policy)
    due = parse_iso(policy["due_date"])
    grace_end = due + timedelta(days=plan["grace_period_days"])
    if get_now() < grace_end:
        raise err("ERR_GRACE_NOT_EXPIRED", "Grace period has not yet expired")
    do_lapse(policy, manual=True)
    return policy


def reinstate(policy):
    plan = db.product_plans.get(policy["product_plan_id"])
    if policy["coverage_status"] != "LAPSED":
        raise err("ERR_INVALID_STATE", "Policy is not LAPSED")
    lapse_instant = parse_iso(policy.get("_lapse_instant"))
    window_end = lapse_instant + timedelta(days=plan["reinstatement_window_days"])
    if get_now() > window_end:
        raise err("ERR_REINSTATEMENT_WINDOW_CLOSED", "Reinstatement window has closed")
    # Back premiums must bring paid_through_date to at least the current due cycle.
    paid_through = policy_calc.compute_paid_through(policy)
    if paid_through < get_now():
        raise err("ERR_BACK_PREMIUM_DUE", "Back premiums are still due")
    policy["coverage_status"] = "ACTIVE"
    policy["payment_status"] = "CURRENT"
    # Each CALLED loan -> ACTIVE.
    for loan in db.policy_loans.values():
        if loan["policy_id"] == policy["id"] and loan["status"] == "CALLED":
            loan["status"] = "ACTIVE"
            db.touch(loan)
    policy.pop("_lapse_instant", None)
    db.touch(policy)
    return policy


def surrender(policy):
    plan = db.product_plans.get(policy["product_plan_id"])
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Policy is not ACTIVE")
    whole_years = timecalc.whole_years_between(parse_iso(policy["issue_date"]), get_now())
    if whole_years < plan["cash_value_vesting_years"]:
        raise err("ERR_CASH_VALUE_NOT_VESTED", "Cash value has not vested")
    # No claim in progress (FILED / UNDER_REVIEW / CONTESTING).
    for claim in db.claims.values():
        if claim["policy_id"] == policy["id"] and claim["status"] in (
            "FILED", "UNDER_REVIEW", "CONTESTING"
        ):
            raise err("ERR_CLAIM_IN_PROGRESS", "A claim is in progress on this policy")

    net_surrender = compute_net_surrender_value(policy, plan)

    policy["coverage_status"] = "SURRENDERED"
    # Settle each ACTIVE loan.
    for loan in db.policy_loans.values():
        if loan["policy_id"] == policy["id"] and loan["status"] == "ACTIVE":
            loan["status"] = "SETTLED"
            loan["settled_date"] = format_iso_millis(get_now())
            db.touch(loan)
    policy_calc.recompute_policy(policy)
    ledger.append(policy["id"], "BENEFIT_PAID", net_surrender, policy["net_cash_value_cents"])
    db.touch(policy)
    return policy


def compute_net_surrender_value(policy, plan):
    """Net surrender proceeds (PRD §3.10), pinned order."""
    # Step 1: gross cash value (independent of loans).
    issue = parse_iso(policy["issue_date"])
    whole_years = timecalc.whole_years_between(issue, get_now())
    vested_years = max(0, whole_years - plan["cash_value_vesting_years"])
    face_units = policy["face_amount_cents"] / 100000
    gross = int(round(plan["cash_value_factor_per_1000_cents"] * face_units * vested_years))
    # Step 2: surrender charge keyed on gross value.
    charge_pct = _surrender_charge_pct(plan, gross)
    charge_cents = round_half_up(gross * charge_pct)
    after_charge = gross - charge_cents
    # Step 3: net out the outstanding loan balance.
    outstanding = policy_calc.outstanding_loan_balance_cents(policy["id"])
    return max(0, after_charge - outstanding)


def _surrender_charge_pct(plan, gross):
    for tier in plan.get("surrender_charge_tiers", []):
        if tier["min_gross_cents"] <= gross <= tier["max_gross_cents"]:
            return tier["charge_pct"]
    return 0


def terminate_on_claim(policy, loan_offset_cents):
    """CASCADE depth-3 step 1 -> 3: Policy ACTIVE -> TERMINATED; settle loans."""
    policy["coverage_status"] = "TERMINATED"
    for loan in db.policy_loans.values():
        if loan["policy_id"] == policy["id"] and loan["status"] in ("ACTIVE", "CALLED"):
            loan["status"] = "SETTLED"
            loan["settled_date"] = format_iso_millis(get_now())
            db.touch(loan)
    db.touch(policy)
