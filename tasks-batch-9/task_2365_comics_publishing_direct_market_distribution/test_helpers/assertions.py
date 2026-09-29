"""Domain assertion helpers for the Comics Direct Market Publishing API."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str) -> None:
    """Two ISO 8601 UTC instants name the same moment.

    Fractional-second formatting is not compared, only the instant itself.
    """
    assert actual is not None, f"expected instant {expected}, got null"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant {actual} is not {expected}"
    )


def assert_date_equals(actual: str, expected_date: str) -> None:
    """An instant falls on the given UTC calendar date (`YYYY-MM-DD`)."""
    assert actual is not None, f"expected a date of {expected_date}, got null"
    assert _parse_instant(actual).date().isoformat() == expected_date, (
        f"{actual} is not on {expected_date}"
    )


# ─── Record identity ──────────────────────────────────

def assert_versioned_record(record: dict, expected_version: int = None) -> None:
    """A record that carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), record["version"]
    assert record["version"] >= 1, record["version"]
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_immutable_record(record: dict) -> None:
    """A variant cover, release window or revenue event: no updated_at, no version."""
    assert is_valid_uuid(record["id"]), f"id is not a bare UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "immutable records must omit updated_at"
    assert "version" not in record, "immutable records must omit version"


def assert_version_advanced(before: dict, after: dict) -> None:
    """The row was mutated: its version strictly increased."""
    assert after["version"] > before["version"], (
        f"version did not advance: {before['version']} -> {after['version']}"
    )


def assert_version_unchanged(before: dict, after: dict) -> None:
    """The row was not mutated: its version is exactly where it was."""
    assert after["version"] == before["version"], (
        f"version moved unexpectedly: {before['version']} -> {after['version']}"
    )


# ─── Issue dimensions ─────────────────────────────────

def assert_issue_dimensions(
    issue: dict,
    production_status: str = None,
    commercial_status: str = None,
    schedule_health: str = None,
) -> None:
    """The issue's two independent status dimensions plus its derived posture."""
    if production_status is not None:
        assert issue["production_status"] == production_status, (
            f"production_status {issue['production_status']} != {production_status}"
        )
    if commercial_status is not None:
        assert issue["commercial_status"] == commercial_status, (
            f"commercial_status {issue['commercial_status']} != {commercial_status}"
        )
    if schedule_health is not None:
        assert issue["schedule_health"] == schedule_health, (
            f"schedule_health {issue['schedule_health']} != {schedule_health}"
        )


def assert_issue_unit_ledgers(
    issue: dict,
    total_ordered_units: int = None,
    printed_units: int = None,
    shipped_units: int = None,
) -> None:
    if total_ordered_units is not None:
        assert issue["total_ordered_units"] == total_ordered_units, (
            f"total_ordered_units {issue['total_ordered_units']} != {total_ordered_units}"
        )
    if printed_units is not None:
        assert issue["printed_units"] == printed_units, (
            f"printed_units {issue['printed_units']} != {printed_units}"
        )
    if shipped_units is not None:
        assert issue["shipped_units"] == shipped_units, (
            f"shipped_units {issue['shipped_units']} != {shipped_units}"
        )


# ─── Retailer ledgers ─────────────────────────────────

def assert_retailer_ledgers(
    retailer: dict,
    cumulative_units_ytd: int = None,
    open_balance_cents: int = None,
    discount_tier: str = None,
) -> None:
    if cumulative_units_ytd is not None:
        assert retailer["cumulative_units_ytd"] == cumulative_units_ytd, (
            f"cumulative_units_ytd {retailer['cumulative_units_ytd']} "
            f"!= {cumulative_units_ytd}"
        )
    if open_balance_cents is not None:
        assert retailer["open_balance_cents"] == open_balance_cents, (
            f"open_balance_cents {retailer['open_balance_cents']} != {open_balance_cents}"
        )
    if discount_tier is not None:
        assert retailer["discount_tier"] == discount_tier, (
            f"discount_tier {retailer['discount_tier']} != {discount_tier}"
        )


# ─── Orders ───────────────────────────────────────────

def assert_allocation_entries(order: dict, expected) -> None:
    """`earned_variant_allocations` matches, entry by entry, in stored order.

    `expected` is a sequence of (variant_cover_id, qty) pairs.
    """
    actual = [
        (entry["variant_cover_id"], entry["qty"])
        for entry in order["earned_variant_allocations"]
    ]
    assert actual == [tuple(pair) for pair in expected], (
        f"earned_variant_allocations {actual} != {list(expected)}"
    )


