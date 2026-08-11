"""Entity assertions, timestamp comparison and domain invariant checkers."""

from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import round_half_up

# ---------------------------------------------------------------------------
# Timestamps: always compared as instants, never as strings.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating Z / +00:00 and any fraction."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp"):
    """Compare two timestamps semantically rather than as raw strings."""
    assert actual is not None, f"{label} is missing"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_instant_close(actual, expected, label: str = "timestamp", tolerance_s=0.0):
    got = parse_instant(actual)
    want = parse_instant(expected)
    delta = abs((got - want).total_seconds())
    assert delta <= tolerance_s, (
        f"{label}: expected within {tolerance_s}s of {expected}, got {actual}"
    )


def assert_millisecond_timestamp(value, label: str = "timestamp"):
    """Timestamps are rendered in ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


def assert_money(actual, expected, label: str = "amount"):
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_hours(actual, expected, label: str = "hours"):
    assert actual is not None, f"{label} is missing"
    assert round_half_up(actual, 2) == round_half_up(expected, 2), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_dp(actual, expected, label: str = "value"):
    assert actual is not None, f"{label} is missing"
    assert round_half_up(actual, 2) == round_half_up(expected, 2), (
        f"{label}: expected {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, entity: str = "resource"):
    """id + created_at + updated_at + version, the shape almost every resource has."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID string"
    assert "_" not in str(data.get("id", "")), f"{entity}.id must carry no type prefix"
    assert_millisecond_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_millisecond_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity: str = "ledger line"):
    """A posted ledger line carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID string"
    assert_millisecond_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert "version" not in data, f"{entity} must not carry a version field"
    assert "updated_at" not in data, f"{entity} must not carry an updated_at field"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_client(data: dict):
    assert_common_fields(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["engagement_count"], int)


def assert_engagement(data: dict):
    assert_common_fields(data, "Engagement")
    assert data["status"] in ("ACTIVE", "ON_HOLD", "CLOSED", "CANCELLED")
    assert data["phase"] in (
        "ASSESSMENT",
        "SORT_PLAN",
        "PACK",
        "MOVE_DAY",
        "SETTLE_IN",
        "CLOSE_OUT",
        "DONE",
    )
    assert data["billing_mode"] in ("HOURLY", "PACKAGE")
    assert data["home_tier"] in ("STUDIO", "ONE_BED", "TWO_BED", "HOUSE")
    assert_millisecond_timestamp(
        data.get("move_freeze_at_utc"), "Engagement.move_freeze_at_utc"
    )


def assert_inventory_item(data: dict):
    assert_common_fields(data, "InventoryItem")
    assert data["disposition"] in ("UNDECIDED", "KEEP", "DONATE", "SELL", "HAUL_AWAY")
    assert data["handling_state"] in (
        "AT_ORIGIN",
        "PACKED",
        "LOADED",
        "DELIVERED",
        "UNPACKED",
        "STAGED_FOR_PICKUP",
        "REMOVED",
    )
    assert data["hold_state"] in ("NONE", "HELD")
    assert isinstance(data["disposition_locked"], bool)


def assert_destination_room(data: dict):
    assert_common_fields(data, "DestinationRoom")
    assert data["room_type"] in (
        "LIVING",
        "BEDROOM",
        "KITCHEN",
        "DINING",
        "STORAGE",
        "BATH",
    )


def assert_invoice(data: dict):
    assert_common_fields(data, "Invoice")
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "FINALIZED")


def assert_move_day_plan(data: dict):
    assert_common_fields(data, "MoveDayPlan")
    assert data["status"] in (
        "DRAFT",
        "CREWED",
        "CONFIRMED",
        "FROZEN",
        "IN_PROGRESS",
        "COMPLETED",
        "RESCHEDULED",
    )


def assert_vendor_assignment(data: dict):
    assert_common_fields(data, "VendorAssignment")
    assert data["status"] in (
        "REQUESTED",
        "ACCEPTED",
        "SCHEDULED",
        "COI_BLOCKED",
        "PERFORMED",
        "SIGNED_OFF",
        "PAID",
        "CANCELLED",
    )


def assert_consignment_lot(data: dict):
    assert_common_fields(data, "ConsignmentLot")
    assert data["status"] in (
        "LISTED",
        "MARKED_DOWN",
        "SOLD",
        "SETTLED",
        "UNSOLD",
        "RETURNED",
        "HAULED",
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_vendor_payout_conservation(assignment: dict):
    """paid_cents plus the outstanding holdback always equals quoted_cents."""
    outstanding = 0 if assignment["holdback_released"] else assignment["holdback_cents"]
    assert assignment["paid_cents"] + outstanding == assignment["quoted_cents"], (
        "vendor payout conservation: paid_cents "
        f"{assignment['paid_cents']} + outstanding holdback {outstanding} "
        f"!= quoted_cents {assignment['quoted_cents']}"
    )


def assert_inventory_volume_conservation(engagement: dict, expected_total):
    assert_two_dp(
        engagement["total_inventory_volume_cft"],
        expected_total,
        "Engagement.total_inventory_volume_cft",
    )
    assert (
        engagement["keep_volume_cft"] + engagement["haul_volume_cft"]
        <= engagement["total_inventory_volume_cft"] + 1e-9
    ), "keep_volume_cft + haul_volume_cft must not exceed total_inventory_volume_cft"


def assert_credits_match_lines(invoice: dict, lines: list):
    """credits_cents is the sum over CONSIGNMENT_CREDIT and CONSIGNMENT_REVERSAL lines."""
    expected = sum(
        line["amount_cents"]
        for line in lines
        if line["line_type"] in ("CONSIGNMENT_CREDIT", "CONSIGNMENT_REVERSAL")
    )
    assert invoice["credits_cents"] == expected, (
        f"Invoice.credits_cents {invoice['credits_cents']} != sum of consignment "
        f"lines {expected}"
    )


def assert_subtotal_excludes_fee_and_credits(invoice: dict, lines: list):
    expected = sum(
        line["amount_cents"]
        for line in lines
        if line["line_type"]
        not in ("COORDINATION_FEE", "CONSIGNMENT_CREDIT", "CONSIGNMENT_REVERSAL")
    )
    assert invoice["subtotal_cents"] == expected, (
        f"Invoice.subtotal_cents {invoice['subtotal_cents']} != sum of non-fee, "
        f"non-consignment lines {expected}"
    )


def lines_of_type(lines: list, line_type: str) -> list:
    return [line for line in lines if line["line_type"] == line_type]


def assert_exactly_one_line(lines: list, line_type: str, amount_cents: int):
    matches = lines_of_type(lines, line_type)
    assert len(matches) == 1, (
        f"expected exactly one {line_type} line, found {len(matches)}"
    )
    assert matches[0]["amount_cents"] == amount_cents, (
        f"{line_type} line: expected {amount_cents} cents, "
        f"got {matches[0]['amount_cents']}"
    )
    return matches[0]


def assert_no_line_of_type(lines: list, line_type: str):
    matches = lines_of_type(lines, line_type)
    assert not matches, f"expected no {line_type} line, found {len(matches)}"


def approx_cents(expected):
    return pytest.approx(expected, abs=0)


__all__ = [
    "parse_instant",
    "assert_same_instant",
    "assert_instant_close",
    "assert_millisecond_timestamp",
    "assert_money",
    "assert_hours",
    "assert_two_dp",
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_client",
    "assert_engagement",
    "assert_inventory_item",
    "assert_destination_room",
    "assert_invoice",
    "assert_move_day_plan",
    "assert_vendor_assignment",
    "assert_consignment_lot",
    "assert_vendor_payout_conservation",
    "assert_inventory_volume_conservation",
    "assert_credits_match_lines",
    "assert_subtotal_excludes_fee_and_credits",
    "lines_of_type",
    "assert_exactly_one_line",
    "assert_no_line_of_type",
    "approx_cents",
]
