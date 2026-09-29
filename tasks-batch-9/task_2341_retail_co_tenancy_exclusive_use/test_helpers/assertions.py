"""Domain-specific assertions layered on the shared validators.

Shape assertions check that a returned record carries every field the PRD
declares for its entity; ``assert_immutable_record_shape`` enforces the opposite
for the one record type that carries neither ``updated_at`` nor ``version``.
"""
from typing import Any, Dict, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ACCRUAL_MONTHS_DECIMAL_PLACES,
    PAGINATION_META_FIELDS,
    RESPONSE_META_FIELDS,
)

COMMON_MUTABLE_FIELDS = ("created_at", "updated_at", "version")


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------
def assert_has_fields(record: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [f for f in fields if f not in record]
    assert not missing, f"record is missing declared fields {missing}: {record}"


def assert_identity_fields(record: Dict[str, Any]) -> None:
    """``id`` is a UUID and ``created_at`` is an ISO-8601 UTC instant."""
    assert is_valid_uuid(record.get("id")), f"id is not a UUID: {record.get('id')}"
    assert is_iso8601_timestamp(
        record.get("created_at")
    ), f"created_at is not ISO-8601: {record.get('created_at')}"


def assert_common_mutable_fields(record: Dict[str, Any]) -> None:
    """Records other than the immutable one carry created_at/updated_at/version."""
    assert_identity_fields(record)
    assert is_iso8601_timestamp(
        record.get("updated_at")
    ), f"updated_at is not ISO-8601: {record.get('updated_at')}"
    assert isinstance(record.get("version"), int), f"version is not an integer: {record}"
    assert record["version"] >= 1, f"version must start at 1: {record['version']}"


def assert_immutable_record_shape(
    record: Dict[str, Any], fields: Sequence[str]
) -> None:
    """The record exposes ``fields`` and neither ``updated_at`` nor ``version``."""
    assert_has_fields(record, fields)
    assert_identity_fields(record)
    assert "updated_at" not in record, f"immutable record exposes updated_at: {record}"
    assert "version" not in record, f"immutable record exposes version: {record}"


def assert_response_meta(body: Dict[str, Any]) -> None:
    meta = body.get("meta")
    assert isinstance(meta, dict), f"envelope has no meta object: {body}"
    assert_has_fields(meta, RESPONSE_META_FIELDS)
    assert is_valid_uuid(
        meta["api_request_id"]
    ), f"api_request_id is not a UUID: {meta['api_request_id']}"
    assert is_iso8601_timestamp(
        meta["api_request_timestamp"]
    ), f"api_request_timestamp is not ISO-8601: {meta['api_request_timestamp']}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    assert_has_fields(meta, PAGINATION_META_FIELDS)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count {meta['total_count']} != {expected_total}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, f"limit {meta['limit']} != {expected_limit}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset {meta['offset']} != {expected_offset}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more {meta['has_more']} != {expected_has_more}"
        )


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def assert_cents(value: Any, expected: Optional[int] = None, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be integer cents, got {value!r}"
    )
    if expected is not None:
        assert value == expected, f"{label} {value} != {expected}"


