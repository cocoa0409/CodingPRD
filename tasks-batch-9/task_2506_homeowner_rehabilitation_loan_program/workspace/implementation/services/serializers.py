"""Entity -> JSON projections."""

import clock
from services import domain


def _common(row):
    return {
        "id": row["id"],
        "created_at": clock.iso(row["created_at"]),
        "updated_at": clock.iso(row["updated_at"]),
        "version": row["version"],
    }


def program_year(row):
    body = _common(row)
    body.update(
        {
            "fiscal_year": row["fiscal_year"],
            "ami_median_income_cents": row["ami_median_income_cents"],
            "max_loan_amount_cents": row["max_loan_amount_cents"],
            "allocation_budget_cents": row["allocation_budget_cents"],
            "program_income_balance_cents": row["program_income_balance_cents"],
        }
    )
    body.update(domain.ledger(row))
    return body


def applicant(row):
    body = _common(row)
    body.update(
        {
            "program_year_id": row["program_year_id"],
            "full_name": row["full_name"],
            "email": row["email"],
            "household_size": row["household_size"],
            "dependents_count": row["dependents_count"],
            "elderly_household": row["elderly_household"],
            "wage_income_cents": row["wage_income_cents"],
            "benefit_income_cents": row["benefit_income_cents"],
            "actual_asset_income_cents": row["actual_asset_income_cents"],
            "household_assets_cents": row["household_assets_cents"],
            "income_calc_method": row["income_calc_method"],
            "annual_income_cents": row["annual_income_cents"],
            "income_limit_cents": row["income_limit_cents"],
            "ami_percent": row["ami_percent"],
            "income_category": row["income_category"],
            "eligibility_status": row["eligibility_status"],
            "verified_by_user_id": row["verified_by_user_id"],
        }
    )
    return body


def application(row):
    body = _common(row)
    body.update(
        {
            "applicant_id": row["applicant_id"],
            "program_year_id": row["program_year_id"],
            "awarded_contractor_id": row["awarded_contractor_id"],
            "address_line1": row["address_line1"],
            "city": row["city"],
            "state_code": row["state_code"],
            "year_built": row["year_built"],
            "assessed_value_cents": row["assessed_value_cents"],
            "senior_lien_balance_cents": row["senior_lien_balance_cents"],
            "historic_district": row["historic_district"],
            "occupancy_type": row["occupancy_type"],
            "ownership_doc_type": row["ownership_doc_type"],
            "deed_recorded_date": clock.iso(row["deed_recorded_date"]),
            "ownership_verification_status": row["ownership_verification_status"],
            "lead_review_required": row["lead_review_required"],
            "historic_review_required": row["historic_review_required"],
            "workflow_state": row["workflow_state"],
            "compliance_posture": row["compliance_posture"],
            "lead_hazard_detected": row["lead_hazard_detected"],
            "lead_hazard_control_method": row["lead_hazard_control_method"],
            "shpo_review_outcome": row["shpo_review_outcome"],
            "initial_deficiency_count": row["initial_deficiency_count"],
            "warranty_expires_at": clock.iso(row["warranty_expires_at"]),
        }
    )
    return body


def inspection(row):
    body = _common(row)
    body.update(
        {
            "application_id": row["application_id"],
            "draw_request_id": row["draw_request_id"],
            "inspection_type": row["inspection_type"],
            "scheduled_start_at": clock.iso(row["scheduled_start_at"]),
            "scheduled_end_at": clock.iso(row["scheduled_end_at"]),
            "performed_by_user_id": row["performed_by_user_id"],
            "status": row["status"],
            "result": row["result"],
            "deficiency_count": row["deficiency_count"],
            "xrf_reading_mg_cm2": row["xrf_reading_mg_cm2"],
            "lead_hazard_present": row["lead_hazard_present"],
        }
    )
    return body


def write_up(row):
    body = _common(row)
    body.update(
        {
            "application_id": row["application_id"],
            "revision_number": row["revision_number"],
            "revision_reason": row["revision_reason"],
            "prepared_by_user_id": row["prepared_by_user_id"],
            "approved_by_user_id": row["approved_by_user_id"],
            "state": row["state"],
            "work_item_count": row["work_item_count"],
            "base_estimate_cents": row["base_estimate_cents"],
            "contingency_cents": row["contingency_cents"],
            "total_estimate_cents": row["total_estimate_cents"],
            "priority_repair_total_cents": row["priority_repair_total_cents"],
        }
    )
    return body


def work_item(row):
    return {
        "id": row["id"],
        "created_at": clock.iso(row["created_at"]),
        "write_up_id": row["write_up_id"],
        "description": row["description"],
        "category": row["category"],
        "priority_class": row["priority_class"],
        "estimated_cost_cents": row["estimated_cost_cents"],
        "is_lead_hazard_reduction": row["is_lead_hazard_reduction"],
        "is_historic_sensitive": row["is_historic_sensitive"],
        "protocol_multiplier": row["protocol_multiplier"],
        "line_total_cents": row["line_total_cents"],
    }


