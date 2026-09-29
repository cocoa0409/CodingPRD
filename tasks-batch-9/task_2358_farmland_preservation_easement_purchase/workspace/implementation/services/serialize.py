"""Entity -> JSON serialisers (SCAFFOLD entities field lists)."""

from decimal import Decimal

from db import db, iso
from services import lookup


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def program(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "soil_weight": num(row["soil_weight"]),
        "size_weight": num(row["size_weight"]),
        "contiguity_weight": num(row["contiguity_weight"]),
        "pressure_weight": num(row["pressure_weight"]),
        "min_composite_score": num(row["min_composite_score"]),
        "max_negotiation_rounds": row["max_negotiation_rounds"],
        "local_match_min_pct": num(row["local_match_min_pct"]),
        "federal_max_share_pct": num(row["federal_max_share_pct"]),
        "impervious_allowance_pct": num(row["impervious_allowance_pct"]),
        "amendment_policy": row["amendment_policy"],
        "monitoring_interval_days": row["monitoring_interval_days"],
        "monitoring_grace_days": row["monitoring_grace_days"],
        "appraisal_engagement_buffer_days": row["appraisal_engagement_buffer_days"],
        "status": row["status"],
        "total_preserved_acres": num(lookup.program_total_preserved_acres(row["id"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def funding_round(row):
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "round_label": row["round_label"],
        "opens_on": iso(row["opens_on"]),
        "closes_on": iso(row["closes_on"]),
        "pool_cents": row["pool_cents"],
        "status": row["status"],
        "score_basis": row["score_basis"],
        "ranked_at": iso(row["ranked_at"]),
        "application_count": lookup.round_application_count(row["id"]),
        "selected_count": lookup.round_selected_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def landowner(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "mailing_state": row["mailing_state"],
        "tax_id_last4": row["tax_id_last4"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def parcel(row):
    return {
        "id": row["id"],
        "landowner_id": row["landowner_id"],
        "county": row["county"],
        "acres": num(row["acres"]),
        "prime_soil_acres": num(row["prime_soil_acres"]),
        "statewide_important_soil_acres": num(row["statewide_important_soil_acres"]),
        "contiguous_preserved_acres": num(row["contiguous_preserved_acres"]),
        "road_frontage_feet": row["road_frontage_feet"],
        "sewer_available": row["sewer_available"],
        "zoning_min_lot_acres": num(row["zoning_min_lot_acres"]),
        "baseline_dwelling_rights": row["baseline_dwelling_rights"],
        "unrestricted_value_cents": row["unrestricted_value_cents"],
        "restricted_value_cents": row["restricted_value_cents"],
        "mortgage_lienholder_name": row["mortgage_lienholder_name"],
        "status": row["status"],
        "soil_quality_score": num(row["soil_quality_score"]),
        "development_pressure_score": num(row["development_pressure_score"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def application(row):
    return {
        "id": row["id"],
        "funding_round_id": row["funding_round_id"],
        "parcel_id": row["parcel_id"],
        "landowner_id": row["landowner_id"],
        "requested_price_cents": row["requested_price_cents"],
        "status": row["status"],
        "closing_status": row["closing_status"],
        "funding_plan_status": row["funding_plan_status"],
        "contiguity_acres_at_receipt": num(row["contiguity_acres_at_receipt"]),
        "composite_score": num(row["composite_score"]),
        "rank_position": row["rank_position"],
        "preliminary_easement_value_cents": row["preliminary_easement_value_cents"],
        "certified_easement_value_cents": row["certified_easement_value_cents"],
        "structure": row["structure"],
        "donation_pct": num(row["donation_pct"]),
        "installment_years": row["installment_years"],
        "negotiation_round_count": lookup.application_negotiation_round_count(row["id"]),
        "proposed_price_cents": row["proposed_price_cents"],
        "current_offer_cents": row["current_offer_cents"],
        "current_offer_expires_on": iso(row["current_offer_expires_on"]),
        "last_counter_cents": row["last_counter_cents"],
        "agreed_price_cents": row["agreed_price_cents"],
        "donation_cents": row["donation_cents"],
        "bargain_sale_price_cents": row["bargain_sale_price_cents"],
        "admin_fee_cents": row["admin_fee_cents"],
        "total_program_cost_cents": row["total_program_cost_cents"],
        "funded_cost_cents": row["funded_cost_cents"],
        "first_installment_cents": row["first_installment_cents"],
        "final_installment_cents": row["final_installment_cents"],
        "installment_interest_total_cents": row["installment_interest_total_cents"],
        "offer_issued_by_user_id": row["offer_issued_by_user_id"],
        "withdrawal_reason": row["withdrawal_reason"],
        "requirement_total": lookup.application_requirement_total(row["id"]),
        "requirement_satisfied_count": lookup.application_requirement_satisfied_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def negotiation_round(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "round_index": row["round_index"],
        "kind": row["kind"],
        "amount_cents": row["amount_cents"],
        "offer_expires_on": iso(row["offer_expires_on"]),
        "actor_role": row["actor_role"],
        "actor_user_id": row["actor_user_id"],
        "rationale": row["rationale"],
        "created_at": row["created_at"],
    }


def appraisal(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "appraiser_user_id": row["appraiser_user_id"],
        "appraiser_firm": row["appraiser_firm"],
        "engagement_start": iso(row["engagement_start"]),
        "engagement_end": iso(row["engagement_end"]),
        "method": row["method"],
        "unrestricted_value_cents": row["unrestricted_value_cents"],
        "restricted_value_cents": row["restricted_value_cents"],
        "easement_value_cents": row["easement_value_cents"],
        "basis": row["basis"],
        "status": row["status"],
        "engaged_by_user_id": row["engaged_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "review_note": row["review_note"],
        "submission_count": row["submission_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def funding_source(row):
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "source_name": row["source_name"],
        "level": row["level"],
        "authorized_cents": row["authorized_cents"],
        "obligation_window_start": iso(row["obligation_window_start"]),
        "obligation_window_end": iso(row["obligation_window_end"]),
        "max_share_pct": num(row["max_share_pct"]),
        "requires_match": row["requires_match"],
        "match_ratio": num(row["match_ratio"]),
        "fully_obligated_threshold_pct": num(row["fully_obligated_threshold_pct"]),
        "priority_order": row["priority_order"],
        "status": row["status"],
        "committed_cents": lookup.source_committed_cents(row["id"]),
        "reserved_cents": lookup.source_reserved_cents(row["id"]),
        "disbursed_cents": lookup.source_disbursed_cents(row["id"]),
        "available_cents": lookup.source_available_cents(row),
        "suspension_reason": row["suspension_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def funding_commitment(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "funding_source_id": row["funding_source_id"],
        "amount_cents": row["amount_cents"],
        "sweep_order": row["sweep_order"],
        "absorbed_remainder_cents": row["absorbed_remainder_cents"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "status": row["status"],
        "lapse_reason": row["lapse_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def closing_requirement(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "requirement_type": row["requirement_type"],
        "status": row["status"],
        "lienholder_name": row["lienholder_name"],
        "exception_count": row["exception_count"],
        "surveyed_acres": num(row["surveyed_acres"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "deficiency_note": row["deficiency_note"],
        "waiver_reason": row["waiver_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def easement(row):
    parcel_row = db.parcels.get(row["parcel_id"])
    baseline = parcel_row["baseline_dwelling_rights"] if parcel_row else 0
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "parcel_id": row["parcel_id"],
        "recorded_on": iso(row["recorded_on"]),
        "protected_acres": num(row["protected_acres"]),
        "impervious_allowance_sqft": row["impervious_allowance_sqft"],
        "impervious_used_sqft": row["impervious_used_sqft"],
        "residential_rights_retained": row["residential_rights_retained"],
        "residential_rights_extinguished": baseline - row["residential_rights_retained"],
        "subdivision_permitted": row["subdivision_permitted"],
        "permitted_uses": list(row["permitted_uses"]),
        "status": row["status"],
        "stewardship_status": row["stewardship_status"],
        "compliance_status": row["compliance_status"],
        "stewardship_hold": row["stewardship_hold"],
        "last_monitored_on": iso(row["last_monitored_on"]),
        "next_monitoring_due_on": iso(row["next_monitoring_due_on"]),
        "open_violation_count": lookup.easement_open_violation_count(row["id"]),
        "pending_amendment_count": lookup.easement_pending_amendment_count(row["id"]),
        "amendment_count": lookup.easement_amendment_count(row["id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def monitoring_visit(row):
    return {
        "id": row["id"],
        "easement_id": row["easement_id"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "status": row["status"],
        "completed_at": iso(row["completed_at"]),
        "observed_impervious_sqft": row["observed_impervious_sqft"],
        "finding": row["finding"],
        "notes": row["notes"],
        "cancellation_reason": row["cancellation_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def violation(row):
    return {
        "id": row["id"],
        "easement_id": row["easement_id"],
        "monitoring_visit_id": row["monitoring_visit_id"],
        "violation_type": row["violation_type"],
        "excess_sqft": row["excess_sqft"],
        "severity": row["severity"],
        "opened_on": iso(row["opened_on"]),
        "cure_deadline_on": iso(row["cure_deadline_on"]),
        "status": row["status"],
        "cure_plan_note": row["cure_plan_note"],
        "cured_on": iso(row["cured_on"]),
        "escalated_on": iso(row["escalated_on"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def amendment(row):
    return {
        "id": row["id"],
        "easement_id": row["easement_id"],
        "amendment_type": row["amendment_type"],
        "requested_impervious_sqft": row["requested_impervious_sqft"],
        "residential_rights_delta": row["residential_rights_delta"],
        "net_conservation_benefit_cents": row["net_conservation_benefit_cents"],
        "status": row["status"],
        "suspended_reason": row["suspended_reason"],
        "decision_reason": row["decision_reason"],
        "rescission_reason": row["rescission_reason"],
        "applied_rights_delta": row["applied_rights_delta"],
        "applied_impervious_sqft": row["applied_impervious_sqft"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