def assert_pct(value: Any, expected: float, label: str = "percentage") -> None:
    """Percentages are carried to two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{label} {value} != {expected}"
    )


def assert_accrual_months(value: Any, expected: float) -> None:
    """Accrual months are rounded to four decimal places before pricing."""
    assert round(float(value), ACCRUAL_MONTHS_DECIMAL_PLACES) == round(
        float(expected), ACCRUAL_MONTHS_DECIMAL_PLACES
    ), f"accrual months {value} != {expected}"


def assert_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], fields: Iterable[str]
) -> None:
    drifted = {
        f: (before.get(f), after.get(f)) for f in fields if before.get(f) != after.get(f)
    }
    assert not drifted, f"fields drifted when they should not have: {drifted}"


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that mutates nothing"
    )


def assert_null(value: Any, label: str) -> None:
    assert value is None, f"{label} should be null, got {value!r}"


# --------------------------------------------------------------------------
# Entity shape assertions
# --------------------------------------------------------------------------
CENTER_FIELDS = (
    "id",
    "name",
    "total_gla_sqft",
    "occupancy_grace_days",
    "occupied_gla_sqft",
    "open_occupancy_pct",
    "operating_store_count",
    "open_anchor_count",
    "protected_exclusive_count",
    "aggregate_effective_rent_cents",
    "open_violation_count",
    "compliance_posture",
    "redevelopment_status",
    "last_sweep_at",
    "created_at",
    "updated_at",
    "version",
)

TENANT_FIELDS = (
    "id",
    "legal_name",
    "notice_email",
    "primary_use_code",
    "is_national_chain",
    "status",
    "created_at",
    "updated_at",
    "version",
)

LEASE_FIELDS = (
    "id",
    "center_id",
    "tenant_id",
    "replacement_for_lease_id",
    "suite_code",
    "gla_sqft",
    "parcel_kind",
    "is_anchor",
    "primary_use_code",
    "incidental_use_codes",
    "projected_incidental_sales_pct",
    "base_rent_monthly_cents",
    "commencement_date",
    "expiration_date",
    "premises_status",
    "remedy_status",
    "use_compliance_status",
    "opened_at",
    "dark_since",
    "remedy_eligible_at",
    "effective_rent_monthly_cents",
    "total_abated_cents",
    "created_at",
    "updated_at",
    "version",
)

CONDITION_FIELDS = (
    "id",
    "lease_id",
    "condition_kind",
    "measurement_basis",
    "required_occupancy_pct",
    "required_open_store_count",
    "required_anchor_count",
    "grace_period_days",
    "cure_period_days",
    "remedy_type",
    "max_reduction_pct",
    "status",
    "breach_detected_at",
    "consecutive_breach_days",
    "last_evaluated_measurement_id",
    "created_at",
    "updated_at",
    "version",
)

ANCHOR_REQUIREMENT_FIELDS = (
    "id",
    "condition_id",
    "anchor_lease_id",
    "substitution_allowed",
    "min_substitute_gla_sqft",
    "created_at",
)

CLAUSE_FIELDS = (
    "id",
    "lease_id",
    "protected_use_codes",
    "exclusivity_scope",
    "gla_carve_out_sqft",
    "incidental_sales_pct_cap",
    "effective_from_date",
    "effective_through_date",
    "status",
    "suspended_by_plan_id",
    "created_at",
    "updated_at",
    "version",
)

RESTRICTION_FIELDS = (
    "id",
    "lease_id",
    "radius_miles",
    "measured_from",
    "recapture_basis",
    "recapture_pct",
    "protected_baseline_cents",
    "window_from_date",
    "window_through_date",
    "status",
    "created_at",
    "updated_at",
    "version",
)

NOTICE_FIELDS = (
    "id",
    "violating_lease_id",
    "clause_id",
    "radius_restriction_id",
    "notice_kind",
    "narrative",
    "issued_by_user_id",
    "issued_at",
    "cure_period_days",
    "cure_deadline_at",
    "cure_restart_count",
    "reported_offending_sales_cents",
    "recapture_assessed_cents",
    "status",
    "escalated_at",
    "created_at",
    "updated_at",
    "version",
)

DISPUTE_FIELDS = (
    "id",
    "notice_id",
    "filed_by_tenant_id",
    "grounds_code",
    "narrative",
    "cure_extension_days",
    "status",
    "adjudicated_by_user_id",
    "adjudicated_at",
    "created_at",
    "updated_at",
    "version",
)

ELECTION_FIELDS = (
    "id",
    "lease_id",
    "condition_id",
    "source_notice_id",
    "election_kind",
    "window_from_date",
    "window_through_date",
    "elected_at",
    "shortfall_pct_at_election",
    "anchor_bonus_applied",
    "reduction_pct",
    "reduced_rent_monthly_cents",
    "termination_effective_date",
    "abated_to_date_cents",
    "status",
    "approved_by_user_id",
    "approved_at",
    "created_at",
    "updated_at",
    "version",
)

MEASUREMENT_FIELDS = (
    "id",
    "center_id",
    "variant",
    "window_from_date",
    "window_through_date",
    "measured_at",
    "total_gla_sqft",
    "occupied_gla_sqft",
    "gla_occupancy_pct",
    "open_store_count",
    "open_anchor_count",
    "counted_lease_count",
    "excluded_lease_count",
    "breached_condition_count",
    "status",
    "created_by_user_id",
    "certified_by_user_id",
    "certified_at",
    "created_at",
    "updated_at",
    "version",
)

CERTIFICATE_FIELDS = (
    "id",
    "lease_id",
    "measurement_id",
    "requested_by_user_id",
    "pinned_lease_version",
    "expedite_requested",
    "disclosed_cotenancy_breach",
    "disclosed_exclusive_count",
    "disclosed_effective_rent_cents",
    "base_fee_cents",
    "total_fee_cents",
    "lender_conditions_met",
    "status",
    "signed_at",
    "accepted_at",
    "created_at",
    "updated_at",
    "version",
)

PLAN_FIELDS = (
    "id",
    "center_id",
    "pad_parcel_lease_id",
    "plan_kind",
    "removed_gla_sqft",
    "gla_after_sqft",
    "impacted_clause_count",
    "impacted_condition_count",
    "consent_required",
    "status",
    "recorded_at",
    "created_at",
    "updated_at",
    "version",
)

SCREEN_DECISION_FIELDS = (
    "decision",
    "controlling_clause_id",
    "eligible_clause_count",
    "conflicting_clause_count",
    "carve_out_applied",
    "screened_use_code",
)

SWEEP_REPORT_FIELDS = (
    "as_of",
    "escalated_notice_count",
    "newly_eligible_lease_count",
    "cured_condition_count",
    "breached_condition_count",
    "compliance_posture",
)


def _assert_record(record: Dict[str, Any], fields: Sequence[str]) -> None:
    assert_has_fields(record, fields)
    assert_common_mutable_fields(record)


def assert_center_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, CENTER_FIELDS)


def assert_tenant_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, TENANT_FIELDS)


def assert_lease_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, LEASE_FIELDS)


def assert_condition_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, CONDITION_FIELDS)


def assert_anchor_requirement_shape(record: Dict[str, Any]) -> None:
    assert_immutable_record_shape(record, ANCHOR_REQUIREMENT_FIELDS)


def assert_clause_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, CLAUSE_FIELDS)


def assert_restriction_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, RESTRICTION_FIELDS)


def assert_notice_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, NOTICE_FIELDS)


def assert_dispute_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, DISPUTE_FIELDS)


def assert_election_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, ELECTION_FIELDS)


def assert_measurement_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, MEASUREMENT_FIELDS)


def assert_certificate_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, CERTIFICATE_FIELDS)


def assert_plan_shape(record: Dict[str, Any]) -> None:
    _assert_record(record, PLAN_FIELDS)


def assert_screen_decision_shape(record: Dict[str, Any]) -> None:
    assert_has_fields(record, SCREEN_DECISION_FIELDS)


def assert_sweep_report_shape(record: Dict[str, Any]) -> None:
    assert_has_fields(record, SWEEP_REPORT_FIELDS)


# --------------------------------------------------------------------------
# Conserved-quantity helpers
# --------------------------------------------------------------------------
def assert_center_quantities(
    center: Dict[str, Any],
    total_gla_sqft: Optional[int] = None,
    occupied_gla_sqft: Optional[int] = None,
    open_occupancy_pct: Optional[float] = None,
    operating_store_count: Optional[int] = None,
    open_anchor_count: Optional[int] = None,
    protected_exclusive_count: Optional[int] = None,
    aggregate_effective_rent_cents: Optional[int] = None,
    open_violation_count: Optional[int] = None,
    compliance_posture: Optional[str] = None,
    redevelopment_status: Optional[str] = None,
) -> None:
    """Assert whichever center figures a test cares about, in one call."""
    checks = {
        "total_gla_sqft": total_gla_sqft,
        "occupied_gla_sqft": occupied_gla_sqft,
        "operating_store_count": operating_store_count,
        "open_anchor_count": open_anchor_count,
        "protected_exclusive_count": protected_exclusive_count,
        "aggregate_effective_rent_cents": aggregate_effective_rent_cents,
        "open_violation_count": open_violation_count,
        "compliance_posture": compliance_posture,
        "redevelopment_status": redevelopment_status,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert center[field] == expected, (
                f"center.{field} is {center[field]}, expected {expected}"
            )
    if open_occupancy_pct is not None:
        assert_pct(center["open_occupancy_pct"], open_occupancy_pct, "open_occupancy_pct")


def assert_lease_dimensions(
    lease: Dict[str, Any],
    premises_status: Optional[str] = None,
    remedy_status: Optional[str] = None,
    use_compliance_status: Optional[str] = None,
    effective_rent_monthly_cents: Optional[int] = None,
    total_abated_cents: Optional[int] = None,
) -> None:
    """Assert the lease's three independent status dimensions and money fields."""
    checks = {
        "premises_status": premises_status,
        "remedy_status": remedy_status,
        "use_compliance_status": use_compliance_status,
        "effective_rent_monthly_cents": effective_rent_monthly_cents,
        "total_abated_cents": total_abated_cents,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert lease[field] == expected, (
                f"lease.{field} is {lease[field]}, expected {expected}"
            )


def ids_of(rows: Iterable[Dict[str, Any]]) -> list:
    return [row["id"] for row in rows]


def assert_only_ids(rows: Iterable[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = ids_of(rows)
    assert sorted(actual) == sorted(expected_ids), (
        f"listing returned {actual}, expected exactly {list(expected_ids)}"
    )
