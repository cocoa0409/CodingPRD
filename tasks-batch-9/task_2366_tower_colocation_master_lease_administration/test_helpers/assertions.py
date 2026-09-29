"""Domain assertion helpers for the Tower Colocation Master Lease API.

These wrap the framework's generic format checks with the vocabulary of the PRD
so that a failing test names the business rule it was checking.
"""

from typing import Any, Dict, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AMENDMENT_BILLING_STATUSES,
    AMENDMENT_EXECUTION_STATUSES,
    CAPACITY_POSTURES,
    CREDIT_STATUSES,
    LOAD_DECIMAL_PLACES,
    PCT_DECIMAL_PLACES,
)

# ─── Common resource properties (PRD §2.4) ───────────────────────────────────


def assert_common_resource_fields(entity: Dict[str, Any]) -> None:
    """Assert the four properties PRD §2.4 requires of almost every resource."""
    assert is_valid_uuid(entity.get("id", "")), f"id must be a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(
        entity.get("created_at", "")
    ), f"created_at must be ISO 8601: {entity.get('created_at')!r}"
    assert is_iso8601_timestamp(
        entity.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {entity.get('updated_at')!r}"
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_immutable_resource_fields(entity: Dict[str, Any]) -> None:
    """Assert the reduced property set PRD §2.4 gives the landlord payment record."""
    assert is_valid_uuid(entity.get("id", "")), f"id must be a UUID: {entity.get('id')!r}"
    assert is_iso8601_timestamp(
        entity.get("created_at", "")
    ), f"created_at must be ISO 8601: {entity.get('created_at')!r}"
    assert "updated_at" not in entity, "updated_at must be absent entirely"
    assert "version" not in entity, "version must be absent entirely"


def assert_request_envelope_meta(meta: Dict[str, Any]) -> None:
    """Assert the meta members PRD §2.2 requires on every response."""
    assert str(meta.get("api_request_id", "")).startswith(
        "req_"
    ), f"api_request_id must start with req_: {meta.get('api_request_id')!r}"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), f"api_request_timestamp must be ISO 8601: {meta.get('api_request_timestamp')!r}"


