"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROGRAM_NAME": "Northlake Transplant Center",
    "CENTER_CODE": "NLT-01",
    "ORGAN_TYPE": "KIDNEY",
    "COOLING_OFF_DAYS": 7,
    "COMPLETENESS_THRESHOLD_PCT": 80,
    "COMPLIANCE_THRESHOLD_PCT": 75,
    "EXPECTED_SURVIVAL_RATE": 0.8,
    "DONOR_FUND_POOL_CENTS": 5000000,
    "LOST_WAGE_DAILY_CAP_CENTS": 30000,
    "LOST_WAGE_WEEKLY_CAP_CENTS": 150000,
    "ROOM_CODE": "OR-1",
    "TURNOVER_BUFFER_MINUTES": 45,
}


def create_program_payload(**overrides) -> dict:
    """Only `name` and `center_code` are required; the rest have PRD defaults."""
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "center_code": DEFAULTS["CENTER_CODE"],
        "organ_type": DEFAULTS["ORGAN_TYPE"],
        "cooling_off_days": DEFAULTS["COOLING_OFF_DAYS"],
        "follow_up_completeness_threshold_pct": DEFAULTS["COMPLETENESS_THRESHOLD_PCT"],
        "follow_up_compliance_threshold_pct": DEFAULTS["COMPLIANCE_THRESHOLD_PCT"],
        "expected_one_year_survival_rate": DEFAULTS["EXPECTED_SURVIVAL_RATE"],
        "donor_fund_pool_cents": DEFAULTS["DONOR_FUND_POOL_CENTS"],
        "lost_wage_daily_cap_cents": DEFAULTS["LOST_WAGE_DAILY_CAP_CENTS"],
        "lost_wage_weekly_cap_cents": DEFAULTS["LOST_WAGE_WEEKLY_CAP_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(program_id, staff_role, npi, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": "Staff Member",
        "staff_role": staff_role,
        "npi": npi,
    }
    payload.update(overrides)
    return payload


def create_operating_room_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "room_code": DEFAULTS["ROOM_CODE"],
        "turnover_buffer_minutes": DEFAULTS["TURNOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_recipient_candidate_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "mrn": "R-001",
        "abo_blood_type": "A",
        "age_years": 44,
        "cpra": 0.85,
        "dialysis_years": 3.0,
        "medical_urgency_points": 7,
    }
    payload.update(overrides)
    return payload


def create_status_update_payload(to_status, reason_code, effective_at, **overrides) -> dict:
    payload = {
        "to_status": to_status,
        "reason_code": reason_code,
        "effective_at": effective_at,
    }
    payload.update(overrides)
    return payload


def create_donor_candidate_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "mrn": "D-001",
        "abo_blood_type": "O",
        "age_years": 41,
    }
    payload.update(overrides)
    return payload


def create_medical_evaluation_payload(donor_candidate_id, **overrides) -> dict:
    """A medical submission carries bmi, egfr_ml_min, systolic_bp and hba1c."""
    payload = {
        "donor_candidate_id": donor_candidate_id,
        "domain": "MEDICAL",
        "bmi": 24.0,
        "egfr_ml_min": 100.0,
        "systolic_bp": 118,
        "hba1c": 5.0,
    }
    payload.update(overrides)
    return payload


def create_psychosocial_evaluation_payload(donor_candidate_id, **overrides) -> dict:
    """A psychosocial submission carries financial_hardship_score and social_support_score."""
    payload = {
        "donor_candidate_id": donor_candidate_id,
        "domain": "PSYCHOSOCIAL",
        "coercion_flag": False,
        "unmanaged_substance_use": False,
        "decisional_capacity_ok": True,
        "financial_hardship_score": 1,
        "social_support_score": 9,
    }
    payload.update(overrides)
    return payload


def create_medical_findings_payload(**overrides) -> dict:
    """Finding fields for a medical resubmission."""
    payload = {"bmi": 24.0, "egfr_ml_min": 100.0, "systolic_bp": 118, "hba1c": 5.0}
    payload.update(overrides)
    return payload


def create_psychosocial_findings_payload(**overrides) -> dict:
    """Finding fields for a psychosocial resubmission."""
    payload = {
        "coercion_flag": False,
        "unmanaged_substance_use": False,
        "decisional_capacity_ok": True,
        "financial_hardship_score": 1,
        "social_support_score": 9,
    }
    payload.update(overrides)
    return payload


def create_exchange_chain_payload(program_id, chain_type="PAIRED_LOOP", **overrides) -> dict:
    payload = {"program_id": program_id, "chain_type": chain_type}
    payload.update(overrides)
    return payload


def create_chain_segment_payload(
    expected_chain_version,
    position,
    donor_candidate_id,
    recipient_candidate_id,
    predecessor_segment_id=None,
    **overrides,
) -> dict:
    payload = {
        "expected_chain_version": expected_chain_version,
        "position": position,
        "donor_candidate_id": donor_candidate_id,
        "recipient_candidate_id": recipient_candidate_id,
    }
    if predecessor_segment_id is not None:
        payload["predecessor_segment_id"] = predecessor_segment_id
    payload.update(overrides)
    return payload


def create_offer_payload(
    planned_cross_clamp_at, planned_reperfusion_at, planned_transport_minutes=90, **overrides
) -> dict:
    payload = {
        "planned_cross_clamp_at": planned_cross_clamp_at,
        "planned_reperfusion_at": planned_reperfusion_at,
        "planned_transport_minutes": planned_transport_minutes,
    }
    payload.update(overrides)
    return payload


def create_procedure_booking_payload(
    operating_room_id,
    chain_segment_id,
    surgeon_staff_id,
    booking_role,
    start_at,
    end_at,
    **overrides,
) -> dict:
    payload = {
        "operating_room_id": operating_room_id,
        "chain_segment_id": chain_segment_id,
        "surgeon_staff_id": surgeon_staff_id,
        "booking_role": booking_role,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_outcome_review_payload(
    program_id,
    period_start_on="2026-01-01",
    period_end_on="2026-06-30",
    cohort_size=10,
    observed_survivor_count=8,
    **overrides,
) -> dict:
    payload = {
        "program_id": program_id,
        "period_start_on": period_start_on,
        "period_end_on": period_end_on,
        "cohort_size": cohort_size,
        "observed_survivor_count": observed_survivor_count,
    }
    payload.update(overrides)
    return payload


def create_improvement_plan_payload(
    program_outcome_review_id,
    expected_review_version,
    title="Corrective Action Plan",
    milestone_count=3,
    target_completion_on="2027-01-31",
    **overrides,
) -> dict:
    payload = {
        "program_outcome_review_id": program_outcome_review_id,
        "expected_review_version": expected_review_version,
        "title": title,
        "milestone_count": milestone_count,
        "target_completion_on": target_completion_on,
    }
    payload.update(overrides)
    return payload


def create_donor_cost_claim_payload(
    donor_candidate_id,
    claim_type="MEDICAL",
    coverage_source="PROGRAM_FUND",
    submitted_amount_cents=100000,
    service_from_on="2026-08-09",
    service_to_on="2026-08-09",
    **overrides,
) -> dict:
    payload = {
        "donor_candidate_id": donor_candidate_id,
        "claim_type": claim_type,
        "coverage_source": coverage_source,
        "submitted_amount_cents": submitted_amount_cents,
        "service_from_on": service_from_on,
        "service_to_on": service_to_on,
    }
    payload.update(overrides)
    return payload
