"""Covenant evaluation (PRD 3.8).  Pure integer cents, no rounding at any step."""

from db import db
from services.constants import TTM_QUARTERS


def priors_newest_first(facility_id, exclude_id=None):
    """Every other covenant test of this facility whose status is PASS, BREACH
    or WAIVED, ordered by period_end descending with created_at descending."""
    rows = [t for t in db.covenant_tests.values()
            if t["facility_id"] == facility_id
            and t["id"] != exclude_id
            and t["status"] in ("PASS", "BREACH", "WAIVED")]
    return sorted(rows, key=lambda t: (t["period_end"], t["created_at"], t["_seq"]),
                  reverse=True)


def evaluate(facility, tangible_net_worth_cents, liquidity_cents, net_income_cents,
             priors):
    breach_codes = []
    if tangible_net_worth_cents < facility["min_tangible_net_worth_cents"]:
        breach_codes.append("NET_WORTH")
    if liquidity_cents < facility["min_liquidity_cents"]:
        breach_codes.append("LIQUIDITY")

    if len(priors) >= 3:
        variant = "TTM_ROLLING"
        metric = net_income_cents + sum(p["net_income_cents"] for p in priors[:3])
    else:
        variant = "ANNUALIZED_QUARTER"
        metric = net_income_cents * TTM_QUARTERS

    if metric < facility["min_ttm_net_income_cents"]:
        breach_codes.append("PROFITABILITY")

    breach_codes.sort()
    status = "PASS" if not breach_codes else "BREACH"
    return variant, metric, breach_codes, status
