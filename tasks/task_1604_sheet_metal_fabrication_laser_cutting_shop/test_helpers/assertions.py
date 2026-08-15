"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.5 primary-resource system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only(data: dict, what: str):
    """PRD §2.5 append-only exception: only id + created_at are carried."""
    assert is_valid_uuid(data.get("id", "")), f"{what} id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{what} created_at must be ISO 8601 UTC"
    )
    assert "version" not in data, f"{what} must not carry version (append-only)"
    assert "updated_at" not in data, f"{what} must not carry updated_at (append-only)"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["scrap_credit_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_material_grade(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["alloy_family"] in ("ALUMINUM", "CARBON_STEEL", "STAINLESS")
    assert isinstance(data["density_g_per_cm3"], (int, float))
    assert isinstance(data["hardness_factor"], (int, float))
    assert isinstance(data["base_cut_rate_cents_per_sec"], (int, float))
    assert isinstance(data["material_cost_cents_per_cm2"], (int, float))
    assert isinstance(data["scrap_rate_cents_per_cm2"], (int, float))
    assert isinstance(data["thickness_tiers"], list) and data["thickness_tiers"]
    assert isinstance(data["weld_compatible"], bool)
    assert isinstance(data["powder_compatible"], bool)


def assert_sheet_stock(data: dict):
    assert_common_fields(data)
    assert isinstance(data["grade_id"], str)
    assert isinstance(data["thickness_mm"], (int, float))
    assert isinstance(data["width_mm"], int)
    assert isinstance(data["height_mm"], int)
    assert data["kind"] in ("FULL_SHEET", "REMNANT")
    assert data["status"] in ("AVAILABLE", "CONSUMED", "SCRAPPED", "DROPPED_OFF")


def assert_machine(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["station"] in ("LASER", "BRAKE", "WELD", "POWDER")
    assert isinstance(data["shift_minutes_per_day"], int)
    assert data["status"] in ("ACTIVE", "DOWN")


def assert_outside_vendor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["process"] in ("PLATING", "ANODIZING")
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["base_cost_cents_per_part"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_quote(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["expedite_tier"] in ("STANDARD", "EXPEDITE", "RUSH")
    assert data["status"] in (
        "DRAFT", "PRICED", "SUBMITTED", "ACCEPTED", "EXPIRED", "REJECTED",
    )
    assert isinstance(data["quoted_subtotal_cents"], int)
    assert isinstance(data["quoted_expedite_cents"], int)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_quote_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["grade_id"], str)
    assert isinstance(data["bbox_width_mm"], int)
    assert isinstance(data["bbox_height_mm"], int)
    assert data["finish"] in ("NONE", "POWDER", "PLATING", "ANODIZING")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in ("ESTIMATED", "PRICED", "SUPERSEDED")


def assert_fabrication_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["expedite_tier"] in ("STANDARD", "EXPEDITE", "RUSH")
    assert data["status"] in (
        "NESTING", "NESTED", "IN_PRODUCTION", "AWAITING_OUTSIDE", "FINISHING",
        "INSPECTION", "COMPLETED", "CANCELLED", "ON_HOLD",
    )
    assert isinstance(data["committed_subtotal_cents"], int)
    assert isinstance(data["committed_total_cents"], int)
    assert isinstance(data["total_plate_area_cm2"], int)
    assert isinstance(data["scrap_credit_applied_cents"], int)
    assert data["payment_status"] in ("UNPAID", "PAID")


def assert_nest_sheet(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["sheet_stock_id"], str)
    assert isinstance(data["sheet_index"], int) and data["sheet_index"] >= 0
    assert isinstance(data["chargeable_area_cm2"], (int, float))
    assert isinstance(data["kerf_allowance_cm2"], (int, float))
    assert isinstance(data["plate_in_area_cm2"], (int, float))
    assert isinstance(data["yield_pct"], (int, float))


def assert_routing_step(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert data["station"] in ("LASER", "BRAKE", "WELD", "POWDER", "OUTSIDE_VENDOR")
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert isinstance(data["planned_minutes"], int)
    assert data["status"] in ("PENDING", "IN_PROGRESS", "COMPLETED", "SKIPPED")


def assert_inspection_report(data: dict):
    _assert_append_only(data, "inspection report")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert isinstance(data["flatness_deviation_mm"], (int, float))
    assert isinstance(data["measured_diagonal_mm"], (int, float))
    assert isinstance(data["dimensional_pass"], bool)
    assert data["result"] in ("PASS", "FAIL")


def assert_scrap_credit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sheet_stock_id"], str)
    assert isinstance(data["credited_area_cm2"], (int, float))
    assert isinstance(data["credit_cents"], int)
    assert data["status"] in ("POSTED", "APPLIED", "VOID")


def assert_audit_event(data: dict):
    _assert_append_only(data, "audit event")
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]


def assert_money_int(value, what: str):
    """PRD §2.6: all monetary values are integer cents."""
    assert isinstance(value, int), f"{what} must be integer cents, got {value!r}"
