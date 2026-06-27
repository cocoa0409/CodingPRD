"""Serialize internal entity dicts into API output shape.

Internal storage uses Decimal for share quantities (4 dp) and dividend rates.
On output, shares/rates serialize as JSON numbers. Money stays integer cents.
"""
from decimal import Decimal


def _num(v):
    """Serialize a Decimal share/rate to a JSON number, trimming to float."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        # 4 dp shares: render as float
        f = float(v)
        return f
    return v


def _common(e, full=True):
    out = {
        "id": e["id"],
        "created_at": e["created_at"],
    }
    if full:
        out["updated_at"] = e["updated_at"]
        out["version"] = e["version"]
    return out


def fund(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "vehicle_type": e["vehicle_type"],
        "status": e["status"],
        "gross_asset_value_cents": e["gross_asset_value_cents"],
        "total_liabilities_cents": e["total_liabilities_cents"],
        "shares_outstanding": _num(e["shares_outstanding"]),
        "nav_per_share_cents": e["nav_per_share_cents"],
        "total_capital_cents": e["total_capital_cents"],
        "current_valuation_seq": e["current_valuation_seq"],
    })
    return out


def share_class(e):
    out = _common(e)
    out.update({
        "fund_id": e["fund_id"],
        "class_code": e["class_code"],
        "min_investment_cents": e["min_investment_cents"],
        "mgmt_fee_bps": e["mgmt_fee_bps"],
        "accredited_only": e["accredited_only"],
        "drip_eligible": e["drip_eligible"],
        "status": e["status"],
    })
    return out


def project(e):
    out = _common(e)
    out.update({
        "fund_id": e["fund_id"],
        "name": e["name"],
        "acquisition_cost_cents": e["acquisition_cost_cents"],
        "appraised_value_cents": e["appraised_value_cents"],
        "status": e["status"],
    })
    return out


def investor(e):
    out = _common(e)
    out.update({
        "email": e["email"],
        "full_name": e["full_name"],
        "accredited_status": e["accredited_status"],
        "annual_income_cents": e["annual_income_cents"],
        "net_worth_cents": e["net_worth_cents"],
        "suitability_status": e["suitability_status"],
        "reviewed_by_user_id": e["reviewed_by_user_id"],
        "ytd_invested_cents": e["ytd_invested_cents"],
    })
    return out


def subscription(e):
    out = _common(e)
    out.update({
        "investor_id": e["investor_id"],
        "share_class_id": e["share_class_id"],
        "funded_amount_cents": e["funded_amount_cents"],
        "drip_elected": e["drip_elected"],
        "status": e["status"],
        "provisional_nav_cents": e["provisional_nav_cents"],
        "settled_nav_cents": e["settled_nav_cents"],
        "shares_allocated": _num(e["shares_allocated"]),
        "ach_fee_cents": e["ach_fee_cents"],
        "total_charged_cents": e["total_charged_cents"],
        "tax_year": e["tax_year"],
        "holding_id": e["holding_id"],
    })
    return out


def holding(e):
    out = _common(e)
    out.update({
        "investor_id": e["investor_id"],
        "share_class_id": e["share_class_id"],
        "shares_owned": _num(e["shares_owned"]),
        "cost_basis_cents": e["cost_basis_cents"],
        "first_acquired_seq": e["first_acquired_seq"],
        "drip_elected": e["drip_elected"],
    })
    return out


def valuation(e):
    out = _common(e, full=False)
    out.update({
        "fund_id": e["fund_id"],
        "seq": e["seq"],
        "period_label": e["period_label"],
        "gross_asset_value_cents": e["gross_asset_value_cents"],
        "total_liabilities_cents": e["total_liabilities_cents"],
        "resulting_nav_per_share_cents": e["resulting_nav_per_share_cents"],
    })
    return out


def distribution(e):
    out = _common(e)
    out.update({
        "fund_id": e["fund_id"],
        "period_label": e["period_label"],
        "dividend_per_share_cents": _num(e["dividend_per_share_cents"]),
        "status": e["status"],
        "total_paid_cents": e["total_paid_cents"],
        "drip_shares_minted": _num(e["drip_shares_minted"]),
    })
    return out


def allocation(e):
    out = _common(e, full=False)
    out.update({
        "distribution_id": e["distribution_id"],
        "holding_id": e["holding_id"],
        "gross_dividend_cents": e["gross_dividend_cents"],
        "mode": e["mode"],
        "drip_shares": _num(e["drip_shares"]),
    })
    return out


def redemption_request(e):
    out = _common(e)
    out.update({
        "holding_id": e["holding_id"],
        "shares_requested": _num(e["shares_requested"]),
        "status": e["status"],
        "queue_seq": e["queue_seq"],
        "gross_value_cents": e["gross_value_cents"],
        "penalty_cents": e["penalty_cents"],
        "net_proceeds_cents": e["net_proceeds_cents"],
        "penalty_tier_rate_bps": e["penalty_tier_rate_bps"],
    })
    return out


def tax_document(e):
    out = _common(e, full=False)
    out.update({
        "investor_id": e["investor_id"],
        "fund_id": e["fund_id"],
        "tax_year": e["tax_year"],
        "doc_type": e["doc_type"],
        "ordinary_dividends_cents": e["ordinary_dividends_cents"],
        "reinvested_dividends_cents": e["reinvested_dividends_cents"],
    })
    return out
