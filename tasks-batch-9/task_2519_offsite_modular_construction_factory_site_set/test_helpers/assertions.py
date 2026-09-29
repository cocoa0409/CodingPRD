"""Domain assertions for the offsite modular API.

These sit on top of the shared structural helpers and speak in the language of
the domain: modules carry three state dimensions, money is an integer count of
cents, and percentages and hour counts are two-decimal values.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BASE_STATE_PERMIT_FEE_CENTS,
    COMPATIBILITY_SCORE_BASE,
    CONNECTION_DETAIL_PENALTY,
    ENVELOPE_CLASS_FEE_MULTIPLIER,
    PENALTY_PER_FIELD_SCOPE_ITEM_OPEN,
    PENALTY_PER_MODULE_SPLIT_DIFFERENCE,
    PENALTY_PER_OPEN_CONNECTION_CONFLICT,
    TAKT_CONGESTION_PENALTY_MINUTES_PER_CONCURRENT_MODULE,
    WIND_DERATE_FACTOR,
)


# ─── Rounding mirrors ─────────────────────────────────────────────────────────
def round_half_up_cents(value: Decimal) -> int:
    """Round a monetary result half up to a whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: Decimal) -> float:
    """Round a percentage or hour count half up to exactly two decimal places."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ─── Calculation mirrors ──────────────────────────────────────────────────────
def expected_compatibility_score(
    open_connection_conflicts: int,
    field_scope_items_open: int,
    connection_detail_state: str,
    module_split_count: int,
    planned_module_count: int,
) -> int:
    """The compatibility score: 100 minus the accumulated penalty, floored at 0."""
    penalty = (
        PENALTY_PER_OPEN_CONNECTION_CONFLICT * open_connection_conflicts
        + PENALTY_PER_FIELD_SCOPE_ITEM_OPEN * field_scope_items_open
        + CONNECTION_DETAIL_PENALTY[connection_detail_state]
        + PENALTY_PER_MODULE_SPLIT_DIFFERENCE
        * abs(module_split_count - planned_module_count)
    )
    return max(0, COMPATIBILITY_SCORE_BASE - penalty)


def expected_line_slot_minutes(
    takt_minutes: int, station_count: int, concurrency_count: int
) -> int:
    """Station count multiplied by the takt degraded by five minutes per module."""
    effective_takt = (
        takt_minutes
        + TAKT_CONGESTION_PENALTY_MINUTES_PER_CONCURRENT_MODULE * concurrency_count
    )
    return station_count * effective_takt


def expected_permit_fee_cents(envelope_class: str, route_state_count: int) -> int:
    """The base state permit fee, by route length, by the class multiplier."""
    return (
        BASE_STATE_PERMIT_FEE_CENTS
        * route_state_count
        * ENVELOPE_CLASS_FEE_MULTIPLIER[envelope_class]
    )


def expected_derated_capacity_lb(capacity_lb: int, wind_gust_mph: int) -> int:
    """Chart capacity, derated and truncated downwards when the gust warrants."""
    from .constants import WIND_DERATE_GUST_THRESHOLD_MPH

    if wind_gust_mph >= WIND_DERATE_GUST_THRESHOLD_MPH:
        return int(capacity_lb * WIND_DERATE_FACTOR)
    return capacity_lb


def expected_wip_earned_cents(
    wip_unit_value_cents: int, station_index: int, station_count: int
) -> int:
    """Unit value pro-rated by completed stations, rounded half up to a cent."""
    return round_half_up_cents(
        Decimal(wip_unit_value_cents) * Decimal(station_index) / Decimal(station_count)
    )


# ─── Structural assertions ────────────────────────────────────────────────────
def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a bare UUID id, both timestamps and a version."""
    assert is_valid_uuid(resource["id"]), f"id must be a bare UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {resource['created_at']!r}"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp: {resource['updated_at']!r}"
    )
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The response envelope's request id and timestamp conventions."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_single_resource_meta_omits_paging(body: Dict[str, Any]) -> None:
    """Single-resource responses omit all four paging fields."""
    meta = body["meta"]
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must omit {field}"


def assert_list_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total_count: int,
    expected_has_more: bool,
) -> None:
    """The four paging fields a list response must carry."""
    assert meta["limit"] == expected_limit
    assert meta["offset"] == expected_offset
    assert meta["total_count"] == expected_total_count
    assert meta["has_more"] is expected_has_more


def assert_created_at_ascending(rows) -> None:
    """List results are ordered by created_at ascending — oldest row first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


# ─── Value assertions ─────────────────────────────────────────────────────────
def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Monetary amounts are integers denominated in cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_two_decimal_value(actual: Any, expected: float, label: str = "value") -> None:
    """Percentages and hour counts are two-decimal values."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Module assertions ────────────────────────────────────────────────────────
def assert_module_dimensions(
    module: Dict[str, Any],
    production_status: Optional[str] = None,
    qc_status: Optional[str] = None,
    site_status: Optional[str] = None,
) -> None:
    """Assert any subset of the module's three independent state dimensions."""
    if production_status is not None:
        assert module["production_status"] == production_status, (
            f"production_status: expected {production_status}, "
            f"got {module['production_status']}"
        )
    if qc_status is not None:
        assert module["qc_status"] == qc_status, (
            f"qc_status: expected {qc_status}, got {module['qc_status']}"
        )
    if site_status is not None:
        assert module["site_status"] == site_status, (
            f"site_status: expected {site_status}, got {module['site_status']}"
        )


def assert_line_slot_cleared(module: Dict[str, Any]) -> None:
    """A released or reverted slot leaves no interval and zero minutes behind."""
    assert module["line_slot_start"] is None, "line_slot_start must be cleared"
    assert module["line_slot_end"] is None, "line_slot_end must be cleared"
    assert module["line_slot_minutes"] == 0, "line_slot_minutes must be 0"


def assert_ledger(resource: Dict[str, Any], field: str, expected: int) -> None:
    """A conserved ledger must read exactly the expected value, with no drift."""
    assert resource[field] == expected, (
        f"{field}: expected {expected}, got {resource[field]}"
    )


# ─── Instant comparison ───────────────────────────────────────────────────────
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Two instants name the same moment, whatever their fractional rendering."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
