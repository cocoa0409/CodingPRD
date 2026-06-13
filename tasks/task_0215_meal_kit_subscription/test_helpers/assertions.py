"""Entity assertions and domain invariant checkers for the Meal Kit Subscription API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_SUBSCRIPTION_STATUSES = {"ACTIVE", "PAUSED", "CANCELLED"}
_SELECTION_STATUSES = {"OPEN", "LOCKED", "SKIPPED"}
_FULFILLMENT_STATUSES = {"PENDING", "CHARGED", "SHIPPED", "REFUNDED"}
_REFERRAL_STATUSES = {"PENDING", "SETTLED", "VOID"}
_MEMBER_STATUSES = {"ACTIVE", "DEACTIVATED"}
_DIET_PREFERENCES = {"STANDARD", "VEGETARIAN", "PESCATARIAN", "LOW_CARB", "FAMILY_FRIENDLY"}
_ZONE_CODES = {"ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"}


def _assert_common_fields(data: dict):
    """Every resource carries id (UUID), created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID without prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is an int >= 1"


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["servings_per_meal"] in (2, 4)
    assert isinstance(data["meals_per_week"], int) and 2 <= data["meals_per_week"] <= 6
    assert isinstance(data["is_active"], bool)


def assert_shipping_zone(data: dict):
    _assert_common_fields(data)
    assert data["zone_code"] in _ZONE_CODES
    assert isinstance(data["cold_pack_surcharge_cents"], int) and data["cold_pack_surcharge_cents"] >= 0
    assert isinstance(data["cutoff_weekday"], int) and 1 <= data["cutoff_weekday"] <= 7
    assert isinstance(data["serviceable"], bool)


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["is_premium"], bool)
    assert isinstance(data["contains_allergens"], list)
    assert isinstance(data["diet_tags"], list)
    assert isinstance(data["is_available"], bool)


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("shipping_zone_id", "")), "shipping_zone_id is a UUID"
    assert isinstance(data["referral_code"], str) and len(data["referral_code"]) > 0
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["lifetime_box_count"], int) and data["lifetime_box_count"] >= 0
    assert data["status"] in _MEMBER_STATUSES
    rb = data.get("referred_by_member_id")
    assert rb is None or is_valid_uuid(rb), "referred_by_member_id is null or a UUID"


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id is a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id is a UUID"
    assert data["diet_preference"] in _DIET_PREFERENCES
    assert isinstance(data["blocked_allergens"], list)
    assert isinstance(data["monthly_addon_fee_cents"], int) and data["monthly_addon_fee_cents"] >= 0
    assert isinstance(data["billing_cycle_day"], int) and 1 <= data["billing_cycle_day"] <= 28
    assert data["status"] in _SUBSCRIPTION_STATUSES
    srd = data.get("scheduled_resume_date")
    assert srd is None or is_iso8601_timestamp(srd), "scheduled_resume_date is null or ISO 8601"


def assert_weekly_box(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id is a UUID"
    assert is_iso8601_timestamp(data["delivery_date"]), "delivery_date is ISO 8601"
    assert is_iso8601_timestamp(data["cutoff_at"]), "cutoff_at is ISO 8601"
    assert isinstance(data["provisional_charge_cents"], int)
    fc = data.get("final_charge_cents")
    assert fc is None or isinstance(fc, int), "final_charge_cents is null or an int"
    assert data["selection_status"] in _SELECTION_STATUSES
    assert data["fulfillment_status"] in _FULFILLMENT_STATUSES


def assert_box_recipe(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("box_id", "")), "box_id is a UUID"
    assert is_valid_uuid(data.get("recipe_id", "")), "recipe_id is a UUID"
    assert isinstance(data["is_premium_snapshot"], bool)


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("referrer_member_id", "")), "referrer_member_id is a UUID"
    assert is_valid_uuid(data.get("referee_member_id", "")), "referee_member_id is a UUID"
    assert isinstance(data["reward_cents"], int) and data["reward_cents"] >= 0
    assert data["status"] in _REFERRAL_STATUSES
