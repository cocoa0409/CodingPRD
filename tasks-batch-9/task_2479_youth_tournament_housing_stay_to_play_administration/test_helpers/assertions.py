"""Domain assertion helpers for repeated structural checks.

These wrap only the checks that are stated once in the PRD and then hold
everywhere: the two common-field shapes of §2.4 and the two conservation
invariants of §2.12. Behaviour-specific expectations stay in the tests.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Record = Dict[str, Any]


def assert_versioned_record(
    record: Record, expected_version: Optional[int] = None
) -> None:
    """Assert the full common-field set of PRD §2.4.

    PRD §2.4: "The resources that carry the full set of `id`, `created_at`,
    `updated_at` and `version` are: `Tournament`, `Hotel`, `HotelContract`,
    `RoomBlock`, `Team`, `TeamRegistration`, `Booking`, `ExceptionRequest`,
    `Complaint`, `RebateInvoice` and `RevenueDistribution`."
    """
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int), record["version"]
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_append_only_record(record: Record) -> None:
    """Assert the narrow common-field set of PRD §2.4.

    PRD §2.4: "Two resources are append-only records of a moment rather than
    mutable rows, and they carry only `id` and `created_at`."
    """
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only record must not carry updated_at"
    assert "version" not in record, "append-only record must not carry version"


def assert_rebate_ledger_conserved(invoice: Record) -> None:
    """Assert the rebate ledger invariant of PRD §2.12.

    PRD §2.12: "On every rebate invoice, `collected_cents`,
    `written_off_cents` and `outstanding_cents` sum to exactly
    `total_due_cents`, and none of the three is ever negative."
    """
    total = (
        invoice["collected_cents"]
        + invoice["written_off_cents"]
        + invoice["outstanding_cents"]
    )
    assert total == invoice["total_due_cents"], (
        "rebate ledger does not conserve: "
        f"collected {invoice['collected_cents']} + written_off "
        f"{invoice['written_off_cents']} + outstanding "
        f"{invoice['outstanding_cents']} != total_due {invoice['total_due_cents']}"
    )
    for field in ("collected_cents", "written_off_cents", "outstanding_cents"):
        assert invoice[field] >= 0, f"{field} is negative: {invoice[field]}"


def assert_block_inventory_conserved(block: Record) -> None:
    """Assert the room-inventory invariant of PRD §2.12, in the right phase.

    PRD §2.12: "While a room block's `status` is `OPEN` or `RESTRICTED`, its
    `rooms_committed` and `rooms_available` sum to exactly `block_size_rooms`,
    and its `rooms_released_unsold` is 0."

    PRD §2.12: "Once the block's `status` is `RELEASED` or `SETTLED`, its
    `rooms_committed` and `rooms_released_unsold` sum to exactly
    `block_size_rooms`, and its `rooms_available` is 0."
    """
    size = block["block_size_rooms"]
    committed = block["rooms_committed"]
    available = block["rooms_available"]
    released = block["rooms_released_unsold"]
    if block["status"] in ("OPEN", "RESTRICTED"):
        assert committed + available == size, (
            f"live block: committed {committed} + available {available} != "
            f"block_size {size}"
        )
        assert released == 0, f"live block has rooms_released_unsold {released}"
    else:
        assert committed + released == size, (
            f"closed block: committed {committed} + released_unsold {released} != "
            f"block_size {size}"
        )
        assert available == 0, f"closed block has rooms_available {available}"