def assert_list_meta(
    meta: Dict[str, Any],
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the pagination members PRD §2.3 requires on every list response."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta must include {key}"
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert (
            meta["total_count"] == total_count
        ), f"expected total_count {total_count}, got {meta['total_count']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, f"expected has_more {has_more}, got {meta['has_more']}"


# ─── Numeric precision (PRD §2.10) ───────────────────────────────────────────


def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """Assert a number carries no more than ``places`` decimal places."""
    numeric = float(value)
    assert round(numeric, places) == pytest.approx(
        numeric, abs=1e-9
    ), f"{field} must be rounded to {places} decimal places, got {value!r}"


def assert_load_units(actual: Any, expected: float, field: str = "load figure") -> None:
    """Assert a structural load figure, which PRD §2.10 rounds to three decimals."""
    assert float(actual) == pytest.approx(
        expected, abs=1e-6
    ), f"expected {field} {expected}, got {actual}"
    assert_decimal_places(actual, LOAD_DECIMAL_PLACES, field)


def assert_pct(actual: Any, expected: float, field: str = "percentage") -> None:
    """Assert a percentage, which PRD §2.10 rounds to three decimals."""
    assert float(actual) == pytest.approx(
        expected, abs=1e-6
    ), f"expected {field} {expected}, got {actual}"
    assert_decimal_places(actual, PCT_DECIMAL_PLACES, field)


def assert_cents(actual: Any, expected: int, field: str = "amount_cents") -> None:
    """Assert an amount is exactly the expected whole number of cents."""
    assert float(actual).is_integer(), f"{field} must be integer cents, got {actual!r}"
    assert int(actual) == expected, f"expected {field} {expected}, got {actual}"


# ─── Towers (PRD §2.7, §2.8, §3.1) ───────────────────────────────────────────


def assert_tower_capacity(
    tower: Dict[str, Any],
    *,
    reserved_load_units: Optional[float] = None,
    reserved_load_pct: Optional[float] = None,
    reserved_ground_space_sqft: Optional[int] = None,
    available_ground_space_sqft: Optional[int] = None,
    rated_capacity_load_units: Optional[float] = None,
    open_review_count: Optional[int] = None,
    capacity_posture: Optional[str] = None,
    occupied_band_count: Optional[int] = None,
) -> None:
    """Assert the reconciled capacity picture of a tower."""
    if reserved_load_units is not None:
        assert_load_units(tower["reserved_load_units"], reserved_load_units, "reserved_load_units")
    if reserved_load_pct is not None:
        assert_pct(tower["reserved_load_pct"], reserved_load_pct, "reserved_load_pct")
    if reserved_ground_space_sqft is not None:
        assert (
            tower["reserved_ground_space_sqft"] == reserved_ground_space_sqft
        ), f"expected reserved_ground_space_sqft {reserved_ground_space_sqft}, got {tower['reserved_ground_space_sqft']}"
    if available_ground_space_sqft is not None:
        assert (
            tower["available_ground_space_sqft"] == available_ground_space_sqft
        ), f"expected available_ground_space_sqft {available_ground_space_sqft}, got {tower['available_ground_space_sqft']}"
    if rated_capacity_load_units is not None:
        assert_load_units(
            tower["rated_capacity_load_units"],
            rated_capacity_load_units,
            "rated_capacity_load_units",
        )
    if open_review_count is not None:
        assert (
            tower["open_review_count"] == open_review_count
        ), f"expected open_review_count {open_review_count}, got {tower['open_review_count']}"
    if capacity_posture is not None:
        assert capacity_posture in CAPACITY_POSTURES
        assert (
            tower["capacity_posture"] == capacity_posture
        ), f"expected capacity_posture {capacity_posture}, got {tower['capacity_posture']}"
    if occupied_band_count is not None:
        bands = tower["occupied_elevation_bands"]
        assert (
            len(bands) == occupied_band_count
        ), f"expected {occupied_band_count} occupied elevation bands, got {len(bands)}"


def assert_occupied_band(
    band: Dict[str, Any],
    *,
    amendment_id: Optional[str] = None,
    bottom_ft: Optional[float] = None,
    top_ft: Optional[float] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """Assert one entry of ``occupied_elevation_bands`` as described in PRD §2.7."""
    for key in ("amendment_id", "bottom_ft", "top_ft", "tenant_id"):
        assert key in band, f"occupied elevation band entry must carry {key}"
    if amendment_id is not None:
        assert band["amendment_id"] == amendment_id
    if bottom_ft is not None:
        assert float(band["bottom_ft"]) == pytest.approx(bottom_ft)
    if top_ft is not None:
        assert float(band["top_ft"]) == pytest.approx(top_ft)
    if tenant_id is not None:
        assert band["tenant_id"] == tenant_id


def assert_capacity_summary_members(summary: Dict[str, Any]) -> None:
    """Assert the nine members PRD §3.1 gives the capacity summary read."""
    for key in (
        "tower_id",
        "rated_capacity_load_units",
        "reserved_load_units",
        "reserved_load_pct",
        "available_ground_space_sqft",
        "capacity_posture",
        "open_review_count",
        "occupied_band_count",
        "capacity_hold_application_count",
    ):
        assert key in summary, f"capacity summary must include {key}"


def assert_capacity_summary(
    summary: Dict[str, Any],
    *,
    reserved_load_units: Optional[float] = None,
    reserved_load_pct: Optional[float] = None,
    available_ground_space_sqft: Optional[int] = None,
    capacity_posture: Optional[str] = None,
    open_review_count: Optional[int] = None,
    occupied_band_count: Optional[int] = None,
    capacity_hold_application_count: Optional[int] = None,
    rated_capacity_load_units: Optional[float] = None,
) -> None:
    """Assert selected members of the computed capacity summary."""
    assert_capacity_summary_members(summary)
    if reserved_load_units is not None:
        assert_load_units(summary["reserved_load_units"], reserved_load_units, "reserved_load_units")
    if reserved_load_pct is not None:
        assert_pct(summary["reserved_load_pct"], reserved_load_pct, "reserved_load_pct")
    if rated_capacity_load_units is not None:
        assert_load_units(
            summary["rated_capacity_load_units"],
            rated_capacity_load_units,
            "rated_capacity_load_units",
        )
    if available_ground_space_sqft is not None:
        assert summary["available_ground_space_sqft"] == available_ground_space_sqft
    if capacity_posture is not None:
        assert summary["capacity_posture"] == capacity_posture
    if open_review_count is not None:
        assert summary["open_review_count"] == open_review_count
    if occupied_band_count is not None:
        assert summary["occupied_band_count"] == occupied_band_count
    if capacity_hold_application_count is not None:
        assert summary["capacity_hold_application_count"] == capacity_hold_application_count


# ─── Analyses (PRD §3.5) ─────────────────────────────────────────────────────


def assert_analysis_outcome(
    analysis: Dict[str, Any],
    *,
    included_load_units: Optional[float] = None,
    projected_loading_pct: Optional[float] = None,
    result: Optional[str] = None,
    variant: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Assert the computed outcome of a structural analysis."""
    if included_load_units is not None:
        assert_load_units(
            analysis["included_load_units"], included_load_units, "included_load_units"
        )
    if projected_loading_pct is not None:
        assert_pct(analysis["projected_loading_pct"], projected_loading_pct, "projected_loading_pct")
    if result is not None:
        assert analysis["result"] == result, f"expected result {result}, got {analysis['result']}"
    if variant is not None:
        assert analysis["variant"] == variant
    if status is not None:
        assert analysis["status"] == status, f"expected status {status}, got {analysis['status']}"


# ─── Receivables (PRD §2.12) ─────────────────────────────────────────────────


def assert_tenant_ledger(
    tenant: Dict[str, Any],
    *,
    outstanding_balance_cents: Optional[int] = None,
    credit_status: Optional[str] = None,
) -> None:
    """Assert a tenant's receivable balance and derived credit standing."""
    if outstanding_balance_cents is not None:
        assert_cents(
            tenant["outstanding_balance_cents"],
            outstanding_balance_cents,
            "outstanding_balance_cents",
        )
    if credit_status is not None:
        assert credit_status in CREDIT_STATUSES
        assert (
            tenant["credit_status"] == credit_status
        ), f"expected credit_status {credit_status}, got {tenant['credit_status']}"


# ─── Site amendments (PRD §2.9) ──────────────────────────────────────────────


def assert_amendment_axes(
    amendment: Dict[str, Any],
    *,
    execution_status: Optional[str] = None,
    billing_status: Optional[str] = None,
    restoration_status: Optional[str] = None,
) -> None:
    """Assert the two independent status axes and the restoration obligation."""
    if execution_status is not None:
        assert execution_status in AMENDMENT_EXECUTION_STATUSES
        assert (
            amendment["execution_status"] == execution_status
        ), f"expected execution_status {execution_status}, got {amendment['execution_status']}"
    if billing_status is not None:
        assert billing_status in AMENDMENT_BILLING_STATUSES
        assert (
            amendment["billing_status"] == billing_status
        ), f"expected billing_status {billing_status}, got {amendment['billing_status']}"
    if restoration_status is not None:
        assert (
            amendment["restoration_status"] == restoration_status
        ), f"expected restoration_status {restoration_status}, got {amendment['restoration_status']}"


# ─── Clock (PRD §2.4) ────────────────────────────────────────────────────────


def assert_clock_summary(
    summary: Dict[str, Any],
    *,
    current_utc: Optional[str] = None,
    expired_ground_lease_count: Optional[int] = None,
    expired_master_lease_count: Optional[int] = None,
    frozen_tower_count: Optional[int] = None,
) -> None:
    """Assert the four members PRD §2.4 gives the clock-advance response."""
    for key in (
        "current_utc",
        "expired_ground_lease_count",
        "expired_master_lease_count",
        "frozen_tower_count",
    ):
        assert key in summary, f"clock response must include {key}"
    if current_utc is not None:
        assert summary["current_utc"] == current_utc
    if expired_ground_lease_count is not None:
        assert summary["expired_ground_lease_count"] == expired_ground_lease_count
    if expired_master_lease_count is not None:
        assert summary["expired_master_lease_count"] == expired_master_lease_count
    if frozen_tower_count is not None:
        assert summary["frozen_tower_count"] == frozen_tower_count


# ─── Ordering ────────────────────────────────────────────────────────────────


def assert_ascending(values: Sequence[Any], field: str = "created_at") -> None:
    """Assert a projected list of values is in non-decreasing order."""
    assert list(values) == sorted(values), f"expected {field} ascending, got {list(values)}"


def assert_descending(values: Sequence[Any], field: str = "created_at") -> None:
    """Assert a projected list of values is in non-increasing order."""
    assert list(values) == sorted(values, reverse=True), (
        f"expected {field} descending, got {list(values)}"
    )
