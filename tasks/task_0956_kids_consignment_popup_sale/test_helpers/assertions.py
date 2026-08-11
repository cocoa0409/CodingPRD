"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    BookingStatus,
    ConsignorStatus,
    HolderType,
    InspectionOutcome,
    ItemCategory,
    ItemStatus,
    PassStatus,
    SaleEventPhase,
    SettlementStatus,
    SignupStatus,
    TransactionStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.4: primary entities carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_audit_fields(data: dict):
    """PRD §2.4: InspectionRecord and TransactionLine carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit rows must not carry updated_at"
    assert "version" not in data, "audit rows must not carry version"


def assert_sale_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for field in ("intake_start", "intake_end", "presale_start", "presale_end",
                  "sale_start", "sale_end", "pickup_deadline"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    assert data["phase"] in [p.value for p in SaleEventPhase]
    assert isinstance(data["sold_gross_cents"], int)


def assert_markdown_rule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["discount_pct"], int)
    assert 1 <= data["discount_pct"] <= 90, "discount_pct must be between 1 and 90"


def assert_consignor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["consignor_code"], str) and data["consignor_code"].startswith("C")
    assert data["status"] in [s.value for s in ConsignorStatus]
    for field in ("sold_count", "unsold_count", "rejected_count", "sold_gross_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data.get("linked_consignor_id") is None or is_valid_uuid(data["linked_consignor_id"])
    assert isinstance(data["completed_hours"], (int, float))
    assert isinstance(data["projected_hours"], (int, float))
    assert isinstance(data["projected_discount_pct"], int)


def assert_drop_off_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0


def assert_drop_off_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["slot_id"])
    assert is_valid_uuid(data["consignor_id"])
    assert data["status"] in [s.value for s in BookingStatus]


def assert_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["consignor_id"])
    assert is_valid_uuid(data["sale_event_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["category"] in [c.value for c in ItemCategory]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 200
    assert data["price_cents"] % 50 == 0, "price_cents must be a multiple of 50"
    assert isinstance(data["discount_eligible"], bool)
    assert isinstance(data["donate_flag"], bool)
    assert isinstance(data["barcode"], str) and "-" in data["barcode"]
    assert data["status"] in [s.value for s in ItemStatus]
    assert data.get("reject_reason") is None or isinstance(data["reject_reason"], str)


def assert_inspection_record(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    assert data["outcome"] in [o.value for o in InspectionOutcome]


def assert_volunteer_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert isinstance(data["role_name"], str) and data["role_name"]
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["signed_up_count"], int) and data["signed_up_count"] >= 0


def assert_shift_signup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["shift_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert data["status"] in [s.value for s in SignupStatus]
    assert isinstance(data["hours_credited"], (int, float))


def assert_presale_pass(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert data["holder_type"] in [h.value for h in HolderType]
    assert isinstance(data["holder_id"], str) and data["holder_id"]
    assert isinstance(data["discount_pct"], int)
    assert data["status"] in [s.value for s in PassStatus]


def assert_pos_transaction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert isinstance(data["cashier_id"], str) and data["cashier_id"]
    assert data.get("presale_pass_id") is None or is_valid_uuid(data["presale_pass_id"])
    assert isinstance(data["pass_discount_pct"], int)
    assert data["status"] in [s.value for s in TransactionStatus]
    for field in ("subtotal_cents", "discount_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    # PRD §3.8: discount_cents is the difference between subtotal and total
    assert data["discount_cents"] == data["subtotal_cents"] - data["total_cents"]


def assert_transaction_line(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["transaction_id"])
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["barcode"], str) and data["barcode"]
    for field in ("tag_price_cents", "markdown_pct_applied", "line_price_cents",
                  "pass_discount_pct_applied", "final_line_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sale_event_id"])
    assert is_valid_uuid(data["consignor_id"])
    assert data["status"] in [s.value for s in SettlementStatus]
    assert isinstance(data["provisional_gross_cents"], int)
    assert isinstance(data["provisional_payout_cents"], int)
    assert isinstance(data["sold_item_count"], int)
    assert isinstance(data["adjustment_cents"], int)


def assert_event_money_invariant(event: dict, consignors: list):
    """PRD §2.10 money invariant: the event's sold_gross_cents always equals the
    sum of sold_gross_cents over the event's consignors."""
    total = sum(c["sold_gross_cents"] for c in consignors)
    assert event["sold_gross_cents"] == total, (
        f"Money invariant violated: event sold_gross_cents {event['sold_gross_cents']} "
        f"!= sum of consignor sold_gross_cents {total}"
    )
