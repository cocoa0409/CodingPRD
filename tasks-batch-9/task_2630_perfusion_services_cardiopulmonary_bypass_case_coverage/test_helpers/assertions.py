"""Domain assertion helpers for the perfusion service API.

These wrap the identity, envelope, money and ledger rules the PRD states once
in section 2 and then relies on everywhere else.
"""
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CE_DECIMAL_PLACES,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    READINESS_DECIMAL_PLACES,
)


# ─── Identity, timestamps and the version counter ─────
def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the full identity set every resource but a device event carries.

    Every resource the service mints carries an `id`, which is a
    server-generated UUID, and a `created_at`; most resources additionally
    carry `updated_at` and `version`, an integer that begins at 1 on creation.
    """
    assert "id" in resource, "resource is missing id"
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {resource.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC timestamp: {resource.get('updated_at')!r}"
    )
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version begins at 1 on creation"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_event_log_fields(event: Dict[str, Any]) -> None:
    """Assert the identity set of an immutable device event log.

    A captured device event log is immutable: once appended it is never
    altered, so it carries only `id` and `created_at`. It has no `updated_at`
    field and no `version` field at all.
    """
    assert is_valid_uuid(event["id"]), f"id is not a UUID: {event.get('id')!r}"
    assert is_iso8601_timestamp(event["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {event.get('created_at')!r}"
    )
    assert "updated_at" not in event, "a device event log has no updated_at field"
    assert "version" not in event, "a device event log has no version field"


def assert_version_advanced_by(new_resource: Dict[str, Any], old_version: int, increment: int = 1) -> None:
    """Assert the counter increased by exactly the expected number of mutations."""
    assert new_resource["version"] == old_version + increment, (
        f"expected version {old_version + increment}, got {new_resource['version']}"
    )


def assert_version_unchanged(new_resource: Dict[str, Any], old_version: int) -> None:
    assert new_resource["version"] == old_version, (
        f"expected the version to stay {old_version}, got {new_resource['version']}"
    )


# ─── Envelope shape ───────────────────────────────────
def assert_success_envelope(response: Dict[str, Any], expected_response_type: str = "object") -> None:
    """Assert the success envelope's declared shape."""
    body = response.json()
    assert body["response_type"] == expected_response_type, (
        f"expected response_type {expected_response_type!r}, got {body.get('response_type')!r}"
    )
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp with three fractional digits"
    )


def assert_error_envelope(response: Dict[str, Any], expected_error_id: str) -> None:
    """Assert the error envelope carries only the declared keys.

    The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`, and `data` carries the error identifier and a
    human-readable message.
    """
    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(body['data'].keys())}"
    )
    assert body["data"]["error_id"] == expected_error_id, (
        f"expected {expected_error_id}, got {body['data']['error_id']}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        "the error message must be a non-empty human-readable string"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the two request fields, got {sorted(body['meta'].keys())}"
    )


def assert_single_resource_meta(response: Dict[str, Any]) -> None:
    """Single-resource endpoints omit the four pagination fields from meta."""
    body = response.json()
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in body["meta"], (
            f"a single-resource response must omit {field} from meta"
        )


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: int,
    has_more: bool,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> None:
    """Assert a list envelope's window and count fields."""
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Collection endpoints return their rows sorted by created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


