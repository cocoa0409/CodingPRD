"""Domain assertions and pure arithmetic mirrors of the contract's rules."""

import math
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    GOP_ACHIEVEMENT_DECIMALS,
    RPI_DECIMALS,
    VARIANCE_PCT_DECIMALS,
)

# ---------------------------------------------------------------------------
# Rounding mirrors
# ---------------------------------------------------------------------------


def round_half_up(value: float) -> int:
    """Take the absolute value, add one half, discard the fraction, re-apply the sign."""
    sign = -1 if value < 0 else 1
    return sign * int(abs(value) + 0.5)


def floor_cents(value: float) -> int:
    """Discard the fractional part outright, so the result never exceeds the input."""
    return math.floor(value)


def base_fee_per_line(rate: float, *revenue_lines: int) -> int:
    """Round half up per revenue line, then sum: n roundings, one addition."""
    return sum(round_half_up(line * rate) for line in revenue_lines)


def base_fee_on_total(rate: float, revenue_total: int) -> int:
    """Round half up once, on the revenue total."""
    return round_half_up(revenue_total * rate)


def period_centralized_cap(gross_revenue_cents: int, cap_pct: float) -> int:
    """Caps are always floored, so the cap can never be generous by a cent."""
    return floor_cents(gross_revenue_cents * cap_pct)


def monthly_priority_twelfth(owner_priority_cents: int) -> int:
    return round_half_up(owner_priority_cents / 12)


# ---------------------------------------------------------------------------
# Envelope assertions
# ---------------------------------------------------------------------------


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """Every response carries a correlation id and a UTC timestamp in ``meta``."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta["api_request_timestamp"]


def assert_error_envelope(response, expected_error_id: str) -> Dict[str, Any]:
    """Assert the error id, its declared status code, and the error envelope shape."""
    body = response.json()
    assert body["response_type"] == "error", body
    assert_meta_envelope(body)
    return validate_error(response, expected_error_id)


def assert_object_envelope(response, expected_status: int = 200) -> Dict[str, Any]:
    body = response.json()
    assert body["response_type"] == "object", body
    assert_meta_envelope(body)
    return validate_success(response, expected_status)


def assert_array_envelope(response) -> tuple:
    body = response.json()
    assert body["response_type"] == "array", body
    assert_meta_envelope(body)
    return validate_paginated(response)


def assert_page(response, expected_rows: int, total_count: int, has_more: bool) -> List[Dict[str, Any]]:
    """One page of a list: row count, the pre-paging total and the has_more flag."""
    rows, meta = validate_paginated(response)
    assert len(rows) == expected_rows, rows
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta
    return rows


def assert_null_data(response) -> None:
    assert response.json()["data"] is None, response.json()


# ---------------------------------------------------------------------------
# Entity shape assertions
# ---------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any]) -> None:
    """Server-minted id, both timestamps and an integer optimistic version."""
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int)
    assert row["version"] >= 1


def assert_append_only_row(row: Dict[str, Any]) -> None:
    """An append-only row carries only ``id`` and ``created_at``: no updated_at, no version."""
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, row
    assert "version" not in row, row


def assert_untyped_uuid(value: str) -> None:
    """Ids are server-minted UUIDs with no type prefix and no embedded meaning."""
    assert is_valid_uuid(value), value


def assert_created_at_ascending(rows: Iterable[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), stamps


def assert_decimal_places(value: float, places: int) -> None:
    """The value is pinned to exactly this many decimal places."""
    quantised = round(value, places)
    assert value == quantised, f"{value} is not pinned to {places} decimal places"


def assert_variance_pct(value: float, expected: float) -> None:
    assert_decimal_places(value, VARIANCE_PCT_DECIMALS)
    assert value == expected, f"{value} != {expected}"


def assert_rpi(value: float, expected: float) -> None:
    assert_decimal_places(value, RPI_DECIMALS)
    assert value == expected, f"{value} != {expected}"


def assert_gop_achievement(value: float, expected: float) -> None:
    assert_decimal_places(value, GOP_ACHIEVEMENT_DECIMALS)
    assert value == expected, f"{value} != {expected}"


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def rows_where(rows: Iterable[Dict[str, Any]], **criteria: Any) -> List[Dict[str, Any]]:
    return [row for row in rows if all(row.get(k) == v for k, v in criteria.items())]


def one_row(rows: Iterable[Dict[str, Any]], **criteria: Any) -> Dict[str, Any]:
    matches = rows_where(rows, **criteria)
    assert len(matches) == 1, f"expected exactly one row matching {criteria}, got {matches}"
    return matches[0]


def no_rows(rows: Iterable[Dict[str, Any]], **criteria: Any) -> None:
    matches = rows_where(rows, **criteria)
    assert matches == [], f"expected no row matching {criteria}, got {matches}"


def find_accrual(
    rows: Iterable[Dict[str, Any]],
    fee_type: str,
    variant: Optional[str] = None,
) -> Dict[str, Any]:
    criteria: Dict[str, Any] = {"fee_type": fee_type}
    if variant is not None:
        criteria["variant"] = variant
    return one_row(rows, **criteria)


def assert_ledger_entry(
    entry: Dict[str, Any],
    entry_type: str,
    amount_cents: int,
    balance_after_cents: int,
    source_kind: str,
) -> None:
    assert entry["entry_type"] == entry_type, entry
    assert entry["amount_cents"] == amount_cents, entry
    assert entry["balance_after_cents"] == balance_after_cents, entry
    assert entry["source_kind"] == source_kind, entry
    assert_append_only_row(entry)


def assert_waterfall(
    distribution: Dict[str, Any],
    available_cash_cents: int,
    wc_restoration_cents: int,
    base_fee_paid_cents: int,
    reserve_contribution_cents: int,
    owner_priority_paid_cents: int,
    incentive_fee_paid_cents: int,
    residual_to_owner_cents: int,
    shortfall_cents: int,
) -> None:
    """Pin all six buckets, the cash snapshot and the residual shortfall at once."""
    assert distribution["available_cash_cents"] == available_cash_cents, distribution
    assert distribution["wc_restoration_cents"] == wc_restoration_cents, distribution
    assert distribution["base_fee_paid_cents"] == base_fee_paid_cents, distribution
    assert distribution["reserve_contribution_cents"] == reserve_contribution_cents, distribution
    assert distribution["owner_priority_paid_cents"] == owner_priority_paid_cents, distribution
    assert distribution["incentive_fee_paid_cents"] == incentive_fee_paid_cents, distribution
    assert distribution["residual_to_owner_cents"] == residual_to_owner_cents, distribution
    assert distribution["shortfall_cents"] == shortfall_cents, distribution


__all__ = [
    "assert_append_only_row",
    "assert_array_envelope",
    "assert_common_fields",
    "assert_created_at_ascending",
    "assert_decimal_places",
    "assert_error_envelope",
    "assert_gop_achievement",
    "assert_ledger_entry",
    "assert_meta_envelope",
    "assert_null_data",
    "assert_object_envelope",
    "assert_page",
    "assert_rpi",
    "assert_untyped_uuid",
    "assert_variance_pct",
    "assert_waterfall",
    "base_fee_on_total",
    "base_fee_per_line",
    "find_accrual",
    "floor_cents",
    "monthly_priority_twelfth",
    "no_rows",
    "one_row",
    "period_centralized_cap",
    "round_half_up",
    "rows_where",
]
