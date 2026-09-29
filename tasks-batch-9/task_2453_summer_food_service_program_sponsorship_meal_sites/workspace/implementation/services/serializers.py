"""Resource representations.

Every entity exposes exactly the fields declared for it.  The three append-only
types (AreaEligibilityRecord, MealCountEntry, HoldingLogEntry) carry only ``id``
and ``created_at`` and omit ``updated_at`` and ``version`` entirely (PRD sec 2.5).
"""

import db
from services import calculations as calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# --------------------------------------------------------------------------
# Advance / sponsor ledger projections
# --------------------------------------------------------------------------
def raw_outstanding(advance):
    return (advance.get("approved_amount_cents") or 0) - (
        advance.get("recovered_amount_cents") or 0
    )


def advance_outstanding(advance):
    if advance["status"] in ("DISBURSED", "PARTIALLY_RECOVERED", "DEMAND_ISSUED"):
        return raw_outstanding(advance)
    return 0


def sponsor_advances(sponsor_id):
    return db.ordered(
        [
            advance
            for advance in db.store.advances.values()
            if advance["sponsor_id"] == sponsor_id
        ]
    )


def sponsor_ledger(sponsor):
    advances = sponsor_advances(sponsor["id"])
    paid = sum(
        (advance.get("approved_amount_cents") or 0)
        for advance in advances
        if advance.get("_reached_disbursed")
    )
    recovered = sum((advance.get("recovered_amount_cents") or 0) for advance in advances)
    reimbursed = sum(
        (claim.get("net_payable_cents") or 0)
        for claim in db.store.claims.values()
        if claim["sponsor_id"] == sponsor["id"] and claim["status"] == "PAID"
    )
    return {
        "advance_paid_cents": paid,
        "advance_recovered_cents": recovered,
        "advance_outstanding_cents": paid - recovered,
        "reimbursement_paid_cents": reimbursed,
    }


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def sponsor(row):
    data = {
        "legal_name": row["legal_name"],
        "sponsor_type": row["sponsor_type"],
        "experience_status": row["experience_status"],
        "program_year": row["program_year"],
        "advance_eligible": row["advance_eligible"],
        "application_status": row["application_status"],
        "application_decision_reason": row["application_decision_reason"],
        "approved_at": row["approved_at"],
    }
    data.update(sponsor_ledger(row))
    data.update(_common(row))
    return data


def area_record(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "area_code": row["area_code"],
        "data_source": row["data_source"],
        "free_reduced_pct": calc.decimal_out(row["free_reduced_pct"]),
        "determination_date": row["determination_date"],
        "valid_through_date": row["valid_through_date"],
    }


