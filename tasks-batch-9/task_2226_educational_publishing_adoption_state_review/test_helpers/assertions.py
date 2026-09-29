"""Domain assertions for the adoption-review contract.

The helpers here express the invariants the PRD states in prose: the print-unit
ledger identity, the signature page budget identity, the two-decimal percentage
convention, the four-decimal recommendation ratio, and the difference between a
mutable record and an append-only one.
"""

from decimal import Decimal
from typing import Any, Mapping, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BASE_IDENTITY_FIELDS, MUTABLE_RECORD_FIELDS


# ---------------------------------------------------------------------------
# Numeric conventions
# ---------------------------------------------------------------------------


def as_decimal(value: Any) -> Decimal:
    """Read a JSON number or numeric string as an exact decimal."""
    assert value is not None, "Expected a numeric value, got null"
    return Decimal(str(value))


def assert_decimal_equals(actual: Any, expected: str, label: str = "value") -> None:
    """Assert a decimal-valued field equals the expected value exactly."""
    assert as_decimal(actual) == Decimal(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_percentage_scale(value: Any, label: str = "percentage") -> None:
    """Assert a percentage carries at most two decimal places and sits in 0..100."""
    amount = as_decimal(value)
    assert Decimal("0") <= amount <= Decimal("100"), (
        f"{label} out of range: {value!r}"
    )
    assert -amount.as_tuple().exponent <= 2, (
        f"{label} carries more than two decimal places: {value!r}"
    )


def assert_ratio_scale(value: Any, label: str = "recommend_ratio") -> None:
    """Assert a recommendation ratio carries at most four decimal places."""
    amount = as_decimal(value)
    assert Decimal("0") <= amount <= Decimal("1"), f"{label} out of range: {value!r}"
    assert -amount.as_tuple().exponent <= 4, (
        f"{label} carries more than four decimal places: {value!r}"
    )


def assert_whole_cents(value: Any, label: str = "amount") -> None:
    """Assert a monetary field is an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


def assert_mutable_record(data: Mapping[str, Any]) -> None:
    """Assert the resource carries an identifier, both timestamps and a version."""
    for field in BASE_IDENTITY_FIELDS + MUTABLE_RECORD_FIELDS:
        assert field in data, f"Missing '{field}' on a mutable resource"
    assert is_valid_uuid(data["id"]), f"'id' is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"'created_at' is not an ISO 8601 UTC timestamp: {data['created_at']!r}"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"'updated_at' is not an ISO 8601 UTC timestamp: {data['updated_at']!r}"
    )
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"'version' must be a positive integer, got {data['version']!r}"
    )


def assert_append_only_record(data: Mapping[str, Any]) -> None:
    """Assert the resource carries only an identifier and a creation timestamp."""
    for field in BASE_IDENTITY_FIELDS:
        assert field in data, f"Missing '{field}' on an append-only resource"
    assert is_valid_uuid(data["id"]), f"'id' is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"'created_at' is not an ISO 8601 UTC timestamp: {data['created_at']!r}"
    )
    for field in MUTABLE_RECORD_FIELDS:
        assert field not in data, (
            f"An append-only resource must not expose '{field}'"
        )


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------


def assert_print_unit_ledger_balances(title: Mapping[str, Any]) -> None:
    """Assert received units equal the sum of the five destination buckets."""
    buckets = (
        "on_hand_units",
        "committed_units",
        "sample_reserved_units",
        "fulfilled_units",
        "written_off_units",
    )
    total = sum(title[bucket] for bucket in buckets)
    assert total == title["total_received_units"], (
        "Print-unit ledger broken: "
        + " + ".join(f"{bucket}={title[bucket]}" for bucket in buckets)
        + f" = {total}, but total_received_units={title['total_received_units']}"
    )


def assert_page_budget_conserved(title: Mapping[str, Any]) -> None:
    """Assert page count plus remaining budget equals the signature capacity."""
    total = title["page_count"] + title["page_budget_remaining"]
    assert total == title["signature_page_capacity"], (
        f"Signature page budget broken: page_count={title['page_count']} + "
        f"page_budget_remaining={title['page_budget_remaining']} = {total}, "
        f"but signature_page_capacity={title['signature_page_capacity']}"
    )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def assert_same_members(actual: Sequence[Any], expected: Sequence[Any], label: str) -> None:
    """Assert two collections hold exactly the same members, order aside."""
    assert sorted(actual) == sorted(expected), (
        f"{label}: expected {sorted(expected)}, got {sorted(actual)}"
    )


def assert_ascending_by_created_at(records: Sequence[Mapping[str, Any]]) -> None:
    """Assert a listing is ordered by creation time, oldest first."""
    stamps = [record["created_at"] for record in records]
    assert stamps == sorted(stamps), f"Listing is not oldest-first: {stamps}"
