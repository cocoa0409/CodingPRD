"""Response payloads.  Derived fields are recomputed on every read so the
conserved quantities of PRD 2.8 can never drift from a fresh recount."""

from services import fee_schedule as fs
from services import health_center as hc_svc
from validation import iso


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def health_center(row):
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "grant_number": row["grant_number"],
        "pps_base_rate_cents": row["pps_base_rate_cents"],
        "medicare_upper_limit_cents": row["medicare_upper_limit_cents"],
        "nominal_fee_cap_cents": row["nominal_fee_cap_cents"],
        "scope_baseline_locked": row["scope_baseline_locked"],
    }
    out.update(hc_svc.derived(row))
    out.update(
        {
            "created_at": iso(row["created_at"]),
            "updated_at": iso(row["updated_at"]),
            "version": row["version"],
        }
    )
    return out


def poverty_guideline(row):
    # PRD 2.4: a guideline carries only id and created_at.
    return {
        "id": row["id"],
        "guideline_year": row["guideline_year"],
        "base_amount_cents": row["base_amount_cents"],
        "increment_cents": row["increment_cents"],
        "created_at": iso(row["created_at"]),
    }


def board_member(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "seat_number": row["seat_number"],
        "seat_type": row["seat_type"],
        "patient_id": row["patient_id"],
        "expertise_category": row["expertise_category"],
        "derives_over_10pct_income_from_healthcare": row[
            "derives_over_10pct_income_from_healthcare"
        ],
        "term_start": iso(row["term_start"]),
        "term_end": iso(row["term_end"]),
        "status": row["status"],
        "resignation_date": iso(row["resignation_date"]),
        "patient_seat_qualified": hc_svc.patient_seat_qualified(row),
    }
    out.update(_common(row))
    return out


def service_site(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "site_name": row["site_name"],
        "site_type": row["site_type"],
        "address_line": row["address_line"],
        "weekly_service_hours": row["weekly_service_hours"],
        "status": row["status"],
        "in_scope_since": iso(row["in_scope_since"]),
        "hold_reason": row["hold_reason"],
    }
    out.update(_common(row))
    return out


