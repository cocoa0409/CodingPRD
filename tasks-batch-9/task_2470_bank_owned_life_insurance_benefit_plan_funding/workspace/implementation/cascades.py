"""Cascades, aggregate refreshes and the authorization hysteresis (PRD 2.10)."""

from decimal import Decimal

import calc
from store import db, ordered, touch
from util import money

ZERO = Decimal("0.00")


# ---- carrier aggregates and hysteresis ----------------------------------


def carrier_policies(carrier_id):
    return [p for p in db.policies.values() if p["carrier_id"] == carrier_id]


def refresh_carrier_totals(carrier):
    reserved = ZERO
    for request in db.purchase_requests.values():
        if request["carrier_id"] != carrier["id"]:
            continue
        if request["status"] in calc.RESERVED_REQUEST_STATUSES:
            reserved += request["reserved_premium_usd"]
    premium = ZERO
    cash_value = ZERO
    for policy in carrier_policies(carrier["id"]):
        if policy["status"] in calc.LIVE_POLICY_STATUSES:
            premium += policy["single_premium_usd"]
            cash_value += policy["cash_surrender_value_usd"]
    carrier["reserved_premium_usd"] = money(reserved)
    carrier["in_force_premium_usd"] = money(premium)
    carrier["in_force_cash_value_usd"] = money(cash_value)


def recompute_concentration(carrier):
    tier1 = calc.tier1_capital(required=False)
    if tier1 is None or tier1 == 0:
        return carrier["concentration_bps"]
    from util import bps as to_bps

    carrier["concentration_bps"] = to_bps(
        carrier["in_force_cash_value_usd"] / tier1 * 10000
    )
    return carrier["concentration_bps"]


def apply_hysteresis(carrier):
    """AUTHORIZED -> RESTRICTED at >= 1500; RESTRICTED -> AUTHORIZED at <= 1200;
    anything strictly above 1200 keeps a RESTRICTED carrier restricted."""
    concentration = carrier["concentration_bps"]
    status = carrier["status"]
    if status == "AUTHORIZED" and concentration >= calc.CARRIER_RESTRICT_BPS:
        carrier["status"] = "RESTRICTED"
    elif status == "RESTRICTED" and concentration <= calc.CARRIER_RELEASE_BPS:
        carrier["status"] = "AUTHORIZED"
    return carrier["status"] != status


def rerate_carrier(carrier, bump=True):
    """Refresh the exposure aggregates, re-derive concentration, apply the
    hysteresis and (by default) bump the carrier's version exactly once."""
    refresh_carrier_totals(carrier)
    recompute_concentration(carrier)
    apply_hysteresis(carrier)
    if bump:
        touch(carrier)
    return carrier


def rerate_all_carriers_after_snapshot():
    """Filing a capital snapshot re-rates every carrier; only carriers whose
    posture or concentration figure changed have their version incremented."""
    for carrier in db.carriers.values():
        before_bps = carrier["concentration_bps"]
        before_status = carrier["status"]
        recompute_concentration(carrier)
        apply_hysteresis(carrier)
        if carrier["concentration_bps"] != before_bps or carrier["status"] != before_status:
            touch(carrier)


def flag_watch_list(carrier):
    """Turning watch_list_flag on reopens every UNDER_REVIEW diligence file."""
    if carrier.get("watch_list_flag") is True:
        touch(carrier)
        return
    carrier["watch_list_flag"] = True
    touch(carrier)
    for review in ordered(list(db.diligence_reviews.values())):
        if review["carrier_id"] != carrier["id"]:
            continue
        if review["status"] != "UNDER_REVIEW":
            continue
        review["status"] = "INFO_REQUESTED"
        # the cascaded information request ignores INFO_REQUEST_LIMIT
        review["info_request_count"] = int(review["info_request_count"]) + 1
        touch(review)


# ---- deferred compensation plans ---------------------------------------


def recompute_plan(plan, freeze_if_critical=False, bump=True):
    totals = calc.plan_totals(plan)
    plan["accrual_liability_usd"] = totals["accrual_liability_usd"]
    plan["pbo_liability_usd"] = totals["pbo_liability_usd"]
    plan["matched_cash_value_usd"] = totals["matched_cash_value_usd"]
    ratio = calc.funded_ratio_bps(
        totals["matched_cash_value_usd"], totals["accrual_liability_usd"]
    )
    plan["funded_ratio_bps"] = ratio
    plan["funding_posture"] = calc.funding_posture(ratio)
    if freeze_if_critical and plan["funding_posture"] == "CRITICAL" and plan["status"] == "ACTIVE":
        plan["status"] = "FROZEN"
    if bump:
        touch(plan)
    return plan


def unmatch_policy_from_plans(policy):
    """Third hop of the distribute / execute-surrender cascade."""
    affected_plan_ids = []
    for liability in ordered(list(db.nqdc_liabilities.values())):
        if liability.get("matched_policy_id") != policy["id"]:
            continue
        liability["matched_policy_id"] = None
        touch(liability)
        if liability["nqdc_plan_id"] not in affected_plan_ids:
            affected_plan_ids.append(liability["nqdc_plan_id"])
    for plan_id in affected_plan_ids:
        plan = db.nqdc_plans.get(plan_id)
        if plan is not None:
            recompute_plan(plan, freeze_if_critical=True)
