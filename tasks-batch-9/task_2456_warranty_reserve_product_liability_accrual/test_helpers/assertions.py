"""Domain assertions for the Warranty Reserve & Product Liability Accrual API."""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

FULL_SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")
NARROW_SYSTEM_FIELDS = ("id", "created_at")


def assert_envelope(response, expected_response_type: str) -> Dict[str, Any]:
    """Every response carries `meta` and `data` shaped as the PRD §2.2 envelope."""
    body = response.json()
    assert "meta" in body, f"response has no meta object: {body}"
    assert "data" in body, f"response has no data member: {body}"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), f"missing api_request_id: {meta}"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_': {meta['api_request_id']!r}"
    )
    timestamp = meta.get("api_request_timestamp")
    assert isinstance(timestamp, str), f"missing api_request_timestamp: {meta}"
    assert is_iso8601_timestamp(timestamp), f"api_request_timestamp not ISO-8601: {timestamp!r}"
    assert body.get("response_type") == expected_response_type, (
        f"expected response_type {expected_response_type!r}, got {body.get('response_type')!r}"
    )
    return body


def assert_identity_fields(entity: Dict[str, Any]) -> None:
    """Rows carrying the full system-managed set (PRD §2.4)."""
    for field in FULL_SYSTEM_FIELDS:
        assert field in entity, f"missing system field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"bad created_at: {entity['created_at']!r}"
    assert is_iso8601_timestamp(entity["updated_at"]), f"bad updated_at: {entity['updated_at']!r}"
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"version must be a positive integer: {entity['version']!r}"
    )


def assert_narrow_identity_fields(entity: Dict[str, Any]) -> None:
    """Rows carrying only `id` and `created_at` (PRD §2.4)."""
    for field in NARROW_SYSTEM_FIELDS:
        assert field in entity, f"missing system field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"bad created_at: {entity['created_at']!r}"
    assert "updated_at" not in entity, f"row must not carry updated_at: {entity}"
    assert "version" not in entity, f"row must not carry version: {entity}"


def assert_fields_equal(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert a batch of field values in one shot with a readable message."""
    mismatches = {
        key: (entity.get(key), value) for key, value in expected.items() if entity.get(key) != value
    }
    assert not mismatches, f"field mismatches (actual, expected): {mismatches}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Listing meta must echo the effective window (PRD §2.3)."""
    assert meta.get("limit") == limit, f"expected limit {limit}, got {meta.get('limit')}"
    assert meta.get("offset") == offset, f"expected offset {offset}, got {meta.get('offset')}"
    if total_count is not None:
        assert meta.get("total_count") == total_count, (
            f"expected total_count {total_count}, got {meta.get('total_count')}"
        )
    if has_more is not None:
        assert meta.get("has_more") is has_more, (
            f"expected has_more {has_more}, got {meta.get('has_more')}"
        )


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    """Collections are ordered by `created_at` ascending (PRD §2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}"
    )


def assert_reserve_state(
    family: Dict[str, Any], balance_cents: int, posture: str
) -> None:
    """The family ledger balance and the posture derived from it (PRD §2.10)."""
    assert family["warranty_reserve_balance_cents"] == balance_cents, (
        f"expected balance {balance_cents}, got {family['warranty_reserve_balance_cents']}"
    )
    assert family["reserve_posture"] == posture, (
        f"expected posture {posture}, got {family['reserve_posture']}"
    )


def assert_rollforward_identity(rollforward: Dict[str, Any]) -> None:
    """The ending balance must tie out to the five movement figures (PRD §3.9)."""
    expected = (
        rollforward["beginning_balance_cents"]
        + rollforward["accruals_cents"]
        + rollforward["campaign_accruals_cents"]
        + rollforward["changes_in_estimate_cents"]
        - rollforward["claims_paid_cents"]
        + rollforward["supplier_recoveries_cents"]
    )
    assert rollforward["ending_balance_cents"] == expected, (
        f"ending balance {rollforward['ending_balance_cents']} does not tie out to {expected}"
    )


def assert_contract_price_conserved(contract: Dict[str, Any]) -> None:
    """Recognized + deferred + refunded always equals the gross price (PRD §3.6)."""
    total = (
        contract["recognized_revenue_cents"]
        + contract["deferred_revenue_cents"]
        + contract["refunded_revenue_cents"]
    )
    assert total == contract["total_contract_price_cents"], (
        "recognized + deferred + refunded "
        f"({total}) != total_contract_price_cents ({contract['total_contract_price_cents']})"
    )


def assert_supplier_aggregates(
    supplier: Dict[str, Any],
    gross_asserted_recovery_cents: Optional[int] = None,
    open_recovery_asset_cents: Optional[int] = None,
    realized_recovery_cents: Optional[int] = None,
    written_off_recovery_cents: Optional[int] = None,
    closed_recovery_count: Optional[int] = None,
    realization_bps: Optional[int] = None,
    collectability_rating: Optional[str] = None,
) -> None:
    """The six supplier aggregates plus the two derived ratings (PRD §3.7)."""
    expected = {
        "gross_asserted_recovery_cents": gross_asserted_recovery_cents,
        "open_recovery_asset_cents": open_recovery_asset_cents,
        "realized_recovery_cents": realized_recovery_cents,
        "written_off_recovery_cents": written_off_recovery_cents,
        "closed_recovery_count": closed_recovery_count,
        "realization_bps": realization_bps,
        "collectability_rating": collectability_rating,
    }
    assert_fields_equal(supplier, **{k: v for k, v in expected.items() if v is not None})


def success_data(response, expected_status: int = 200) -> Dict[str, Any]:
    """Validate a single-object success response and return its `data`."""
    return validate_success(response, expected_status)
