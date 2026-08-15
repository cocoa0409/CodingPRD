"""Payload factories — input fields only (PRD §4 endpoints)."""

DEFAULT_CATEGORY_NAME = "TestCategory"
DEFAULT_RISK_TITLE = "Test Risk"
DEFAULT_OWNER = "user_owner_1"
DEFAULT_MANAGER = "user_rm_1"
DEFAULT_MANAGER_2 = "user_rm_2"
DEFAULT_CONTROL_OWNER = "user_co_1"
DEFAULT_REPORTER = "user_br_1"
DEFAULT_AUDITOR = "user_aud_1"


def create_category_payload(**overrides) -> dict:
    """POST /categories — name required; parent_category_id/weight_factor optional."""
    defaults = {"name": DEFAULT_CATEGORY_NAME}
    defaults.update(overrides)
    return defaults


def create_risk_payload(category_id, **overrides) -> dict:
    """POST /risks — category_id, title, owner_user_id required."""
    defaults = {
        "category_id": category_id,
        "title": DEFAULT_RISK_TITLE,
        "owner_user_id": DEFAULT_OWNER,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(kind, expected_risk_version, **overrides) -> dict:
    """POST /risks/{id}/assessments — kind, expected_risk_version required."""
    defaults = {
        "kind": kind,
        "expected_risk_version": expected_risk_version,
    }
    defaults.update(overrides)
    return defaults


def create_control_payload(**overrides) -> dict:
    """POST /controls — name + effectiveness_pct required."""
    defaults = {
        "name": "Test Control",
        "effectiveness_pct": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_mapping_payload(control_id, coverage_weight=0.5, **overrides) -> dict:
    """POST /risks/{id}/control-mappings — control_id, coverage_weight required."""
    defaults = {
        "control_id": control_id,
        "coverage_weight": coverage_weight,
    }
    defaults.update(overrides)
    return defaults


def create_appetite_payload(category_id, **overrides) -> dict:
    """POST /appetite-statements — all five inputs required."""
    defaults = {
        "category_id": category_id,
        "tolerance_score": 10,
        "acceptance_cap_score": 20,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_plan_payload(expected_risk_version, **overrides) -> dict:
    """POST /risks/{id}/treatment-plans."""
    defaults = {
        "title": "Test Plan",
        "budget_cents": 10000,
        "due_date": "2026-12-31T00:00:00Z",
        "owner_user_id": DEFAULT_OWNER,
        "expected_risk_version": expected_risk_version,
    }
    defaults.update(overrides)
    return defaults


def create_treatment_action_payload(**overrides) -> dict:
    defaults = {"title": "Test Action"}
    defaults.update(overrides)
    return defaults


def create_kri_payload(category_id, **overrides) -> dict:
    """POST /kris — category_id, name, direction, amber_threshold, red_threshold."""
    defaults = {
        "category_id": category_id,
        "name": "Test KRI",
        "direction": "ABOVE",
        "amber_threshold": 50,
        "red_threshold": 75,
    }
    defaults.update(overrides)
    return defaults


def create_kri_observation_payload(observed_value, observed_at, **overrides) -> dict:
    defaults = {
        "observed_value": observed_value,
        "observed_at": observed_at,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T00:00:00Z",
        "variant": "FINAL",
    }
    defaults.update(overrides)
    return defaults


def create_emerging_risk_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "title": "Test Emerging",
        "scenario_severity": 4,
        "scenario_probability": 3,
    }
    defaults.update(overrides)
    return defaults
