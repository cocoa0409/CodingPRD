"""Entity serializers. Computed fields are derived fresh on every read."""
from db import pub
import services as svc


def customer(c):
    return pub(c)


def contract(c):
    out = pub(c)
    billed, recognized, deferred, asset = svc.balances(c)
    out["transaction_price_cents"] = c["fixed_consideration_cents"] + c["vc_estimate_cents"]
    out["allocated_total_cents"] = svc.allocated_total(c["id"])
    out["billed_to_date_cents"] = billed
    out["recognized_to_date_cents"] = recognized
    out["deferred_revenue_balance_cents"] = deferred
    out["contract_asset_balance_cents"] = asset
    return out


def pob(p):
    out = pub(p)
    out["costs_incurred_to_date_cents"] = svc.pob_costs(p["id"])
    out["recognized_revenue_cents"] = svc.pob_recognized(p["id"])
    out["progress_pct"] = svc.progress_pct(p)
    return out


def ssp_price(s):
    return pub(s)


def estimate(e):
    return pub(e)


def modification(m):
    return pub(m)


def clause(c):
    return pub(c)


def review_task(t):
    return pub(t)


def invoice(i):
    return pub(i)


def period(p):
    out = pub(p)
    out["recognized_total_cents"] = svc.period_recognized_total(p)
    return out


def entry(e):
    return pub(e)


def cost_entry(c):
    return pub(c)


def pack(p):
    return pub(p)
