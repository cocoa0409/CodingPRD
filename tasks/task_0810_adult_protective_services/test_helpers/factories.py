"""Payload factories — one per entity, input fields only (PRD-declared)."""

DEFAULTS = {
    "CLIENT_NAME": "Test Client",
    "DOB": "1948-01-01",
    "ADDRESS": "1 Test Way",
    "INSTITUTION": "Test Bank",
    "BALANCE": 500_000,
    "FACILITY": "Test Facility",
    "TOTAL_BEDS": 2,
    "NARRATIVE": "test allegation narrative",
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "address": DEFAULTS["ADDRESS"],
    }
    payload.update(overrides)
    return payload


def create_report_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "reporter_type": "MANDATORY",
        "allegation_types": ["NEGLECT"],
        "priority": "ROUTINE",
        "narrative": DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def create_account_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "institution_name": DEFAULTS["INSTITUTION"],
        "total_balance_cents": DEFAULTS["BALANCE"],
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FACILITY"],
        "total_beds": DEFAULTS["TOTAL_BEDS"],
    }
    payload.update(overrides)
    return payload


def risk_assessment_payload(assessment_type, expected_client_version, **overrides) -> dict:
    payload = {
        "assessment_type": assessment_type,
        "isolation_level": 2,
        "cognitive_impairment_level": 2,
        "financial_vulnerability_level": 1,
        "caregiver_dependency_level": 0,
        "prior_report_count": 0,
        "expected_client_version": expected_client_version,
    }
    payload.update(overrides)
    return payload


def create_placement_payload(case_id, facility_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "facility_id": facility_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_freeze_payload(case_id, account_id, flagged_amount_cents, freeze_start, freeze_end, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "account_id": account_id,
        "flagged_amount_cents": flagged_amount_cents,
        "freeze_start": freeze_start,
        "freeze_end": freeze_end,
    }
    payload.update(overrides)
    return payload
