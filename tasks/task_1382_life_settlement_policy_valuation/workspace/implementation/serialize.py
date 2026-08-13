"""Entity serialization: native store dicts -> API payloads.

Internal keys (prefixed with "_") are dropped; datetimes/dates are rendered
as ISO 8601 strings. Computed-on-read fields (age_years, in_contestability,
investor_shares) are injected here.
"""

from datetime import date, datetime

import calc
from db import store
from util import fmt_dt


def _conv(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return [_conv(x) for x in v]
    if isinstance(v, dict):
        return {k: _conv(x) for k, x in v.items()}
    return v


def pub(entity):
    return {k: _conv(v) for k, v in entity.items() if not k.startswith("_")}


def ser_broker(e):
    return pub(e)


def ser_investor(e):
    return pub(e)


def ser_insured(e):
    d = pub(e)
    d["age_years"] = calc.age_years(e["date_of_birth"], store.clock.date())
    return d


def ser_license(e):
    return pub(e)


def ser_policy(e):
    d = pub(e)
    d["in_contestability"] = calc.policy_in_contestability(e, store.clock.date())
    return d


def ser_case(e):
    return pub(e)


def ser_screening(e):
    return pub(e)


def ser_le_report(e):
    return pub(e)


def ser_offer(e):
    return pub(e)


def ser_package(e):
    return pub(e)


def ser_escrow(e):
    return pub(e)


def ser_disbursement(e):
    return pub(e)


def ser_schedule(e):
    return pub(e)


def ser_payment(e):
    return pub(e)


def ser_tracking_event(e):
    return pub(e)


def ser_death_claim(e):
    return pub(e)


def ser_portfolio(e):
    return pub(e)


def ser_snapshot(e):
    d = pub(e)
    pf = store.portfolios.get(e["portfolio_id"])
    d["investor_shares"] = calc.investor_shares(pf, e["nav_cents"]) if pf else []
    return d
