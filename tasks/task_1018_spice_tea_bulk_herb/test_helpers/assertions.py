"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("SPICE", "TEA", "HERB")
    assert data["kind"] in ("SIMPLE", "BLEND")
    assert float(data["unit_price_cents_per_gram"]) > 0
    assert int(data["tare_default_grams"]) >= 0
    assert isinstance(data["allergen_tags"], list)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["stock_state"] in ("IN_STOCK", "OUT_OF_STOCK")


def assert_blend_component(data: dict):
    # Immutable junction row: id + created_at only, NO updated_at / version.
    _common(data)
    assert is_valid_uuid(data["blend_product_id"])
    assert is_valid_uuid(data["component_product_id"])
    assert 1 <= int(data["weight_ratio_bps"]) <= 10000
    assert "updated_at" not in data, "BlendComponent must not carry updated_at"
    assert "version" not in data, "BlendComponent must not carry version"


def assert_inventory_lot(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str)
    assert int(data["grams_received"]) > 0
    assert int(data["grams_on_hand"]) >= 0
    assert data["status"] in ("AVAILABLE", "DEPLETED", "EXPIRED")


def assert_production_line(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str)


def assert_batch(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data["blend_product_id"])
    assert is_valid_uuid(data["production_line_id"])
    assert int(data["target_output_grams"]) > 0
    assert data["status"] in ("PLANNED", "PRODUCED")


def assert_labeling_station(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str)


def assert_tin_run(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data["labeling_station_id"])
    assert isinstance(data["product_ids"], list)
    assert isinstance(data["allergen_set"], list)


def assert_wholesale_account(data: dict):
    _common_versioned(data)
    assert isinstance(data["business_name"], str)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert int(data["credit_limit_cents"]) >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_customer_order(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data["wholesale_account_id"])
    assert data["fulfillment_status"] in (
        "DRAFT", "PRICED", "CONFIRMED", "PACKED", "SHIPPED", "CANCELLED",
    )
    assert isinstance(data["allergen_ack"], bool)


def assert_order_line(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert int(data["requested_grams"]) > 0


def assert_credit_conserved(account: dict):
    """available_credit_cents + committed_exposure_cents == credit_limit_cents."""
    assert (
        account["available_credit_cents"] + account["committed_exposure_cents"]
        == account["credit_limit_cents"]
    ), (
        "credit must be conserved: available + committed == limit "
        f"({account['available_credit_cents']} + {account['committed_exposure_cents']} "
        f"!= {account['credit_limit_cents']})"
    )
