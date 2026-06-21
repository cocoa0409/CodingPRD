"""Payload factories — one per entity, input fields only (PRD §3 / §4)."""


def create_applicant_payload(**overrides) -> dict:
    """Required: full_name, date_of_birth. Optional: prior_marriage_status
    (default NEVER_MARRIED), prior_dissolution_date, has_judicial_consent
    (default false)."""
    defaults = {
        "full_name": "Test Applicant",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_officiant_payload(**overrides) -> dict:
    """Required: full_name, credential_type, registration_expires_on."""
    defaults = {
        "full_name": "Rev. Test",
        "credential_type": "CLERGY",
        "registration_expires_on": "2030-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_a_id, applicant_b_id, **overrides) -> dict:
    """Required: applicant_a_id, applicant_b_id, ceremony_county.
    Optional: is_confidential (default false)."""
    defaults = {
        "applicant_a_id": applicant_a_id,
        "applicant_b_id": applicant_b_id,
        "ceremony_county": "Kern",
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(license_id, officiant_id, ceremony_date, **overrides) -> dict:
    """Required: license_id, officiant_id, ceremony_date."""
    defaults = {
        "license_id": license_id,
        "officiant_id": officiant_id,
        "ceremony_date": ceremony_date,
    }
    defaults.update(overrides)
    return defaults


def create_certified_copy_payload(record_id, requester_kind, copies_requested, **overrides) -> dict:
    """Required: record_id, requester_kind, copies_requested.
    Optional: fee_waiver_id (default null)."""
    defaults = {
        "record_id": record_id,
        "requester_kind": requester_kind,
        "copies_requested": copies_requested,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(record_id, amendment_type, **overrides) -> dict:
    """Required: record_id, amendment_type, field_path, new_value."""
    defaults = {
        "record_id": record_id,
        "amendment_type": amendment_type,
        "field_path": "spouse_a_name",
        "new_value": "Corrected Name",
    }
    defaults.update(overrides)
    return defaults


def create_apostille_payload(copy_request_id, destination_country="France", **overrides) -> dict:
    """Required: copy_request_id, destination_country."""
    defaults = {
        "copy_request_id": copy_request_id,
        "destination_country": destination_country,
    }
    defaults.update(overrides)
    return defaults


def create_fee_waiver_payload(applicant_id, declared_monthly_income_cents, household_size, **overrides) -> dict:
    """Required: applicant_id, declared_monthly_income_cents, household_size."""
    defaults = {
        "applicant_id": applicant_id,
        "declared_monthly_income_cents": declared_monthly_income_cents,
        "household_size": household_size,
    }
    defaults.update(overrides)
    return defaults
