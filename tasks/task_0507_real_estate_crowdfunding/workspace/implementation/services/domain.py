"""Shared domain helpers: lookups, recompute cascades, ytd recompute."""
from decimal import Decimal

import db
from errors import err
from services import calc


# ---- Lookups (raise ERR_NOT_FOUND when missing) ----
def get_fund(fund_id):
    e = db.funds.get(fund_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "Fund not found")
    return e


def get_share_class(sc_id):
    e = db.share_classes.get(sc_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "ShareClass not found")
    return e


def get_project(pid):
    e = db.projects.get(pid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    return e


def get_investor(iid):
    e = db.investors.get(iid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Investor not found")
    return e


def get_subscription(sid):
    e = db.subscriptions.get(sid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Subscription not found")
    return e


def get_holding(hid):
    e = db.holdings.get(hid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Holding not found")
    return e


def get_distribution(did):
    e = db.distributions.get(did)
    if e is None:
        raise err("ERR_NOT_FOUND", "Distribution not found")
    return e


def get_redemption(rid):
    e = db.redemption_requests.get(rid)
    if e is None:
        raise err("ERR_NOT_FOUND", "RedemptionRequest not found")
    return e


# ---- Fund relationships ----
def share_class_ids_of_fund(fund_id):
    return {sc["id"] for sc in db.share_classes.values() if sc["fund_id"] == fund_id}


def holdings_of_fund(fund_id):
    sc_ids = share_class_ids_of_fund(fund_id)
    return [h for h in db.holdings.values() if h["share_class_id"] in sc_ids]


def fund_of_share_class(sc):
    return get_fund(sc["fund_id"])


def fund_of_holding(holding):
    sc = get_share_class(holding["share_class_id"])
    return get_fund(sc["fund_id"])


# ---- Derived-field recompute (PRD §2.8, §3.1) ----
def recompute_fund_derived(fund):
    """Recompute shares_outstanding and nav_per_share_cents after a cash event."""
    holds = holdings_of_fund(fund["id"])
    fund["shares_outstanding"] = calc.fund_shares_outstanding(holds)
    fund["nav_per_share_cents"] = calc.nav_per_share(
        fund["gross_asset_value_cents"],
        fund["total_liabilities_cents"],
        fund["shares_outstanding"],
    )


# ---- ytd_invested recompute (calc ytd_invested) ----
def recompute_ytd_invested(investor):
    year = db.clock_year()
    total = 0
    for s in db.subscriptions.values():
        if (s["investor_id"] == investor["id"]
                and s["status"] == "SETTLED"
                and s["tax_year"] == year):
            total += s["funded_amount_cents"]
    investor["ytd_invested_cents"] = total