def assert_invoice_figures(
    order: dict,
    discount_tier_applied: str = None,
    merchandise_net_cents: int = None,
    handling_fee_cents: int = None,
    invoice_total_cents: int = None,
) -> None:
    if discount_tier_applied is not None:
        assert order["discount_tier_applied"] == discount_tier_applied, (
            f"discount_tier_applied {order['discount_tier_applied']} "
            f"!= {discount_tier_applied}"
        )
    if merchandise_net_cents is not None:
        assert order["merchandise_net_cents"] == merchandise_net_cents, (
            f"merchandise_net_cents {order['merchandise_net_cents']} "
            f"!= {merchandise_net_cents}"
        )
    if handling_fee_cents is not None:
        assert order["handling_fee_cents"] == handling_fee_cents, (
            f"handling_fee_cents {order['handling_fee_cents']} != {handling_fee_cents}"
        )
    if invoice_total_cents is not None:
        assert order["invoice_total_cents"] == invoice_total_cents, (
            f"invoice_total_cents {order['invoice_total_cents']} != {invoice_total_cents}"
        )


# ─── Print runs ───────────────────────────────────────

def assert_print_run_quantities(
    print_run: dict,
    order_base_units: int = None,
    overprint_units: int = None,
    quantity: int = None,
    printing_number: int = None,
) -> None:
    if order_base_units is not None:
        assert print_run["order_base_units"] == order_base_units, (
            f"order_base_units {print_run['order_base_units']} != {order_base_units}"
        )
    if overprint_units is not None:
        assert print_run["overprint_units"] == overprint_units, (
            f"overprint_units {print_run['overprint_units']} != {overprint_units}"
        )
    if quantity is not None:
        assert print_run["quantity"] == quantity, (
            f"quantity {print_run['quantity']} != {quantity}"
        )
    if printing_number is not None:
        assert print_run["printing_number"] == printing_number, (
            f"printing_number {print_run['printing_number']} != {printing_number}"
        )


# ─── Royalty statements ───────────────────────────────

def assert_statement_channels(statement: dict, expected_channels) -> None:
    """The statement's lines carry exactly these channels, in this order."""
    actual = [line["channel"] for line in statement["lines"]]
    assert actual == list(expected_channels), (
        f"statement line channels {actual} != {list(expected_channels)}"
    )


def statement_line(statement: dict, channel: str) -> dict:
    """The single line of `statement` for `channel`."""
    matches = [line for line in statement["lines"] if line["channel"] == channel]
    assert len(matches) == 1, (
        f"expected exactly one {channel} line, found {len(matches)}"
    )
    return matches[0]


def assert_statement_line(
    statement: dict,
    channel: str,
    included_net_cents: int = None,
    channel_pool_cents: int = None,
    creator_share_cents: int = None,
) -> None:
    line = statement_line(statement, channel)
    if included_net_cents is not None:
        assert line["included_net_cents"] == included_net_cents, (
            f"{channel} included_net_cents {line['included_net_cents']} "
            f"!= {included_net_cents}"
        )
    if channel_pool_cents is not None:
        assert line["channel_pool_cents"] == channel_pool_cents, (
            f"{channel} channel_pool_cents {line['channel_pool_cents']} "
            f"!= {channel_pool_cents}"
        )
    if creator_share_cents is not None:
        assert line["creator_share_cents"] == creator_share_cents, (
            f"{channel} creator_share_cents {line['creator_share_cents']} "
            f"!= {creator_share_cents}"
        )


def assert_statement_money(
    statement: dict,
    gross_royalty_cents: int = None,
    recoupment_applied_cents: int = None,
    payable_cents: int = None,
) -> None:
    if gross_royalty_cents is not None:
        assert statement["gross_royalty_cents"] == gross_royalty_cents, (
            f"gross_royalty_cents {statement['gross_royalty_cents']} "
            f"!= {gross_royalty_cents}"
        )
    if recoupment_applied_cents is not None:
        assert statement["recoupment_applied_cents"] == recoupment_applied_cents, (
            f"recoupment_applied_cents {statement['recoupment_applied_cents']} "
            f"!= {recoupment_applied_cents}"
        )
    if payable_cents is not None:
        assert statement["payable_cents"] == payable_cents, (
            f"payable_cents {statement['payable_cents']} != {payable_cents}"
        )


# ─── Listing helpers ──────────────────────────────────

def assert_ids_in_order(rows, expected_ids) -> None:
    """The listed rows carry exactly these ids, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"row ids {actual} != {list(expected_ids)}"


def assert_field_sequence(rows, field: str, expected) -> None:
    """The listed rows carry exactly these values of `field`, in this order."""
    actual = [row[field] for row in rows]
    assert actual == list(expected), f"{field} sequence {actual} != {list(expected)}"
