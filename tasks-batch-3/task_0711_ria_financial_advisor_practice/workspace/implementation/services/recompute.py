"""Derived-field reconciliation. Each recomputation is a mutation of the
resource it writes (refreshes updated_at, bumps version) per PRD §2.4."""

from datetime import date

from db import db
from services import calculations as calc
from services.common import touch


# --------------------------------------------------------------------------- #
# Household aggregation (PRD §2.8, §3.3)
# --------------------------------------------------------------------------- #
def _household_accounts(household_id):
    return [a for a in db.accounts.values() if a["household_id"] == household_id]


def recompute_household_aggregation(household, include_tier=True):
    """Recompute billable_aum_cents, aggregated_aum_cents, and (optionally)
    breakpoint_tier_index. Always a mutation of the household row."""
    accounts = _household_accounts(household["id"])
    # PRD §3.3: "a frozen account's value is still aggregated into
    # aggregated_aum_cents but is no longer billable, so the two figures diverge."
    # Aggregated spans ACTIVE and FROZEN accounts; billable is restricted to
    # ACTIVE, billable, not-held-away accounts (PRD §2.8).
    aggregated = sum(
        a["market_value_cents"] for a in accounts
        if a["status"] in {"ACTIVE", "FROZEN"}
    )
    billable = sum(
        a["market_value_cents"] for a in accounts
        if a["status"] == "ACTIVE" and a["billable"] and not a["held_away"]
    )
    household["billable_aum_cents"] = billable
    household["aggregated_aum_cents"] = aggregated
    if include_tier:
        schedule = db.fee_schedules.get(household["fee_schedule_id"])
        tiers = schedule["tiers"] if schedule else []
        household["breakpoint_tier_index"] = calc.tier_index(aggregated, tiers)
    touch(household)


# --------------------------------------------------------------------------- #
# Account drift (PRD §3.3)
# --------------------------------------------------------------------------- #
def _approved_ips_for_client(client_id):
    for ips in db.investment_policy_statements.values():
        if ips["client_id"] == client_id and ips["status"] == "APPROVED":
            return ips
    return None


def _model_equity_pct_for_account(account):
    ips = _approved_ips_for_client(account["client_id"])
    if not ips:
        return None
    portfolio = db.portfolios.get(ips["target_portfolio_id"])
    if not portfolio:
        return None
    return portfolio["model_equity_pct"]


def recompute_account_drift(account):
    """Recompute drift_bps and rebalance_flagged. Mutates the account."""
    model_pct = _model_equity_pct_for_account(account)
    if model_pct is None:
        account["drift_bps"] = 0
        account["rebalance_flagged"] = False
    else:
        d = calc.drift_bps(
            account["market_value_cents"],
            account["equity_value_cents"],
            model_pct,
        )
        ips = _approved_ips_for_client(account["client_id"])
        tolerance = ips["drift_tolerance_bps"]
        account["drift_bps"] = d
        account["rebalance_flagged"] = d >= tolerance
    touch(account)


# --------------------------------------------------------------------------- #
# Goal funding (PRD §3.6)
# --------------------------------------------------------------------------- #
def _plan_goals(plan_id):
    return [g for g in db.goals.values() if g["plan_id"] == plan_id]


def recompute_goal(goal, plan):
    """Recompute a single goal's funded_ratio_bps and on_track. Mutates goal."""
    today = db.clock_date()
    target_date = date.fromisoformat(goal["target_date"])
    if plan["lifecycle_status"] == "ACTIVE":
        n = calc.months_between(today, target_date)
        pv = calc.projected_value_cents(
            goal["current_amount_cents"],
            plan["monthly_contribution_cents"],
            plan["assumed_annual_return_bps"],
            n,
        )
    else:  # actual variant (DRAFT or otherwise not ACTIVE)
        pv = goal["current_amount_cents"]
    ratio = calc.funded_ratio_bps(pv, goal["target_amount_cents"])
    goal["funded_ratio_bps"] = ratio
    goal["on_track"] = ratio >= calc.BPS_FULL
    touch(goal)


def recompute_plan_goals(plan):
    for g in _plan_goals(plan["id"]):
        recompute_goal(g, plan)
