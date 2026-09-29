"""Entity serializers. Computed fields are derived at read time so that the
conserved-quantity identities hold at every observable instant."""
from core import DB, fmt_date, num, rows
import calcs


def ser_counterparty(row):
    open_count = 0
    for transfer in rows("transfers"):
        if transfer["status"] != "IN_PROGRESS":
            continue
        agreement = DB["agreements"].get(transfer["purchase_agreement_id"])
        if agreement is not None and agreement["buyer_id"] == row["id"]:
            open_count += 1
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "role_type": row["role_type"],
        "net_worth_cents": row["net_worth_cents"],
        "servicer_rating": row["servicer_rating"],
        "agency_approvals": list(row["agency_approvals"]),
        "status": row["status"],
        "suspended_at": row["suspended_at"],
        "open_transfer_count": open_count,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_portfolio(row):
    return {
        "id": row["id"],
        "seller_id": row["seller_id"],
        "portfolio_name": row["portfolio_name"],
        "agency_type": row["agency_type"],
        "status": row["status"],
        "loan_count": calcs.portfolio_loan_count(row["id"]),
        "total_upb_cents": calcs.portfolio_total_upb(row["id"]),
        "weighted_avg_note_rate_pct": num(calcs.portfolio_wanr(row["id"]), 4),
        "custodial_funds_total_cents": calcs.custodial_funds_total(row["id"]),
        "valuation_freshness": calcs.valuation_freshness(row["id"]),
        "tape_locked_at": row["tape_locked_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_loan(row):
    return {
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "loan_number": row["loan_number"],
        "upb_cents": row["upb_cents"],
        "note_rate_pct": num(row["note_rate_pct"], 4),
        "servicing_fee_bps": row["servicing_fee_bps"],
        "escrow_balance_cents": row["escrow_balance_cents"],
        "suspense_balance_cents": row["suspense_balance_cents"],
        "delinquency_bucket": row["delinquency_bucket"],
        "loss_mit_status": row["loss_mit_status"],
        "state_code": row["state_code"],
        "status": row["status"],
        "escrow_balance_at_mapping_cents": row["escrow_balance_at_mapping_cents"],
        "suspense_balance_at_mapping_cents": row["suspense_balance_at_mapping_cents"],
        "transferred_at": row["transferred_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_assumption_set(row):
    return {
        "id": row["id"],
        "assumption_name": row["assumption_name"],
        "cpr_pct": num(row["cpr_pct"], 4),
        "discount_rate_pct": num(row["discount_rate_pct"], 4),
        "cost_to_service_annual_cents": row["cost_to_service_annual_cents"],
        "float_earnings_rate_pct": num(row["float_earnings_rate_pct"], 4),
        "projection_years": row["projection_years"],
        "created_at": row["created_at"],
    }


def ser_rate_curve(row):
    return {
        "id": row["id"],
        "as_of_date": row["as_of_date"],
        "base_rate_bps": row["base_rate_bps"],
        "primary_secondary_spread_bps": row["primary_secondary_spread_bps"],
        "status": row["status"],
        "superseded_at": row["superseded_at"],
        "published_by_user_id": row["published_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_valuation_run(row):
    return {
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "assumption_set_id": row["assumption_set_id"],
        "rate_curve_snapshot_id": row["rate_curve_snapshot_id"],
        "method": row["method"],
        "sequence_no": row["sequence_no"],
        "status": row["status"],
        "value_cents": row["value_cents"],
        "value_bps_of_upb": num(row["value_bps_of_upb"], 2),
        "included_loan_count": row["included_loan_count"],
        "effective_discount_rate_pct": num(row["effective_discount_rate_pct"], 4),
        "scenario_values": (dict(row["scenario_values"])
                            if row["scenario_values"] is not None else None),
        "run_by_user_id": row["run_by_user_id"],
        "staled_at": row["staled_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_bid_package(row):
    return {
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "valuation_run_id": row["valuation_run_id"],
        "stratification_scheme": row["stratification_scheme"],
        "reserve_price_floor_pct": num(row["reserve_price_floor_pct"], 2),
        "marketing_start_at": row["marketing_start_at"],
        "bid_deadline_at": row["bid_deadline_at"],
        "status": row["status"],
        "tape_upb_cents": calcs.tape_upb_cents(row["id"]),
        "tape_loan_count": calcs.tape_loan_count(row["id"]),
        "stratum_count": calcs.stratum_count(row["id"]),
        "reserve_price_cents": row["reserve_price_cents"],
        "bid_count": calcs.package_bid_count(row["id"]),
        "published_at": row["published_at"],
        "suspended_reason": row["suspended_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_tape_line(row):
    return {
        "id": row["id"],
        "bid_package_id": row["bid_package_id"],
        "loan_id": row["loan_id"],
        "stratum_label": row["stratum_label"],
        "included": row["included"],
        "exclusion_reason": row["exclusion_reason"],
        "upb_snapshot_cents": row["upb_snapshot_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_bid(row):
    return {
        "id": row["id"],
        "bid_package_id": row["bid_package_id"],
        "bidder_id": row["bidder_id"],
        "price_bps": row["price_bps"],
        "holdback_pct": num(row["holdback_pct"], 2),
        "round_number": row["round_number"],
        "status": row["status"],
        "bid_value_cents": row["bid_value_cents"],
        "counter_price_bps": row["counter_price_bps"],
        "counter_expires_at": row["counter_expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_agreement(row):
    return {
        "id": row["id"],
        "bid_package_id": row["bid_package_id"],
        "winning_bid_id": row["winning_bid_id"],
        "buyer_id": row["buyer_id"],
        "purchase_price_cents": row["purchase_price_cents"],
        "stratum_price_breakdown": dict(row["stratum_price_breakdown"]),
        "holdback_pct": num(row["holdback_pct"], 2),
        "holdback_cents": row["holdback_cents"],
        "holdback_retained_cents": row["holdback_retained_cents"],
        "holdback_released_cents": row["holdback_released_cents"],
        "holdback_applied_cents": row["holdback_applied_cents"],
        "settlement_wire_cents": row["settlement_wire_cents"],
        "rep_warrant_days": row["rep_warrant_days"],
        "indemnification_days": row["indemnification_days"],
        "sale_date": fmt_date(row["sale_date"]),
        "transfer_date": fmt_date(row["transfer_date"]),
        "holdback_release_eligible_at": fmt_date(row["holdback_release_eligible_at"]),
        "status": row["status"],
        "approval_pending_count": row["approval_pending_count"],
        "condition_count": row["condition_count"],
        "condition_waiver_reference": row["condition_waiver_reference"],
        "drafted_by_user_id": row["drafted_by_user_id"],
        "termination_reason": row["termination_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_approval_request(row):
    return {
        "id": row["id"],
        "purchase_agreement_id": row["purchase_agreement_id"],
        "approver_type": row["approver_type"],
        "agency_type": row["agency_type"],
        "status": row["status"],
        "condition_text": row["condition_text"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_transfer(row):
    return {
        "id": row["id"],
        "purchase_agreement_id": row["purchase_agreement_id"],
        "transfer_date": fmt_date(row["transfer_date"]),
        "notice_status": row["notice_status"],
        "data_status": row["data_status"],
        "pipeline_status": row["pipeline_status"],
        "readiness": row["readiness"],
        "status": row["status"],
        "mapping_scheme": row["mapping_scheme"],
        "escrow_transferred_cents": row["escrow_transferred_cents"],
        "suspense_transferred_cents": row["suspense_transferred_cents"],
        "loss_mit_pipeline_count": row["loss_mit_pipeline_count"],
        "transferred_loan_count": row["transferred_loan_count"],
        "onboarding_window_start": fmt_date(row["onboarding_window_start"]),
        "onboarding_window_end": fmt_date(row["onboarding_window_end"]),
        "notice_count": row["notice_count"],
        "late_notice_count": row["late_notice_count"],
        "notice_attested_at": row["notice_attested_at"],
        "reconciled_at": row["reconciled_at"],
        "notice_attested_by_user_id": row["notice_attested_by_user_id"],
        "completed_at": row["completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_notice(row):
    return {
        "id": row["id"],
        "servicing_transfer_id": row["servicing_transfer_id"],
        "loan_id": row["loan_id"],
        "notice_type": row["notice_type"],
        "effective_date": fmt_date(row["effective_date"]),
        "sent_at": row["sent_at"],
        "lead_days": row["lead_days"],
        "compliance_status": row["compliance_status"],
        "sent_by_role": row["sent_by_role"],
        "created_at": row["created_at"],
    }


def ser_error_case(row):
    return {
        "id": row["id"],
        "servicing_transfer_id": row["servicing_transfer_id"],
        "loan_id": row["loan_id"],
        "category": row["category"],
        "description": row["description"],
        "status": row["status"],
        "opened_at": row["opened_at"],
        "ack_deadline_at": row["ack_deadline_at"],
        "resolution_deadline_at": row["resolution_deadline_at"],
        "acknowledged_at": row["acknowledged_at"],
        "resolved_at": row["resolved_at"],
        "ack_breached": row["ack_breached"],
        "resolution_breached": row["resolution_breached"],
        "remediation_cents": row["remediation_cents"],
        "reopen_count": row["reopen_count"],
        "resolution_note": row["resolution_note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_hedge(row):
    return {
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "instrument": row["instrument"],
        "notional_cents": row["notional_cents"],
        "hedge_ratio_pct": num(row["hedge_ratio_pct"], 2),
        "entry_base_rate_bps": row["entry_base_rate_bps"],
        "mark_to_market_cents": row["mark_to_market_cents"],
        "status": row["status"],
        "close_base_rate_bps": row["close_base_rate_bps"],
        "realized_pnl_cents": row["realized_pnl_cents"],
        "closed_at": row["closed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
