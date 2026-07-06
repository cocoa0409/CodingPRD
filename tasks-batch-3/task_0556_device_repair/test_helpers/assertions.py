"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["store_credit_balance_cents"], int)


def assert_device(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["category"] in ["PHONE", "LAPTOP", "TABLET", "WEARABLE"]
    assert isinstance(data["market_value_cents"], int) and data["market_value_cents"] >= 0


def assert_technician(data: dict):
    _assert_common(data)
    assert data["certification_level"] in ["STANDARD", "MASTER"]


def assert_repair_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_name"], str)


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["intake_channel"] in ["WALK_IN", "MAIL_IN"]
    assert isinstance(data["is_under_warranty"], bool)
    assert isinstance(data["is_callback"], bool)
    assert isinstance(data["spend_cap_cents"], int) and data["spend_cap_cents"] >= 0
    assert data["status"] in ["INTAKE", "DIAGNOSING", "AWAITING_APPROVAL",
                              "IN_REPAIR", "COMPLETED", "CANCELLED"]


def assert_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["repair_ticket_id"])
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["labor_cost_cents"], int)
    assert isinstance(data["parts_cost_cents"], int)
    assert isinstance(data["diagnostic_fee_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert data["recommendation"] in ["REPAIR", "REPLACE"]
    assert data["status"] in ["SENT", "APPROVED", "REJECTED", "SUPERSEDED", "FINALIZED"]


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert_part_inventory_invariant(data)


def assert_part_inventory_invariant(data: dict):
    """PRD 2.10: available_qty == on_hand_qty - reserved_qty, always reconciled."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        f"available_qty ({data['available_qty']}) must equal on_hand_qty "
        f"({data['on_hand_qty']}) - reserved_qty ({data['reserved_qty']})"
    )


def assert_part_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["repair_ticket_id"])
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_cost_cents"], int)
    assert data["status"] in ["REQUESTED", "RESERVED", "BACKORDERED", "INSTALLED", "RETURNED"]


def assert_trade_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["declared_grade"] in ["A", "B", "C", "D"]
    assert isinstance(data["quoted_payout_cents"], int)
    assert data["status"] in ["SUBMITTED", "OFFER_MADE", "ACCEPTED", "PAID", "DECLINED", "CANCELLED"]


def assert_data_wipe_certificate(data: dict):
    """PRD 2.4: immutable event record — id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DataWipeCertificate must not carry updated_at"
    assert "version" not in data, "DataWipeCertificate must not carry version"
    assert is_valid_uuid(data["device_id"])
    assert data["method"] in ["CRYPTO_ERASE", "FACTORY_RESET", "PHYSICAL_DESTRUCTION"]
    assert data["wipe_result"] in ["SUCCESS", "FAILED"]
    assert isinstance(data["certificate_number"], str) and len(data["certificate_number"]) > 0


def assert_protection_plan_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["repair_ticket_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["plan_type"] in ["ADH", "EXTENDED_WARRANTY", "ACCESSORY"]
    assert isinstance(data["deductible_cents"], int)
    assert data["status"] in ["FILED", "ROUTED", "APPROVED", "DENIED"]
