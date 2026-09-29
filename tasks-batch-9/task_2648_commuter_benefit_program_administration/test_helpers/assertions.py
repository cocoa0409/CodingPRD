"""Domain assertions for the commuter benefit service.

These encode the invariants the PRD states must hold after every mutation, so a
test can assert an outcome and its conservation identity in one line.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def as_instant(value: Any) -> datetime:
    """Parse a UTC ISO 8601 string into an aware datetime.

    The PRD pins the *instant* a field must carry, not its fractional-digit
    spelling, so every timestamp comparison goes through this parser rather than
    comparing raw strings.
    """
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant_equals(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 spellings name the same UTC instant."""
    assert actual is not None, f"{label} must be stamped, got None"
    assert as_instant(actual) == as_instant(expected), (
        f"{label} must be {expected}, got {actual!r}"
    )


# --------------------------------------------------------------- common fields
def assert_mutable_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert "_" not in str(row["id"]), "id must carry no type prefix"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_common_fields(row: Dict[str, Any]) -> None:
    """An append-only audit row carries only id and created_at."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "version" not in row, "append-only records must not carry version"
    assert "updated_at" not in row, "append-only records must not carry updated_at"


# ------------------------------------------------------- account conservation --
def assert_account_conservation(account: Dict[str, Any]) -> None:
    """available_balance_cents equals the seven-bucket identity."""
    expected = (
        account["rollover_in_cents"]
        + account["contributed_cents"]
        - account["spent_cents"]
        - account["forfeited_cents"]
        - account["refunded_cents"]
        - account["reversed_cents"]
        - account["fee_charged_cents"]
    )
    assert account["available_balance_cents"] == expected, (
        "available_balance_cents "
        f"{account['available_balance_cents']} != bucket identity {expected}"
    )


def assert_ledger_matches_account(
    account: Dict[str, Any], entries: List[Dict[str, Any]]
) -> None:
    """The signed ledger sum equals available_balance_cents and the running total
    stored on each row equals the prefix sum up to and including itself."""
    total = 0
    for index, entry in enumerate(entries):
        total += entry["amount_cents"]
        assert entry["balance_after_cents"] == total, (
            f"ledger row {index} balance_after_cents {entry['balance_after_cents']} "
            f"!= running total {total}"
        )
    assert account["available_balance_cents"] == total, (
        f"available_balance_cents {account['available_balance_cents']} "
        f"!= signed ledger sum {total}"
    )
    assert account["ledger_entry_count"] == len(entries), (
        f"ledger_entry_count {account['ledger_entry_count']} != {len(entries)} rows"
    )


def assert_ledger_sequence(
    entries: List[Dict[str, Any]], expected: List[tuple]
) -> None:
    """Assert the exact (entry_type, amount_cents, balance_after_cents) sequence."""
    actual = [
        (e["entry_type"], e["amount_cents"], e["balance_after_cents"]) for e in entries
    ]
    assert actual == expected, f"ledger sequence {actual} != expected {expected}"


def assert_entry_types(entries: List[Dict[str, Any]], expected: List[str]) -> None:
    actual = [e["entry_type"] for e in entries]
    assert actual == expected, f"entry_type sequence {actual} != {expected}"


# ------------------------------------------------------------ election helpers -
def assert_election_axes(
    election: Dict[str, Any], funding_status: str, fulfillment_status: str
) -> None:
    """The two Election state dimensions are asserted together, never singly."""
    assert election["funding_status"] == funding_status, (
        f"funding_status {election['funding_status']} != {funding_status}"
    )
    assert election["fulfillment_status"] == fulfillment_status, (
        f"fulfillment_status {election['fulfillment_status']} != {fulfillment_status}"
    )


def assert_exclusion_split(
    election: Dict[str, Any],
    excluded_amount_cents: int,
    posttax_spill_cents: int,
    total_amount_cents: int,
    exclusion_basis: Optional[str] = None,
) -> None:
    assert election["excluded_amount_cents"] == excluded_amount_cents
    assert election["posttax_spill_cents"] == posttax_spill_cents
    assert election["total_amount_cents"] == total_amount_cents
    if exclusion_basis is not None:
        assert election["exclusion_basis"] == exclusion_basis


# ------------------------------------------------------------- invoice helpers -
def assert_invoice_totals(
    batch: Dict[str, Any],
    line_count: int,
    subtotal_cents: int,
    discount_cents: int,
    total_cents: int,
) -> None:
    assert batch["line_count"] == line_count
    assert batch["subtotal_cents"] == subtotal_cents
    assert batch["discount_cents"] == discount_cents
    assert batch["total_cents"] == total_cents
    assert batch["total_cents"] == batch["subtotal_cents"] - batch["discount_cents"], (
        "total_cents must be subtotal_cents minus discount_cents"
    )


def assert_media_line(
    order: Dict[str, Any],
    line_gross_cents: int,
    line_surcharge_cents: int,
    line_total_cents: int,
) -> None:
    assert order["line_gross_cents"] == line_gross_cents
    assert order["line_surcharge_cents"] == line_surcharge_cents
    assert order["line_total_cents"] == line_total_cents
    assert order["line_total_cents"] == (
        order["line_gross_cents"] + order["line_surcharge_cents"]
    )


# ------------------------------------------------------------- misc predicates -
def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """No-write proof: the named fields plus version must be byte-identical."""
    for field in ("version",) + fields:
        if field in before or field in after:
            assert before.get(field) == after.get(field), (
                f"{field} changed from {before.get(field)!r} to {after.get(field)!r}"
            )


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, f"meta.limit {meta['limit']} != {limit}"
    assert meta["offset"] == offset, f"meta.offset {meta['offset']} != {offset}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count {meta['total_count']} != {total_count}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more {meta['has_more']} != {has_more}"
    )
