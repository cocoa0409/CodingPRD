"""Entity assertions and domain invariant checkers for the Styling Box API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_client(data: dict):
    assert is_valid_uuid(data.get("id", "")), "client id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str)
    assert data["region_code"] in ("CA", "NY", "OR")
    assert data["cadence"] in ("EVERY_2_WEEKS", "MONTHLY", "EVERY_2_MONTHS", "QUARTERLY")
    assert data["status"] in ("PROSPECT", "ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data.get("version"), int)


def assert_style_profile(data: dict):
    assert is_valid_uuid(data.get("id", "")), "style profile id must be a valid UUID"
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert isinstance(data["quiz_top_size"], int)
    assert data["price_tier"] in ("BUDGET", "MID", "PREMIUM")
    assert isinstance(data["learned_top_size"], int)
    assert isinstance(data["learned_bottom_size"], int)
    assert isinstance(data["learned_shoe_size"], int)
    assert 0 <= data["fit_confidence"] <= 100
    assert isinstance(data["feedback_count"], int)


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "product id must be a valid UUID"
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("TOP", "BOTTOM", "SHOE", "ACCESSORY")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["price_cents"] >= 0
    assert_inventory_conserved(data)


def assert_inventory_conserved(product: dict):
    """PRD §2.7: available_count + reserved_count + sold_count == total_stock,
    and no count is ever negative."""
    a = product["available_count"]
    r = product["reserved_count"]
    s = product["sold_count"]
    t = product["total_stock"]
    assert a >= 0 and r >= 0 and s >= 0, f"counts must be non-negative: {product}"
    assert a + r + s == t, (
        f"inventory invariant broken: available({a}) + reserved({r}) + sold({s}) != total_stock({t})"
    )


def assert_stylist(data: dict):
    assert is_valid_uuid(data.get("id", "")), "stylist id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["max_concurrent_fixes"] >= 1
    assert data["active_fix_count"] >= 0


def assert_fix(data: dict):
    assert is_valid_uuid(data.get("id", "")), "fix id must be a valid UUID"
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a valid UUID"
    assert data["status"] in (
        "REQUESTED", "STYLING", "PREVIEW", "SHIPPED", "DELIVERED",
        "CHECKED_OUT", "CLOSED", "CANCELLED",
    )


def assert_fix_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "fix item id must be a valid UUID"
    assert is_valid_uuid(data.get("fix_id", "")), "fix_id must be a valid UUID"
    assert data["status"] in ("SELECTED", "KEPT", "RETURNED", "RELEASED")
    assert data["category"] in ("TOP", "BOTTOM", "SHOE", "ACCESSORY")


def assert_return_shipment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "return shipment id must be a valid UUID"
    assert data["status"] in ("LABEL_ISSUED", "IN_TRANSIT", "RECEIVED")


def assert_feedback_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "feedback entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["rating"] in (
        "TOO_SMALL", "SLIGHTLY_SMALL", "PERFECT", "SLIGHTLY_LARGE", "TOO_LARGE",
    )


def assert_purchase(data: dict):
    assert is_valid_uuid(data.get("id", "")), "purchase id must be a valid UUID"
    assert data["status"] in ("PLACED", "CANCELLED")
    assert data["quantity"] >= 1
