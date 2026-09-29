"""Domain assertion helpers.

These wrap the framework's generic assertions with the PRD's own rules about
which fields a resource carries, so a shape check is written once. Money is
compared exactly because every monetary field is an integer count of cents;
percentages are compared with a two-decimal tolerance.
"""

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
JOURNAL_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(row: dict) -> None:
    """PRD 2.4: a versioned resource carries id, created_at, updated_at, version."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in row, f"Missing common field {field!r}: {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1, row["version"]


def assert_journal_fields(row: dict) -> None:
    """PRD 2.4: a StationLog and a QuoteLine carry only id and created_at."""
    for field in JOURNAL_COMMON_FIELDS:
        assert field in row, f"Missing journal field {field!r}: {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "An immutable journal row must not carry updated_at"
    assert "version" not in row, "An immutable journal row must not carry version"


def assert_fields_present(row: dict, field_names) -> None:
    missing = [name for name in field_names if name not in row]
    assert not missing, f"Missing fields {missing}: got {sorted(row)}"


def assert_pct(actual, expected) -> None:
    """Percentages carry exactly two decimal places (PRD 2.6)."""
    assert float(actual) == pytest.approx(float(expected), abs=0.01), (
        f"Expected percentage {expected}, got {actual}"
    )


def assert_cents(actual, expected) -> None:
    """Money is an integer count of cents, so the comparison is exact."""
    assert isinstance(actual, int), f"Money must be an integer, got {actual!r}"
    assert actual == expected, f"Expected {expected} cents, got {actual}"


def assert_money_identity(quote: dict) -> None:
    """PRD 3.8: total_cents == line_subtotal_cents - discount_cents + freight_cents."""
    expected = (
        quote["line_subtotal_cents"] - quote["discount_cents"] + quote["freight_cents"]
    )
    assert quote["total_cents"] == expected, (
        f"Money identity broken: {quote['line_subtotal_cents']} - "
        f"{quote['discount_cents']} + {quote['freight_cents']} != {quote['total_cents']}"
    )


def assert_unit_conservation(part: dict, expected_total: int) -> None:
    """PRD 3.9: on_hand_qty + reserved_qty is conserved by approve and by void."""
    total = part["on_hand_qty"] + part["reserved_qty"]
    assert total == expected_total, (
        f"Unit conservation broken: on_hand {part['on_hand_qty']} + reserved "
        f"{part['reserved_qty']} == {total}, expected {expected_total}"
    )


def assert_stock_state(part: dict) -> None:
    """PRD 3.9: BACKORDERED at zero, LOW up to and including the reorder point."""
    on_hand = part["on_hand_qty"]
    reorder = part["reorder_point_qty"]
    if on_hand == 0:
        expected = "BACKORDERED"
    elif on_hand <= reorder:
        expected = "LOW"
    else:
        expected = "IN_STOCK"
    assert part["stock_state"] == expected, (
        f"on_hand {on_hand} against reorder point {reorder} should project "
        f"{expected}, got {part['stock_state']}"
    )


def assert_build_state(build: dict, expected: str) -> None:
    assert build["build_state"] == expected, (
        f"Expected build_state {expected}, got {build['build_state']}"
    )


def assert_claim_state(claim: dict, expected: str) -> None:
    assert claim["claim_state"] == expected, (
        f"Expected claim_state {expected}, got {claim['claim_state']}"
    )


def assert_quote_state(quote: dict, expected: str) -> None:
    assert quote["quote_state"] == expected, (
        f"Expected quote_state {expected}, got {quote['quote_state']}"
    )


def assert_ids_in_order(rows: list, expected_ids: list) -> None:
    """Assert a listing returned exactly these ids in exactly this order."""
    assert [row["id"] for row in rows] == expected_ids, (
        f"Expected order {expected_ids}, got {[row['id'] for row in rows]}"
    )


def assert_values_in_order(rows: list, field: str, expected: list) -> None:
    assert [row[field] for row in rows] == expected, (
        f"Expected {field} order {expected}, got {[row[field] for row in rows]}"
    )
