"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full-quartet entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_paint_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["surface_kind"] in ("INTERIOR", "EXTERIOR", "BOTH")
    assert data["finish_type"] in ("FLAT", "EGGSHELL", "SATIN", "SEMI_GLOSS", "GLOSS")
    assert isinstance(data["price_per_gallon_cents"], int) and data["price_per_gallon_cents"] >= 1
    assert isinstance(data["coverage_sqft_per_gallon_per_coat"], int)
    assert data["coverage_sqft_per_gallon_per_coat"] >= 1
    assert isinstance(data["active"], bool)


def assert_crew_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["skill_level"] in ("APPRENTICE", "JOURNEYMAN", "MASTER")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 1
    assert isinstance(data["scheduled_day_count"], int) and data["scheduled_day_count"] >= 0
    assert isinstance(data["active"], bool)


def assert_equipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["equipment_kind"] in ("SPRAYER", "SCAFFOLD", "LIFT")
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["units_reserved"], int) and data["units_reserved"] >= 0


def assert_weather_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["window_date"], str) and len(data["window_date"]) > 0
    assert isinstance(data["forecast_temp_f"], int)
    assert isinstance(data["precipitation_pct"], int) and 0 <= data["precipitation_pct"] <= 100
    assert isinstance(data["exterior_suitable"], bool)


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str) and len(data["customer_id"]) > 0
    assert isinstance(data["site_address"], str)
    assert data["scope"] in ("INTERIOR", "EXTERIOR", "BOTH")
    assert isinstance(data["deposit_pct"], int) and 0 <= data["deposit_pct"] <= 100
    assert data["workflow_status"] in (
        "DRAFT", "ESTIMATED", "SCHEDULED", "IN_PROGRESS",
        "WALKTHROUGH_PENDING", "COMPLETED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL")
    for cents_field in (
        "estimate_material_cents", "estimate_labor_cents", "estimate_total_cents",
        "revised_total_cents", "deposit_due_cents", "amount_paid_cents", "balance_due_cents",
    ):
        assert isinstance(data[cents_field], int), f"{cents_field} must be int cents"
    assert isinstance(data["warranty_months"], int)


def assert_surface(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["label"], str)
    assert data["surface_kind"] in ("INTERIOR", "EXTERIOR")
    assert isinstance(data["area_sqft"], int) and data["area_sqft"] >= 1
    assert isinstance(data["coats"], int) and 1 <= data["coats"] <= 4
    assert data["prep_level"] in ("LIGHT", "STANDARD", "HEAVY", "RESTORATION")
    assert isinstance(data["paint_product_id"], str)
    assert data["status"] in ("PLANNED", "EXECUTED", "REMOVED")
    assert isinstance(data["color_locked"], bool)


def assert_color_selection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["surface_id"], str)
    assert isinstance(data["color_code"], str)
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["surface_id"], str)
    assert isinstance(data["gallons_required"], int) and data["gallons_required"] >= 0
    assert isinstance(data["material_cost_cents"], int)
    assert isinstance(data["labor_cost_cents"], int)
    assert isinstance(data["executed"], bool)


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert data["action"] in ("ADD_SURFACE", "REMOVE_SURFACE", "REVISE_SURFACE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["delta_total_cents"], int)


def assert_crew_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["crew_member_id"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["requires_exterior_weather"], bool)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE", "CANCELLED")
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1


def assert_walkthrough(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["punch_list_count"], int) and data["punch_list_count"] >= 0
    assert data["status"] in ("PENDING", "PASSED", "FAILED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["surface_id"], str)
    assert isinstance(data["description"], str)
    assert data["status"] in ("FILED", "APPROVED", "RESOLVED", "DENIED")
    assert isinstance(data["provisional_payout_cents"], int)


def assert_payment(data: dict):
    """Payment is an append-only ledger row: id + created_at only (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["project_id"], str)
    assert data["kind"] in ("DEPOSIT", "FINAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ("CAPTURED", "REFUNDED")
