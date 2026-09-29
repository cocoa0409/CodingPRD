"""Domain assertion helpers built on the framework validators.

Every helper here restates a rule the PRD states in prose, so that a test can
say what it means once instead of repeating a field-by-field comparison. The
generic envelope/pagination/error validators come from the framework and are
re-exported so a test file needs only one import site.
"""
import math
from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import (  # noqa: F401  (re-exported)
    NON_EXISTENT_UUID,
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

MONEY_FIELDS_SUFFIX = "_cents"


# --------------------------------------------------------------------------
# Envelope and identifier conventions
# --------------------------------------------------------------------------
def assert_identifier_conventions(entity: Dict[str, Any]) -> None:
    """`id` is a bare UUID and `created_at` an ISO 8601 UTC timestamp."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not ISO 8601: {entity['created_at']}"


def assert_three_fractional_digits(timestamp: str) -> None:
    """Timestamps carry exactly three fractional-second digits."""
    assert "." in timestamp, f"timestamp has no fractional part: {timestamp}"
    digits = timestamp.split(".", 1)[1]
    # Take the digit run immediately after the decimal point.
    run = ""
    for char in digits:
        if char.isdigit():
            run += char
        else:
            break
    assert len(run) == 3, (
        f"expected exactly three fractional digits, got {len(run)} in {timestamp}"
    )


def assert_version_starts_at_one(entity: Dict[str, Any]) -> None:
    """A freshly created record carries version 1."""
    assert entity["version"] == 1, f"expected version 1, got {entity['version']}"


def assert_no_version_surface(entity: Dict[str, Any]) -> None:
    """Immutable rows carry `id` and `created_at` but no update surface.

    Ownership periods, contaminant samples and work windows are recorded once
    and never modified, so they expose neither `updated_at` nor `version`.
    """
    assert "version" not in entity, "immutable row unexpectedly exposes version"
    assert "updated_at" not in entity, (
        "immutable row unexpectedly exposes updated_at"
    )
    assert_identifier_conventions(entity)


# --------------------------------------------------------------------------
# Money and rounding
# --------------------------------------------------------------------------
def assert_integer_cents(value: Any, field: str = "amount") -> None:
    """Monetary fields are integer counts of cents, never decimals or strings."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r}"
    )


def assert_money_fields_are_integers(entity: Dict[str, Any]) -> None:
    """Every `*_cents` field on a body is an integer."""
    for key, value in entity.items():
        if key.endswith(MONEY_FIELDS_SUFFIX) and value is not None:
            assert_integer_cents(value, key)


def round_half_up(value: float, places: int = 0) -> float:
    """Round half away from zero, the rounding mode the PRD mandates."""
    factor = 10 ** places
    scaled = value * factor
    if scaled >= 0:
        rounded = math.floor(scaled + 0.5)
    else:
        rounded = math.ceil(scaled - 0.5)
    result = rounded / factor
    return result if places > 0 else float(result)


def assert_percentage(value: Any, expected: float, field: str = "pct") -> None:
    """A percentage is reported to two decimal places."""
    assert value == pytest.approx(expected, abs=0.01), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_seven_decimal_risk(value: Any, expected: float, field: str = "risk") -> None:
    """Risk estimates are carried to seven decimal places."""
    assert value == pytest.approx(expected, abs=0.00000005), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_epc(value: Any, expected: float, field: str = "epc") -> None:
    """Exposure point concentrations are carried to three decimal places."""
    assert value == pytest.approx(expected, abs=0.0005), (
        f"{field}: expected {expected}, got {value}"
    )


# --------------------------------------------------------------------------
# Site derived state
# --------------------------------------------------------------------------
def assert_cost_posture(site: Dict[str, Any], expected: str) -> None:
    """`cost_posture` is derived, never supplied."""
    assert site["cost_posture"] == expected, (
        f"expected cost_posture {expected}, got {site['cost_posture']}"
    )