def contractor(row):
    body = _common(row)
    body.update(
        {
            "legal_name": row["legal_name"],
            "license_number": row["license_number"],
            "insurance_expires_on": clock.iso(row["insurance_expires_on"]),
            "lead_safe_certified": row["lead_safe_certified"],
            "historic_qualified": row["historic_qualified"],
            "approved_list_status": row["approved_list_status"],
            "open_complaint_count": domain.open_complaint_count(row),
            "sanction_count": row["sanction_count"],
            "on_time_completion_count": row["on_time_completion_count"],
            "performance_score": domain.performance_score(row),
            "active_award_count": domain.active_award_count(row),
        }
    )
    return body


def solicitation(row):
    body = _common(row)
    body.update(
        {
            "application_id": row["application_id"],
            "write_up_id": row["write_up_id"],
            "award_bid_id": row["award_bid_id"],
            "bid_due_at": clock.iso(row["bid_due_at"]),
            "min_bids_required": row["min_bids_required"],
            "independent_cost_estimate_cents": row["independent_cost_estimate_cents"],
            "responsive_ceiling_cents": row["responsive_ceiling_cents"],
            "responsive_floor_cents": row["responsive_floor_cents"],
            "status": row["status"],
            "bid_count": row["bid_count"],
            "responsive_bid_count": row["responsive_bid_count"],
            "reopen_count": row["reopen_count"],
            "awarded_by_user_id": row["awarded_by_user_id"],
        }
    )
    return body


def bid(row):
    body = _common(row)
    body.update(
        {
            "solicitation_id": row["solicitation_id"],
            "contractor_id": row["contractor_id"],
            "amount_cents": row["amount_cents"],
            "proposed_start_date": clock.iso(row["proposed_start_date"]),
            "proposed_end_date": clock.iso(row["proposed_end_date"]),
            "submitted_at": clock.iso(row["submitted_at"]),
            "status": row["status"],
            "non_responsive_reason": row["non_responsive_reason"],
            "rank": row["rank"],
        }
    )
    return body


def loan(row):
    body = _common(row)
    body.update(
        {
            "application_id": row["application_id"],
            "structure_type": row["structure_type"],
            "awarded_bid_amount_cents": row["awarded_bid_amount_cents"],
            "approved_project_cost_cents": row["approved_project_cost_cents"],
            "lien_recording_fee_cents": row["lien_recording_fee_cents"],
            "principal_cents": row["principal_cents"],
            "interest_rate_bps": row["interest_rate_bps"],
            "term_months": row["term_months"],
            "forgiveness_term_months": row["forgiveness_term_months"],
            "monthly_payment_cents": row["monthly_payment_cents"],
            "lien_position": row["lien_position"],
            "lien_recorded_at": clock.iso(row["lien_recorded_at"]),
            "forgiveness_start_date": clock.iso(row["forgiveness_start_date"]),
            "status": row["status"],
            "contract_earned_cents": row["contract_earned_cents"],
            "disbursed_cents": row["disbursed_cents"],
            "retainage_held_cents": row["retainage_held_cents"],
            "forgiven_cents": row["forgiven_cents"],
            "principal_repaid_cents": row["principal_repaid_cents"],
            "unforgiven_balance_cents": row["unforgiven_balance_cents"],
            "recapture_event_type": row["recapture_event_type"],
            "recapture_event_date": clock.iso(row["recapture_event_date"]),
            "net_proceeds_cents": row["net_proceeds_cents"],
            "recapture_amount_cents": row["recapture_amount_cents"],
            "shortfall_forgiven_cents": row["shortfall_forgiven_cents"],
            "program_income_posted_cents": row["program_income_posted_cents"],
        }
    )
    return body


def draw_request(row):
    body = _common(row)
    body.update(
        {
            "loan_id": row["loan_id"],
            "contractor_id": row["contractor_id"],
            "requested_amount_cents": row["requested_amount_cents"],
            "is_final_draw": row["is_final_draw"],
            "approved_amount_cents": row["approved_amount_cents"],
            "retainage_cents": row["retainage_cents"],
            "net_payment_cents": row["net_payment_cents"],
            "status": row["status"],
            "approved_by_user_id": row["approved_by_user_id"],
            "paid_at": clock.iso(row["paid_at"]),
        }
    )
    return body


def change_order(row):
    body = _common(row)
    body.update(
        {
            "loan_id": row["loan_id"],
            "supersedes_change_order_id": row["supersedes_change_order_id"],
            "amount_delta_cents": row["amount_delta_cents"],
            "justification": row["justification"],
            "affects_lead_hazard_work": row["affects_lead_hazard_work"],
            "cumulative_delta_pct": row["cumulative_delta_pct"],
            "status": row["status"],
            "submitted_by_user_id": row["submitted_by_user_id"],
        }
    )
    return body


def complaint(row):
    body = _common(row)
    body.update(
        {
            "contractor_id": row["contractor_id"],
            "application_id": row["application_id"],
            "defect_category": row["defect_category"],
            "description": row["description"],
            "filed_at": clock.iso(row["filed_at"]),
            "warranty_expires_at": clock.iso(row["warranty_expires_at"]),
            "remedy_deadline_at": clock.iso(row["remedy_deadline_at"]),
            "status": row["status"],
            "sanction_level": row["sanction_level"],
            "resolved_at": clock.iso(row["resolved_at"]),
        }
    )
    return body
