"""Entity assertions and domain invariant checkers for the Restaurant POS API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Shared id/created_at/updated_at/version checks for full-field entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_line_detail(data: dict):
    """id + created_at only — immutable line-detail records (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_restaurant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_rate_bps"], int) and 0 <= data["tax_rate_bps"] <= 2000
    assert isinstance(data["large_party_threshold"], int) and data["large_party_threshold"] >= 2
    assert isinstance(data["auto_gratuity_bps"], int) and 0 <= data["auto_gratuity_bps"] <= 5000
    assert isinstance(data["comp_cap_bps"], int) and 0 <= data["comp_cap_bps"] <= 10000
    assert isinstance(data["min_rest_minutes"], int) and data["min_rest_minutes"] >= 0


def assert_menu_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["station"] in ["GRILL", "FRY", "SAUTE", "COLD", "BAR", "EXPO"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["happy_hour_price_cents"], int)
    assert 0 <= data["happy_hour_price_cents"] <= data["base_price_cents"]
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert isinstance(data["is_86"], bool)
    assert data["is_86"] == (data["available_count"] == 0), "is_86 must be true iff available_count==0"


def assert_dining_table(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert isinstance(data["table_number"], str) and len(data["table_number"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["occupancy_status"] in ["AVAILABLE", "SEATED", "DIRTY"]


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert isinstance(data["party_name"], str) and len(data["party_name"]) > 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in ["WAITING", "PROMOTED", "SEATED", "CANCELLED"]


def assert_seating(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["table_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in ["OPEN", "CLEARED"]


def assert_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["seating_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in ["OPEN", "PRESENTED", "CLOSED", "VOID"]
    assert isinstance(data["provisional_subtotal_cents"], int)
    assert isinstance(data["comp_total_cents"], int)
    assert isinstance(data["auto_gratuity_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["tip_cents"], int)


def assert_course(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["check_id"])
    assert isinstance(data["course_number"], int) and data["course_number"] >= 1
    assert data["status"] in ["BUILDING", "FIRED"]


def assert_order_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ["PENDING", "FIRED", "SERVED", "VOIDED", "COMPED"]


def assert_item_modifier(data: dict):
    _assert_line_detail(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["order_item_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0


def assert_staff_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["role"] in ["SERVER", "BARTENDER", "BUSSER"]
    assert isinstance(data["tip_weight_bps"], int) and data["tip_weight_bps"] >= 0


def assert_staff_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["staff_id"])
    assert isinstance(data["business_date"], str)
    assert isinstance(data["clock_in_minute"], int)
    assert isinstance(data["clock_out_minute"], int)
    assert data["clock_in_minute"] < data["clock_out_minute"] <= 1440


def assert_tip_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert isinstance(data["business_date"], str)
    assert data["distribution_mode"] in ["EVEN_BY_HOURS", "WEIGHTED_BY_ROLE"]
    assert data["status"] in ["ACCUMULATING", "DISTRIBUTED"]
    assert isinstance(data["pooled_cents"], int)
    assert isinstance(data["distributed_cents"], int)


def assert_tip_allocation(data: dict):
    _assert_line_detail(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["tip_pool_id"])
    assert is_valid_uuid(data["staff_shift_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["check_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["tip_cents"], int) and data["tip_cents"] >= 0
    assert data["method"] in ["CASH", "CARD", "GIFT"]
    assert data["status"] in ["SETTLED", "VOIDED"]
