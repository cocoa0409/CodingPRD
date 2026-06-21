"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the common system fields (PRD §2.4) plus the
entity's own fields against the PRD. Domain invariant checkers verify the
reconciled-total relationships described in PRD §2.5 and §3.2.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["turf_area_sqft"], int) and data["turf_area_sqft"] > 0
    assert data["snow_zone"] in ("PRIORITY", "STANDARD", "EXEMPT")


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["annual_budget_cents"], int) and data["annual_budget_cents"] > 0
    assert data["billing_cycle"] in ("MONTHLY", "QUARTERLY")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert_contract_ledger_invariants(data)


def assert_contract_ledger_invariants(data: dict):
    """PRD §3.2: budget_remaining_cents is annual_budget_cents minus committed_cents."""
    assert data["budget_remaining_cents"] == data["annual_budget_cents"] - data["committed_cents"], (
        f"budget_remaining_cents ({data['budget_remaining_cents']}) must equal "
        f"annual_budget_cents ({data['annual_budget_cents']}) - committed_cents ({data['committed_cents']})"
    )


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["service_contract_id"], str)
    assert isinstance(data["site_id"], str)
    assert data["service_type"] in ("MOWING", "MULCH", "AERATION")
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY", "SEASONAL")
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] > 0
    assert data["status"] in ("ACTIVE", "PAUSED")


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["certified_for_snow"], bool)


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["shift_start_minute"], int)
    assert isinstance(data["shift_end_minute"], int)
    assert data["shift_end_minute"] > data["shift_start_minute"]
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert data["status"] in ("OPEN", "LOCKED")


def assert_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["service_plan_id"], str)
    assert isinstance(data["service_contract_id"], str)
    assert isinstance(data["route_schedule_id"], str)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["slot_start_minute"], int)
    assert isinstance(data["slot_duration_minute"], int) and data["slot_duration_minute"] > 0
    assert isinstance(data["estimated_charge_cents"], int)
    assert isinstance(data["final_charge_cents"], int)
    assert data["execution_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "WRITTEN_OFF")


def assert_addon(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert data["addon_type"] in ("IRRIGATION_TUNEUP", "MULCH_INSTALL", "AERATION_PASS")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["addon_charge_cents"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED")


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["hourly_usage_cost_cents"], int) and data["hourly_usage_cost_cents"] > 0
    assert isinstance(data["service_interval_hours"], int) and data["service_interval_hours"] > 0
    assert isinstance(data["accumulated_usage_minutes"], int) and data["accumulated_usage_minutes"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["equipment_asset_id"], str)
    assert isinstance(data["service_visit_id"], str)
    assert data["window_end_minute"] > data["window_start_minute"]
    assert data["reserved_minutes"] == data["window_end_minute"] - data["window_start_minute"]
    assert isinstance(data["usage_cost_cents"], int)
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")


def assert_storm_event(data: dict):
    _assert_common(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["snowfall_inches"], int) and data["snowfall_inches"] >= 0
    assert isinstance(data["dispatch_charge_cents"], int)
    assert data["status"] in ("REPORTED", "DISPATCHED", "RESOLVED", "STOOD_DOWN")


def assert_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert isinstance(data["score"], int)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in ("PENDING", "PASSED", "REWORK_REQUIRED", "FAILED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["service_contract_id"], str)
    assert isinstance(data["period_label"], str)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"], (
        "total_cents must equal subtotal_cents + tax_cents (PRD §3.10)"
    )
    assert isinstance(data["line_item_count"], int) and data["line_item_count"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
