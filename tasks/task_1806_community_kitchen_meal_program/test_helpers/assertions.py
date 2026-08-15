"""Entity assertions and domain invariant checkers (PRD sections 2.4 and 3)."""
from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Enumerated value sets drawn from PRD section 3 narratives.
ALLERGENS = {
    "GLUTEN", "DAIRY", "EGG", "SOY", "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME",
}
DIETARY_LABELS = {
    "VEGETARIAN", "VEGAN", "HALAL", "KOSHER_STYLE", "LOW_SODIUM", "DIABETIC_FRIENDLY",
}
SITE_STATUSES = {"OPEN", "CLOSED"}
EQUIPMENT_POSTURES = {"OPERATIONAL", "RESTRICTED", "HALTED"}
MENU_DAY_STATUSES = {
    "DRAFT", "FORECAST_LOCKED", "IN_PRODUCTION", "SERVING", "RECONCILED", "CANCELLED",
}
FORECAST_VARIANTS = {"TRAILING_AVERAGE", "DOW_WEIGHTED"}
MENU_ITEM_STATUSES = {"PLANNED", "CONFIRMED", "UNAVAILABLE", "SOLD_OUT"}
FOOD_BATCH_STATUSES = {
    "RECEIVED", "INSPECTING", "ACCEPTED", "QUARANTINED", "REJECTED", "DEPLETED",
}
INSPECTION_RESULTS = {"PENDING", "PASSED", "FAILED"}
SOURCE_TYPES = {"DONATION", "PURCHASE", "RESCUE"}
VOLUNTEER_STATUSES = {"ACTIVE", "SUSPENDED", "INACTIVE"}
CERTIFICATION_LEVELS = {"NONE", "BASIC", "SUPERVISOR"}
SHIFT_STATUSES = {"SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"}
ROLES_ON_SHIFT = {"PREP", "COOK", "SERVER", "DRIVER", "SUPERVISOR_ON_DUTY"}
GUEST_STATUSES = {"ACTIVE", "FLAGGED", "INACTIVE"}
SERVICE_MODELS = {"DINE_IN", "TO_GO", "DELIVERY"}
SERVICE_STATUSES = {"PLANNED", "OPEN", "PAUSED", "CLOSED", "ABORTED"}
PREP_STATUSES = {"QUEUED", "IN_PREP", "READY"}
FULFILLMENT_STATUSES = {"RESERVED", "SERVED", "DELIVERED", "RELEASED", "EXPIRED"}
EQUIPMENT_CLASSES = {"OVEN", "STOVETOP", "COLD_HOLDING", "GENERAL"}
CRITICALITIES = {"CRITICAL", "SUPPORT"}
EQUIPMENT_STATUSES = {"OPERATIONAL", "IN_MAINTENANCE", "DOWN_FOR_REPAIR", "DECOMMISSIONED"}
WASTE_REASONS = {"OVERPRODUCTION", "SPOILAGE", "SAFETY_DISCARD", "PACKAGING_DAMAGE"}
WASTE_DISPOSITIONS = {"DISCARD", "COMPOST", "RESCUE_REDIRECT"}


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD 2.4 common fields: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD 2.4 append-only exception: only id + created_at are present."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_site(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dine_in_capacity"], int) and data["dine_in_capacity"] >= 1
    assert isinstance(data["togo_capacity_per_window"], int)
    assert isinstance(data["delivery_radius_km"], (int, float))
    assert data["equipment_posture"] in EQUIPMENT_POSTURES
    assert data["status"] in SITE_STATUSES


