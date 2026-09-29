"""Domain assertion helpers.

These wrap the shared envelope validators with the vocabulary of this API so
that a test body reads as a statement about archives, not about dictionaries.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .types import (
    REQUEST_ID_PREFIX,
    RESPONSE_TYPE_ERROR,
)

MONEY_TOLERANCE = 0


# ─── Envelope ─────────────────────────────────────────────────────────────

def assert_envelope_meta(response) -> Dict[str, Any]:
    """Every response carries a correlation id and an ISO 8601 timestamp."""
    meta = response.json()["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        f"api_request_id must start with '{REQUEST_ID_PREFIX}': "
        f"{meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
        f"api_request_timestamp is not ISO 8601: "
        f"{meta['api_request_timestamp']!r}"
    )
    return meta


def created(response) -> Dict[str, Any]:
    """A creation endpoint answered 201; returns the created row."""
    return validate_success(response, 201)


def ok(response) -> Dict[str, Any]:
    """A read or action endpoint answered 200; returns the row."""
    return validate_success(response, 200)


def failed(response, expected_error_id: str, expected_status: Optional[int] = None):
    """The call was refused with the named error_id."""
    return validate_error(response, expected_error_id, expected_status)


def page(response):
    """A list endpoint answered 200; returns ``(rows, meta)``."""
    return validate_paginated(response)


def setup(response) -> Dict[str, Any]:
    """A fixture step succeeded; returns the row it produced."""
    return get_success_data(response)


# ─── Identity and common fields ───────────────────────────────────────────

def assert_server_assigned_id(row: Dict[str, Any]) -> None:
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row.get('id')!r}"


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None):
    """Rows that carry the common field set: id, created_at, updated_at, version."""
    assert_server_assigned_id(row)
    assert is_iso8601_timestamp(row["created_at"]), row.get("created_at")
    assert is_iso8601_timestamp(row["updated_at"]), row.get("updated_at")
    assert isinstance(row["version"], int)
    assert row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_no_common_fields(row: Dict[str, Any]) -> None:
    """Rows declared to carry only ``id`` and ``created_at``."""
    assert_server_assigned_id(row)
    assert is_iso8601_timestamp(row["created_at"]), row.get("created_at")
    assert "version" not in row, "row must not expose a version field"
    assert "updated_at" not in row, "row must not expose an updated_at field"


# ─── Field-level helpers ──────────────────────────────────────────────────

def assert_fields(row: Dict[str, Any], **expected) -> None:
    """Assert a batch of exact field values with a readable failure message."""
    for field, value in expected.items():
        assert field in row, f"missing field {field!r} in {sorted(row)}"
        assert row[field] == value, (
            f"{field}: expected {value!r}, got {row[field]!r}"
        )


def assert_nulls(row: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert field in row, f"missing field {field!r} in {sorted(row)}"
        assert row[field] is None, f"{field}: expected null, got {row[field]!r}"


def assert_money_cents(row: Dict[str, Any], field: str, expected: int) -> None:
    """Money is carried as an integer number of cents."""
    actual = row[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_score_2dp(row: Dict[str, Any], field: str, expected: float) -> None:
    """Scores and percentages are carried to two decimal places."""
    actual = row[field]
    assert actual is not None, f"{field} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_one_decimal(row: Dict[str, Any], field: str, expected: float) -> None:
    """Temperature and relative humidity are carried to one decimal place."""
    assert float(row[field]) == pytest.approx(expected, abs=0.01), (
        f"{field}: expected {expected}, got {row[field]}"
    )


def assert_instant(row: Dict[str, Any], field: str, expected: str) -> None:
    """A timestamp field stamped from the logical clock."""
    actual = row[field]
    assert actual is not None, f"{field} must not be null"
    assert is_iso8601_timestamp(actual), f"{field} is not ISO 8601: {actual!r}"
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


# ─── Collections ──────────────────────────────────────────────────────────

def assert_total_count(response, expected: int) -> List[Dict[str, Any]]:
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_ids_exactly(response, expected_ids: List[str]) -> None:
    """The list contains exactly the named rows, in creation order."""
    rows, meta = validate_paginated(response)
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected exactly {list(expected_ids)}, got {actual}"
    )
    assert meta["total_count"] == len(expected_ids)


def assert_empty(response) -> None:
    rows, meta = validate_paginated(response)
    assert rows == [], f"expected an empty page, got {len(rows)} rows"
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ─── Custody and budget invariants ────────────────────────────────────────

def assert_unit_custody_identity(item: Dict[str, Any]) -> None:
    """unit_count == units_on_shelf + units_on_loan + units_deaccessioned."""
    total = (
        item["units_on_shelf"] + item["units_on_loan"] + item["units_deaccessioned"]
    )
    assert item["unit_count"] == total, (
        f"unit custody broken: unit_count {item['unit_count']} != "
        f"{item['units_on_shelf']} + {item['units_on_loan']} + "
        f"{item['units_deaccessioned']}"
    )


def assert_custody_triple(
    item: Dict[str, Any], on_shelf: int, on_loan: int, deaccessioned: int
) -> None:
    assert_fields(
        item,
        units_on_shelf=on_shelf,
        units_on_loan=on_loan,
        units_deaccessioned=deaccessioned,
    )
    assert_unit_custody_identity(item)


def assert_budget_ledger(plan: Dict[str, Any], committed: int, spent: int) -> None:
    assert_money_cents(plan, "budget_committed_cents", committed)
    assert_money_cents(plan, "budget_spent_cents", spent)


def assert_cost_breakdown(
    job: Dict[str, Any],
    subtotal: int,
    discount_pct: float,
    discounted: int,
    handling: int,
    surcharge: int,
    committed: int,
) -> None:
    """The six frozen steps of the migration cost waterfall."""
    assert_money_cents(job, "subtotal_cents", subtotal)
    assert float(job["volume_discount_pct"]) == pytest.approx(discount_pct, abs=0.001)
    assert_money_cents(job, "discounted_cents", discounted)
    assert_money_cents(job, "handling_fee_cents", handling)
    assert_money_cents(job, "condition_surcharge_cents", surcharge)
    assert_money_cents(job, "committed_cost_cents", committed)
    assert discounted + handling + surcharge == committed, (
        "committed_cost_cents must be the sum of steps 3, 4 and 5"
    )


def assert_is_error_envelope(response) -> None:
    assert response.json().get("response_type") == RESPONSE_TYPE_ERROR
