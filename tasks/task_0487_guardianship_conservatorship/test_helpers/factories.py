"""Payload factories — one per entity, input fields only.

Each factory provides PRD-valid defaults and accepts **overrides for the
fields a test needs to control. Computed/system fields are never included.
"""

DEFAULTS = {
    "PERSON_NAME": "Test Ward",
    "DOB": "1948-01-01",
    "FIDUCIARY_NAME": "Test Fiduciary",
    "INSTITUTION": "First Trust",
    "SURETY": "Acme Surety",
    "ALLEGED_GROUNDS": "diminished capacity",
    "PERIOD_YEAR": 2026,
}


def create_protected_person_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["PERSON_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "annual_income_cents": 0,
        "liquid_estate_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_fiduciary_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["FIDUCIARY_NAME"],
        "fiduciary_kind": "PROFESSIONAL",
    }
    payload.update(overrides)
    return payload


def create_case_payload(protected_person_id, **overrides) -> dict:
    payload = {
        "protected_person_id": protected_person_id,
        "case_type": "GUARDIANSHIP",
    }
    payload.update(overrides)
    return payload


def create_petition_payload(case_id, nominated_fiduciary_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "nominated_fiduciary_id": nominated_fiduciary_id,
        "requested_authority": "PERSON",
        "alleged_grounds": DEFAULTS["ALLEGED_GROUNDS"],
    }
    payload.update(overrides)
    return payload


def create_evaluation_payload(petition_id, **overrides) -> dict:
    payload = {
        "petition_id": petition_id,
        "finding": "INCAPACITATED",
        "recommended_scope": "PERSON",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(case_id, fiduciary_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "fiduciary_id": fiduciary_id,
    }
    payload.update(overrides)
    return payload


def post_bond_payload(**overrides) -> dict:
    payload = {
        "posted_amount_cents": 10_000_000,
        "surety_name": DEFAULTS["SURETY"],
    }
    payload.update(overrides)
    return payload


def create_restricted_account_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "institution_name": DEFAULTS["INSTITUTION"],
    }
    payload.update(overrides)
    return payload


def create_inventory_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "real_property_cents": 0,
        "liquid_assets_cents": 0,
        "tangible_property_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_budget_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "period_year": DEFAULTS["PERIOD_YEAR"],
        "care_cap_cents": 0,
        "medical_cap_cents": 0,
        "admin_cap_cents": 0,
    }
    payload.update(overrides)
    return payload


def approve_budget_payload(expected_case_version, **overrides) -> dict:
    payload = {"expected_case_version": expected_case_version}
    payload.update(overrides)
    return payload


def create_expenditure_payload(
    case_id, budget_id, expected_case_version, **overrides
) -> dict:
    payload = {
        "case_id": case_id,
        "budget_id": budget_id,
        "category": "CARE",
        "amount_cents": 100_000,
        "payee_name": "Test Payee",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_accounting_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "period_year": DEFAULTS["PERIOD_YEAR"],
        "opening_balance_cents": 0,
        "reported_income_cents": 0,
        "reported_disbursed_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "residence_type": "HOME",
        "visitation_min_per_month": 4,
        "window_start_iso": "2026-01-01T00:00:00Z",
        "window_end_iso": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_review_payload(case_id, subject_kind, subject_ref_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "subject_kind": subject_kind,
        "subject_ref_id": subject_ref_id,
        "review_window_start_iso": "2026-01-01T00:00:00Z",
        "review_window_end_iso": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def remove_appointment_payload(for_cause=False, **overrides) -> dict:
    payload = {"for_cause": for_cause}
    payload.update(overrides)
    return payload


def dispose_review_payload(outcome, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload
