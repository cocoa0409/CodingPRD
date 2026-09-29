"""Wire representations. Every entity exposes exactly the fields the PRD names."""

from money import num


def _v(value):
    return num(value)


def jurisdiction(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "gob_license_required": row["gob_license_required"],
        "max_sale_days": row["max_sale_days"],
        "license_cooling_off_days": row["license_cooling_off_days"],
        "max_augmentation_ratio": _v(row["max_augmentation_ratio"]),
        "augmentation_disclosure_required": row["augmentation_disclosure_required"],
        "augmentation_prohibited": row["augmentation_prohibited"],
        "prohibited_claim_codes": list(row["prohibited_claim_codes"]),
        "advertising_disclosure_required": row["advertising_disclosure_required"],
        "surrender_notice_days": row["surrender_notice_days"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def engagement(row):
    return {
        "id": row["id"],
        "retailer_name": row["retailer_name"],
        "liquidator_name": row["liquidator_name"],
        "economics_model": row["economics_model"],
        "guaranty_pct": _v(row["guaranty_pct"]),
        "hybrid_retailer_excess_pct": _v(row["hybrid_retailer_excess_pct"]),
        "expense_responsibility": row["expense_responsibility"],
        "shared_expense_liquidator_pct": _v(row["shared_expense_liquidator_pct"]),
        "sale_start_date": row["sale_start_date"],
        "target_end_date": row["target_end_date"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "engagement_status": row["engagement_status"],
        "compliance_strike_count": row["compliance_strike_count"],
        "compliance_posture": row["compliance_posture"],
        "original_cost_value_cents": row["original_cost_value_cents"],
        "guaranty_amount_cents": row["guaranty_amount_cents"],
        "projected_gross_recovery_cents": row["projected_gross_recovery_cents"],
        "projected_shortfall_cents": row["projected_shortfall_cents"],
        "original_net_sales_cents": row["original_net_sales_cents"],
        "augmentation_net_sales_cents": row["augmentation_net_sales_cents"],
        "gross_recovery_cents": row["gross_recovery_cents"],
        "expense_total_cents": row["expense_total_cents"],
        "expense_liquidator_share_cents": row["expense_liquidator_share_cents"],
        "expense_retailer_share_cents": row["expense_retailer_share_cents"],
        "retention_accrual_cents": row["retention_accrual_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def store(row):
    return {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "store_code": row["store_code"],
        "address_line": row["address_line"],
        "store_status": row["store_status"],
        "suspension_reason": row["suspension_reason"],
        "selling_start_date": row["selling_start_date"],
        "selling_end_date": row["selling_end_date"],
        "original_cost_value_cents": row["original_cost_value_cents"],
        "augmentation_cost_value_cents": row["augmentation_cost_value_cents"],
        "units_initial_total": row["units_initial_total"],
        "units_sold_total": row["units_sold_total"],
        "realized_sell_through_pct": _v(row["realized_sell_through_pct"]),
        "planned_avg_discount_pct": _v(row["planned_avg_discount_pct"]),
        "projected_gross_recovery_cents": row["projected_gross_recovery_cents"],
        "projected_recovery_ratio": _v(row["projected_recovery_ratio"]),
        "realized_gross_recovery_cents": row["realized_gross_recovery_cents"],
        "realized_recovery_ratio": _v(row["realized_recovery_ratio"]),
        "augmentation_units_accounted": row["augmentation_units_accounted"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def lot(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "consignment_id": row["consignment_id"],
        "category": row["category"],
        "source": row["source"],
        "units_initial": row["units_initial"],
        "units_on_hand": row["units_on_hand"],
        "units_sold": row["units_sold"],
        "units_returned": row["units_returned"],
        "unit_cost_cents": row["unit_cost_cents"],
        "unit_retail_cents": row["unit_retail_cents"],
        "cost_value_cents": row["cost_value_cents"],
        "retail_value_cents": row["retail_value_cents"],
        "lot_status": row["lot_status"],
        "projected_recovery_cents": row["projected_recovery_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def consignment(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "supplier_name": row["supplier_name"],
        "category": row["category"],
        "units_supplied": row["units_supplied"],
        "unit_cost_cents": row["unit_cost_cents"],
        "unit_retail_cents": row["unit_retail_cents"],
        "cost_value_cents": row["cost_value_cents"],
        "delivery_window_start_date": row["delivery_window_start_date"],
        "delivery_window_end_date": row["delivery_window_end_date"],
        "consignment_status": row["consignment_status"],
        "disclosure_reference": row["disclosure_reference"],
        "disclosure_filed_at": row["disclosure_filed_at"],
        "units_returned": row["units_returned"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def stage(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "stage_index": row["stage_index"],
        "discount_pct": _v(row["discount_pct"]),
        "sell_through_target_pct": _v(row["sell_through_target_pct"]),
        "window_start_date": row["window_start_date"],
        "window_end_date": row["window_end_date"],
        "stage_status": row["stage_status"],
        "closed_reason": row["closed_reason"],
        "checkpoint_sell_through_pct": _v(row["checkpoint_sell_through_pct"]),
        "escalation_applied_pct": _v(row["escalation_applied_pct"]),
        "activated_at": row["activated_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def license(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "license_number": row["license_number"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "requested_days": row["requested_days"],
        "advertising_claim_codes": list(row["advertising_claim_codes"]),
        "license_status": row["license_status"],
        "applied_by_user_id": row["applied_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_reason": row["decision_reason"],
        "revoked_reason": row["revoked_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def employee(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "employee_code": row["employee_code"],
        "employment_status": row["employment_status"],
        "bonus_status": row["bonus_status"],
        "retention_bonus_cents": row["retention_bonus_cents"],
        "retention_start_date": row["retention_start_date"],
        "retention_target_date": row["retention_target_date"],
        "attendance_rate": _v(row["attendance_rate"]),
        "served_days": row["served_days"],
        "earned_bonus_cents": row["earned_bonus_cents"],
        "notice_given_date": row["notice_given_date"],
        "termination_date": row["termination_date"],
        "bonus_paid_at": row["bonus_paid_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def sales_day(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "business_date": row["business_date"],
        "original_net_sales_cents": row["original_net_sales_cents"],
        "augmentation_net_sales_cents": row["augmentation_net_sales_cents"],
        "original_units_sold": row["original_units_sold"],
        "augmentation_units_sold": row["augmentation_units_sold"],
        "net_sales_cents": row["net_sales_cents"],
        "day_status": row["day_status"],
        "posted_at": row["posted_at"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "allocation_note": row["allocation_note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def expense_item(row):
    return {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "store_id": row["store_id"],
        "expense_category": row["expense_category"],
        "amount_cents": row["amount_cents"],
        "incurred_date": row["incurred_date"],
        "expense_status": row["expense_status"],
        "liquidator_share_cents": row["liquidator_share_cents"],
        "retailer_share_cents": row["retailer_share_cents"],
        "auto_generated": row["auto_generated"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def lease(row):
    return {
        "id": row["id"],
        "store_id": row["store_id"],
        "landlord_name": row["landlord_name"],
        "surrender_deadline_date": row["surrender_deadline_date"],
        "daily_holdover_rate_cents": row["daily_holdover_rate_cents"],
        "rent_arrears_cents": row["rent_arrears_cents"],
        "cam_arrears_cents": row["cam_arrears_cents"],
        "restoration_cost_cents": row["restoration_cost_cents"],
        "fixture_reserve_price_cents": row["fixture_reserve_price_cents"],
        "surrender_credit_cents": row["surrender_credit_cents"],
        "disposition_status": row["disposition_status"],
        "negotiation_round": row["negotiation_round"],
        "offered_surrender_payment_cents": row["offered_surrender_payment_cents"],
        "landlord_counter_amount_cents": row["landlord_counter_amount_cents"],
        "agreed_surrender_payment_cents": row["agreed_surrender_payment_cents"],
        "landlord_agreed_date": row["landlord_agreed_date"],
        "fixture_sale_price_cents": row["fixture_sale_price_cents"],
        "holdover_days": row["holdover_days"],
        "holdover_penalty_cents": row["holdover_penalty_cents"],
        "allocated_rent_cents": row["allocated_rent_cents"],
        "allocated_cam_cents": row["allocated_cam_cents"],
        "allocated_restoration_cents": row["allocated_restoration_cents"],
        "allocated_holdover_cents": row["allocated_holdover_cents"],
        "unpaid_landlord_balance_cents": row["unpaid_landlord_balance_cents"],
        "residual_to_retailer_cents": row["residual_to_retailer_cents"],
        "surrendered_at": row["surrendered_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def settlement(row):
    return {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "settlement_basis": row["settlement_basis"],
        "settlement_status": row["settlement_status"],
        "gross_recovery_cents": row["gross_recovery_cents"],
        "original_net_sales_cents": row["original_net_sales_cents"],
        "recovery_ratio": _v(row["recovery_ratio"]),
        "fee_rate": _v(row["fee_rate"]),
        "liquidator_fee_cents": row["liquidator_fee_cents"],
        "guaranty_amount_cents": row["guaranty_amount_cents"],
        "expense_total_cents": row["expense_total_cents"],
        "liquidator_expense_cents": row["liquidator_expense_cents"],
        "retailer_expense_cents": row["retailer_expense_cents"],
        "retailer_proceeds_cents": row["retailer_proceeds_cents"],
        "liquidator_proceeds_cents": row["liquidator_proceeds_cents"],
        "retention_accrual_cents": row["retention_accrual_cents"],
        "dispute_reason": row["dispute_reason"],
        "dispute_round": row["dispute_round"],
        "computed_at": row["computed_at"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
