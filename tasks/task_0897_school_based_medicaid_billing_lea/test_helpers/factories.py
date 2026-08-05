"""Payload factories — one per entity, input fields only.

Each factory returns a plain dict suitable as a request body; pass ``**overrides``
to control any field a given test needs to pin.
"""
import itertools

_seq = itertools.count(1)


def _uid(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def create_student_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/students. medicaid_eligible is optional."""
    defaults = {
        "medicaid_id": _uid("MA"),
        "first_name": "Test",
        "last_name": "Student",
        "date_of_birth": "2015-04-01",
        "district_student_id": _uid("D"),
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/providers."""
    defaults = {
        "npi": _uid("NPI"),
        "first_name": "Pat",
        "last_name": "Roe",
        "discipline": "SLP",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/provider-credentials."""
    defaults = {
        "provider_id": None,
        "credential_type": "STATE_LICENSE",
        "license_number": _uid("L"),
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/iep-authorizations."""
    defaults = {
        "student_id": None,
        "service_type": "SPEECH_THERAPY",
        "procedure_code": "92507",
        "unit_minutes": 15,
        "unit_rate_cents": 3000,
        "authorized_minutes_per_session": 30,
        "sessions_per_week": 2,
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/parental-consents."""
    defaults = {
        "student_id": None,
        "consent_type": "BILLING",
        "signed_by": "Parent",
    }
    defaults.update(overrides)
    return defaults


def create_service_log_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/service-logs. group_size is optional."""
    defaults = {
        "iep_authorization_id": None,
        "provider_id": None,
        "student_id": None,
        "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z",
        "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/claims."""
    defaults = {
        "student_id": None,
        "service_month": "2026-03",
    }
    defaults.update(overrides)
    return defaults


def create_quarter_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/rmts-quarters."""
    defaults = {"fiscal_quarter": "2026-Q1"}
    defaults.update(overrides)
    return defaults


def create_moment_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/rmts-moments."""
    defaults = {
        "rmts_quarter_id": None,
        "provider_id": None,
        "moment_timestamp": "2026-02-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    """Input fields for POST /sbmb/cost-settlements."""
    defaults = {
        "rmts_quarter_id": None,
        "certified_cost_cents": 1000000,
        "iep_ratio_bps": 4000,
        "fmap_bps": 5000,
        "interim_paid_cents": 0,
        "expected_rmts_quarter_version": 1,
    }
    defaults.update(overrides)
    return defaults
