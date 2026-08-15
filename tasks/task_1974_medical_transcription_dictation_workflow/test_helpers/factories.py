"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    T0,
    WIDE_WINDOW_START,
    WIDE_WINDOW_END,
    TEST_DEFAULTS,
    TEXT_65_CHARS,
)


def create_clinic_account_payload(**overrides) -> dict:
    """PRD §3.1: only `name` is required; the four config knobs carry defaults."""
    defaults = {"name": "Test Clinic"}
    defaults.update(overrides)
    return defaults


def create_sla_policy_payload(clinic_account_id, **overrides) -> dict:
    defaults = {
        "clinic_account_id": clinic_account_id,
        "priority": "ROUTINE",
        "tat_minutes": TEST_DEFAULTS["ROUTINE_TAT_MINUTES"],
        "rate_per_line_cents": 10,
        "breach_credit_pct": 5,
        "measurement_basis": "END_TO_END",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(clinic_account_id, **overrides) -> dict:
    defaults = {
        "clinic_account_id": clinic_account_id,
        "full_name": "Dr. Test Provider",
        "specialty": "GENERAL",
    }
    defaults.update(overrides)
    return defaults


def create_editor_payload(**overrides) -> dict:
    defaults = {"display_name": "Test Editor"}
    defaults.update(overrides)
    return defaults


def create_shift_window_payload(editor_id, **overrides) -> dict:
    defaults = {
        "editor_id": editor_id,
        "start_at": WIDE_WINDOW_START,
        "end_at": WIDE_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_dictation_job_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "work_type": "CONSULT",
        "priority": "ROUTINE",
        "audio_duration_seconds": TEST_DEFAULTS["AUDIO_DURATION_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_submit_payload(**overrides) -> dict:
    defaults = {"final_text": TEXT_65_CHARS}
    defaults.update(overrides)
    return defaults


def create_qa_review_payload(dictation_job_id, **overrides) -> dict:
    defaults = {
        "dictation_job_id": dictation_job_id,
        "critical_error_count": 0,
        "major_error_count": 0,
        "minor_error_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_provider_template_payload(provider_id, expected_provider_version, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "work_type": "CONSULT",
        "name": "Template",
        "body_text": "Template body",
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults


def create_macro_payload(provider_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "shortcut": "sig",
        "expansion_text": "Regards, Dr. Provider",
    }
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(clinic_account_id, **overrides) -> dict:
    defaults = {
        "clinic_account_id": clinic_account_id,
        "period_start": WIDE_WINDOW_START,
        "period_end": WIDE_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults
