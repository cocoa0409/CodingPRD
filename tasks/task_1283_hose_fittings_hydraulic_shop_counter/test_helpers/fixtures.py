"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
Every helper builds its preconditions from scratch through PRD-declared
endpoints; the server is restarted (empty database) before every test.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assembly_order_payload,
    create_coupling_payload,
    create_customer_payload,
    create_equipment_asset_payload,
    create_inspection_payload,
    create_reel_payload,
    create_service_dispatch_payload,
)
from .test_users import TEST_USERS

MANAGER = TEST_USERS["shop_manager_headers"]
COUNTER = TEST_USERS["counter_sales_headers"]
TECH = TEST_USERS["shop_technician_headers"]
FIELD = TEST_USERS["field_technician_headers"]


def unique_tag_serial(prefix: str = "TAG") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ─── Tier 1: single-resource creation ─────────────────

def create_customer(**overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), MANAGER))


def create_reel(**overrides):
    return get_success_data(
        api_client.create_reel(create_reel_payload(**overrides), MANAGER))


def create_coupling(**overrides):
    return get_success_data(
        api_client.create_coupling(create_coupling_payload(**overrides), MANAGER))


def create_equipment_asset(customer_id, **overrides):
    return get_success_data(api_client.create_equipment_asset(
        create_equipment_asset_payload(customer_id, **overrides), MANAGER))


def get_equipment_asset(asset_id):
    return get_success_data(api_client.get_equipment_asset(asset_id, MANAGER))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, MANAGER))


def get_reel(reel_id):
    return get_success_data(api_client.get_reel(reel_id, MANAGER))


def get_coupling(coupling_id):
    return get_success_data(api_client.get_coupling(coupling_id, MANAGER))


def get_assembly_order(order_id):
    return get_success_data(api_client.get_assembly_order(order_id, COUNTER))


def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER))


# ─── Tier 2/3: assembly order lifecycle progression ───

def create_assembly_order(customer_id, reel_id, **overrides):
    """Create a DRAFT order. Returns the created order."""
    return get_success_data(api_client.create_assembly_order(
        create_assembly_order_payload(customer_id, reel_id, **overrides), COUNTER))


def confirm_assembly_order(order_id, payload=None):
    return get_success_data(
        api_client.confirm_assembly_order(order_id, payload or {}, COUNTER))


def build_assembly_order(order_id, measured_crimp_diameter_mm=25.0,
                         actual_labor_minutes=10):
    return get_success_data(api_client.complete_build(order_id, {
        "measured_crimp_diameter_mm": measured_crimp_diameter_mm,
        "actual_labor_minutes": actual_labor_minutes,
    }, TECH))


def record_pressure_test(order_id, test_pressure_psi=4000, result="PASSED"):
    return get_success_data(api_client.record_pressure_test(order_id, {
        "test_pressure_psi": test_pressure_psi,
        "result": result,
    }, TECH))


def rework_assembly_order(order_id):
    return get_success_data(api_client.rework_assembly_order(order_id, TECH))


def tag_assembly_order(order_id, tag_serial=None):
    return get_success_data(api_client.tag_assembly_order(
        order_id, {"tag_serial": tag_serial or unique_tag_serial()}, TECH))


def complete_assembly_order(order_id):
    return get_success_data(api_client.complete_assembly_order(order_id, COUNTER))


def cancel_assembly_order(order_id):
    return get_success_data(api_client.cancel_assembly_order(order_id, COUNTER))


def create_confirmed_order(customer_id, reel_id, confirm_payload=None, **overrides):
    """DRAFT -> CONFIRMED. Returns the confirmed order."""
    order = create_assembly_order(customer_id, reel_id, **overrides)
    return confirm_assembly_order(order["id"], confirm_payload)


def create_built_order(customer_id, reel_id, measured_crimp_diameter_mm=25.0,
                       actual_labor_minutes=10, **overrides):
    """DRAFT -> CONFIRMED -> BUILT. Returns the built order."""
    order = create_confirmed_order(customer_id, reel_id, **overrides)
    return build_assembly_order(
        order["id"], measured_crimp_diameter_mm, actual_labor_minutes)


def create_test_passed_order(customer_id, reel_id, test_pressure_psi=4000,
                             measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10, **overrides):
    """DRAFT -> CONFIRMED -> BUILT -> TEST_PASSED."""
    order = create_built_order(
        customer_id, reel_id, measured_crimp_diameter_mm, actual_labor_minutes,
        **overrides)
    return record_pressure_test(order["id"], test_pressure_psi, "PASSED")


def create_tagged_order(customer_id, reel_id, tag_serial=None, **overrides):
    """DRAFT -> CONFIRMED -> BUILT -> TEST_PASSED -> TAGGED."""
    order = create_test_passed_order(customer_id, reel_id, **overrides)
    return tag_assembly_order(order["id"], tag_serial)


def create_completed_order(customer_id, reel_id, tag_serial=None, **overrides):
    """Full counter lifecycle through COMPLETED."""
    order = create_tagged_order(customer_id, reel_id, tag_serial, **overrides)
    return complete_assembly_order(order["id"])


# ─── Inspections ──────────────────────────────────────

def schedule_inspection(asset_id, expected_equipment_asset_version,
                        window_start="2026-08-10T00:00:00Z",
                        window_end="2026-08-11T00:00:00Z", **overrides):
    return get_success_data(api_client.create_inspection(
        asset_id,
        create_inspection_payload(
            expected_equipment_asset_version, window_start, window_end, **overrides),
        COUNTER))


def start_inspection(inspection_id):
    return get_success_data(api_client.start_inspection(inspection_id, FIELD))


def complete_inspection(inspection_id, result):
    return get_success_data(
        api_client.complete_inspection(inspection_id, {"result": result}, FIELD))


def list_inspections(asset_id):
    data, _meta = _validate_paginated(
        api_client.list_inspections(asset_id, MANAGER))
    return data


def _validate_paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ─── Service dispatches ───────────────────────────────

def create_service_dispatch(customer_id, van_id="VAN-1", **overrides):
    return get_success_data(api_client.create_service_dispatch(
        create_service_dispatch_payload(customer_id, van_id, **overrides), COUNTER))


def advance_service_dispatch(dispatch_id):
    return get_success_data(api_client.advance_service_dispatch(dispatch_id, FIELD))


def create_on_site_dispatch(customer_id, van_id="VAN-1", **overrides):
    """REQUESTED -> DISPATCHED -> ON_SITE."""
    dispatch = create_service_dispatch(customer_id, van_id, **overrides)
    advance_service_dispatch(dispatch["id"])
    return advance_service_dispatch(dispatch["id"])
