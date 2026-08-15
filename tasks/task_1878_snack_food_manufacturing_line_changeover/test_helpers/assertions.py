"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ALLERGENS = ["PEANUT", "TREE_NUT", "DAIRY", "SOY", "GLUTEN", "SESAME", "EGG"]
FLAVOR_GROUPS = ["PLAIN", "CHEESE", "SPICY", "SWEET"]


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Immutable records carry only id + created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["process_type"] in ["FRYER", "OVEN"]
    assert isinstance(data["allergen_profile"], list)
    for tag in data["allergen_profile"]:
        assert tag in ALLERGENS
    assert data["flavor_group"] in FLAVOR_GROUPS
    assert data["declared_net_weight_g"] > 0
    assert data["tne_g"] > 0
    assert data["giveaway_target_pct"] >= 0
    assert data["giveaway_max_pct"] >= 0
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] >= 1
    assert data["seasoning_target_pct"] >= 0
    assert data["standard_oil_price_cents_per_gal"] >= 0
    assert data["case_revenue_cents"] >= 0
    assert data["min_margin_cents_per_case"] >= 0
    assert isinstance(data["bags_per_case"], int) and data["bags_per_case"] >= 1


def assert_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["line_type"] in ["FRYER", "OVEN", "BOTH"]
    assert data["oil_capacity_gallons"] > 0
    assert isinstance(data["cleaning_minutes_full_wash"], int)
    assert isinstance(data["cleaning_minutes_dry"], int)
    assert data["posture"] in ["IDLE", "RUNNING", "CLEANING", "BLOCKED"]
    assert isinstance(data["current_allergen_profile"], list)
    assert data["current_flavor_group"] in FLAVOR_GROUPS


def assert_fryer_oil(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", "")), "line_id must be valid UUID"
    assert data["initial_charge_gallons"] > 0
    assert data["current_gallons"] >= 0
    assert data["tpm_pct"] >= 0
    assert data["state"] in ["ACTIVE", "QUALITY_HOLD", "DRAINING"]
    assert data["total_lbs_since_replace"] >= 0
    assert data.get("last_oil_price_cents_per_gal") is None or (
        data["last_oil_price_cents_per_gal"] >= 0
    )


def assert_oil_movement(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("fryer_oil_id", "")), (
        "fryer_oil_id must be valid UUID"
    )
    assert data["movement_type"] in ["TOP_OFF", "DISCARD", "FILTRATION", "FULL_REPLACE"]
    assert data["gallons"] >= 0
    assert isinstance(data["tpm_after_pct"], (int, float))
    assert is_iso8601_timestamp(data.get("recorded_at", "")), (
        "recorded_at must be ISO 8601"
    )
    assert isinstance(data["recorded_by_user_id"], str)


def assert_changeover(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", "")), "line_id must be valid UUID"
    assert is_valid_uuid(data.get("to_product_id", "")), (
        "to_product_id must be valid UUID"
    )
    assert isinstance(data["from_allergen_profile"], list)
    assert isinstance(data["to_allergen_profile"], list)
    assert data["from_flavor_group"] in FLAVOR_GROUPS
    assert data["to_flavor_group"] in FLAVOR_GROUPS
    assert data["required_level"] in ["NONE", "DRY_CLEAN", "FULL_WASH"]
    assert data["status"] in [
        "REQUIRED", "CLEANING", "SWAB_PENDING", "VALIDATED", "APPLIED", "CANCELLED",
    ]
    assert isinstance(data["swab_attempts"], int) and data["swab_attempts"] >= 0
    assert data.get("swab_result") in (None, "PASS", "FAIL")


def assert_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", "")), "line_id must be valid UUID"
    assert is_valid_uuid(data.get("product_id", "")), (
        "product_id must be valid UUID"
    )
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["lbs_planned"] > 0
    assert isinstance(data["cases_planned"], int) and data["cases_planned"] >= 1
    assert data["execution_status"] in [
        "SCHEDULED", "RUNNING", "HELD", "COMPLETED", "CANCELLED",
    ]
    assert data["quality_status"] in ["PENDING", "QHOLD", "PASSED", "REJECTED"]
    assert isinstance(data["accepted_cases"], int)
    assert isinstance(data["cases_unrouted"], int)


def assert_weight_check(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("run_id", "")), "run_id must be valid UUID"
    assert data["bag_weight_g"] > 0
    assert data["lbs_fried_since_last_check"] >= 0
    assert isinstance(data["is_reject"], bool)
    assert is_iso8601_timestamp(data.get("recorded_at", "")), (
        "recorded_at must be ISO 8601"
    )
    assert isinstance(data["checked_by_user_id"], str)


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("run_id", "")), "run_id must be valid UUID"
    assert isinstance(data["cases"], int) and data["cases"] >= 1
    assert data["requested_route"] in ["DSD", "WAREHOUSE", "AUTO"]
    assert isinstance(data["transit_days"], int) and data["transit_days"] >= 0
    assert data.get("planned_route") in (None, "DSD", "WAREHOUSE")
    assert data["status"] in [
        "DRAFT", "DSD_PLANNED", "WAREHOUSE_PLANNED", "DISPATCHED", "CANCELLED",
    ]


def assert_promo_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", "")), (
        "product_id must be valid UUID"
    )
    assert isinstance(data["quota_total_cases"], int)
    assert data["quota_total_cases"] >= 1
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["case_size_bags"], int) and data["case_size_bags"] >= 1
    assert data["status"] in ["DRAFT", "ACTIVE", "EXHAUSTED", "CLOSED"]
    assert isinstance(data["quota_consumed_cases"], int)
    assert isinstance(data["quota_released_cases"], int)
    assert isinstance(data["quota_remaining_cases"], int)


def assert_display_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("promo_window_id", "")), (
        "promo_window_id must be valid UUID"
    )
    assert is_valid_uuid(data.get("run_id", "")), "run_id must be valid UUID"
    assert isinstance(data["cases_planned"], int) and data["cases_planned"] >= 1
    assert data["status"] in ["PLANNED", "BUILT", "CANCELLED"]
    assert data.get("cancelled_reason") in (
        None, "OIL_HOLD", "QUOTA_EXHAUSTED", "OVER_RESERVED",
        "RUN_CANCELLED", "RUN_REJECTED", "MANUAL",
    )


def assert_co_manufacturer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["active"], bool)


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("co_manufacturer_id", "")), (
        "co_manufacturer_id must be valid UUID"
    )
    assert data["weekly_capacity_lbs"] > 0
    assert data["rate_per_lb_cents"] >= 0
    assert data["budget_cents"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", "")), (
        "agreement_id must be valid UUID"
    )
    assert is_valid_uuid(data.get("product_id", "")), (
        "product_id must be valid UUID"
    )
    assert isinstance(data["week_start_date"], str)
    assert data["reserved_lbs"] > 0
    assert data["status"] in ["BOOKED", "CONFIRMED", "CONSUMED", "RELEASED"]


def assert_quota_invariant(window: dict):
    """Promo quota conservation: total == remaining + consumed - released."""
    assert window["quota_total_cases"] == (
        window["quota_remaining_cases"]
        + window["quota_consumed_cases"]
        - window["quota_released_cases"]
    ), (
        f"Quota invariant broken: total {window['quota_total_cases']} != "
        f"remaining {window['quota_remaining_cases']} + consumed "
        f"{window['quota_consumed_cases']} - released "
        f"{window['quota_released_cases']}"
    )
