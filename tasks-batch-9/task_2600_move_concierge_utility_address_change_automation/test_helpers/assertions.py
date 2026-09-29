"""Domain assertion helpers for the Move Concierge API.

These wrap the framework validators with the vocabulary the PRD uses, so a
test reads as a statement about the contract rather than about JSON.
"""

from typing import Any, Dict, List, Optional, Sequence

import requests

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    assert_timestamp_format,
    assert_version_incremented,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_errors import ApiErrorId
from .constants import (
    DEPOSIT_CAP_CENTS,
    READINESS_MAX,
    READINESS_MIN,
)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def assert_created(response: requests.Response) -> Dict[str, Any]:
    """Assert an HTTP 201 creation envelope and return its data object."""
    return validate_success(response, expected_status=201)


def assert_ok(response: requests.Response) -> Dict[str, Any]:
    """Assert an HTTP 200 envelope and return its data object."""
    return validate_success(response, expected_status=200)


def assert_error(
    response: requests.Response,
    error_id: ApiErrorId,
    expected_status: Optional[int] = None,
) -> Dict[str, Any]:
    """Assert the error envelope carries exactly `error_id`.

    The HTTP status is cross-checked against the catalogue in section 5
    automatically when `expected_status` is omitted.
    """
    return validate_error(response, error_id.value, expected_status=expected_status)


def assert_error_one_of(response: requests.Response, error_ids: Sequence[ApiErrorId]) -> str:
    """Assert the error is one of `error_ids` and return the one observed."""
    return validate_error_is_one_of(response, [e.value for e in error_ids])


def assert_list(response: requests.Response):
    """Assert a list envelope and return the (data, meta) pair."""
    return validate_paginated(response)


