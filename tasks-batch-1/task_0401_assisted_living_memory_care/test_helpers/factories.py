"""Payload factories — one per entity, input fields only.

Required fields are always present in the defaults; optional fields (those the PRD
marks optional or with a server default) are omitted unless overridden, so that
required-field-omission tests can delete a required key without optional noise.
"""


def create_facility_payload(**overrides) -> dict:
    """Required: name, state_code, license_number, care_point_rate_cents."""
    payload = {
        "name": "Test Facility",
        "state_code": "CA",
        "license_number": "CA-TEST-001",
        "care_point_rate_cents": 2000,
    }
    payload.update(overrides)
    return payload


def create_unit_payload(**overrides) -> dict:
    """Required: unit_number, wing, monthly_base_rent_cents."""
    payload = {
        "unit_number": "100",
        "wing": "ASSISTED_LIVING",
        "monthly_base_rent_cents": 400000,
    }
    payload.update(overrides)
    return payload


def create_resident_payload(facility_id, **overrides) -> dict:
    """Required: facility_id, full_name, date_of_birth. Optional: stay_type, respite_end_date."""
    payload = {
        "facility_id": facility_id,
        "full_name": "Test Resident",
        "date_of_birth": "1940-01-01",
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(resident_id, **overrides) -> dict:
    """Required: resident_id, five ADL scores, cognition_score. Optional: behavior_flags."""
    payload = {
        "resident_id": resident_id,
        "adl_bathing": 1,
        "adl_dressing": 1,
        "adl_toileting": 1,
        "adl_transferring": 1,
        "adl_eating": 1,
        "cognition_score": 0,
        "behavior_flags": 0,
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(resident_id, source_assessment_id, **overrides) -> dict:
    """Required: resident_id, source_assessment_id, adl_support_items. Optional: supersedes_care_plan_id."""
    payload = {
        "resident_id": resident_id,
        "source_assessment_id": source_assessment_id,
        "adl_support_items": [{"task": "bathing", "frequency_per_day": 1}],
    }
    payload.update(overrides)
    return payload


def create_medication_order_payload(resident_id, **overrides) -> dict:
    """Required: resident_id, drug_name, dose, schedule_times. Optional: is_controlled."""
    payload = {
        "resident_id": resident_id,
        "drug_name": "Test Drug",
        "dose": "5 mg",
        "schedule_times": ["08:00"],
    }
    payload.update(overrides)
    return payload


def create_administration_payload(scheduled_time, outcome, **overrides) -> dict:
    """Required: scheduled_time, outcome. Optional: witness_user_id."""
    payload = {
        "scheduled_time": scheduled_time,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def create_move_in_agreement_payload(resident_id, unit_id, move_in_date, **overrides) -> dict:
    """Required: resident_id, unit_id, move_in_date. Optional: community_fee_cents (default 0)."""
    payload = {
        "resident_id": resident_id,
        "unit_id": unit_id,
        "move_in_date": move_in_date,
    }
    payload.update(overrides)
    return payload


def create_billing_statement_payload(resident_id, period_year, period_month, **overrides) -> dict:
    """Required: resident_id, period_year, period_month. Optional: is_first_statement (default false)."""
    payload = {
        "resident_id": resident_id,
        "period_year": period_year,
        "period_month": period_month,
    }
    payload.update(overrides)
    return payload


def create_incident_report_payload(resident_id, **overrides) -> dict:
    """Required: resident_id, incident_type, occurred_at, severity."""
    payload = {
        "resident_id": resident_id,
        "incident_type": "FALL",
        "occurred_at": "2026-03-01T08:00:00Z",
        "severity": "MINOR",
    }
    payload.update(overrides)
    return payload


def create_deficiency_payload(**overrides) -> dict:
    """Required: tag_code, scope_severity, cited_at."""
    payload = {
        "tag_code": "F-880",
        "scope_severity": "D_F_NO_HARM",
        "cited_at": "2026-03-05T10:00:00Z",
    }
    payload.update(overrides)
    return payload
