"""Serializers: produce JSON `data` payloads with computed fields (PRD §2.6).

Each serializer emits the stored fields plus the entity's computed/derived
fields, recomputed at read time.
"""
from services import derive

COMMON = ("id", "created_at", "updated_at", "version")


def _base(obj):
    return {k: obj[k] for k in COMMON}


def fund(obj):
    out = _base(obj)
    out.update(
        {
            "name": obj["name"],
            "vintage_year": obj["vintage_year"],
            "target_size_cents": obj["target_size_cents"],
            "mgmt_fee_rate_bps": obj["mgmt_fee_rate_bps"],
            "carry_rate_bps": obj["carry_rate_bps"],
            "pref_rate_bps": obj["pref_rate_bps"],
            "gp_catchup_rate_bps": obj["gp_catchup_rate_bps"],
            "recycling_cap_pct_bps": obj["recycling_cap_pct_bps"],
            "fee_offset_pct_bps": obj["fee_offset_pct_bps"],
            "status": obj["status"],
            "total_committed_cents": derive.fund_total_committed(obj["id"]),
            "total_called_cents": derive.fund_total_called(obj["id"]),
            "total_distributed_cents": derive.fund_total_distributed(obj["id"]),
            "recycled_to_date_cents": derive.fund_recycled_to_date(obj["id"]),
        }
    )
    return out


def limited_partner(obj):
    out = _base(obj)
    out.update(
        {
            "legal_name": obj["legal_name"],
            "lp_type": obj["lp_type"],
            "tax_id_last4": obj["tax_id_last4"],
            "is_tax_exempt": obj["is_tax_exempt"],
            "default_strike_count": derive.lp_default_strike_count(obj["id"]),
        }
    )
    return out


def commitment(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "lp_id": obj["lp_id"],
            "committed_cents": obj["committed_cents"],
            "status": obj["status"],
            "drawn_cents": derive.commitment_drawn(obj),
            "distributed_cents": derive.commitment_distributed(obj),
            "unfunded_cents": derive.commitment_unfunded(obj),
        }
    )
    return out


def capital_call(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "call_number": obj["call_number"],
            "purpose": obj["purpose"],
            "called_amount_cents": obj["called_amount_cents"],
            "due_date": obj["due_date"],
            "status": obj["status"],
            "funded_amount_cents": derive.call_funded_amount(obj),
        }
    )
    return out


def capital_call_allocation(obj):
    out = _base(obj)
    out.update(
        {
            "capital_call_id": obj["capital_call_id"],
            "commitment_id": obj["commitment_id"],
            "allocated_amount_cents": obj["allocated_amount_cents"],
            "paid_amount_cents": obj["paid_amount_cents"],
            "status": obj["status"],
        }
    )
    return out


def portfolio_company(obj):
    out = _base(obj)
    out.update(
        {
            "name": obj["name"],
            "sector": obj["sector"],
            "status": obj["status"],
        }
    )
    return out


def investment(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "portfolio_company_id": obj["portfolio_company_id"],
            "cost_basis_cents": obj["cost_basis_cents"],
            "ownership_pct_bps": obj["ownership_pct_bps"],
            "status": obj["status"],
            "current_mark_cents": derive.investment_current_mark(obj),
            "realized_proceeds_cents": obj["realized_proceeds_cents"],
        }
    )
    return out


def valuation_mark(obj):
    out = _base(obj)
    out.update(
        {
            "investment_id": obj["investment_id"],
            "as_of_date": obj["as_of_date"],
            "fair_value_cents": obj["fair_value_cents"],
            "methodology": obj["methodology"],
            "status": obj["status"],
        }
    )
    return out


def management_fee_accrual(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "period_start": obj["period_start"],
            "period_end": obj["period_end"],
            "gross_fee_cents": obj["gross_fee_cents"],
            "offset_applied_cents": obj["offset_applied_cents"],
            "net_fee_cents": obj["net_fee_cents"],
            "status": obj["status"],
        }
    )
    return out


def distribution_event(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "source_investment_id": obj["source_investment_id"],
            "gross_amount_cents": obj["gross_amount_cents"],
            "distribution_type": obj["distribution_type"],
            "recyclable": obj["recyclable"],
            "lp_share_cents": obj["lp_share_cents"],
            "gp_carry_cents": obj["gp_carry_cents"],
            "recycled_amount_cents": obj["recycled_amount_cents"],
            "status": obj["status"],
        }
    )
    return out


def distribution_allocation(obj):
    out = _base(obj)
    out.update(
        {
            "distribution_event_id": obj["distribution_event_id"],
            "commitment_id": obj["commitment_id"],
            "amount_cents": obj["amount_cents"],
            "clawback_flag": obj["clawback_flag"],
        }
    )
    return out


def side_letter(obj):
    out = _base(obj)
    out.update(
        {
            "fund_id": obj["fund_id"],
            "lp_id": obj["lp_id"],
            "mfn_rank": obj["mfn_rank"],
            "fee_discount_bps": obj["fee_discount_bps"],
            "excused_purposes": list(obj["excused_purposes"]),
            "status": obj["status"],
        }
    )
    return out
