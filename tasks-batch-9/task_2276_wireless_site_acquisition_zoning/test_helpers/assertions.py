"""Domain assertions layered on top of the framework validators."""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
import requests
from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_errors import ApiError

MONEY_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def ok(response: requests.Response, expected_status: int = 200) -> Dict[str, Any]:
    """Assert a successful envelope and return its ``data`` object."""
    return validate_success(response, expected_status=expected_status)


def setup_data(response: requests.Response) -> Dict[str, Any]:
    """Read a successful envelope for a *setup* step.

    Setup steps are preconditions rather than the behaviour under test, so a
    broken precondition should surface as a plain assertion naming the failing
    step instead of masquerading as a status-code failure.
    """
    return get_success_data(response)


def created(response: requests.Response) -> Dict[str, Any]:
    """Assert a `201` create envelope and return its ``data`` object."""
    return validate_success(response, expected_status=201)


def failed(
    response: requests.Response, error: ApiError, expected_status: Optional[int] = None
) -> Dict[str, Any]:
    """Assert an error envelope carrying ``error``; return its ``data`` object."""
    return validate_error(
        response, str(error.value), expected_status=expected_status
    )


def page(response: requests.Response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Assert a paginated envelope and return ``(rows, meta)``."""
    return validate_paginated(response)


def assert_error_data_shape(response: requests.Response) -> None:
    """The PRD limits an error ``data`` object to `error_id` and `message`."""
    body = response.json()
    data = body["data"]
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry exactly error_id and message, got {sorted(data.keys())}"
    )
    assert isinstance(data["message"], str) and data["message"], "message must be non-empty"


def assert_error_meta_shape(response: requests.Response) -> None:
    """The PRD limits an error ``meta`` object to the two request identifiers."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry exactly api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )
    assert str(meta["api_request_id"]).startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count expected {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset expected {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more expected {has_more}, got {meta['has_more']}"
        )


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Every resource carries `id`, `created_at`, `updated_at` and `version`."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in resource, f"resource is missing {field}"
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int) and resource["version"] >= 1


# ---------------------------------------------------------------------------
# Money and numbers
# ---------------------------------------------------------------------------
def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} expected {expected:.2f}, got {actual}"
    )


def assert_money_not(actual: Any, forbidden: float, label: str = "amount") -> None:
    """Guard against a plausible-but-wrong rounding or tiering order."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - forbidden) > MONEY_TOLERANCE / 2, (
        f"{label} must not equal the mis-ordered value {forbidden:.2f}, got {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "score") -> None:
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"{label} expected {expected:.2f}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected_iso: str, label: str = "timestamp") -> None:
    """Compare two UTC instants, tolerating the optional fractional-second form."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(str(actual)) == parse_instant(expected_iso), (
        f"{label} expected {expected_iso}, got {actual}"
    )


def assert_instant_is_none(actual: Any, label: str = "timestamp") -> None:
    assert actual is None, f"{label} expected null, got {actual}"


# ---------------------------------------------------------------------------
# Field bundles
# ---------------------------------------------------------------------------
def assert_fields(resource: Dict[str, Any], **expected: Any) -> None:
    """Assert plain equality for a bundle of scalar fields."""
    for field, want in expected.items():
        assert field in resource, f"resource is missing {field}"
        got = resource[field]
        if isinstance(want, float):
            assert float(got) == pytest.approx(want, abs=MONEY_TOLERANCE), (
                f"{field} expected {want}, got {got}"
            )
        else:
            assert got == want, f"{field} expected {want!r}, got {got!r}"


def assert_version(resource: Dict[str, Any], expected: int) -> None:
    assert resource["version"] == expected, (
        f"version expected {expected}, got {resource['version']}"
    )


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids)


__all__ = [
    "MONEY_TOLERANCE",
    "ok",
    "setup_data",
    "created",
    "failed",
    "page",
    "assert_error_data_shape",
    "assert_error_meta_shape",
    "assert_pagination_meta",
    "assert_common_fields",
    "assert_money",
    "assert_money_not",
    "assert_score",
    "parse_instant",
    "assert_instant",
    "assert_instant_is_none",
    "assert_fields",
    "assert_version",
    "assert_ids_in_order",
]
