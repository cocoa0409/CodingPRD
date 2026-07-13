"""Composite setup helpers for the Marine Dealer API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before each
test. Helpers use the lenient get_success_data() validator so a broken setup
surfaces as a clear "Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_unit_payload,
    create_floor_plan_payload,
    create_deal_payload,
    create_consignment_payload,
    create_service_bay_payload,
    create_repair_order_payload,
    create_service_line_payload,
    create_part_payload,
    create_berth_payload,
    create_slip_reservation_payload,
)

MANAGER = TEST_USERS["manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, MANAGER))


# --------------------------------------------------------------------------
# Unit
# --------------------------------------------------------------------------
def create_unit(**overrides) -> dict:
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), MANAGER))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_unit(unit_id, MANAGER))


def create_available_unit(**overrides) -> dict:
    """Create a unit and list it for sale (INTAKE -> AVAILABLE)."""
    unit = create_unit(**overrides)
    return get_success_data(api_client.list_unit_for_sale(unit["id"], MANAGER))


# --------------------------------------------------------------------------
# FloorPlan
# --------------------------------------------------------------------------
def open_floor_plan(unit: dict, **overrides) -> dict:
    """Open a floor-plan advance against `unit`, using the unit's current version."""
    payload = create_floor_plan_payload(unit["id"], unit["version"], **overrides)
    return get_success_data(api_client.create_floor_plan(payload, MANAGER))


def create_floor_planned_unit(fp_overrides=None, **unit_overrides):
    """A FLOOR_PLAN unit with one ACTIVE floor plan. Returns (fresh_unit, floor_plan)."""
    unit_overrides.setdefault("acquisition_type", "FLOOR_PLAN")
    unit = create_unit(**unit_overrides)
    fp = open_floor_plan(unit, **(fp_overrides or {}))
    return get_unit(unit["id"]), fp


# --------------------------------------------------------------------------
# Service bay / Part
# --------------------------------------------------------------------------
def create_service_bay(**overrides) -> dict:
    return get_success_data(api_client.create_service_bay(create_service_bay_payload(**overrides), MANAGER))


def create_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(**overrides), PARTS))


# --------------------------------------------------------------------------
# RepairOrder / ServiceLine
# --------------------------------------------------------------------------
def create_repair_order(unit_id: str, service_bay_id: str, **overrides) -> dict:
    payload = create_repair_order_payload(unit_id, service_bay_id, **overrides)
    return get_success_data(api_client.create_repair_order(payload, SERVICE))


def create_ro_scenario(ro_overrides=None, unit_overrides=None, bay_overrides=None):
    """Fresh unit + bay + OPEN repair order. Returns (unit, bay, repair_order)."""
    unit = create_unit(**(unit_overrides or {}))
    bay = create_service_bay(**(bay_overrides or {}))
    ro = create_repair_order(unit["id"], bay["id"], **(ro_overrides or {}))
    return unit, bay, ro


def add_service_line(repair_order_id: str, line_type: str, **overrides) -> dict:
    payload = create_service_line_payload(repair_order_id, line_type, **overrides)
    return get_success_data(api_client.create_service_line(payload, SERVICE))


def start_ro(repair_order_id: str) -> dict:
    return get_success_data(api_client.start_repair_order(repair_order_id, SERVICE))


def complete_ro(repair_order_id: str) -> dict:
    return get_success_data(api_client.complete_repair_order(repair_order_id, SERVICE))


def invoice_ro(repair_order_id: str) -> dict:
    return get_success_data(api_client.invoice_repair_order(repair_order_id, SERVICE))


def reopen_ro(repair_order_id: str) -> dict:
    return get_success_data(api_client.reopen_repair_order(repair_order_id, SERVICE))


def create_completed_ro(ro_overrides=None, lines=None, unit_overrides=None, bay_overrides=None):
    """Unit + bay + RO carrying `lines`, walked to COMPLETED.

    `lines` is a list of (line_type, kwargs) tuples added while the RO is OPEN.
    Returns (unit, bay, repair_order_after_complete, service_lines).
    """
    unit, bay, ro = create_ro_scenario(ro_overrides, unit_overrides, bay_overrides)
    created_lines = []
    for line_type, kwargs in (lines or []):
        created_lines.append(add_service_line(ro["id"], line_type, **kwargs))
    start_ro(ro["id"])
    ro_done = complete_ro(ro["id"])
    return unit, bay, ro_done, created_lines


# --------------------------------------------------------------------------
# Deal
# --------------------------------------------------------------------------
def create_draft_deal(unit_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_deal(create_deal_payload(unit_id, **overrides), SALES))


def create_signed_deal(unit_overrides=None, deal_overrides=None):
    """AVAILABLE unit + SIGNED deal. Returns (unit, deal)."""
    unit = create_available_unit(**(unit_overrides or {}))
    deal = create_draft_deal(unit["id"], **(deal_overrides or {}))
    signed = get_success_data(api_client.sign_deal(deal["id"], SALES))
    return unit, signed


def fund_deal(deal_id: str) -> dict:
    return get_success_data(api_client.fund_deal(deal_id, MANAGER))


def create_funded_floor_planned_deal(fp_overrides=None, deal_overrides=None, **unit_overrides):
    """A FUNDED deal on a floor-planned unit (Unit SOLD, FloorPlan PAID_OFF).

    Returns (unit_id, floor_plan_id, deal_id).
    """
    unit_overrides.setdefault("acquisition_type", "FLOOR_PLAN")
    unit = create_unit(**unit_overrides)
    fp = open_floor_plan(unit, **(fp_overrides or {}))
    get_success_data(api_client.list_unit_for_sale(unit["id"], MANAGER))
    deal = create_draft_deal(unit["id"], **(deal_overrides or {}))
    get_success_data(api_client.sign_deal(deal["id"], SALES))
    fund_deal(deal["id"])
    return unit["id"], fp["id"], deal["id"]


# --------------------------------------------------------------------------
# Consignment
# --------------------------------------------------------------------------
def create_consignment(unit_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_consignment(create_consignment_payload(unit_id, **overrides), MANAGER))


# --------------------------------------------------------------------------
# Berth / SlipReservation
# --------------------------------------------------------------------------
def create_berth(**overrides) -> dict:
    return get_success_data(api_client.create_berth(create_berth_payload(**overrides), MANAGER))


def create_closed_berth(**overrides) -> dict:
    berth = create_berth(**overrides)
    return get_success_data(api_client.close_berth(berth["id"], MANAGER))


def create_reservation(berth_id: str, unit_id: str, **overrides) -> dict:
    payload = create_slip_reservation_payload(berth_id, unit_id, **overrides)
    return get_success_data(api_client.create_slip_reservation(payload, SERVICE))
