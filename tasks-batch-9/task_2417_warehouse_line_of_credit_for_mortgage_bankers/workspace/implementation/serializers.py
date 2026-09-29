"""Resource serialisation.

Computed fields are projected at read time (PRD 2.6: no balance is a stored
counter).  A FUNDED or SHIPPED advance's valuation is recomputed for the
response so that the live figures always reflect the current logical clock.
"""

from clock import fmt_dt
from db import db
from money import rate_out
from services import computed
from services.constants import ON_BOOK_FUNDING


def facility_out(facility):
    fid = facility["id"]
    return {
        "id": facility["id"],
        "borrower_legal_name": facility["borrower_legal_name"],
        "committed_amount_cents": facility["committed_amount_cents"],
        "wet_sublimit_cents": facility["wet_sublimit_cents"],
        "aged_sublimit_cents": facility["aged_sublimit_cents"],
        "scratch_and_dent_sublimit_cents": facility["scratch_and_dent_sublimit_cents"],
        "min_tangible_net_worth_cents": facility["min_tangible_net_worth_cents"],
        "min_liquidity_cents": facility["min_liquidity_cents"],
        "min_ttm_net_income_cents": facility["min_ttm_net_income_cents"],
        "max_investor_concentration_pct":
            rate_out(facility["max_investor_concentration_pct"]),
        "bailee_period_days": facility["bailee_period_days"],
        "unused_line_fee_rate": rate_out(facility["unused_line_fee_rate"]),
        "settlement_account_last4": facility["settlement_account_last4"],
        "status": facility["status"],
        "created_by_user_id": facility["created_by_user_id"],
        "approved_by_user_id": facility["approved_by_user_id"],
        "approved_at": fmt_dt(facility["approved_at"]),
        "last_accrual_at": fmt_dt(facility["last_accrual_at"]),
        "outstanding_principal_cents": computed.outstanding_principal(fid),
        "availability_cents": computed.availability(facility),
        "accrued_fee_balance_cents": computed.accrued_fee_balance(fid),
        "wet_outstanding_cents": computed.wet_outstanding(fid),
        "aged_outstanding_cents": computed.aged_outstanding(fid),
        "scratch_and_dent_outstanding_cents":
            computed.scratch_and_dent_outstanding(fid),
        "open_margin_call_count": computed.open_margin_call_count(fid),
        "consecutive_breach_count": computed.consecutive_breach_count(fid),
        "last_covenant_status": computed.last_covenant_status(fid),
        "escalated_demand_count": computed.escalated_demand_count(fid),
        "created_at": facility["created_at"],
        "updated_at": facility["updated_at"],
        "version": facility["version"],
    }


