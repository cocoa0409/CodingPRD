"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_model_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Model {n}",
        "business_unit": TEST_DEFAULTS["BUSINESS_UNIT"],
        "declared_complexity": TEST_DEFAULTS["DECLARED_COMPLEXITY"],
        "usage_scope": TEST_DEFAULTS["USAGE_SCOPE"],
        "exposure_amount": TEST_DEFAULTS["EXPOSURE_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_documentation_payload(**overrides) -> dict:
    defaults = {
        "version_label": "1.0",
        "has_development_evidence": True,
        "has_testing_evidence": True,
        "has_data_lineage": True,
    }
    defaults.update(overrides)
    return defaults


def create_change_request_payload(change_type="MINOR", expected_model_version=None, **overrides) -> dict:
    defaults = {
        "change_type": change_type,
        "description": f"change {change_type.lower()}",
        "expected_model_version": expected_model_version,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(
    period_start="2026-08-01T00:00:00Z",
    period_end="2026-08-01T06:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "scope_conceptual_soundness": True,
        "scope_outcomes_analysis": True,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def complete_engagement_payload(outcome="EFFECTIVE", assessed_complexity="LOW", **overrides) -> dict:
    defaults = {"outcome": outcome, "assessed_complexity": assessed_complexity}
    defaults.update(overrides)
    return defaults


def create_finding_payload(severity="LOW", title=None, **overrides) -> dict:
    defaults = {"severity": severity, "title": title or f"{severity.lower()} finding {_seq()}"}
    defaults.update(overrides)
    return defaults


def create_metric_payload(
    metric_name=None,
    direction=None,
    threshold_value=None,
    **overrides,
) -> dict:
    defaults = {
        "metric_name": metric_name or TEST_DEFAULTS["METRIC_NAME"],
        "direction": direction or TEST_DEFAULTS["METRIC_DIRECTION"],
        "threshold_value": TEST_DEFAULTS["METRIC_THRESHOLD"] if threshold_value is None else threshold_value,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(value, observed_at, **overrides) -> dict:
    defaults = {"value": value, "observed_at": observed_at}
    defaults.update(overrides)
    return defaults


def create_vendor_assessment_payload(completeness_score=80, valid_months=6, **overrides) -> dict:
    defaults = {"completeness_score": completeness_score, "valid_months": valid_months}
    defaults.update(overrides)
    return defaults


def create_report_payload(
    report_type="BOARD_QUARTERLY",
    period_start="2026-07-01T00:00:00Z",
    period_end="2026-09-30T00:00:00Z",
    aggregation_method="EQUAL_WEIGHTED",
    **overrides,
) -> dict:
    defaults = {
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "aggregation_method": aggregation_method,
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision="APPROVE") -> dict:
    return {"decision": decision}
