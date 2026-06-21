"""Payload factories — one per entity, input fields only (Private Adoption Agency API)."""

DEFAULTS = {
    "AGENCY_NAME": "Grace Adoption",
    "LICENSED_STATE": "CA",
    "FEE_SCHEDULE_CENTS": 3_000_000,
    "CASE_LABEL": "C-1",
    "CHILD_STATE": "CA",
    "FAMILY_STATE": "CA",
    "APPLICANT_NAME": "Lee",
    "RESIDENCE_STATE": "CA",
    "HOUSEHOLD_SIZE": 2,
    "ANNUAL_INCOME_CENTS": 8_000_000,
    "BIRTH_PARENT_NAME": "Pat Doe",
    "BIRTH_STATE": "CA",
    "PARENT_ROLE": "BIRTH_MOTHER",
    "CHILD_DOB": "2026-06-01T08:00:00.000Z",
    "REVOCATION_BASIS": "BUSINESS_DAYS",
    "EXPENSE_CATEGORY": "MEDICAL",
    "EXPENSE_AMOUNT_CENTS": 100_000,
    "TXN_TYPE": "DEPOSIT",
    "TXN_AMOUNT_CENTS": 500_000,
}


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "licensed_state": DEFAULTS["LICENSED_STATE"],
        "fee_schedule_cents": DEFAULTS["FEE_SCHEDULE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(agency_id: str, to_iso8601: str) -> dict:
    return {"agency_id": agency_id, "to_iso8601": to_iso8601}


def create_case_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "case_label": DEFAULTS["CASE_LABEL"],
        "child_state": DEFAULTS["CHILD_STATE"],
        "family_state": DEFAULTS["FAMILY_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "primary_applicant_name": DEFAULTS["APPLICANT_NAME"],
        "residence_state": DEFAULTS["RESIDENCE_STATE"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_home_study_payload(case_id: str, family_id: str, **overrides) -> dict:
    defaults = {"case_id": case_id, "family_id": family_id}
    defaults.update(overrides)
    return defaults


def create_birth_parent_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "legal_name": DEFAULTS["BIRTH_PARENT_NAME"],
        "birth_state": DEFAULTS["BIRTH_STATE"],
        "parent_role": DEFAULTS["PARENT_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_counseling_session_payload(birth_parent_id: str, case_id: str,
                                      start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "birth_parent_id": birth_parent_id,
        "case_id": case_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(case_id: str, family_id: str, birth_parent_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "family_id": family_id,
        "birth_parent_id": birth_parent_id,
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(case_id: str, birth_parent_id: str, expected_case_version,
                           **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "birth_parent_id": birth_parent_id,
        "child_dob": DEFAULTS["CHILD_DOB"],
        "revocation_basis": DEFAULTS["REVOCATION_BASIS"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_icpc_payload(case_id: str, **overrides) -> dict:
    defaults = {"case_id": case_id}
    defaults.update(overrides)
    return defaults


def create_placement_payload(case_id: str, family_id: str, **overrides) -> dict:
    defaults = {"case_id": case_id, "family_id": family_id}
    defaults.update(overrides)
    return defaults


def create_visit_payload(case_id: str, placement_id: str, window_start: str,
                         window_end: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "placement_id": placement_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "category": DEFAULTS["EXPENSE_CATEGORY"],
        "amount_cents": DEFAULTS["EXPENSE_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_escrow_payload(case_id: str, expected_case_version, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "txn_type": DEFAULTS["TXN_TYPE"],
        "amount_cents": DEFAULTS["TXN_AMOUNT_CENTS"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(case_id: str, **overrides) -> dict:
    defaults = {"case_id": case_id}
    defaults.update(overrides)
    return defaults