def service_definition(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "service_code": row["service_code"],
        "service_category": row["service_category"],
        "delivery_method": row["delivery_method"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def scope_change_request(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "target_site_id": row["target_site_id"],
        "target_service_definition_id": row["target_service_definition_id"],
        "request_type": row["request_type"],
        "justification": row["justification"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "held_from_status": row["held_from_status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "decision_note": row["decision_note"],
    }
    out.update(_common(row))
    return out


def fee_schedule(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "fpg_year": row["fpg_year"],
        "effective_start": iso(row["effective_start"]),
        "effective_end": iso(row["effective_end"]),
        "nominal_fee_cents": row["nominal_fee_cents"],
        "status": row["status"],
        "board_vote_date": iso(row["board_vote_date"]),
        "adopted_at": iso(row["adopted_at"]),
        "adopted_by_user_id": row["adopted_by_user_id"],
        "last_reviewed_at": iso(row["last_reviewed_at"]),
        "reviewed_against_guideline_year": row["reviewed_against_guideline_year"],
        "review_status": fs.review_status(row),
        "superseded_by_fee_schedule_id": row["superseded_by_fee_schedule_id"],
    }
    out.update(_common(row))
    return out


def discount_tier(row):
    out = {
        "id": row["id"],
        "fee_schedule_id": row["fee_schedule_id"],
        "tier_label": row["tier_label"],
        "fpg_min_pct": row["fpg_min_pct"],
        "fpg_max_pct": row["fpg_max_pct"],
        "discount_kind": row["discount_kind"],
        "discount_pct": row["discount_pct"],
        "sort_order": row["sort_order"],
    }
    out.update(_common(row))
    return out


def patient(row):
    out = {
        "id": row["id"],
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "household_size": row["household_size"],
        "sliding_fee_status": hc_svc.sliding_fee_status(row["id"]),
        "patient_balance_cents": hc_svc.patient_balance_cents(row["id"]),
    }
    out.update(_common(row))
    return out


def income_verification(row):
    out = {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "declared_annual_income_cents": row["declared_annual_income_cents"],
        "household_size": row["household_size"],
        "documentation_type": row["documentation_type"],
        "effective_date": iso(row["effective_date"]),
        "expires_at": iso(row["expires_at"]),
        "status": row["status"],
        "resubmit_round": row["resubmit_round"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "verified_by_user_id": row["verified_by_user_id"],
        "insufficiency_reason": row["insufficiency_reason"],
        "guideline_year_used": row["guideline_year_used"],
        "fpg_percent": row["fpg_percent"],
        "uds_guideline_year_used": row["uds_guideline_year_used"],
        "uds_fpg_percent": row["uds_fpg_percent"],
        "assigned_discount_tier_id": row["assigned_discount_tier_id"],
        "assigned_tier_label": row["assigned_tier_label"],
        "supersedes_income_verification_id": row["supersedes_income_verification_id"],
    }
    out.update(_common(row))
    return out


def encounter(row):
    out = {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "service_site_id": row["service_site_id"],
        "service_definition_id": row["service_definition_id"],
        "fee_schedule_id": row["fee_schedule_id"],
        "income_verification_id": row["income_verification_id"],
        "pinned_discount_tier_id": row["pinned_discount_tier_id"],
        "encounter_date": iso(row["encounter_date"]),
        "payer_type": row["payer_type"],
        "gross_charge_cents": row["gross_charge_cents"],
        "patient_charge_cents": row["patient_charge_cents"],
        "charge_basis": row["charge_basis"],
        "sliding_fee_applied": row["sliding_fee_applied"],
        "charge_adjustment_cents": row["charge_adjustment_cents"],
        "waived_amount_cents": row["waived_amount_cents"],
        "pps_encounter_rate_cents": row["pps_encounter_rate_cents"],
        "mco_paid_cents": row["mco_paid_cents"],
        "wraparound_due_cents": row["wraparound_due_cents"],
        "pps_claim_status": row["pps_claim_status"],
        "wraparound_status": row["wraparound_status"],
        "claim_reference": row["claim_reference"],
        "void_reason": row["void_reason"],
    }
    out.update(_common(row))
    return out


def waiver(row):
    out = {
        "id": row["id"],
        "encounter_id": row["encounter_id"],
        "waiver_reason": row["waiver_reason"],
        "status": row["status"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
        "waived_amount_cents": row["waived_amount_cents"],
    }
    out.update(_common(row))
    return out


def uds_report(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "reporting_year": row["reporting_year"],
        "status": row["status"],
        "total_patient_count": row["total_patient_count"],
        "patients_at_or_below_100_count": row["patients_at_or_below_100_count"],
        "patients_101_to_150_count": row["patients_101_to_150_count"],
        "patients_151_to_200_count": row["patients_151_to_200_count"],
        "patients_over_200_count": row["patients_over_200_count"],
        "unverified_patient_count": row["unverified_patient_count"],
        "composite_quality_rate_pct": row["composite_quality_rate_pct"],
        "included_measure_count": row["included_measure_count"],
        "computed_at": iso(row["computed_at"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "return_reason": row["return_reason"],
        "return_round": row["return_round"],
    }
    out.update(_common(row))
    return out


def quality_measure_result(row):
    out = {
        "id": row["id"],
        "uds_report_id": row["uds_report_id"],
        "measure_code": row["measure_code"],
        "numerator": row["numerator"],
        "denominator": row["denominator"],
        "benchmark_pct": row["benchmark_pct"],
        "rate_pct": row["rate_pct"],
        "inclusion_status": row["inclusion_status"],
        "meets_benchmark": row["meets_benchmark"],
    }
    out.update(_common(row))
    return out


def site_visit_finding(row):
    out = {
        "id": row["id"],
        "health_center_id": row["health_center_id"],
        "service_site_id": row["service_site_id"],
        "requirement_code": row["requirement_code"],
        "severity": row["severity"],
        "finding_summary": row["finding_summary"],
        "cap_due_days": row["cap_due_days"],
        "cap_due_at": iso(row["cap_due_at"]),
        "status": row["status"],
        "escalated_at": iso(row["escalated_at"]),
        "issued_by_user_id": row["issued_by_user_id"],
    }
    out.update(_common(row))
    return out


def corrective_action_plan(row):
    out = {
        "id": row["id"],
        "site_visit_finding_id": row["site_visit_finding_id"],
        "narrative": row["narrative"],
        "milestone_count": row["milestone_count"],
        "target_completion_date": iso(row["target_completion_date"]),
        "status": row["status"],
        "submit_round": row["submit_round"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "rejection_reason": row["rejection_reason"],
    }
    out.update(_common(row))
    return out
