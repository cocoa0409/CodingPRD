"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3).

Each assert_{entity} validates the system fields and field types the PRD
guarantees on that entity's responses. The ledger-style records (RecallNotice,
RecallAck, Payment) carry only id + created_at per PRD §2.4 — their assertions
do NOT demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_system_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 (PRD §2.4)"


def _assert_ledger_system_fields(data: dict):
    """id + created_at only — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ledger record must not carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "ledger record must not carry updated_at (PRD §2.4)"


def assert_customer(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert "@" in data["email"]
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0
    assert isinstance(data["open_recall_count"], int)
    assert data["open_recall_count"] >= 0


def assert_sku(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("BIKE", "PART", "ACCESSORY")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 1
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["reserved"], int) and data["reserved"] >= 0
    assert data["warranty_class"] in ("NONE", "COMPONENT", "FRAME_AND_COMPONENT")
    assert isinstance(data["is_serialized"], bool)


def assert_tune_up_tier(data: dict):
    _assert_common_system_fields(data)
    assert data["code"] in ("BASIC", "STANDARD", "PREMIUM")
    assert isinstance(data["base_labor_cents"], int) and data["base_labor_cents"] >= 0
    assert isinstance(data["turnaround_hours"], int) and data["turnaround_hours"] >= 1
    assert isinstance(data["rush_multiplier_bps"], int) and data["rush_multiplier_bps"] >= 0


def assert_service_bay(data: dict):
    _assert_common_system_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["is_active"], bool)


def assert_bay_booking(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["bay_id"])
    assert is_valid_uuid(data["ticket_id"])
    assert data["status"] in ("BOOKED", "RELEASED")


def assert_service_ticket(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["tier_id"])
    assert data["status"] in (
        "INTAKE", "AWAITING_APPROVAL", "IN_PROGRESS",
        "READY_FOR_PICKUP", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["is_rush"], bool)
    assert isinstance(data["labor_subtotal_cents"], int) and data["labor_subtotal_cents"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["customer_owes_cents"], int) and data["customer_owes_cents"] >= 0


def assert_labor_line(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["menu_code"], str) and len(data["menu_code"]) > 0
    assert isinstance(data["labor_cents"], int) and data["labor_cents"] >= 0
    assert isinstance(data["added_after_approval"], bool)


def assert_sales_order(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PENDING", "RESERVED", "DELIVERED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["store_credit_applied_cents"], int) and data["store_credit_applied_cents"] >= 0
    assert isinstance(data["total_due_cents"], int) and data["total_due_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_order_line(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0


def assert_reservation(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["sku_id"])
    assert data["holder_type"] in ("SALES_ORDER", "BUILD_JOB", "LAYAWAY_PLAN", "SPECIAL_ORDER")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in ("ACTIVE", "COMMITTED", "RELEASED")


def assert_layaway_plan(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "FORFEITED", "FULFILLED", "CANCELLED")
    assert isinstance(data["forfeit_fee_cents"], int) and data["forfeit_fee_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_special_order(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["deposit_required_cents"], int) and data["deposit_required_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert data["status"] in ("QUOTED", "CONFIRMED", "ARRIVED", "FULFILLED", "CANCELLED")


def assert_build_job(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["frame_sku_id"])
    assert isinstance(data["required_part_count"], int) and data["required_part_count"] >= 1
    assert isinstance(data["reserved_part_count"], int) and data["reserved_part_count"] >= 0
    assert data["status"] in ("DRAFT", "PARTS_RESERVED", "ASSEMBLING", "COMPLETED", "CANCELLED")
    assert isinstance(data["build_fee_cents"], int) and data["build_fee_cents"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["source_order_line_id"])
    assert data["defect_part"] in ("FRAME", "COMPONENT")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED_REPAIR",
        "APPROVED_REPLACE", "DENIED", "RESOLVED",
    )


def assert_trade_in(data: dict):
    _assert_common_system_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["condition_grade"] in ("A", "B", "C")
    assert isinstance(data["appraised_value_cents"], int) and data["appraised_value_cents"] >= 0
    assert isinstance(data["offer_cents"], int) and data["offer_cents"] >= 0
    assert data["apply_to"] in ("STORE_CREDIT", "CASH")
    assert data["status"] in ("APPRAISED", "ACCEPTED", "REJECTED")


def assert_recall_notice(data: dict):
    _assert_ledger_system_fields(data)
    assert is_valid_uuid(data["sku_id"])
    assert data["severity"] in ("ADVISORY", "MANDATORY")
    assert isinstance(data["remedy"], str)


def assert_recall_ack(data: dict):
    _assert_ledger_system_fields(data)
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["customer_id"])


def assert_payment(data: dict):
    _assert_ledger_system_fields(data)
    assert data["target_type"] in ("SALES_ORDER", "LAYAWAY_PLAN", "SPECIAL_ORDER")
    assert is_valid_uuid(data["target_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ("CAPTURED", "VOIDED")


# ─── Domain invariant checkers (PRD §2.6) ───────────────────────────────────
def assert_sku_unit_conservation(data: dict, expected_on_hand: int, expected_reserved: int):
    """PRD §2.6: reserved is the sum of ACTIVE reservation qty; available is
    on_hand - reserved. After a compensating cancel/release the totals must
    land exactly on the expected values with zero drift."""
    assert data["on_hand"] == expected_on_hand, (
        f"on_hand expected {expected_on_hand}, got {data['on_hand']}"
    )
    assert data["reserved"] == expected_reserved, (
        f"reserved expected {expected_reserved}, got {data['reserved']}"
    )
    assert data["on_hand"] >= 0 and data["reserved"] >= 0