def product_rate_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "product_code": row["product_code"],
        "advance_rate": rate_out(row["advance_rate"]),
        "wet_funding_allowed": row["wet_funding_allowed"],
        "wet_haircut": rate_out(row["wet_haircut"]),
        "dwell_limit_days": row["dwell_limit_days"],
        "aging_step_days": row["aging_step_days"],
        "curtailment_step_rate": rate_out(row["curtailment_step_rate"]),
        "product_sublimit_cents": row["product_sublimit_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def custodian_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "custodian_name": row["custodian_name"],
        "wet_receipt_deadline_hours": row["wet_receipt_deadline_hours"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def investor_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "investor_name": row["investor_name"],
        "counterparty_rating": row["counterparty_rating"],
        "concentration_limit_pct": rate_out(row["concentration_limit_pct"]),
        "status": row["status"],
        "approved_at": fmt_dt(row["approved_at"]),
        "exposure_cents": computed.investor_exposure(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def commitment_out(row):
    allocated, settled, remaining = computed.commitment_buckets(row)
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "investor_id": row["investor_id"],
        "product_code": row["product_code"],
        "committed_amount_cents": row["committed_amount_cents"],
        "price_pct": rate_out(row["price_pct"]),
        "effective_on": row["effective_on"],
        "expires_on": row["expires_on"],
        "status": row["status"],
        "allocated_amount_cents": allocated,
        "settled_amount_cents": settled,
        "remaining_amount_cents": remaining,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def advance_out(advance):
    result = computed.valuation(advance)
    if advance["funding_status"] in ON_BOOK_FUNDING:
        advance["_effective_advance_rate"] = result["effective_advance_rate"]
        advance["_eligible_collateral_value_cents"] = \
            result["eligible_collateral_value_cents"]
        advance["_required_paydown_cents"] = result["required_paydown_cents"]
    return {
        "id": advance["id"],
        "facility_id": advance["facility_id"],
        "custodian_id": advance["custodian_id"],
        "investor_commitment_id": advance["investor_commitment_id"],
        "product_code": advance["product_code"],
        "loan_amount_cents": advance["loan_amount_cents"],
        "note_rate": rate_out(advance["note_rate"]),
        "funding_type": advance["funding_type"],
        "payee_name": advance["payee_name"],
        "payee_account_last4": advance["payee_account_last4"],
        "payee_routing_last4": advance["payee_routing_last4"],
        "funding_status": advance["funding_status"],
        "custody_status": advance["custody_status"],
        "rejected_reason": advance["rejected_reason"],
        "market_value_cents": advance["market_value_cents"],
        "provisional_advance_amount_cents": advance["provisional_advance_amount_cents"],
        "advance_amount_cents": advance["advance_amount_cents"],
        "concentration_capped": advance["concentration_capped"],
        "effective_advance_rate": rate_out(result["effective_advance_rate"]),
        "eligible_collateral_value_cents": result["eligible_collateral_value_cents"],
        "required_paydown_cents": result["required_paydown_cents"],
        "outstanding_balance_cents": result["outstanding_balance_cents"],
        "dwell_days": result["dwell_days"],
        "is_aged": result["is_aged"],
        "funded_at": fmt_dt(advance["funded_at"]),
        "wet_receipt_deadline_at": fmt_dt(advance["wet_receipt_deadline_at"]),
        "shipped_at": fmt_dt(advance["shipped_at"]),
        "purchased_at": fmt_dt(advance["purchased_at"]),
        "created_at": advance["created_at"],
        "updated_at": advance["updated_at"],
        "version": advance["version"],
    }


def wire_out(row):
    return {
        "id": row["id"],
        "advance_id": row["advance_id"],
        "payee_name": row["payee_name"],
        "payee_account_last4": row["payee_account_last4"],
        "payee_routing_last4": row["payee_routing_last4"],
        "amount_cents": row["amount_cents"],
        "callback_reference": row["callback_reference"],
        "decided_by_user_id": row["decided_by_user_id"],
        "status": row["status"],
        "block_reason": row["block_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def receipt_out(row):
    return {
        "id": row["id"],
        "advance_id": row["advance_id"],
        "custodian_id": row["custodian_id"],
        "document_types": list(row["document_types"]),
        "exception_codes": list(row["exception_codes"]),
        "cured_exception_codes": list(row["cured_exception_codes"]),
        "received_at": fmt_dt(row["received_at"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def bailee_letter_out(row):
    return {
        "id": row["id"],
        "advance_id": row["advance_id"],
        "investor_id": row["investor_id"],
        "effective_from": fmt_dt(row["effective_from"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "bailee_period_days": row["bailee_period_days"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def margin_call_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "advance_id": row["advance_id"],
        "trigger_reason": row["trigger_reason"],
        "call_amount_cents": row["call_amount_cents"],
        "cured_amount_cents": row["cured_amount_cents"],
        "issued_at": fmt_dt(row["issued_at"]),
        "cure_deadline_at": fmt_dt(row["cure_deadline_at"]),
        "issued_by_user_id": row["issued_by_user_id"],
        "waived_by_user_id": row["waived_by_user_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def cure_payment_out(row):
    return {
        "id": row["id"],
        "margin_call_id": row["margin_call_id"],
        "amount_cents": row["amount_cents"],
        "applied_to_fees_cents": row["applied_to_fees_cents"],
        "applied_to_principal_cents": row["applied_to_principal_cents"],
        "principal_allocation": [dict(entry) for entry in row["principal_allocation"]],
        "applied_at": fmt_dt(row["applied_at"]),
        "created_at": row["created_at"],
    }


def covenant_test_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "period_end": row["period_end"],
        "tangible_net_worth_cents": row["tangible_net_worth_cents"],
        "liquidity_cents": row["liquidity_cents"],
        "net_income_cents": row["net_income_cents"],
        "profitability_variant": row["profitability_variant"],
        "profitability_metric_cents": row["profitability_metric_cents"],
        "breach_codes": list(row["breach_codes"]),
        "status": row["status"],
        "certified_by_user_id": row["certified_by_user_id"],
        "waived_by_user_id": row["waived_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def demand_out(row):
    return {
        "id": row["id"],
        "advance_id": row["advance_id"],
        "reason": row["reason"],
        "demand_amount_cents": row["demand_amount_cents"],
        "raised_at": fmt_dt(row["raised_at"]),
        "deadline_at": fmt_dt(row["deadline_at"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ledger_entry_out(row):
    return {
        "id": row["id"],
        "facility_id": row["facility_id"],
        "advance_id": row["advance_id"],
        "entry_type": row["entry_type"],
        "direction": row["direction"],
        "amount_cents": row["amount_cents"],
        "posted_at": fmt_dt(row["posted_at"]),
        "memo": row["memo"],
        "created_at": row["created_at"],
    }


def exposure_summary_out(facility):
    fid = facility["id"]
    debit, credit = computed.facility_principal_totals(fid)
    return {
        "facility_id": fid,
        "committed_amount_cents": facility["committed_amount_cents"],
        "outstanding_principal_cents": computed.outstanding_principal(fid),
        "availability_cents": computed.availability(facility),
        "accrued_fee_balance_cents": computed.accrued_fee_balance(fid),
        "wet_outstanding_cents": computed.wet_outstanding(fid),
        "aged_outstanding_cents": computed.aged_outstanding(fid),
        "scratch_and_dent_outstanding_cents":
            computed.scratch_and_dent_outstanding(fid),
        "ledger_debit_total_cents": debit,
        "ledger_credit_total_cents": credit,
        "advance_outstanding_sum_cents": computed.advance_outstanding_sum(fid),
        "investor_exposures": [
            {"investor_id": investor["id"],
             "exposure_cents": computed.investor_exposure(investor["id"])}
            for investor in computed.facility_investors(fid)
        ],
        "open_margin_call_count": computed.open_margin_call_count(fid),
    }


def aging_run_out(summary):
    out = dict(summary)
    out["run_at"] = fmt_dt(summary["run_at"])
    return out
