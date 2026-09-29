"""Domain assertion helpers for the Club Demo Sampling API."""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# common fields (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Every audited entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), "created_at must be ISO-8601"
    assert is_iso8601_timestamp(entity["updated_at"]), "updated_at must be ISO-8601"
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_ledger_row_fields(entity: Dict[str, Any]) -> None:
    """An append-only ledger row carries only id and created_at, never version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), "created_at must be ISO-8601"
    assert "updated_at" not in entity, "an append-only ledger row has no updated_at"
    assert "version" not in entity, "an append-only ledger row has no version"


# ---------------------------------------------------------------------------
# money and decimal comparisons
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is an exact integer number of cents — never a float."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_decimal2(actual: Any, expected: float, label: str = "value") -> None:
    """A two-decimal quantity compared with cent-level tolerance."""
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# event dimensions (PRD 2.9)
# ---------------------------------------------------------------------------
def assert_event_dimensions(
    event: Dict[str, Any],
    booking_status: Optional[str] = None,
    staffing_status: Optional[str] = None,
    settlement_status: Optional[str] = None,
) -> None:
    if booking_status is not None:
        assert event["booking_status"] == booking_status, (
            f"booking_status: expected {booking_status}, got {event['booking_status']}"
        )
    if staffing_status is not None:
        assert event["staffing_status"] == staffing_status, (
            f"staffing_status: expected {staffing_status}, "
            f"got {event['staffing_status']}"
        )
    if settlement_status is not None:
        assert event["settlement_status"] == settlement_status, (
            f"settlement_status: expected {settlement_status}, "
            f"got {event['settlement_status']}"
        )


# ---------------------------------------------------------------------------
# invoice line items (PRD 3.9)
# ---------------------------------------------------------------------------
def line_amounts_by_type(invoice: Dict[str, Any], line_type: str) -> List[int]:
    return [
        line["amount_cents"]
        for line in invoice["line_items"]
        if line["line_type"] == line_type
    ]


def assert_line_type_order(invoice: Dict[str, Any]) -> None:
    """Lines are emitted BASE, then ADDON, then STAFFING, then HANDLING."""
    order = {"BASE": 0, "ADDON": 1, "STAFFING": 2, "HANDLING": 3}
    ranks = [order[line["line_type"]] for line in invoice["line_items"]]
    assert ranks == sorted(ranks), (
        f"line_items must follow BASE/ADDON/STAFFING/HANDLING order, got "
        f"{[line['line_type'] for line in invoice['line_items']]}"
    )


def assert_subtotal_is_sum_of_lines(invoice: Dict[str, Any]) -> None:
    """The subtotal is the plain integer sum of the already-rounded lines."""
    total = sum(line["amount_cents"] for line in invoice["line_items"])
    assert invoice["subtotal_cents"] == total, (
        f"subtotal_cents {invoice['subtotal_cents']} must equal the sum of the "
        f"rounded line items {total}"
    )


# ---------------------------------------------------------------------------
# list helpers
# ---------------------------------------------------------------------------
def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be ordered created_at ASC, got {stamps}"


def assert_created_at_descending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"rows must be ordered created_at DESC, got {stamps}"
    )


def find_row(rows: List[Dict[str, Any]], **match: Any) -> Dict[str, Any]:
    for row in rows:
        if all(row.get(key) == value for key, value in match.items()):
            return row
    raise AssertionError(f"no row matching {match} in {rows}")
