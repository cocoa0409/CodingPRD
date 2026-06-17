"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["billing_zip"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["shift_start_sec"], int)
    assert isinstance(data["shift_end_sec"], int)
    assert isinstance(data["backflow_certified"], bool)
    assert data["status"] in ("AVAILABLE", "INACTIVE")


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["site_address"], str)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")
    assert data["compliance_status"] in ("NON_COMPLIANT", "COMPLIANT")


def assert_system(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["static_psi"], int)
    assert isinstance(data["has_backflow_device"], bool)
    assert data["season_state"] in ("DORMANT", "ACTIVE", "WINTERIZED")
    assert data["backflow_status"] in ("UNTESTED", "CERTIFIED", "FAILED")
    assert data["lifecycle_state"] in ("OPERATIONAL", "DECOMMISSIONED")
    assert isinstance(data["zone_count"], int) and data["zone_count"] >= 0
    assert isinstance(data["committed_cost_cents"], int) and data["committed_cost_cents"] >= 0
    assert isinstance(data["provisional_winter_risk"], int)
    assert isinstance(data["assessed_winter_risk"], int)


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["zone_number"], int) and data["zone_number"] >= 1
    assert data["plant_type"] in ("TURF", "SHRUB", "DRIP", "ROTOR")
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert isinstance(data["gpm_per_head"], int) and data["gpm_per_head"] >= 1
    assert data["zone_state"] in ("MAPPED", "ACTIVE", "ARCHIVED")


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert data["program_state"] in ("DRAFT", "ACTIVE", "STALE")
    assert isinstance(data["slots"], list)
    assert isinstance(data["total_run_minutes"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert data["quote_type"] in ("INSTALL", "REPAIR")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)
    assert data["quote_state"] in ("DRAFT", "SENT", "CHANGES_REQUESTED", "APPROVED", "REJECTED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert data["job_type"] in (
        "INSTALL", "STARTUP", "WINTERIZATION", "LEAK_REPAIR", "HEAD_REPAIR", "BACKFLOW_TEST",
    )
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 1
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert data["dispatch_status"] in ("UNSCHEDULED", "SCHEDULED", "EN_ROUTE", "ON_SITE")
    assert data["completion_status"] in (
        "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED",
    )


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert data["tier"] in ("BASIC", "PLUS", "PREMIUM")
    assert isinstance(data["visits_per_year"], int) and data["visits_per_year"] >= 1
    assert isinstance(data["annual_dues_cents"], int)
    assert data["plan_state"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_backflow_test(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["tester_technician_id"], str)
    assert isinstance(data["relief_open_psi"], int)
    assert isinstance(data["checkvalve_hold_psi"], int)
    assert data["result"] in ("PASS", "FAIL")


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["technician_id"], str)
    assert isinstance(data["route_date"], str)
    assert data["route_state"] in ("PLANNING", "DISPATCHED", "CLOSED")
    assert isinstance(data["stops_used"], int) and data["stops_used"] >= 0
    assert isinstance(data["minutes_committed"], int) and data["minutes_committed"] >= 0


def assert_route_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["arrival_start_sec"], int)
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 1
    assert data["stop_state"] in ("SCHEDULED", "REMOVED")