def assert_page(
    response: requests.Response,
    total_count: int,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Assert a list envelope reports the expected window bookkeeping.

    `total_count` is the number of rows matching the filters before the page
    window is applied, and `has_more` is true when rows remain after it.
    """
    data, meta = validate_paginated(response)
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    return data


# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_versioned_resource(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert a resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])
    assert_timestamp_format(resource["updated_at"])
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_immutable_resource(resource: Dict[str, Any]) -> None:
    """Assert an append-only resource carries only id and created_at.

    A ledger entry has no `updated_at` field and no `version` field, and
    neither key appears in its response body.
    """
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])
    assert "updated_at" not in resource, "an append-only entry must not carry updated_at"
    assert "version" not in resource, "an append-only entry must not carry version"


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert a read left the row untouched: same version and same updated_at."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} without a write"
    )
    assert after["updated_at"] == before["updated_at"], "updated_at moved without a write"


def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """Assert a mutation incremented `version` by exactly `by`."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Domain-specific assertions
# ---------------------------------------------------------------------------
def assert_move_state(
    move: Dict[str, Any],
    lifecycle_status: Optional[str] = None,
    duplicate_flag: Optional[str] = None,
    consent_gate: Optional[str] = None,
    blocked_reason: Optional[str] = None,
    readiness_score: Optional[int] = None,
) -> None:
    """Assert the derived fields a move exposes on read."""
    if lifecycle_status is not None:
        assert move["lifecycle_status"] == lifecycle_status, (
            f"expected lifecycle_status {lifecycle_status}, got {move['lifecycle_status']}"
        )
    if duplicate_flag is not None:
        assert move["duplicate_flag"] == duplicate_flag, (
            f"expected duplicate_flag {duplicate_flag}, got {move['duplicate_flag']}"
        )
    if consent_gate is not None:
        assert move["consent_gate"] == consent_gate, (
            f"expected consent_gate {consent_gate}, got {move['consent_gate']}"
        )
    if blocked_reason is not None:
        assert move["blocked_reason"] == blocked_reason, (
            f"expected blocked_reason {blocked_reason}, got {move['blocked_reason']}"
        )
    if readiness_score is not None:
        assert move["readiness_score"] == readiness_score, (
            f"expected readiness_score {readiness_score}, got {move['readiness_score']}"
        )


def assert_order_dimensions(
    order: Dict[str, Any],
    provision_status: Optional[str] = None,
    credit_status: Optional[str] = None,
) -> None:
    """Assert both of a service order's independent state dimensions."""
    if provision_status is not None:
        assert order["provision_status"] == provision_status, (
            f"expected provision_status {provision_status}, got {order['provision_status']}"
        )
    if credit_status is not None:
        assert order["credit_status"] == credit_status, (
            f"expected credit_status {credit_status}, got {order['credit_status']}"
        )


def assert_window_released(order: Dict[str, Any]) -> None:
    """Assert both window fields are cleared, releasing the occupancy window."""
    assert order["scheduled_window_start"] is None, "scheduled_window_start was not cleared"
    assert order["scheduled_window_end"] is None, "scheduled_window_end was not cleared"


def assert_window_retained(order: Dict[str, Any]) -> None:
    """Assert both window fields survive for audit even though the window is free."""
    assert order["scheduled_window_start"] is not None, "scheduled_window_start must survive for audit"
    assert order["scheduled_window_end"] is not None, "scheduled_window_end must survive for audit"


def assert_readiness_breakdown(
    breakdown: Dict[str, Any],
    variant: str,
    identity_component: int,
    utility_component: int,
    filing_component: int,
    consent_component: int,
    readiness_score: int,
) -> None:
    """Assert the computed readiness read exposes the full arithmetic."""
    assert breakdown["variant"] == variant, (
        f"expected variant {variant}, got {breakdown['variant']}"
    )
    assert breakdown["identity_component"] == identity_component, (
        f"expected identity_component {identity_component}, got {breakdown['identity_component']}"
    )
    assert breakdown["utility_component"] == utility_component, (
        f"expected utility_component {utility_component}, got {breakdown['utility_component']}"
    )
    assert breakdown["filing_component"] == filing_component, (
        f"expected filing_component {filing_component}, got {breakdown['filing_component']}"
    )
    assert breakdown["consent_component"] == consent_component, (
        f"expected consent_component {consent_component}, got {breakdown['consent_component']}"
    )
    assert breakdown["readiness_score"] == readiness_score, (
        f"expected readiness_score {readiness_score}, got {breakdown['readiness_score']}"
    )


def assert_readiness_clamped(readiness_score: int) -> None:
    """Assert the score sits inside the inclusive range 0 through 100."""
    assert isinstance(readiness_score, int), "readiness_score must be an integer"
    assert READINESS_MIN <= readiness_score <= READINESS_MAX, (
        f"readiness_score {readiness_score} escaped the inclusive range 0 through 100"
    )


def assert_duplicate_score(move: Dict[str, Any], expected: float) -> None:
    """Assert `duplicate_match_score` matches to exactly two decimal places."""
    actual = float(move["duplicate_match_score"])
    assert round(actual, 2) == round(expected, 2), (
        f"expected duplicate_match_score {expected:.2f}, got {actual}"
    )


def assert_pct_field(resource: Dict[str, Any], field: str, expected: float) -> None:
    """Assert a percentage-shaped field carried at four decimal places."""
    actual = float(resource[field])
    assert round(actual, 4) == round(expected, 4), (
        f"expected {field} {expected:.4f}, got {actual}"
    )


def assert_cents(resource: Dict[str, Any], field: str, expected: int) -> None:
    """Assert a monetary field is an integer number of cents equal to `expected`."""
    actual = resource[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {field} {expected}, got {actual}"


def assert_deposit_within_cap(order: Dict[str, Any]) -> None:
    """Assert the deposit respects the platform deposit ceiling of 50000 cents."""
    assert order["deposit_amount_cents"] <= DEPOSIT_CAP_CENTS, (
        f"deposit_amount_cents {order['deposit_amount_cents']} exceeded the ceiling"
    )
    assert order["deposit_estimate_cents"] <= DEPOSIT_CAP_CENTS, (
        f"deposit_estimate_cents {order['deposit_estimate_cents']} exceeded the ceiling"
    )


def ledger_net(entries: Sequence[Dict[str, Any]]) -> int:
    """Sum the signed `amount_cents` over a sequence of ledger entries."""
    return sum(entry["amount_cents"] for entry in entries)


def assert_ledger_net(
    entries: Sequence[Dict[str, Any]], placement: Dict[str, Any]
) -> None:
    """Assert a placement's ledger net equals attributed minus feed-source share."""
    expected = placement["attributed_share_cents"] - placement["feed_source_share_cents"]
    actual = ledger_net(entries)
    assert actual == expected, (
        f"ledger net {actual} does not equal attributed_share_cents minus "
        f"feed_source_share_cents ({expected})"
    )


def assert_entry_types(entries: Sequence[Dict[str, Any]], expected: Sequence[str]) -> None:
    """Assert the ledger holds exactly these entry types in posting sequence."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == list(expected), f"expected entry types {list(expected)}, got {actual}"


def assert_all_distinct(values: Sequence[Any]) -> None:
    """Assert every value in the sequence is pairwise distinct."""
    assert len(set(values)) == len(values), f"values are not pairwise distinct: {list(values)}"


__all__ = [
    "assert_all_distinct",
    "assert_cents",
    "assert_cost_precision",
    "assert_created",
    "assert_deposit_within_cap",
    "assert_duplicate_score",
    "assert_entry_types",
    "assert_error",
    "assert_error_one_of",
    "assert_immutable_resource",
    "assert_ledger_net",
    "assert_list",
    "assert_move_state",
    "assert_ok",
    "assert_order_dimensions",
    "assert_page",
    "assert_pct_field",
    "assert_readiness_breakdown",
    "assert_readiness_clamped",
    "assert_timestamp_format",
    "assert_unchanged",
    "assert_version_bumped",
    "assert_version_incremented",
    "assert_versioned_resource",
    "assert_window_released",
    "assert_window_retained",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "ledger_net",
    "validate_error",
    "validate_paginated",
    "validate_success",
]