def budget(row):
    data = {
        "sponsor_id": row["sponsor_id"],
        "program_year": row["program_year"],
        "operating_cost_budget_cents": row["operating_cost_budget_cents"],
        "admin_cost_budget_cents": row["admin_cost_budget_cents"],
        "projected_total_meals": row["projected_total_meals"],
        "admin_cost_ratio": calc.decimal_out(row["admin_cost_ratio"]),
        "approved_operating_cost_cents": row["approved_operating_cost_cents"],
        "approved_admin_cost_cents": row["approved_admin_cost_cents"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "decision_reason": row["decision_reason"],
        "submitted_at": row["submitted_at"],
        "decided_at": row["decided_at"],
    }
    data.update(_common(row))
    return data


def advance(row):
    data = {
        "sponsor_id": row["sponsor_id"],
        "request_month": row["request_month"],
        "requested_amount_cents": row["requested_amount_cents"],
        "approved_amount_cents": row["approved_amount_cents"],
        "recovered_amount_cents": row["recovered_amount_cents"],
        "outstanding_cents": advance_outstanding(row),
        "status": row["status"],
        "disbursed_at": row["disbursed_at"],
        "demand_issued_at": row["demand_issued_at"],
        "decision_reason": row["decision_reason"],
    }
    data.update(_common(row))
    return data


def site(row):
    data = {
        "sponsor_id": row["sponsor_id"],
        "area_eligibility_record_id": row["area_eligibility_record_id"],
        "name": row["name"],
        "site_type": row["site_type"],
        "production_mode": row["production_mode"],
        "is_open_air": row["is_open_air"],
        "is_rural": row["is_rural"],
        "approved_meal_types": list(row["approved_meal_types"]),
        "approved_max_attendance": row["approved_max_attendance"],
        "enrolled_free_reduced_pct": calc.decimal_out(row["enrolled_free_reduced_pct"]),
        "operating_start_date": row["operating_start_date"],
        "operating_end_date": row["operating_end_date"],
        "eligibility_basis": row["eligibility_basis"],
        "eligibility_pct_used": calc.decimal_out(row["eligibility_pct_used"]),
        "approval_status": row["approval_status"],
        "operating_status": row["operating_status"],
        "first_operating_date": row["first_operating_date"],
        "claim_hold": row["claim_hold"],
        "compliance_flag_count": row["compliance_flag_count"],
        "voided_day_count": row["voided_day_count"],
        "suspension_reason": row["suspension_reason"],
    }
    data.update(_common(row))
    return data


def service_day(row):
    data = {
        "site_id": row["site_id"],
        "service_date": row["service_date"],
        "meal_services": [dict(service) for service in row["meal_services"]],
        "production_mode": row["production_mode"],
        "production_counts": dict(row["production_counts"])
        if row["production_counts"] is not None
        else None,
        "food_received_at": row["food_received_at"],
        "status": row["status"],
        "food_safety_status": row["food_safety_status"],
        "breach_at": row["breach_at"],
        "counted_first_meals": row["counted_first_meals"],
        "counted_second_meals": row["counted_second_meals"],
        "counted_adult_meals": row["counted_adult_meals"],
        "reimbursable_meals": row["reimbursable_meals"],
        "non_reimbursable_meals": row["non_reimbursable_meals"],
        "discarded_meals": row["discarded_meals"],
        "leftover_meals": row["leftover_meals"],
        "void_reason": row["void_reason"],
    }
    data.update(_common(row))
    return data


def count_entry(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "meal_service_day_id": row["meal_service_day_id"],
        "reversal_of_entry_id": row["reversal_of_entry_id"],
        "meal_type": row["meal_type"],
        "first_meals": row["first_meals"],
        "second_meals": row["second_meals"],
        "adult_meals": row["adult_meals"],
        "entry_kind": row["entry_kind"],
        "reimbursable_first_meals": row["reimbursable_first_meals"],
        "reimbursable_second_meals": row["reimbursable_second_meals"],
        "non_reimbursable_meals": row["non_reimbursable_meals"],
        "recorded_at": row["recorded_at"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }


def holding_log(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "meal_service_day_id": row["meal_service_day_id"],
        "meal_type": row["meal_type"],
        "temperature_class": row["temperature_class"],
        "temperature_f": calc.decimal_out(row["temperature_f"]),
        "measured_at": row["measured_at"],
        "holding_minutes": row["holding_minutes"],
        "breach_flag": row["breach_flag"],
        "breach_reason": row["breach_reason"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }


def visit(row):
    data = {
        "site_id": row["site_id"],
        "monitor_user_id": row["monitor_user_id"],
        "visit_type": row["visit_type"],
        "scheduled_date": row["scheduled_date"],
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "status": row["status"],
        "conducted_at": row["conducted_at"],
        "findings": [dict(finding) for finding in row["findings"]]
        if row["findings"] is not None
        else None,
        "highest_severity": row["highest_severity"],
        "due_date": row["due_date"],
        "is_late": calc.visit_is_late(row),
        "cancel_reason": row["cancel_reason"],
    }
    data.update(_common(row))
    return data


def corrective_action(row):
    data = {
        "site_id": row["site_id"],
        "monitoring_visit_id": row["monitoring_visit_id"],
        "follow_up_of_corrective_action_id": row["follow_up_of_corrective_action_id"],
        "origin": row["origin"],
        "finding_code": row["finding_code"],
        "severity": row["severity"],
        "status": row["status"],
        "due_date": row["due_date"],
        "rejection_count": row["rejection_count"],
        "response_note": row["response_note"],
        "evidence_ref": row["evidence_ref"],
        "opened_by_user_id": row["opened_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
    }
    data.update(_common(row))
    return data


def meal_claim(row):
    data = {
        "sponsor_id": row["sponsor_id"],
        "claim_month": row["claim_month"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "claimed_operating_cost_cents": row["claimed_operating_cost_cents"],
        "claimed_admin_cost_cents": row["claimed_admin_cost_cents"],
        "meals_rate_value_cents": row["meals_rate_value_cents"],
        "preliminary_reimbursement_cents": row["preliminary_reimbursement_cents"],
        "final_reimbursement_cents": row["final_reimbursement_cents"],
        "advance_offset_cents": row["advance_offset_cents"],
        "net_payable_cents": row["net_payable_cents"],
        "disallowed_meal_count": row["disallowed_meal_count"],
        "blocking_hold_count": row["blocking_hold_count"],
        "edit_check_failure_codes": list(row["edit_check_failure_codes"])
        if row["edit_check_failure_codes"] is not None
        else None,
        "deadline_date": row["deadline_date"],
        "is_late": row["is_late"],
        "submitted_at": row["submitted_at"],
        "paid_at": row["paid_at"],
    }
    data.update(_common(row))
    return data


def claim_line_item(row):
    data = {
        "meal_claim_id": row["meal_claim_id"],
        "site_id": row["site_id"],
        "rate_class": row["rate_class"],
        "finalized_day_count": row["finalized_day_count"],
        "claimed_first_meals_by_type": dict(row["claimed_first_meals_by_type"]),
        "claimed_second_meals_by_type": dict(row["claimed_second_meals_by_type"]),
        "disallowed_counts_by_type": dict(row["disallowed_counts_by_type"])
        if row["disallowed_counts_by_type"] is not None
        else None,
        "meals_rate_value_cents": row["meals_rate_value_cents"],
        "disallowed_meal_count": row["disallowed_meal_count"],
        "edit_check_status": row["edit_check_status"],
        "disallow_reason": row["disallow_reason"],
        "hold_flag": row["hold_flag"],
    }
    data.update(_common(row))
    return data
