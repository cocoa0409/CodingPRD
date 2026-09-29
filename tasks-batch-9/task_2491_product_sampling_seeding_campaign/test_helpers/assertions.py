"""Domain assertion helpers.

These wrap the repeated multi-field checks the PRD pins, so a test reads as one
statement of intent instead of a wall of dictionary lookups.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common-field shape (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_mutable_entity_shape(entity: Dict[str, Any]) -> None:
    """Every entity except a purchase match carries updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_immutable_entity_shape(entity: Dict[str, Any]) -> None:
    """A purchase match carries only id and created_at, never the mutable pair."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity, "updated_at must be absent from a purchase match"
    assert "version" not in entity, "version must be absent from a purchase match"


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
def assert_campaign_status(campaign: Dict[str, Any], expected_status: str) -> None:
    assert campaign["status"] == expected_status, (
        f"expected campaign status {expected_status}, got {campaign['status']}"
    )


def assert_compliance_posture(campaign: Dict[str, Any], expected_posture: str) -> None:
    assert campaign["compliance_posture"] == expected_posture, (
        f"expected posture {expected_posture}, got {campaign['compliance_posture']}"
    )


def assert_budget_conserved(campaign: Dict[str, Any]) -> None:
    """committed plus available always equals the declared total."""
    total = campaign["budget_total_cents"]
    committed = campaign["budget_committed_cents"]
    available = campaign["budget_available_cents"]
    assert committed + available == total, (
        f"budget not conserved: {committed} + {available} != {total}"
    )


def assert_campaign_counters(campaign: Dict[str, Any], **expected: int) -> None:
    """Assert any subset of the campaign's derived counters by keyword."""
    for field, value in expected.items():
        assert campaign[field] == value, (
            f"expected campaign {field} == {value}, got {campaign[field]}"
        )


# ---------------------------------------------------------------------------
# KitLine
# ---------------------------------------------------------------------------
def assert_kit_line_buckets(
    kit_line: Dict[str, Any],
    units_received: Optional[int] = None,
    units_available: Optional[int] = None,
    units_reserved: Optional[int] = None,
    units_shipped: Optional[int] = None,
    units_written_off: Optional[int] = None,
) -> None:
    expected = {
        "units_received": units_received,
        "units_available": units_available,
        "units_reserved": units_reserved,
        "units_shipped": units_shipped,
        "units_written_off": units_written_off,
    }
    for field, value in expected.items():
        if value is not None:
            assert kit_line[field] == value, (
                f"expected {field} == {value}, got {kit_line[field]}"
            )


def assert_kit_unit_conservation(kit_line: Dict[str, Any]) -> None:
    """Received units always equal the sum of the four downstream buckets."""
    total = (
        kit_line["units_available"]
        + kit_line["units_reserved"]
        + kit_line["units_shipped"]
        + kit_line["units_written_off"]
    )
    assert kit_line["units_received"] == total, (
        f"kit units not conserved on {kit_line['component_sku']}: "
        f"received {kit_line['units_received']} != {total}"
    )


# ---------------------------------------------------------------------------
# FulfillmentWave
# ---------------------------------------------------------------------------
def assert_wave_state(
    wave: Dict[str, Any],
    status: Optional[str] = None,
    planned_unit_count: Optional[int] = None,
    shipped_unit_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert wave["status"] == status, (
            f"expected wave status {status}, got {wave['status']}"
        )
    if planned_unit_count is not None:
        assert wave["planned_unit_count"] == planned_unit_count
    if shipped_unit_count is not None:
        assert wave["shipped_unit_count"] == shipped_unit_count


# ---------------------------------------------------------------------------
# Enrollment — the two axes move independently
# ---------------------------------------------------------------------------
def assert_enrollment_axes(
    enrollment: Dict[str, Any],
    screening_status: Optional[str] = None,
    obligation_status: Optional[str] = None,
) -> None:
    if screening_status is not None:
        assert enrollment["screening_status"] == screening_status, (
            f"expected screening_status {screening_status}, "
            f"got {enrollment['screening_status']}"
        )
    if obligation_status is not None:
        assert enrollment["obligation_status"] == obligation_status, (
            f"expected obligation_status {obligation_status}, "
            f"got {enrollment['obligation_status']}"
        )


# ---------------------------------------------------------------------------
# Panelist
# ---------------------------------------------------------------------------
def assert_risk_scores(
    panelist: Dict[str, Any],
    screening: Optional[float] = None,
    audit: Optional[float] = None,
) -> None:
    if screening is not None:
        assert panelist["fraud_risk_score_screening"] == pytest.approx(
            screening, abs=0.01
        ), (
            f"expected screening score {screening}, "
            f"got {panelist['fraud_risk_score_screening']}"
        )
    if audit is not None:
        assert panelist["fraud_risk_score_audit"] == pytest.approx(audit, abs=0.01), (
            f"expected audit score {audit}, got {panelist['fraud_risk_score_audit']}"
        )


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert any set of exact field values on any entity."""
    for field, value in expected.items():
        assert entity[field] == value, (
            f"expected {field} == {value!r}, got {entity[field]!r}"
        )


def assert_absent(entity: Dict[str, Any], field_names: Iterable[str]) -> None:
    for field in field_names:
        assert field not in entity, f"{field} must be absent, found {entity.get(field)!r}"


def assert_money(actual: int, expected: int, label: str = "amount") -> None:
    assert actual == expected, f"expected {label} {expected} cents, got {actual} cents"


def assert_rate(actual: float, expected: float, label: str = "rate") -> None:
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected {label} {expected}, got {actual}"
    )


def assert_instant(
    actual: Optional[str], expected_iso: str, label: str = "timestamp"
) -> None:
    """The stamp names exactly the expected instant, at whatever precision.

    ``created_at`` is specified with three fractional digits while the logical
    clock is positioned with whole-second instants, so the two spellings of one
    and the same moment have to compare equal.
    """
    assert actual is not None, f"{label} is missing"
    assert _to_instant(actual) == _to_instant(expected_iso), (
        f"expected {label} {expected_iso}, got {actual}"
    )


def _to_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
