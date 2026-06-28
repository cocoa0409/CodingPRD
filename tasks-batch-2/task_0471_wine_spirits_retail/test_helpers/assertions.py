"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_versioned_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # append-only records carry NO updated_at and NO version (PRD §2.4)
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_customer(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age_verified"], bool)
    assert data["compliance_status"] in ("CLEAR", "WATCH", "BLOCKED")
    assert isinstance(data["lifetime_spend_cents"], int)
    assert data["lifetime_spend_cents"] >= 0


def assert_product(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("WINE", "SPIRITS", "BEER", "GROWLER", "KEG")
    assert data["container_type"] in ("BOTTLE", "CAN", "GROWLER_FILL", "KEG_HALF_BBL")
    assert isinstance(data["bottle_volume_ml"], int) and data["bottle_volume_ml"] >= 1
    assert isinstance(data["min_purchase_age"], int)
    assert isinstance(data["is_allocated"], bool)
    assert data["status"] == "ACTIVE"


def assert_vintage(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 1
    assert isinstance(data["case_pack_size"], int) and data["case_pack_size"] >= 1
    assert data["status"] in ("DRAFT", "RELEASED", "ALLOCATION_OPEN", "SOLD_OUT", "DELISTED")
    assert isinstance(data["units_committed"], int) and data["units_committed"] >= 0


def assert_inventory_lot(data: dict):
    _assert_versioned_common(data)
    assert data["tax_status"] in ("BONDED", "TAXED")
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_reserved"], int) and data["qty_reserved"] >= 0
    assert isinstance(data["excise_band_cents_per_unit"], int)


def assert_order(data: dict):
    _assert_versioned_common(data)
    assert data["channel"] in ("POS", "PICKUP", "DELIVERY", "SHIP")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert data["fulfillment_status"] in ("CART", "SUBMITTED", "READY", "COMPLETED", "CANCELLED")
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["settled_total_cents"], int)
    assert isinstance(data["discount_cents"], int)


def assert_order_line(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["reservation_state"] in ("PENDING", "COMMITTED", "FULFILLED", "RELEASED")


def assert_id_scan(data: dict):
    _assert_append_only_common(data)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_compliance_window(data: dict):
    _assert_append_only_common(data)
    assert isinstance(data["volume_ml"], int) and data["volume_ml"] >= 0
    assert isinstance(data["active"], bool)


def assert_membership(data: dict):
    _assert_versioned_common(data)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["accrued_points"], int) and data["accrued_points"] >= 0


def assert_special_order(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["requested_qty"], int) and data["requested_qty"] >= 1
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert data["status"] in ("REQUESTED", "QUOTED", "COUNTERED", "ACCEPTED",
                              "CONVERTED", "DECLINED")


def assert_shipment(data: dict):
    _assert_versioned_common(data)
    assert data["carrier"] in ("STORE_COURIER", "LICENSED_COMMON_CARRIER")
    assert isinstance(data["adult_signature_required"], bool)
    assert data["status"] in ("LABELED", "DISPATCHED", "DELIVERED", "RETURNED")


def assert_state_rule(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["ship_allowed"], bool)
    assert isinstance(data["growler_keg_allowed"], bool)
    assert isinstance(data["requires_adult_signature"], bool)
