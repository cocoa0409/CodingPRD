"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PATIENT_NAME": "Test Patient",
    "PATIENT_DOB": "1980-01-01",
    "ENCOUNTER_DATE": "2026-01-10",
    "TOTAL_CHARGES_CENTS": 100000,
    "INSURANCE_PAID_CENTS": 0,
    "REPORTED_INCOME_CENTS": 2000000,
    "REPORTED_ASSETS_CENTS": 0,
    "MEMBER_AGE": 40,
    "DOC_PERIOD_START": "2025-01-01",
    "DOC_PERIOD_END": "2025-12-31",
    "PAID_AT": "2026-02-01T00:00:00Z",
}


def create_policy_payload(**overrides) -> dict:
    """Financial assistance policy create payload (PRD §3.1)."""
    defaults = {
        "policy_code": "FAP-2026",
        "fpl_base_cents": 1500000,
        "fpl_increment_cents": 500000,
        "full_discount_max_fpl_pct": 200,
        "partial_discount_max_fpl_pct": 300,
        "partial_discount_floor_pct": 50.0,
        "asset_limit_cents": 2500000,
        "retroactive_window_days": 240,
        "notification_period_days": 120,
        "eca_notice_days": 30,
        "doc_response_days": 30,
        "presumptive_partial_score_threshold": 70.0,
        "presumptive_full_score_threshold": 90.0,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["PATIENT_DOB"],
        "ssn_last4": "0001",
        "mrn": "MRN-0001",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "encounter_date": DEFAULTS["ENCOUNTER_DATE"],
        "total_charges_cents": DEFAULTS["TOTAL_CHARGES_CENTS"],
        "insurance_paid_cents": DEFAULTS["INSURANCE_PAID_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1000,
        "paid_at": DEFAULTS["PAID_AT"],
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(patient_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "screening_source": "STANDARD",
        "reported_annual_income_cents": DEFAULTS["REPORTED_INCOME_CENTS"],
        "reported_liquid_assets_cents": DEFAULTS["REPORTED_ASSETS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Household Member",
        "relationship": "SELF",
        "age": DEFAULTS["MEMBER_AGE"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    """Verification document upload payload (PRD §3.5). household_member_id is
    optional and omitted unless supplied."""
    defaults = {
        "doc_type": "TAX_RETURN",
        "period_start": DEFAULTS["DOC_PERIOD_START"],
        "period_end": DEFAULTS["DOC_PERIOD_END"],
        "amount_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    """Presumptive screening payload (PRD §3.7); factors omitted keys stay null."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_determination_payload(
    application_id, basis, covered_account_ids, expected_application_version
) -> dict:
    return {
        "application_id": application_id,
        "basis": basis,
        "covered_account_ids": covered_account_ids,
        "expected_application_version": expected_application_version,
    }


def create_adjustment_payload(determination_id, expected_account_version) -> dict:
    return {
        "determination_id": determination_id,
        "expected_account_version": expected_account_version,
    }


def create_notice_payload(notice_type, delivery_channel="MAIL") -> dict:
    return {"notice_type": notice_type, "delivery_channel": delivery_channel}


def create_collection_action_payload(action_type="CREDIT_REPORT") -> dict:
    return {"action_type": action_type}


def create_report_payload(reporting_year=2026) -> dict:
    return {"reporting_year": reporting_year}
