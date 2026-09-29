"""Wire representations of every resource.

Institution aggregate counters are rendered from a fresh recompute rather than
from stored copies, so a read issued immediately after any mutation observes
every consequence of that mutation (PRD sections 2.7 and 2.8).
"""

from services import aggregates


def _audit(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def institution(row):
    out = _audit(row)
    out.update(
        {
            "cert_number": row["cert_number"],
            "legal_name": row["legal_name"],
            "charter_state": row["charter_state"],
            "book_asset_value_cents": row["book_asset_value_cents"],
            "estimated_liquidation_recovery_cents": row[
                "estimated_liquidation_recovery_cents"
            ],
            "status": row["status"],
            "failure_datetime": row["failure_datetime"],
            "readiness_standardized": row["readiness_standardized"],
            "franchise_marketing_status": row["franchise_marketing_status"],
            "bid_deadline_at": row["bid_deadline_at"],
            "least_cost_status": row["least_cost_status"],
            "least_cost_test_variant": row["least_cost_test_variant"],
            "liquidation_baseline_cents": row["liquidation_baseline_cents"],
            "conforming_bid_count": row["conforming_bid_count"],
            "resolution_method": row["resolution_method"],
        }
    )
    out.update(aggregates.derived(row))
    return out


def submission(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "file_format": row["file_format"],
            "record_count": row["record_count"],
            "malformed_record_count": row["malformed_record_count"],
            "reported_deposit_total_cents": row["reported_deposit_total_cents"],
            "standardization_score_bps": row["standardization_score_bps"],
            "deposit_total_variance_bps": row["deposit_total_variance_bps"],
            "status": row["status"],
            "rejection_reason": row["rejection_reason"],
        }
    )
    return out


def depositor(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "tin_hash": row["tin_hash"],
            "legal_name": row["legal_name"],
            "depositor_type": row["depositor_type"],
            "contact_email": row["contact_email"],
            "notice_status": row["notice_status"],
            "notice_template_code": row["notice_template_code"],
            "notice_sent_at": row["notice_sent_at"],
            "acknowledged_at": row["acknowledged_at"],
            "attributed_total_cents": row["attributed_total_cents"],
            "certified_insured_cents": row["certified_insured_cents"],
            "certified_uninsured_cents": row["certified_uninsured_cents"],
        }
    )
    return out


def account(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "primary_depositor_id": row["primary_depositor_id"],
            "account_number": row["account_number"],
            "ownership_category": row["ownership_category"],
            "balance_cents": row["balance_cents"],
            "accrued_interest_cents": row["accrued_interest_cents"],
            "opened_at": row["opened_at"],
            "broker_name": row["broker_name"],
            "recordkeeping_status": row["recordkeeping_status"],
            "insurance_status": row["insurance_status"],
            "hold_status": row["hold_status"],
            "held_amount_cents": row["held_amount_cents"],
            "transition_status": row["transition_status"],
            "attributed_amount_cents": row["attributed_amount_cents"],
        }
    )
    return out


def interest(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "deposit_account_id": row["deposit_account_id"],
        "depositor_record_id": row["depositor_record_id"],
        "interest_role": row["interest_role"],
        "designated_share_bps": row["designated_share_bps"],
    }


def determination(row):
    out = _audit(row)
    out.update(
        {
            "depositor_record_id": row["depositor_record_id"],
            "status": row["status"],
            "method_variant": row["method_variant"],
            "insured_amount_cents": row["insured_amount_cents"],
            "uninsured_amount_cents": row["uninsured_amount_cents"],
            "attributed_total_cents": row["attributed_total_cents"],
            "category_breakdown": row["category_breakdown"],
            "prepared_by_user_id": row["prepared_by_user_id"],
            "certified_by_user_id": row["certified_by_user_id"],
            "revision_round": row["revision_round"],
            "revision_reason": row["revision_reason"],
            "prepared_at": row["prepared_at"],
            "certified_at": row["certified_at"],
        }
    )
    return out


def certificate(row):
    out = _audit(row)
    out.update(
        {
            "insurance_determination_id": row["insurance_determination_id"],
            "depositor_record_id": row["depositor_record_id"],
            "institution_id": row["institution_id"],
            "face_amount_cents": row["face_amount_cents"],
            "cumulative_dividends_cents": row["cumulative_dividends_cents"],
            "last_dividend_amount_cents": row["last_dividend_amount_cents"],
            "last_dividend_round": row["last_dividend_round"],
            "status": row["status"],
            "issued_at": row["issued_at"],
        }
    )
    return out


def bidder(row):
    out = _audit(row)
    out.update(
        {
            "legal_name": row["legal_name"],
            "cert_number": row["cert_number"],
            "tier1_capital_ratio_bps": row["tier1_capital_ratio_bps"],
            "camels_composite": row["camels_composite"],
            "qualification_status": row["qualification_status"],
            "qualified_at": row["qualified_at"],
            "disqualification_reason": row["disqualification_reason"],
        }
    )
    return out


def bid(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "bidder_id": row["bidder_id"],
            "structure": row["structure"],
            "deposit_premium_bps": row["deposit_premium_bps"],
            "asset_discount_bps": row["asset_discount_bps"],
            "loss_share_pct_bps": row["loss_share_pct_bps"],
            "asset_retention_pool_cents": row["asset_retention_pool_cents"],
            "data_room_window_start": row["data_room_window_start"],
            "data_room_window_end": row["data_room_window_end"],
            "status": row["status"],
            "assumed_deposit_base_cents": row["assumed_deposit_base_cents"],
            "pre_fee_cost_cents": row["pre_fee_cost_cents"],
            "loss_share_fee_cents": row["loss_share_fee_cents"],
            "expected_loss_share_reimbursement_cents": row[
                "expected_loss_share_reimbursement_cents"
            ],
            "evaluated_cost_cents": row["evaluated_cost_cents"],
            "non_conformance_reason": row["non_conformance_reason"],
        }
    )
    return out


def reopening(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "branch_code": row["branch_code"],
            "reopen_window_start": row["reopen_window_start"],
            "reopen_window_end": row["reopen_window_end"],
            "staffing_headcount": row["staffing_headcount"],
            "status": row["status"],
            "reschedule_count": row["reschedule_count"],
            "reopened_at": row["reopened_at"],
        }
    )
    return out


def distribution(row):
    out = _audit(row)
    out.update(
        {
            "institution_id": row["institution_id"],
            "distribution_round": row["distribution_round"],
            "priority_class": row["priority_class"],
            "declared_rate_bps": row["declared_rate_bps"],
            "status": row["status"],
            "total_distributed_cents": row["total_distributed_cents"],
            "certificate_count": row["certificate_count"],
            "settled_at": row["settled_at"],
            "voided_at": row["voided_at"],
        }
    )
    return out