# ─── Money ────────────────────────────────────────────
def assert_cents(value: Any, expected: int, label: str = "amount") -> None:
    """Every monetary amount is a whole number of cents, stored as an integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"expected {label} {expected}, got {value}"


def assert_decimal_places(value: float, places: int, label: str = "value") -> None:
    """Assert a rounded quantity carries no more than the declared precision."""
    assert round(float(value), places) == float(value), (
        f"{label} must carry at most {places} decimal places, got {value!r}"
    )


def assert_readiness_score(value: Any, expected: float) -> None:
    """A readiness score is clamped into [0, 1] and rounded to three decimals."""
    assert 0.0 <= float(value) <= 1.0, f"readiness score must lie in [0, 1], got {value!r}"
    assert_decimal_places(value, READINESS_DECIMAL_PLACES, "readiness_score")
    assert abs(float(value) - expected) < 1e-9, (
        f"expected readiness_score {expected}, got {value}"
    )


def assert_ce_hours(value: Any, expected: float) -> None:
    """Continuing-education ledgers carry one decimal place."""
    assert_decimal_places(value, CE_DECIMAL_PLACES, "credit hours")
    assert abs(float(value) - expected) < 1e-9, f"expected {expected} credit hours, got {value}"


# ─── Case, contract and device state ──────────────────
def assert_case_dimensions(case: Dict[str, Any], bypass_status: str, billing_status: str) -> None:
    """The clinical and fiscal dimensions of a case advance independently."""
    assert case["bypass_status"] == bypass_status, (
        f"expected bypass_status {bypass_status}, got {case['bypass_status']}"
    )
    assert case["billing_status"] == billing_status, (
        f"expected billing_status {billing_status}, got {case['billing_status']}"
    )


def assert_contract_ledger(contract: Dict[str, Any], accrued_fee_cents: int, accrued_case_count: int) -> None:
    """Assert the contract's denormalised accrual ledger."""
    assert_cents(contract["accrued_case_fee_cents"], accrued_fee_cents, "accrued_case_fee_cents")
    assert contract["accrued_case_count"] == accrued_case_count, (
        f"expected accrued_case_count {accrued_case_count}, got {contract['accrued_case_count']}"
    )


def assert_device_state(
    device: Dict[str, Any],
    status: Optional[str] = None,
    open_reservation_count: Optional[int] = None,
    alarm_count_since_service: Optional[int] = None,
    runtime_hours_since_service: Optional[float] = None,
) -> None:
    """Assert a machine's status and its service and reservation counters."""
    if status is not None:
        assert device["status"] == status, f"expected device status {status}, got {device['status']}"
    if open_reservation_count is not None:
        assert device["open_reservation_count"] == open_reservation_count, (
            f"expected open_reservation_count {open_reservation_count}, "
            f"got {device['open_reservation_count']}"
        )
    if alarm_count_since_service is not None:
        assert device["alarm_count_since_service"] == alarm_count_since_service, (
            f"expected alarm_count_since_service {alarm_count_since_service}, "
            f"got {device['alarm_count_since_service']}"
        )
    if runtime_hours_since_service is not None:
        assert abs(float(device["runtime_hours_since_service"]) - runtime_hours_since_service) < 1e-9, (
            f"expected runtime_hours_since_service {runtime_hours_since_service}, "
            f"got {device['runtime_hours_since_service']}"
        )


def assert_pack_line(
    line: Dict[str, Any],
    line_code: str,
    quantity: int,
    unit_cost_cents: int,
    line_total_cents: int,
    substituted: bool,
) -> None:
    """Assert one materialised pack line, including its own rounded total."""
    assert line["line_code"] == line_code, f"expected line_code {line_code}, got {line['line_code']}"
    assert line["quantity"] == quantity, f"expected quantity {quantity}, got {line['quantity']}"
    assert_cents(line["unit_cost_cents"], unit_cost_cents, "unit_cost_cents")
    assert_cents(line["line_total_cents"], line_total_cents, "line_total_cents")
    assert line["substituted"] is substituted, (
        f"expected substituted {substituted}, got {line['substituted']}"
    )


def assert_line_codes_ascending(line_items: List[Dict[str, Any]]) -> None:
    """The materialised lines are ordered by line_code ascending."""
    codes = [line["line_code"] for line in line_items]
    assert codes == sorted(codes), f"line codes are not in ascending order: {codes}"


def assert_fields_absent(resource: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert field not in resource, f"{field} must not appear on this resource"


def assert_fields_null(resource: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert resource[field] is None, f"expected {field} to be null, got {resource[field]!r}"
