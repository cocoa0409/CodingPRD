"""Policy reconciliation, cash-value ledger, and lazy time-based transitions.

PRD §2.7 (two independent clocks), §2.8 (cash-value reconciliation),
§3.7-§3.8 (premiums, grace, lapse, reinstatement, termination, contestability).
"""
import calculations
import validate
from clock import clock
from db import store
from models import make_record, touch


def product_for_policy(policy):
    app = store.applications[policy["application_id"]]
    return store.products[app["product_id"]]


def policy_cash_entries(policy_id):
    entries = [e for e in store.cash_value_entries.values() if e["policy_id"] == policy_id]
    entries.sort(key=lambda e: e["_seq"])
    return entries


def add_cash_value_entry(policy, amount_cents, reason):
    rec = make_record("CashValueEntry", {
        "policy_id": policy["id"],
        "amount_cents": amount_cents,
        "reason": reason,
    })
    store.cash_value_entries[rec["id"]] = rec
    return rec


def reconcile(policy):
    """Recompute gross_cash_value, outstanding_loan_principal, net_cash_value.

    Does NOT bump version on its own — callers bump policy.version once per
    business event (PRD §2.8 folds reconciliation into the triggering mutation).
    """
    gross = sum(e["amount_cents"] for e in policy_cash_entries(policy["id"]))
    outstanding = sum(
        loan["principal_cents"]
        for loan in store.policy_loans.values()
        if loan["policy_id"] == policy["id"] and loan["status"] == "ACTIVE"
    )
    policy["gross_cash_value_cents"] = gross
    policy["outstanding_loan_principal_cents"] = outstanding
    policy["net_cash_value_cents"] = max(0, gross - outstanding)


def accrue_cash_value(policy):
    """Append a PREMIUM_ACCRUAL entry based on cumulative_premium_paid_cents."""
    product = product_for_policy(policy)
    increment = calculations.accrual_increment(
        policy["cumulative_premium_paid_cents"], product["cash_value_accrual_rate_bps"]
    )
    add_cash_value_entry(policy, increment, "PREMIUM_ACCRUAL")
    reconcile(policy)


# ---- lazy time-based transitions ------------------------------------------

def reconcile_policy_time(policy):
    """Reconcile lifecycle and contestability against the current clock.

    Observed lazily on any read/write that touches the policy. Each status
    change is a mutation: bumps version + updated_at (PRD §2.7).
    """
    product = product_for_policy(policy)
    now_date = clock.now().date()
    changed = False

    # --- funding lifecycle ---
    # Loop so a single large clock jump can walk IN_FORCE -> GRACE -> LAPSED
    # -> TERMINATED in one reconciliation pass.
    while True:
        status = policy["lifecycle_status"]
        if status == "IN_FORCE":
            due = _d(policy["next_premium_due_date"])
            if now_date > due:
                policy["lifecycle_status"] = "GRACE"
                changed = True
                continue
            break
        elif status == "GRACE":
            due = _d(policy["next_premium_due_date"])
            lapse_at = validate.add_days(due, product["grace_period_days"])
            if now_date > lapse_at:
                # Forfeit accumulated cash value.
                gross = policy["gross_cash_value_cents"]
                if gross != 0:
                    add_cash_value_entry(policy, -gross, "LAPSE_FORFEIT")
                    reconcile(policy)
                policy["lifecycle_status"] = "LAPSED"
                changed = True
                continue
            break
        elif status == "LAPSED":
            issue = _d(policy["issue_date"])
            terminate_at = validate.add_years(issue, 3)
            if now_date > terminate_at:
                policy["lifecycle_status"] = "TERMINATED"
                changed = True
                continue
            break
        else:
            break

    # --- contestability (independent dimension) ---
    if policy["contestability_status"] == "CONTESTABLE":
        flip_at = validate.add_months(_d(policy["_contestability_start"]),
                                      product["contestability_months"])
        if now_date >= flip_at:
            policy["contestability_status"] = "INCONTESTABLE"
            changed = True

    if changed:
        touch(policy)
    return changed


def _d(date_str):
    from datetime import date
    return date.fromisoformat(date_str)
