"""Payload factories — one per entity, input fields only."""

# Default ISO 8601 UTC instants used across setups.
DEFAULT_HIRE_DATE = "2026-06-01T00:00:00Z"
FAR_FUTURE_EXPIRY = "2030-01-01T00:00:00Z"


def create_onboarding_payload(**overrides) -> dict:
    """POST /onboardings. citizenship_status and hire_date are required;
    work_auth_expiration only when ALIEN_AUTHORIZED; requires_everify defaults true."""
    defaults = {
        "employee_full_name": "Test Hire",
        "employee_email": "hire@example.com",
        "citizenship_status": "US_CITIZEN",
        "hire_date": DEFAULT_HIRE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_identity_document_payload(onboarding_id, **overrides) -> dict:
    """POST /identity-documents."""
    defaults = {
        "onboarding_id": onboarding_id,
        "list_category": "LIST_A",
        "document_title": "US_PASSPORT",
        "document_number": "P000",
        "expiration_date": FAR_FUTURE_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def section1_attest_payload(**overrides) -> dict:
    """POST /onboardings/{id}/section1-attest. section1_preparer_used is optional."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def section2_complete_payload(document_ids, expected_onboarding_version, **overrides) -> dict:
    """POST /onboardings/{id}/section2-complete."""
    defaults = {
        "document_ids": document_ids,
        "expected_onboarding_version": expected_onboarding_version,
    }
    defaults.update(overrides)
    return defaults


def override_payload(**overrides) -> dict:
    """POST /onboardings/{id}/override."""
    defaults = {"override_reason": "documented good-faith delay"}
    defaults.update(overrides)
    return defaults


def create_everify_case_payload(onboarding_id, i9_form_id, expected_onboarding_version, **overrides) -> dict:
    """POST /everify-cases. late_reason is optional unless the submission is late."""
    defaults = {
        "onboarding_id": onboarding_id,
        "i9_form_id": i9_form_id,
        "expected_onboarding_version": expected_onboarding_version,
    }
    defaults.update(overrides)
    return defaults


def everify_result_payload(result, **overrides) -> dict:
    """POST /everify-cases/{id}/result. agency required only when result == TNC."""
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_work_authorization_payload(onboarding_id, **overrides) -> dict:
    """POST /work-authorizations."""
    defaults = {
        "onboarding_id": onboarding_id,
        "auth_type": "EAD",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-09-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_section3_payload(work_authorization_id, reverification_reason, new_expiration_date, **overrides) -> dict:
    """POST /i9-forms/{id}/section3."""
    defaults = {
        "work_authorization_id": work_authorization_id,
        "reverification_reason": reverification_reason,
        "new_expiration_date": new_expiration_date,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    """POST /_clock/set_current_utc."""
    return {"to_iso8601": to_iso8601}
