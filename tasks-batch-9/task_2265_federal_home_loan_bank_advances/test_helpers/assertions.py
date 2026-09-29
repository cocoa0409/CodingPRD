"""Domain assertion helpers.

These wrap the repetitive field-by-field checks the PRD's derived aggregates
demand, so individual tests read as statements about the contract rather than as
long chains of dictionary lookups.
"""
import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import PAR_VALUE_CENTS


def assert_fields(entity: dict, **expected) -> None:
    """Assert every named field of ``entity`` equals the expected value."""
    for field, value in expected.items():
        assert field in entity, f"missing field {field!r} in {sorted(entity)}"
        assert entity[field] == value, (
            f"{field}: expected {value!r}, got {entity[field]!r}"
        )


def assert_common_fields(entity: dict) -> None:
    """Every entity carries a uuid id, ISO-8601 audit stamps and a version."""
    assert is_valid_uuid(entity["id"]), f"not a uuid: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_envelope(response, expected_status: int = 200) -> dict:
    """Validate the standard envelope and return the data payload."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta[
        "api_request_timestamp"
    ]
    return validate_success(response, expected_status)


def assert_error_envelope(response) -> dict:
    """An error envelope still carries request identity and a non-empty message."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta[
        "api_request_timestamp"
    ]
    assert body["response_type"] == "error", body["response_type"]
    data = body["data"]
    assert data["message"], "error message must not be empty"
    return data


def assert_total_count(response, expected_total: int) -> list:
    """Assert a list response reports the expected ``total_count``."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"total_count: expected {expected_total}, got {meta['total_count']}"
    )
    return rows


def assert_page(response, expected_limit, expected_offset, expected_total, expected_has_more):
    """Assert the full pagination meta block of a list response."""
    rows, meta = validate_paginated(response)
    assert meta["limit"] == expected_limit, meta
    assert meta["offset"] == expected_offset, meta
    assert meta["total_count"] == expected_total, meta
    assert meta["has_more"] is expected_has_more, meta
    return rows


def assert_same_instant(actual: str, expected: str) -> None:
    """Two ISO-8601 UTC strings denote the same instant.

    Used where the PRD says a resource records a client-supplied instant but does
    not fix the fractional-digit rendering of the echoed value.
    """
    assert _instant(actual) == _instant(expected), f"expected {expected}, got {actual}"


def _instant(value: str):
    from datetime import datetime, timezone

    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_par_multiple(amount_cents: int) -> None:
    """Stock amounts are exact multiples of the 10,000-cent par value."""
    assert amount_cents % PAR_VALUE_CENTS == 0, amount_cents


def assert_shares(subscription: dict) -> None:
    """``shares`` is ``amount_cents`` divided by the par value."""
    assert subscription["shares"] == subscription["amount_cents"] // PAR_VALUE_CENTS


def assert_exception_rate(review: dict, expected_pct: float) -> None:
    """``exception_rate_pct`` is carried to exactly two decimal places."""
    assert review["exception_rate_pct"] == pytest.approx(expected_pct, abs=1e-9), (
        f"exception_rate_pct: expected {expected_pct}, got {review['exception_rate_pct']}"
    )


def assert_weighted_score(review: dict, expected_score: float) -> None:
    """``weighted_exception_score`` is an unrounded decimal sum of weights."""
    assert review["weighted_exception_score"] == pytest.approx(
        expected_score, abs=1e-9
    ), (
        "weighted_exception_score: expected "
        f"{expected_score}, got {review['weighted_exception_score']}"
    )


def assert_advance_dimensions(advance: dict, credit_status: str, collateral_status: str) -> None:
    """The credit and collateral dimensions are separate state machines."""
    assert advance["credit_status"] == credit_status, advance["credit_status"]
    assert advance["collateral_status"] == collateral_status, advance[
        "collateral_status"
    ]


def assert_capacity_breakdown(breakdown: dict, **expected) -> None:
    """Assert the inline borrowing-capacity breakdown field by field."""
    assert_fields(breakdown, **expected)


def assert_asset_valuation(asset: dict, discount_factor_bps: int, lendable_value_cents: int) -> None:
    """A per-asset factor and its rounded lendable value."""
    assert asset["discount_factor_bps"] == discount_factor_bps, asset[
        "discount_factor_bps"
    ]
    assert asset["lendable_value_cents"] == lendable_value_cents, asset[
        "lendable_value_cents"
    ]


def assert_shortfall(
    member: dict,
    shortfall_status: str,
    shortfall_required_cure_cents: int,
    shortfall_opened_at=...,
    shortfall_cure_deadline=...,
) -> None:
    """Assert the shortfall block of a member bank."""
    assert member["shortfall_status"] == shortfall_status, member["shortfall_status"]
    assert (
        member["shortfall_required_cure_cents"] == shortfall_required_cure_cents
    ), member["shortfall_required_cure_cents"]
    if shortfall_opened_at is not ...:
        assert member["shortfall_opened_at"] == shortfall_opened_at, member[
            "shortfall_opened_at"
        ]
    if shortfall_cure_deadline is not ...:
        assert member["shortfall_cure_deadline"] == shortfall_cure_deadline, member[
            "shortfall_cure_deadline"
        ]


def assert_stock_position(
    member: dict,
    required_membership_stock_cents=...,
    required_activity_stock_cents=...,
    required_total_stock_cents=...,
    stock_held_cents=...,
    stock_deficiency_cents=...,
    excess_stock_cents=...,
) -> None:
    """Assert the member's stock requirement and holdings block."""
    for field, value in (
        ("required_membership_stock_cents", required_membership_stock_cents),
        ("required_activity_stock_cents", required_activity_stock_cents),
        ("required_total_stock_cents", required_total_stock_cents),
        ("stock_held_cents", stock_held_cents),
        ("stock_deficiency_cents", stock_deficiency_cents),
        ("excess_stock_cents", excess_stock_cents),
    ):
        if value is not ...:
            assert member[field] == value, f"{field}: expected {value}, got {member[field]}"
