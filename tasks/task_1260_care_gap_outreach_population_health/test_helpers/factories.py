"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_registry_payload(**overrides) -> dict:
    defaults = {"name": "Registry", "program_year": TEST_DEFAULTS["PROGRAM_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_measure_payload(**overrides) -> dict:
    defaults = {
        "measure_code": "SCR",
        "measure_domain": "SCREENING",
        "lookback_days": TEST_DEFAULTS["LOOKBACK_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(**overrides) -> dict:
    defaults = {
        "cohort_code": "C",
        "min_age": 50,
        "max_age": 75,
        "risk_tier_filter": "ANY",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "mrn": "M",
        "date_of_birth": TEST_DEFAULTS["MEMBER_DOB"],
        "risk_tier": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_panel_payload(**overrides) -> dict:
    defaults = {
        "cohort_id": "",
        "measure_id": "",
        "panel_manager_id": TEST_DEFAULTS["PANEL_MANAGER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "panel_id": "",
        "measure_id": "",
        "name": "Campaign",
        "channel": "CALL",
        "starts_at": TEST_DEFAULTS["CAMPAIGN_START"],
        "ends_at": TEST_DEFAULTS["CAMPAIGN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(**overrides) -> dict:
    defaults = {
        "campaign_id": "",
        "channel": "CALL",
        "outcome": "NO_ANSWER",
        "expected_care_gap_version": 0,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "provider_id": "prov_A",
        "slot_start_at": "2026-06-01T14:00:00Z",
        "slot_end_at": "2026-06-01T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_transportation_assist_payload(**overrides) -> dict:
    defaults = {
        "vendor": "RideCo",
        "pickup_at": "2026-06-01T13:00:00Z",
        "cost_cents": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "CHART_REVIEW",
        "service_date": TEST_DEFAULTS["EVIDENCE_SERVICE_DATE"],
        "document_uri": "s3://docs/evidence.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_request_payload(**overrides) -> dict:
    defaults = {
        "exclusion_kind": "MEMBER_REFUSAL",
        "justification": "member declined outreach",
        "effective_from": TEST_DEFAULTS["CAMPAIGN_START"],
    }
    defaults.update(overrides)
    return defaults


def create_workload_payload(**overrides) -> dict:
    defaults = {
        "panel_manager_id": TEST_DEFAULTS["PANEL_MANAGER_ID"],
        "period_key": TEST_DEFAULTS["PERIOD_KEY"],
    }
    defaults.update(overrides)
    return defaults


def create_performance_report_payload(**overrides) -> dict:
    defaults = {"period_key": TEST_DEFAULTS["PERIOD_KEY"]}
    defaults.update(overrides)
    return defaults
