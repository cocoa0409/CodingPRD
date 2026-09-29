"""Domain assertions for the LED Display Manufacturing API.

The helpers here compare records field by field with the precision the
requirements document pins: money as exact integer cents, areas at 4 decimal
places, uniformity scores and percentages at 2, and instants at millisecond
resolution.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import TOLERANCE_2DP, TOLERANCE_4DP, TOLERANCE_6DP

_UNSET = object()


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------


def normalize_instant(value: str) -> str:
    """Render an ISO 8601 UTC instant as a millisecond-precision string.

    Instants are compared at millisecond resolution, so a value written with
    fewer or more fractional digits is the same instant as one written with
    exactly three.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    millis = round(parsed.microsecond / 1000)
    return f"{parsed.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    assert actual is not None, f"{field} must not be null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_instant_format(value: Any, field: str = "instant") -> None:
    """An instant is an ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{field} must be a UTC instant ending in Z: {value}"
    assert "." in value, f"{field} must carry fractional digits: {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, f"{field} must carry three fractional digits: {value}"
    normalize_instant(value)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def assert_cents(actual: Any, expected: int, field: str = "amount_cents") -> None:
    """Money is always an integer count of cents; there are no fractional cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_2dp(actual: Any, expected: float, field: str = "value") -> None:
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=TOLERANCE_2DP), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_4dp(actual: Any, expected: float, field: str = "value") -> None:
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=TOLERANCE_4DP), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_6dp(actual: Any, expected: float, field: str = "value") -> None:
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=TOLERANCE_6DP), (
        f"{field}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Identity block
# ---------------------------------------------------------------------------


def assert_common_fields(record: Dict[str, Any], label: str = "record") -> None:
    """Every persisted record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record.get("id")), (
        f"{label}.id must be a UUID string with no type prefix, got {record.get('id')!r}"
    )
    assert_instant_format(record.get("created_at"), f"{label}.created_at")
    assert_instant_format(record.get("updated_at"), f"{label}.updated_at")
    version = record.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version starts at 1, got {version}"


def assert_version(record: Dict[str, Any], expected: int, label: str = "record") -> None:
    assert record.get("version") == expected, (
        f"{label}.version: expected {expected}, got {record.get('version')}"
    )


def assert_fields_absent_or_null(record: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert record.get(field) is None, f"{field} must be null, got {record.get(field)!r}"


# ---------------------------------------------------------------------------
# Per-entity field checks
# ---------------------------------------------------------------------------


def _check(record: Dict[str, Any], label: str, expectations: Dict[str, Any]) -> None:
    for field, expected in expectations.items():
        if expected is _UNSET:
            continue
        actual = record.get(field)
        assert actual == expected, f"{label}.{field}: expected {expected!r}, got {actual!r}"


def assert_module_fields(
    module: Dict[str, Any],
    module_state: Any = _UNSET,
    cabinet_id: Any = _UNSET,
    slot_index: Any = _UNSET,
    color_bin: Any = _UNSET,
    color_bin_rank: Any = _UNSET,
    rework_cycles: Any = _UNSET,
    dead_pixel_count: Any = _UNSET,
    max_cluster_size: Any = _UNSET,
    reserved_service_contract_id: Any = _UNSET,
    replaces_module_id: Any = _UNSET,
    calibrated_by_user_id: Any = _UNSET,
    measured_brightness_nits: Any = _UNSET,
) -> None:
    _check(
        module,
        "module",
        {
            "module_state": module_state,
            "cabinet_id": cabinet_id,
            "slot_index": slot_index,
            "color_bin": color_bin,
            "color_bin_rank": color_bin_rank,
            "rework_cycles": rework_cycles,
            "dead_pixel_count": dead_pixel_count,
            "max_cluster_size": max_cluster_size,
            "reserved_service_contract_id": reserved_service_contract_id,
            "replaces_module_id": replaces_module_id,
            "calibrated_by_user_id": calibrated_by_user_id,
            "measured_brightness_nits": measured_brightness_nits,
        },
    )


def assert_cabinet_fields(
    cabinet: Dict[str, Any],
    cabinet_state: Any = _UNSET,
    installed_module_count: Any = _UNSET,
    occupied_slot_indexes: Any = _UNSET,
    total_dead_pixel_count: Any = _UNSET,
    qa_approved_by_user_id: Any = _UNSET,
) -> None:
    _check(
        cabinet,
        "cabinet",
        {
            "cabinet_state": cabinet_state,
            "installed_module_count": installed_module_count,
            "occupied_slot_indexes": occupied_slot_indexes,
            "total_dead_pixel_count": total_dead_pixel_count,
            "qa_approved_by_user_id": qa_approved_by_user_id,
        },
    )


def assert_project_fields(
    project: Dict[str, Any],
    engineering_state: Any = _UNSET,
    production_state: Any = _UNSET,
    service_posture: Any = _UNSET,
    cabinet_count: Any = _UNSET,
    module_count: Any = _UNSET,
    qa_passed_cabinet_count: Any = _UNSET,
    mounted_cabinet_count: Any = _UNSET,
    quarantined_cabinet_count: Any = _UNSET,
    approved_revision_number: Any = _UNSET,
) -> None:
    _check(
        project,
        "project",
        {
            "engineering_state": engineering_state,
            "production_state": production_state,
            "service_posture": service_posture,
            "cabinet_count": cabinet_count,
            "module_count": module_count,
            "qa_passed_cabinet_count": qa_passed_cabinet_count,
            "mounted_cabinet_count": mounted_cabinet_count,
            "quarantined_cabinet_count": quarantined_cabinet_count,
            "approved_revision_number": approved_revision_number,
        },
    )


def assert_chamber_fields(
    chamber: Dict[str, Any],
    reserved_slot_total: Any = _UNSET,
    scheduled_run_count: Any = _UNSET,
    slot_capacity: Any = _UNSET,
    turnaround_minutes: Any = _UNSET,
) -> None:
    _check(
        chamber,
        "chamber",
        {
            "reserved_slot_total": reserved_slot_total,
            "scheduled_run_count": scheduled_run_count,
            "slot_capacity": slot_capacity,
            "turnaround_minutes": turnaround_minutes,
        },
    )


def assert_run_fields(
    run: Dict[str, Any],
    run_state: Any = _UNSET,
    slots_required: Any = _UNSET,
    abort_reason: Any = _UNSET,
    completed_by_user_id: Any = _UNSET,
    new_dead_pixel_count: Any = _UNSET,
) -> None:
    _check(
        run,
        "run",
        {
            "run_state": run_state,
            "slots_required": slots_required,
            "abort_reason": abort_reason,
            "completed_by_user_id": completed_by_user_id,
            "new_dead_pixel_count": new_dead_pixel_count,
        },
    )


def assert_visit_fields(
    visit: Dict[str, Any],
    visit_state: Any = _UNSET,
    commissioning_crew_id: Any = _UNSET,
    abort_reason: Any = _UNSET,
    measured_brightness_nits: Any = _UNSET,
) -> None:
    _check(
        visit,
        "visit",
        {
            "visit_state": visit_state,
            "commissioning_crew_id": commissioning_crew_id,
            "abort_reason": abort_reason,
            "measured_brightness_nits": measured_brightness_nits,
        },
    )


def assert_contract_fields(
    contract: Dict[str, Any],
    contract_state: Any = _UNSET,
    response_hours: Any = _UNSET,
    spare_required_count: Any = _UNSET,
    spare_reserved_count: Any = _UNSET,
    sla_breach_count: Any = _UNSET,
    tier: Any = _UNSET,
) -> None:
    _check(
        contract,
        "contract",
        {
            "contract_state": contract_state,
            "response_hours": response_hours,
            "spare_required_count": spare_required_count,
            "spare_reserved_count": spare_reserved_count,
            "sla_breach_count": sla_breach_count,
            "tier": tier,
        },
    )


def assert_case_fields(
    case: Dict[str, Any],
    case_state: Any = _UNSET,
    case_type: Any = _UNSET,
    severity: Any = _UNSET,
    response_breached: Any = _UNSET,
    assessment_basis: Any = _UNSET,
    resolved_faulty_module_id: Any = _UNSET,
    replacement_module_id: Any = _UNSET,
    faulty_module_id: Any = _UNSET,
    denial_reason: Any = _UNSET,
) -> None:
    _check(
        case,
        "case",
        {
            "case_state": case_state,
            "case_type": case_type,
            "severity": severity,
            "response_breached": response_breached,
            "assessment_basis": assessment_basis,
            "resolved_faulty_module_id": resolved_faulty_module_id,
            "replacement_module_id": replacement_module_id,
            "faulty_module_id": faulty_module_id,
            "denial_reason": denial_reason,
        },
    )


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def assert_page_meta(
    meta: Dict[str, Any],
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """limit and offset echo the effective page window; total_count counts matches."""
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset: expected {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_no_pagination_meta(meta: Dict[str, Any]) -> None:
    """Single-resource reads carry none of the four pagination fields."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must not carry {field}"


def assert_ordered_by_created_at(records: List[Dict[str, Any]]) -> None:
    """Results are ordered by created_at ascending — oldest record first."""
    stamps = [normalize_instant(record["created_at"]) for record in records]
    assert stamps == sorted(stamps), f"records are not in ascending created_at order: {stamps}"


def assert_id_sequence(records: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [record["id"] for record in records]
    assert actual == expected_ids, f"expected ids {expected_ids}, got {actual}"


def ids_of(records: List[Dict[str, Any]]) -> List[str]:
    return [record["id"] for record in records]
