"""Entity assertions and small domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BaleStatus,
    BatchStatus,
    CycleStatus,
    GuidelineStatus,
    ItemStatus,
    ReceiptStatus,
    RotationColor,
    RouteStatus,
    SaleStatus,
    StopStatus,
    TillStatus,
    TransferStatus,
)


def _assert_common(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_donor(data):
    _assert_common(data, "Donor")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["tier"] in ("STANDARD", "FREQUENT")
    assert isinstance(data["lifetime_donation_count"], int)


def assert_batch(data):
    _assert_common(data, "DonationBatch")
    assert data["status"] in [s.value for s in BatchStatus]
    assert isinstance(data["item_count"], int)
    assert isinstance(data["untriaged_count"], int)
    assert isinstance(data["provisional_value_cents"], int)
    assert isinstance(data["sold_item_count"], int)


def assert_item(data):
    _assert_common(data, "DonationItem")
    assert data["status"] in [s.value for s in ItemStatus]
    assert isinstance(data["provisional_value_cents"], int)
    assert isinstance(data["markdown_round"], int)


def assert_guideline(data):
    _assert_common(data, "PricingGuideline")
    assert data["status"] in [s.value for s in GuidelineStatus]
    assert isinstance(data["base_cents"], int) and data["base_cents"] > 0
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1


def assert_bale(data):
    _assert_common(data, "SalvageBale")
    assert data["status"] in [s.value for s in BaleStatus]
    assert isinstance(data["item_count"], int)
    assert isinstance(data["estimated_revenue_cents"], int)


def assert_sale(data):
    _assert_common(data, "SalesTransaction")
    assert data["status"] in [s.value for s in SaleStatus]
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["line_count"], int)


def assert_till_session(data):
    _assert_common(data, "TillSession")
    assert data["status"] in [s.value for s in TillStatus]
    assert isinstance(data["opening_float_cents"], int)
    assert isinstance(data["cash_sales_cents"], int)
    assert isinstance(data["card_sales_cents"], int)
    assert isinstance(data["expected_cash_cents"], int)


def assert_route(data):
    _assert_common(data, "PickupRoute")
    assert data["status"] in [s.value for s in RouteStatus]
    assert isinstance(data["stop_count"], int)


def assert_stop(data):
    _assert_common(data, "PickupStop")
    assert data["status"] in [s.value for s in StopStatus]


def assert_worker(data):
    _assert_common(data, "Worker")
    assert data["status"] in ("ACTIVE", "INACTIVE", "CAP_REACHED")
    assert data["employment_type"] in ("VOLUNTEER", "TRANSITIONAL", "STAFF")


def assert_shift(data):
    _assert_common(data, "Shift")
    assert isinstance(data["required_headcount"], int)
    assert isinstance(data["assigned_count"], int)


def assert_assignment(data):
    _assert_common(data, "ShiftAssignment")
    assert data["status"] in (
        "ASSIGNED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"
    )


def assert_cycle(data):
    _assert_common(data, "WeeklyCycle")
    assert data["status"] in [s.value for s in CycleStatus]
    assert data["rotation_color"] in [c.value for c in RotationColor]
    assert isinstance(data["sequence_number"], int)
    assert isinstance(data["markdown_runs_count"], int)


def assert_transfer(data):
    _assert_common(data, "MissionTransfer")
    assert data["status"] in [s.value for s in TransferStatus]
    assert isinstance(data["gross_pool_cents"], int)
    assert isinstance(data["reserve_cents"], int)
    assert isinstance(data["net_pool_cents"], int)
    assert isinstance(data["allocation_amounts"], list)


def assert_receipt(data):
    _assert_common(data, "TaxReceipt")
    assert data["status"] in [s.value for s in ReceiptStatus]
    assert isinstance(data["receipt_number"], str)
    assert data["receipt_number"].startswith("RCT-")
    assert isinstance(data["total_value_cents"], int)
    assert isinstance(data["itemized_required"], bool)
    assert isinstance(data["form_8283_required"], bool)


def parse_instant(ts):
    """Parse an ISO 8601 UTC timestamp (with optional fractional digits)."""
    assert is_iso8601_timestamp(ts), f"Not an ISO 8601 UTC timestamp: {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_same_instant(actual_ts, expected_iso):
    """Compare two instants regardless of fractional-digit rendering."""
    assert parse_instant(actual_ts) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual_ts}"
    )
