"""Domain assertion helpers for the Studio Production Pipeline suite.

These wrap the response-envelope validators supplied by the test framework with
studio-specific checks: the four common resource properties, the budget
position identity, the earned-value report shape, and the derived calibration
status.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    COLOR_SPACES,
    OVERHEAD_RATE_TIER_1,
    OVERHEAD_RATE_TIER_2,
    OVERHEAD_RATE_TIER_3,
    OVERHEAD_TIER_1_CEILING_CENTS,
    OVERHEAD_TIER_2_CEILING_CENTS,
)

JsonDict = Dict[str, Any]

MONEY_TOLERANCE = 0.01
INDEX_TOLERANCE = 0.0001


def assert_common_fields(entity: JsonDict, expected_version: Optional[int] = None) -> None:
    """Assert the four properties every resource carries."""
    assert "id" in entity, "resource is missing its id"
    assert isinstance(entity["id"], str) and entity["id"], "id must be a non-empty string"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO-8601 UTC timestamp: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO-8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert an integer-cents money field matches exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_two_decimal(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a two-decimal-place numeric field."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_decimal(actual: Any, expected: float, label: str = "index") -> None:
    """Assert a four-decimal-place performance index."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=INDEX_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def overhead_fee_for(direct_committed_cents: int) -> int:
    """Overhead fee for a direct commitment, applying the tiered rate."""
    if direct_committed_cents < OVERHEAD_TIER_1_CEILING_CENTS:
        rate = OVERHEAD_RATE_TIER_1
    elif direct_committed_cents < OVERHEAD_TIER_2_CEILING_CENTS:
        rate = OVERHEAD_RATE_TIER_2
    else:
        rate = OVERHEAD_RATE_TIER_3
    return round_half_up(direct_committed_cents * rate)


def round_half_up(value: float) -> int:
    """Round a non-negative amount half-up to a whole number of cents."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def assert_budget_position(
    production: JsonDict,
    expected_direct_cents: int,
    expected_overhead_cents: Optional[int] = None,
) -> None:
    """Assert the four-step budget position of a production hangs together."""
    assert_cents(
        production["direct_committed_cents"], expected_direct_cents, "direct_committed_cents"
    )
    overhead = (
        expected_overhead_cents
        if expected_overhead_cents is not None
        else overhead_fee_for(expected_direct_cents)
    )
    assert_cents(production["overhead_fee_cents"], overhead, "overhead_fee_cents")
    assert_cents(
        production["total_committed_cents"],
        expected_direct_cents + overhead,
        "total_committed_cents",
    )
    ceiling = round_half_up(
        production["budget_cents"] * (1 + production["contingency_pct"])
    )
    assert_cents(
        production["available_cents"],
        ceiling - production["total_committed_cents"],
        "available_cents",
    )


def assert_earned_value_report(
    report: JsonDict,
    expected_variant: str,
    bcws_cents: Optional[int] = None,
    bcwp_cents: Optional[int] = None,
    acwp_cents: Optional[int] = None,
    cpi: Optional[float] = "unset",
    spi: Optional[float] = "unset",
) -> None:
    """Assert the shape and values of an earned-value read."""
    for field in (
        "shot_id",
        "variant",
        "bcws_cents",
        "bcwp_cents",
        "acwp_cents",
        "cpi",
        "spi",
        "computed_at",
    ):
        assert field in report, f"earned-value report is missing {field}"
    assert report["variant"] == expected_variant, (
        f"expected variant {expected_variant}, got {report['variant']}"
    )
    if bcws_cents is not None:
        assert_cents(report["bcws_cents"], bcws_cents, "bcws_cents")
    if bcwp_cents is not None:
        assert_cents(report["bcwp_cents"], bcwp_cents, "bcwp_cents")
    if acwp_cents is not None:
        assert_cents(report["acwp_cents"], acwp_cents, "acwp_cents")
    if cpi != "unset":
        if cpi is None:
            assert report["cpi"] is None, f"expected cpi null, got {report['cpi']}"
        else:
            assert_four_decimal(report["cpi"], cpi, "cpi")
    if spi != "unset":
        if spi is None:
            assert report["spi"] is None, f"expected spi null, got {report['spi']}"
        else:
            assert_four_decimal(report["spi"], spi, "spi")
    assert is_iso8601_timestamp(report["computed_at"]), (
        f"computed_at is not an ISO-8601 UTC timestamp: {report['computed_at']!r}"
    )


def assert_color_space(value: Any, label: str = "color space") -> None:
    """Assert a color-space value is one of the four recognized identifiers."""
    assert value in COLOR_SPACES, (
        f"{label} must be one of {list(COLOR_SPACES)}, got {value!r}"
    )


def assert_version_label(label: Any, expected_index: int) -> None:
    """Assert a deliverable version label is zero-padded to at least two digits."""
    assert isinstance(label, str), f"version_label must be a string, got {label!r}"
    assert label.startswith("v"), f"version_label must start with v, got {label!r}"
    digits = label[1:]
    assert digits.isdigit(), f"version_label must carry digits after v, got {label!r}"
    assert len(digits) >= 2, f"version_label must be padded to two digits, got {label!r}"
    assert int(digits) == expected_index, (
        f"version_label {label!r} does not encode version index {expected_index}"
    )


def assert_list_total(response, expected_total: int, label: str = "collection") -> List[JsonDict]:
    """Assert a paginated collection reports the expected total_count."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"{label}: expected total_count {expected_total}, got {meta['total_count']}"
    )
    return rows


def assert_codes_in_order(rows: List[JsonDict], field: str, expected: List[Any]) -> None:
    """Assert a projection of a collection matches an expected ordered sequence."""
    actual = [row[field] for row in rows]
    assert actual == expected, f"expected {field} order {expected}, got {actual}"


def assert_unchanged(before: JsonDict, after: JsonDict, fields: List[str]) -> None:
    """Assert the named fields are byte-identical across a rejected mutation."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r} "
            "across a rejected request"
        )


def parse_instant(value: str):
    """Parse an ISO-8601 UTC timestamp into a comparable datetime."""
    from datetime import datetime, timezone

    assert isinstance(value, str), f"expected an ISO-8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected_iso: str, label: str = "timestamp") -> None:
    """Assert a written timestamp denotes the expected instant."""
    assert actual is not None, f"{label} must not be null"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )
