"""Domain assertion helpers shared across the suite."""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_bare_uuid(value: Any, label: str = "id") -> None:
    """The identifier is a bare UUID string with no prefix and no braces."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert is_valid_uuid(value), f"{label} must be a bare UUID, got {value!r}"


def assert_iso_timestamp(value: Any, label: str = "timestamp") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO-8601, got {value!r}"


def assert_has_system_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Shared system fields: id, created_at, updated_at and version."""
    assert_bare_uuid(entity.get("id"), f"{label}.id")
    assert_iso_timestamp(entity.get("created_at"), f"{label}.created_at")
    assert_iso_timestamp(entity.get("updated_at"), f"{label}.updated_at")
    assert isinstance(entity.get("version"), int), f"{label}.version must be an int"
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_no_optimistic_lock_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """The two immutable entities expose neither updated_at nor version."""
    assert "updated_at" not in entity, f"{label} must not expose updated_at"
    assert "version" not in entity, f"{label} must not expose version"
    assert_bare_uuid(entity.get("id"), f"{label}.id")
    assert_iso_timestamp(entity.get("created_at"), f"{label}.created_at")


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """The failure envelope carries an error id and a message and no payload."""
    assert body.get("response_type") == "error", (
        f"Expected response_type 'error', got {body.get('response_type')!r}"
    )
    payload = body.get("data") or {}
    assert payload.get("error_id"), "Error envelope must carry data.error_id"
    assert payload.get("message"), "Error envelope must carry data.message"


def assert_money(actual: Any, expected: int, label: str = "amount") -> None:
    """Monetary amounts are whole cents, compared exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label} expected {expected} cents, got {actual}"


def assert_one_decimal(actual: Any, expected: float, label: str = "percentage") -> None:
    """One-decimal percentages must match to the tenth with no float drift."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label} expected {expected}, got {actual}"
    )
    assert round(float(actual), 1) == pytest.approx(float(actual), abs=1e-9), (
        f"{label} must be serialized to one decimal place, got {actual!r}"
    )


def assert_row_ids(rows: List[Dict[str, Any]], expected_ids: List[str], label: str = "listing") -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"{label} expected ids {expected_ids}, got {[row['id'] for row in rows]}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]], label: str = "listing") -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"{label} must be ordered by created_at ascending: {stamps}"


def assert_family_risk(
    family: Dict[str, Any],
    score: int,
    tier: str,
    variant: Optional[str] = None,
    headcount: Optional[int] = None,
    misclassified: Optional[int] = None,
) -> None:
    assert family["risk_score"] == score, (
        f"risk_score expected {score}, got {family['risk_score']}"
    )
    assert family["risk_tier"] == tier, f"risk_tier expected {tier}, got {family['risk_tier']}"
    if variant is not None:
        assert family["risk_variant"] == variant, (
            f"risk_variant expected {variant}, got {family['risk_variant']}"
        )
    if headcount is not None:
        assert family["family_headcount"] == headcount, (
            f"family_headcount expected {headcount}, got {family['family_headcount']}"
        )
    if misclassified is not None:
        assert family["open_misclassified_count"] == misclassified, (
            "open_misclassified_count expected "
            f"{misclassified}, got {family['open_misclassified_count']}"
        )


def assert_estimate_totals(
    estimate: Dict[str, Any],
    lookback_weeks: int,
    weekly_ot_hours: float,
    week_ot_cents: int,
    gross_exposure_cents: int,
    liquidated_damages_cents: int,
    total_exposure_cents: int,
) -> None:
    assert estimate["lookback_weeks"] == lookback_weeks, (
        f"lookback_weeks expected {lookback_weeks}, got {estimate['lookback_weeks']}"
    )
    assert estimate["weekly_ot_hours"] == pytest.approx(weekly_ot_hours, abs=0.01), (
        f"weekly_ot_hours expected {weekly_ot_hours}, got {estimate['weekly_ot_hours']}"
    )
    assert_money(estimate["week_ot_cents"], week_ot_cents, "week_ot_cents")
    assert_money(estimate["gross_exposure_cents"], gross_exposure_cents, "gross_exposure_cents")
    assert_money(
        estimate["liquidated_damages_cents"], liquidated_damages_cents, "liquidated_damages_cents"
    )
    assert_money(estimate["total_exposure_cents"], total_exposure_cents, "total_exposure_cents")


def assert_project_ledgers(
    project: Dict[str, Any],
    headcount: Optional[int] = None,
    exposure_cents: Optional[int] = None,
    payroll_delta_cents: Optional[int] = None,
    committed_correction_cents: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    if headcount is not None:
        assert project["open_misclassified_headcount"] == headcount, (
            "open_misclassified_headcount expected "
            f"{headcount}, got {project['open_misclassified_headcount']}"
        )
    if exposure_cents is not None:
        assert_money(
            project["total_back_wage_exposure_cents"],
            exposure_cents,
            "total_back_wage_exposure_cents",
        )
    if payroll_delta_cents is not None:
        assert_money(
            project["converted_annual_payroll_delta_cents"],
            payroll_delta_cents,
            "converted_annual_payroll_delta_cents",
        )
    if committed_correction_cents is not None:
        assert_money(
            project["committed_correction_cents"],
            committed_correction_cents,
            "committed_correction_cents",
        )
    if posture is not None:
        assert project["remediation_posture"] == posture, (
            f"remediation_posture expected {posture}, got {project['remediation_posture']}"
        )