def assert_listing_status(site: Dict[str, Any], expected: str) -> None:
    assert site["listing_status"] == expected, (
        f"expected listing_status {expected}, got {site['listing_status']}"
    )


def assert_ledger_identity(ledger: Dict[str, Any]) -> None:
    """recovered + orphan write-off + unrecovered equals the total response cost."""
    total = ledger["total_response_cost_cents"]
    parts = (
        ledger["recovered_cost_cents"]
        + ledger["orphan_write_off_cents"]
        + ledger["unrecovered_cost_cents"]
    )
    assert parts == total, (
        "ledger identity broken: "
        f"{ledger['recovered_cost_cents']} + {ledger['orphan_write_off_cents']} + "
        f"{ledger['unrecovered_cost_cents']} != {total}"
    )
    assert ledger["ledger_balanced"] is True, "ledger_balanced should be true"


def assert_ledger_figures(
    ledger: Dict[str, Any],
    total: int,
    recovered: int,
    orphan: int,
    unrecovered: int,
) -> None:
    """Pin the four headline ledger figures and the identity between them."""
    assert ledger["total_response_cost_cents"] == total
    assert ledger["recovered_cost_cents"] == recovered
    assert ledger["orphan_write_off_cents"] == orphan
    assert ledger["unrecovered_cost_cents"] == unrecovered
    assert_ledger_identity(ledger)


def assert_share_identity(round_body: Dict[str, Any]) -> None:
    """allocated + orphan + settled share totals sum to exactly 100.00."""
    total = (
        round_body["allocated_share_total_pct"]
        + round_body["orphan_share_pct"]
        + round_body["settled_share_pct"]
    )
    assert total == pytest.approx(100.00, abs=0.005), (
        "share identity broken: "
        f"{round_body['allocated_share_total_pct']} + {round_body['orphan_share_pct']} + "
        f"{round_body['settled_share_pct']} = {total}, expected 100.00"
    )


def assert_share_totals(
    round_body: Dict[str, Any], allocated: float, orphan: float, settled: float
) -> None:
    assert_percentage(
        round_body["allocated_share_total_pct"], allocated, "allocated_share_total_pct"
    )
    assert_percentage(round_body["orphan_share_pct"], orphan, "orphan_share_pct")
    assert_percentage(round_body["settled_share_pct"], settled, "settled_share_pct")
    assert_share_identity(round_body)


def assert_percentages_sum_to_100(values: Iterable[float]) -> None:
    """A complete set of provisional or final percentages sums to 100.00."""
    total = sum(values)
    assert total == pytest.approx(100.00, abs=0.005), (
        f"percentages sum to {total}, expected 100.00"
    )


# --------------------------------------------------------------------------
# Oversight fee tiers
# --------------------------------------------------------------------------
def expected_indirect_rate_bp(direct_subtotal_cents: int) -> int:
    """The tier is keyed on the pre-fee direct subtotal, ceilings inclusive."""
    if direct_subtotal_cents <= 5_000_000:
        return 1550
    if direct_subtotal_cents <= 25_000_000:
        return 1275
    return 1050


def assert_oversight_figures(
    site: Dict[str, Any],
    direct: int,
    rate_bp: int,
    indirect: int,
    billed: int,
) -> None:
    """The whole direct subtotal is re-rated at the tier each posting."""
    assert site["oversight_direct_cents"] == direct
    assert site["oversight_indirect_rate_bp"] == rate_bp
    assert site["oversight_indirect_cents"] == indirect
    assert site["oversight_billed_cents"] == billed
    assert direct + indirect == billed, "billed must equal direct plus indirect"


# --------------------------------------------------------------------------
# Ordering and listings
# --------------------------------------------------------------------------
def assert_ordered_by(
    rows: List[Dict[str, Any]], field: str, descending: bool = False
) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'DESC' if descending else 'ASC'}: {values}"
    )


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected order {expected_ids}, got {actual}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def assert_days_between(actual: int, expected: int, label: str = "days") -> None:
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
