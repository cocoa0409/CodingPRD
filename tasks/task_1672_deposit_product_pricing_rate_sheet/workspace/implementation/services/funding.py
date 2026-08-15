"""Funding curves and margin analysis (PRD 3.4)."""

from datetime import date

from db import STORE, today
from errors import ApiError, ERR_MARGIN_NOT_COMPUTABLE, ERR_NO_FUNDING_CURVE
from utils import round_half_up_int


def operative_curve():
    """Latest FundingCurve with curve_date <= logical today; None if none."""
    t = today()
    best = None
    for c in STORE["curves"].values():
        d = date.fromisoformat(c["curve_date"])
        if d <= t and (best is None or date.fromisoformat(best["curve_date"]) < d):
            best = c
    return best


def funding_cost_at_term(term_months):
    """Cost of funds in bp; exact match, else linear interpolation (round half up)."""
    curve = operative_curve()
    if curve is None:
        raise ApiError(ERR_NO_FUNDING_CURVE, 422, "No operative funding curve")
    pts = sorted(curve["points"], key=lambda p: p["tenor_months"])
    if term_months > pts[-1]["tenor_months"]:
        raise ApiError(ERR_NO_FUNDING_CURVE, 422,
                       "Product tenor beyond the curve's maximum point")
    for p in pts:
        if p["tenor_months"] == term_months:
            return p["cost_bp"]
    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        if p1["tenor_months"] < term_months < p2["tenor_months"]:
            numer = (p2["cost_bp"] - p1["cost_bp"]) * (term_months - p1["tenor_months"])
            denom = p2["tenor_months"] - p1["tenor_months"]
            return p1["cost_bp"] + round_half_up_int(numer, denom)
    raise ApiError(ERR_NO_FUNDING_CURVE, 422, "No operative funding curve")


def sheet_margin(sheet, variant):
    """sheet_margin_analysis. Evaluation order pinned: (1) rate, (2) funding,
    (3) margin."""
    product = STORE["products"][sheet["product_id"]]
    if variant == "FORWARD_LOOKING":
        numer = sum(t["rate_bp"] * t["projected_balance_cents"] for t in sheet["tiers"])
        denom = sum(t["projected_balance_cents"] for t in sheet["tiers"])
        if denom == 0:
            raise ApiError(ERR_MARGIN_NOT_COMPUTABLE, 422,
                           "Projected balances sum to zero")
        weighted = round_half_up_int(numer, denom)
    else:  # REALIZED_BOOK
        rows = [
            a for a in STORE["accounts"].values()
            if a["product_id"] == sheet["product_id"]
            and a["market_code"] == sheet["market_code"]
            and a["lifecycle"] == "OPEN"
            and a["rate_source"] in ("SHEET", "PROMO", "EXCEPTION")
        ]
        denom = sum(a["balance_cents"] for a in rows)
        if not rows or denom == 0:
            raise ApiError(ERR_MARGIN_NOT_COMPUTABLE, 422,
                           "No qualifying OPEN accounts for REALIZED_BOOK margin")
        numer = sum(a["balance_cents"] * a["current_rate_bp"] for a in rows)
        weighted = round_half_up_int(numer, denom)
    funding = funding_cost_at_term(product["term_months"])
    margin = weighted - funding
    return {
        "variant": variant,
        "weighted_rate_bp": weighted,
        "funding_cost_bp": funding,
        "margin_bp": margin,
        "margin_floor_bp": sheet["margin_floor_bp"],
        "passes_floor": margin >= sheet["margin_floor_bp"],
    }
