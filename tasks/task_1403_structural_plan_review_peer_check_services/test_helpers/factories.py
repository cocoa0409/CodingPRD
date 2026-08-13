"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STATE_CODE": "CA",
    "IBC_EDITION": "IBC_2021",
    "ASCE7_EDITION": "ASCE7_22",
    "FEE_METHOD": "VALUATION",
    "TURNAROUND_DAYS": 15,
    "SLA_MODE": "BUSINESS",
    "LICENSE_NUMBER": "P100",
    "LICENSE_EXPIRES": "2030-01-01",
    "VALUATION_CENTS": 30_000_000,
    "FLOOR_AREA_SQFT": 10_000,
    "DOCUMENTS_REF": "s3://plan-set",
}


def make_license(state_code="CA", license_type="PE", license_number=None,
                 expires_on="2030-01-01"):
    return {
        "state_code": state_code,
        "license_type": license_type,
        "license_number": license_number or DEFAULTS["LICENSE_NUMBER"],
        "expires_on": expires_on,
    }


def create_jurisdiction_payload(**overrides) -> dict:
    """Required jurisdiction inputs; optional knobs omitted unless given so
    server-side defaults stay observable."""
    payload = {
        "state_code": DEFAULTS["STATE_CODE"],
        "ibc_edition": DEFAULTS["IBC_EDITION"],
        "asce7_edition": DEFAULTS["ASCE7_EDITION"],
        "fee_method": DEFAULTS["FEE_METHOD"],
        "turnaround_days": DEFAULTS["TURNAROUND_DAYS"],
        "sla_mode": DEFAULTS["SLA_MODE"],
    }
    payload.update(overrides)
    return payload


def create_reviewer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Reviewer",
        "licenses": [make_license()],
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(jurisdiction_id, reviewer_of_record_id,
                              applicant_contact_id="app-1", **overrides) -> dict:
    payload = {
        "project_name": "Test Project",
        "jurisdiction_id": jurisdiction_id,
        "applicant_contact_id": applicant_contact_id,
        "reviewer_of_record_id": reviewer_of_record_id,
        "building_type": "COMMERCIAL",
        "risk_category": "II",
        "scope": "FULL_REVIEW",
        "declared_valuation_cents": DEFAULTS["VALUATION_CENTS"],
        "floor_area_sqft": DEFAULTS["FLOOR_AREA_SQFT"],
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "documents_ref": DEFAULTS["DOCUMENTS_REF"],
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(cycle_id, reviewer_id, expected_cycle_version) -> dict:
    return {
        "cycle_id": cycle_id,
        "reviewer_id": reviewer_id,
        "expected_cycle_version": expected_cycle_version,
    }


def create_comment_payload(raised_in_cycle_id, **overrides) -> dict:
    payload = {
        "raised_in_cycle_id": raised_in_cycle_id,
        "code_section_ref": "1604.3",
        "reference_edition": DEFAULTS["IBC_EDITION"],
        "severity": "MINOR",
        "category": "CALCULATION",
        "comment_text": "Deficiency noted",
    }
    payload.update(overrides)
    return payload


def create_response_payload(**overrides) -> dict:
    payload = {"response_text": "Addressed in the attached revision"}
    payload.update(overrides)
    return payload


def create_deferred_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "item_type": "TRUSS",
        "description": "Deferred design package",
    }
    payload.update(overrides)
    return payload


def approve_cycle_payload(load_path_confirmed=True, lateral_system_confirmed=True) -> dict:
    return {
        "load_path_confirmed": load_path_confirmed,
        "lateral_system_confirmed": lateral_system_confirmed,
    }