def assert_menu_day(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert data["forecast_variant"] in FORECAST_VARIANTS
    assert isinstance(data["committed_servings"], int)
    assert isinstance(data["served_count"], int)
    assert data["status"] in MENU_DAY_STATUSES
    # forecast_servings is null until locked (PRD 3.2)
    if data.get("forecast_servings") is not None:
        assert isinstance(data["forecast_servings"], int)
    # overproduction_ratio stays null until at least one guest is served (PRD 2.9)
    if data.get("overproduction_ratio") is not None:
        assert isinstance(data["overproduction_ratio"], (int, float))


def assert_menu_item(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["menu_day_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["planned_servings"], int)
    assert isinstance(data["allergen_tags"], list)
    assert set(data["allergen_tags"]) <= ALLERGENS
    assert isinstance(data["dietary_labels"], list)
    assert set(data["dietary_labels"]) <= DIETARY_LABELS
    assert data["requires_equipment_class"] in {"OVEN", "STOVETOP", "COLD_HOLDING", "NONE"}
    assert data["status"] in MENU_ITEM_STATUSES


def assert_food_batch(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert data["source_type"] in SOURCE_TYPES
    assert isinstance(data["item_description"], str)
    assert isinstance(data["quantity_servings"], int) and data["quantity_servings"] >= 1
    assert isinstance(data["remaining_servings"], int)
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["use_by"])
    assert data["inspection_result"] in INSPECTION_RESULTS
    assert isinstance(data["allergen_tags"], list)
    assert data["status"] in FOOD_BATCH_STATUSES


def assert_batch_allocation(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["menu_item_id"])
    assert is_valid_uuid(data["food_batch_id"])
    assert isinstance(data["servings"], int) and data["servings"] >= 1
    assert is_iso8601_timestamp(data["allocated_at"])


def assert_volunteer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["certification_level"] in CERTIFICATION_LEVELS
    assert isinstance(data["hours_balance"], (int, float))
    assert isinstance(data["strike_count"], int)
    assert data["status"] in VOLUNTEER_STATUSES


def assert_volunteer_shift(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert is_valid_uuid(data["menu_day_id"])
    assert data["role_on_shift"] in ROLES_ON_SHIFT
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in SHIFT_STATUSES


def assert_guest_profile(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["allergens"], list)
    assert isinstance(data["dietary_preferences"], list)
    assert isinstance(data["visits_count"], int)
    assert data["status"] in GUEST_STATUSES


def assert_meal_service(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["menu_day_id"])
    assert data["service_model"] in SERVICE_MODELS
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["requires_supervisor"], bool)
    assert data["status"] in SERVICE_STATUSES


def assert_meal_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["meal_service_id"])
    assert is_valid_uuid(data["guest_id"])
    assert is_valid_uuid(data["menu_item_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["substitution_allowed"], bool)
    assert data["prep_status"] in PREP_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    # PRD 3.5: the no-charge policy pins charge_cents to zero.
    assert data["charge_cents"] == 0, (
        f"no-charge policy: charge_cents must be 0, got {data['charge_cents']!r}"
    )


def assert_equipment_asset(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["equipment_class"] in EQUIPMENT_CLASSES
    assert data["criticality"] in CRITICALITIES
    assert data["status"] in EQUIPMENT_STATUSES


def assert_waste_log(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["menu_day_id"])
    assert is_valid_uuid(data["food_batch_id"])
    assert isinstance(data["servings_wasted"], int) and data["servings_wasted"] >= 1
    assert data["reason"] in WASTE_REASONS
    assert data["disposition"] in WASTE_DISPOSITIONS
    assert is_iso8601_timestamp(data["logged_at"])


def assert_batch_conservation(
    batch: Dict[str, Any], allocated: int, wasted_discard_compost: int, rescue_redirected: int = 0
) -> None:
    """PRD 3.3 conservation identity: quantity == allocated + wasted + remaining.

    RESCUE_REDIRECT servings reduce remaining (the food left the building) but
    are not kitchen waste; pass them separately.
    """
    expected_remaining = (
        batch["quantity_servings"] - allocated - wasted_discard_compost - rescue_redirected
    )
    assert batch["remaining_servings"] == expected_remaining, (
        f"conservation violated: quantity={batch['quantity_servings']}, "
        f"allocated={allocated}, wasted(D/C)={wasted_discard_compost}, "
        f"rescue_redirected={rescue_redirected}, "
        f"remaining={batch['remaining_servings']} (expected {expected_remaining})"
    )
