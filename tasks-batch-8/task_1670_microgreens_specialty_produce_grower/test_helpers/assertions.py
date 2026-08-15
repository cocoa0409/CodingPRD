"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic field helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict):
    """PRD §2.4 — every primary resource carries id, created_at, updated_at,
    and a version that starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_money_cents(value, field="value"):
    """PRD §2.7 — all monetary amounts are integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}")


def expected_line_extension_cents(qty_kg, unit_price_cents_per_kg) -> int:
    """PRD §2.7/§3.5 — round_half_up(qty_kg * unit_price_cents_per_kg) to whole
    cents, computed with exact decimal arithmetic."""
    return int((Decimal(str(qty_kg)) * Decimal(int(unit_price_cents_per_kg)))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_germination_rate(germinated_count, seeds_sown_count) -> float:
    """PRD §3.2 — germinated / sown carried to four decimal places, half-up."""
    return float((Decimal(int(germinated_count)) / Decimal(int(seeds_sown_count)))
                 .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Per-entity structural assertions
# ---------------------------------------------------------------------------

def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["delivery_zone"], str) and data["delivery_zone"]
    assert_money_cents(data["credit_balance_cents"], "credit_balance_cents")
    assert isinstance(data["is_active"], bool)


def assert_variety(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["crop_category"] in (
        "MICROGREEN", "PETITE_GREEN", "EDIBLE_FLOWER", "SPECIALTY_HERB")
    assert isinstance(data["days_to_harvest"], int) and data["days_to_harvest"] > 0
    assert isinstance(data["expected_yield_grams_per_tray"], int)
    assert_money_cents(data["listed_price_cents_per_kg"], "listed_price_cents_per_kg")
    assert data["stage"] in ("TRIAL", "EVALUATION", "LISTED", "RETIRED")
    assert isinstance(data["min_order_grams"], int)


def assert_variety_trial(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["sow_date"], str) and data["sow_date"]
    assert isinstance(data["chef_panel_size"], int) and data["chef_panel_size"] >= 1
    assert data["avg_flavor_score"] is None or isinstance(
        data["avg_flavor_score"], (int, float))
    assert isinstance(data["yield_score"], (int, float))
    assert data["decision"] in ("PENDING", "ADOPTED", "REJECTED")


def assert_seed_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["received_date"], str) and data["received_date"]
    assert isinstance(data["seeds_on_hand_grams"], int)
    assert data["seeds_on_hand_grams"] >= 0
    assert data["status"] in ("QUARANTINE", "RELEASED", "BLOCKED", "DEPLETED")


def assert_germination_test(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["seed_lot_id"])
    assert isinstance(data["seeds_sown_count"], int) and data["seeds_sown_count"] > 0
    assert data["germinated_count"] is None or isinstance(data["germinated_count"], int)
    assert data["germination_rate"] is None or isinstance(
        data["germination_rate"], (int, float))
    assert data["result"] in ("PENDING", "PASS", "FAIL")


def assert_crop_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["planned_sow_date"], str) and data["planned_sow_date"]
    assert isinstance(data["planned_tray_count"], int) and data["planned_tray_count"] > 0
    assert isinstance(data["seed_grams_required"], int) and data["seed_grams_required"] > 0
    assert data["status"] in (
        "PLANNED", "SOWING", "GROWING", "READY", "HARVESTED", "CANCELLED")
    assert isinstance(data["base_harvest_kg"], (int, float))
    assert data["base_harvest_kg"] >= 0
    assert isinstance(data["sown_tray_count"], int) and data["sown_tray_count"] >= 0


def assert_tray_batch(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["crop_plan_id"])
    assert is_valid_uuid(data["seed_lot_id"])
    assert isinstance(data["tray_count"], int) and data["tray_count"] > 0
    assert isinstance(data["sown_at"], str) and data["sown_at"]
    assert isinstance(data["expected_harvest_date"], str) and data["expected_harvest_date"]
    assert data["status"] in (
        "SOWN", "GERMINATING", "GROWING", "READY", "HARVESTED", "FAILED")
    assert isinstance(data["harvested_kg"], (int, float))
    assert data["harvested_kg"] >= 0


def assert_food_safety_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["water_test_current"], bool)
    assert isinstance(data["sanitation_sop_version"], str)
    assert data["approved_at"] is None or is_iso8601_timestamp(data["approved_at"])
    assert data["status"] in ("DRAFT", "APPROVED", "SUSPENDED")


def assert_sanitation_log(data: dict):
    """PRD §2.4 — a sanitation log is an immutable, append-only record and
    carries only id and created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only log must not carry updated_at"
    assert "version" not in data, "append-only log must not carry version"
    assert is_valid_uuid(data["harvest_batch_id"])
    assert isinstance(data["surface_swab_passed"], bool)
    assert isinstance(data["wash_water_ppm"], int)
    assert isinstance(data["logged_by"], str) and data["logged_by"]


def assert_standing_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["effective_week_start"], str) and data["effective_week_start"]
    assert isinstance(data["change_cutoff_day"], int)
    assert 0 <= data["change_cutoff_day"] <= 6
    assert data["status"] in ("DRAFT", "CONFIRMED", "LOCKED", "CANCELLED")
    assert_money_cents(data["weekly_subtotal_cents"], "weekly_subtotal_cents")


def assert_order_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["standing_order_id"])
    assert is_valid_uuid(data["variety_id"])
    assert isinstance(data["qty_kg"], (int, float)) and data["qty_kg"] > 0
    assert_money_cents(data["unit_price_cents_per_kg"], "unit_price_cents_per_kg")
    assert_money_cents(data["line_extension_cents"], "line_extension_cents")
    assert data["fulfillment"] in (
        "PLANNED", "ALLOCATED", "SHORTED", "DELIVERED", "CREDITED")


def assert_delivery_route(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert_money_cents(data["min_stop_subtotal_cents"], "min_stop_subtotal_cents")
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")


def assert_delivery_stop(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["standing_order_id"])
    assert data["stop_subtotal_cents"] is None or isinstance(
        data["stop_subtotal_cents"], int)
    assert data["outcome"] in ("SCHEDULED", "INCLUDED", "SKIPPED", "DELIVERED")


def assert_spoilage_credit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["delivery_stop_id"])
    assert is_valid_uuid(data["order_item_id"])
    assert isinstance(data["credit_qty_kg"], (int, float)) and data["credit_qty_kg"] > 0
    assert data["pricing_variant"] in ("ORIGINAL_PAPER", "POST_HARVEST_PRICING")
    assert_money_cents(data["credit_cents"], "credit_cents")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_surplus_listing(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["variety_id"])
    assert is_valid_uuid(data["tray_batch_id"])
    assert isinstance(data["qty_kg"], (int, float)) and data["qty_kg"] > 0
    assert_money_cents(data["market_price_cents_per_kg"], "market_price_cents_per_kg")
    assert isinstance(data["market_date"], str) and data["market_date"]
    assert data["status"] in ("LISTED", "SOLD", "WITHDRAWN")
