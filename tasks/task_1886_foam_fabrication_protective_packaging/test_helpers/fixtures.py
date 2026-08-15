"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Customer-role calls that are ownership-gated (approve / release create /
release cancel) always thread the acting customer's id through
make_customer_headers (PRD §2.1).

Default geometry (used by most pricing tests): part 10x8 in on a 108x48x2 in
sheet at 250 cents/board-foot nests to 52 parts per sheet (rotated
orientation); the spec defaults (5 lb, 30 in drop, 60 g) require an ILD of 50
against a material with ILD 130.
"""
from typing import Dict, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_confirm_payload,
    create_customer_payload,
    create_cut_program_payload,
    create_drop_test_payload,
    create_inventory_program_payload,
    create_material_payload,
    create_package_spec_payload,
    create_production_order_payload,
    create_release_order_payload,
    create_scrap_batch_payload,
    create_tooling_payload,
)
from .test_users import TEST_USERS, make_customer_headers

# Short aliases for the shared role-header dicts.
ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
DESIGN = TEST_USERS["design_engineer_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
PLANT = TEST_USERS["plant_manager_headers"]

# Laboratory bookings used across setups. The 09:00-10:00 booking is the
# standard validation slot; a second booking must respect the 30-minute
# laboratory buffer (PRD §2.8), so it starts at 10:30.
LAB_SLOT_A = ("2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
LAB_SLOT_B = ("2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z")

# Default machine confirmation window and the default replenishment window
# (half-open intervals on distinct days/machines do not interfere).
CONFIRM_WINDOW = ("DIE-1", "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
REPLENISH_WINDOW = ("DIE-1", "2026-08-04T08:00:00Z", "2026-08-04T09:00:00Z")


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), SALES)
    )


def create_material(**overrides) -> dict:
    return get_success_data(
        api_client.create_material(create_material_payload(**overrides), PLANT)
    )


def patch_material(material_id: str, **fields) -> dict:
    return get_success_data(api_client.patch_material(material_id, fields, PLANT))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, PLANT))


# ---------------------------------------------------------------------------
# Package specification lifecycle
# ---------------------------------------------------------------------------

def create_spec(customer_id: str, material_id: str, **overrides) -> dict:
    """Create a DRAFT package spec (required_ild_lb computed at creation)."""
    return get_success_data(
        api_client.create_package_spec(
            create_package_spec_payload(customer_id, material_id, **overrides), SALES,
        )
    )


def get_spec(spec_id: str) -> dict:
    return get_success_data(api_client.get_package_spec(spec_id, DESIGN))


def patch_spec(spec_id: str, **fields) -> dict:
    return get_success_data(api_client.patch_package_spec(spec_id, fields, SALES))


def submit_spec(spec_id: str) -> dict:
    return get_success_data(api_client.submit_spec(spec_id, SALES))


def begin_validation(spec_id: str) -> dict:
    return get_success_data(api_client.begin_validation(spec_id, QUALITY))


def approve_spec(spec_id: str, customer_id: str) -> dict:
    """Customer sign-off; ownership-gated, so thread the owning customer's id."""
    return get_success_data(
        api_client.approve_spec(spec_id, make_customer_headers(customer_id))
    )


def create_submitted_spec(
    customer: Optional[dict] = None,
    material: Optional[dict] = None,
    **spec_overrides,
) -> Tuple[dict, dict, dict]:
    """Customer + material + spec driven DRAFT -> SUBMITTED."""
    customer = customer or create_customer()
    material = material or create_material()
    spec = create_spec(customer["id"], material["id"], **spec_overrides)
    spec = submit_spec(spec["id"])
    return customer, material, spec


def create_validated_spec(
    customer: Optional[dict] = None,
    material: Optional[dict] = None,
    measured_peak_g: Optional[int] = None,
    lab_slot: Tuple[str, str] = LAB_SLOT_A,
    **spec_overrides,
) -> Tuple[dict, dict, dict]:
    """Spec driven to VALIDATED via one passing drop test at the current
    revision (measured peak defaults to exactly the spec's max_fragility_g,
    which passes because the comparison is inclusive). Pass lab_slot=LAB_SLOT_B
    when a second spec is validated within the same test, so its booking
    respects the laboratory's 30-minute buffer (PRD §2.8)."""
    customer, material, spec = create_submitted_spec(
        customer, material, **spec_overrides,
    )
    spec = begin_validation(spec["id"])
    measured = measured_peak_g if measured_peak_g is not None else spec["max_fragility_g"]
    drop_test = schedule_drop_test(spec["id"], *lab_slot)
    record_drop_test(drop_test["id"], measured)
    return customer, material, get_spec(spec["id"])


def create_approved_spec(
    customer: Optional[dict] = None,
    material: Optional[dict] = None,
    lab_slot: Tuple[str, str] = LAB_SLOT_A,
    **spec_overrides,
) -> Tuple[dict, dict, dict]:
    """Spec driven through validation to APPROVED by its owning customer."""
    customer, material, spec = create_validated_spec(
        customer, material, lab_slot=lab_slot, **spec_overrides,
    )
    assert spec["status"] == "VALIDATED", (
        f"spec should be VALIDATED after a passing drop test, got {spec['status']}"
    )
    spec = approve_spec(spec["id"], customer["id"])
    return customer, material, spec


# ---------------------------------------------------------------------------
# Drop tests
# ---------------------------------------------------------------------------

def schedule_drop_test(
    spec_id: str,
    scheduled_start: str = LAB_SLOT_A[0],
    scheduled_end: str = LAB_SLOT_A[1],
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_drop_test(
            create_drop_test_payload(spec_id, scheduled_start, scheduled_end,
                                     **overrides),
            QUALITY,
        )
    )


def record_drop_test(drop_test_id: str, measured_peak_g: int) -> dict:
    return get_success_data(
        api_client.record_drop_test(drop_test_id, measured_peak_g, QUALITY)
    )


def get_drop_test(drop_test_id: str) -> dict:
    return get_success_data(api_client.get_drop_test(drop_test_id, QUALITY))


# ---------------------------------------------------------------------------
# Cut programs and tooling
# ---------------------------------------------------------------------------

def create_cut_program(
    spec_id: str,
    method: str = "DIE_CUT",
    machine_seconds_per_part: Optional[int] = None,
    supersedes_cut_program_id: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> dict:
    """Create a DRAFT cut program. Reads the spec's current version to satisfy
    the optimistic-concurrency token unless expected_version is given."""
    if expected_version is None:
        expected_version = get_spec(spec_id)["version"]
    payload = create_cut_program_payload(
        spec_id,
        expected_version,
        method=method,
        machine_seconds_per_part=machine_seconds_per_part,
        supersedes_cut_program_id=supersedes_cut_program_id,
    )
    return get_success_data(api_client.create_cut_program(payload, DESIGN))


def nest_program(program_id: str) -> dict:
    return get_success_data(api_client.nest_cut_program(program_id, DESIGN))


def lock_program(program_id: str) -> dict:
    return get_success_data(api_client.lock_cut_program(program_id, DESIGN))


def create_tooling(cut_program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_tooling(
            create_tooling_payload(cut_program_id, **overrides), DESIGN,
        )
    )


def commission_tooling(tooling_id: str) -> dict:
    return get_success_data(api_client.commission_tooling(tooling_id, DESIGN))


def get_tooling(tooling_id: str) -> dict:
    return get_success_data(api_client.get_tooling(tooling_id, DESIGN))


def create_locked_die_program(spec_id: str, **tooling_overrides) -> Tuple[dict, dict]:
    """DIE_CUT program driven to LOCKED with an IN_SERVICE die.
    Returns (program, tooling). The spec must be SUBMITTED or beyond."""
    program = create_cut_program(spec_id, method="DIE_CUT")
    program = nest_program(program["id"])
    tooling = create_tooling(program["id"], **tooling_overrides)
    tooling = commission_tooling(tooling["id"])
    program = lock_program(program["id"])
    return program, tooling


def create_locked_cnc_program(
    spec_id: str, machine_seconds_per_part: int = TEST_DEFAULTS["CNC_MACHINE_SECONDS_PER_PART"],
) -> dict:
    """CNC_ROUTE program driven to LOCKED (no tooling involved)."""
    program = create_cut_program(
        spec_id, method="CNC_ROUTE",
        machine_seconds_per_part=machine_seconds_per_part,
    )
    program = nest_program(program["id"])
    return lock_program(program["id"])


# ---------------------------------------------------------------------------
# Production orders
# ---------------------------------------------------------------------------

def create_quoted_order(spec_id: str, cut_program_id: str, qty: int) -> dict:
    return get_success_data(
        api_client.create_production_order(
            create_production_order_payload(spec_id, cut_program_id, qty), SALES,
        )
    )


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_production_order(order_id, SALES))


def confirm_order(
    order_id: str,
    machine_id: str = CONFIRM_WINDOW[0],
    window_start: str = CONFIRM_WINDOW[1],
    window_end: str = CONFIRM_WINDOW[2],
) -> dict:
    return get_success_data(
        api_client.confirm_production_order(
            order_id, create_confirm_payload(machine_id, window_start, window_end),
            SALES,
        )
    )


def start_order(order_id: str) -> dict:
    return get_success_data(api_client.start_production_order(order_id, PLANT))


def complete_order(order_id: str) -> dict:
    return get_success_data(api_client.complete_production_order(order_id, PLANT))


def cancel_order(order_id: str) -> dict:
    return get_success_data(api_client.cancel_production_order(order_id, SALES))


def create_completed_customer_order(
    spec_id: str,
    cut_program_id: str,
    qty: int,
    machine_id: str = CONFIRM_WINDOW[0],
    window_start: str = CONFIRM_WINDOW[1],
    window_end: str = CONFIRM_WINDOW[2],
) -> dict:
    """CUSTOMER order driven QUOTED -> CONFIRMED -> IN_PROGRESS -> COMPLETED."""
    order = create_quoted_order(spec_id, cut_program_id, qty)
    order = confirm_order(order["id"], machine_id, window_start, window_end)
    order = start_order(order["id"])
    return complete_order(order["id"])


# ---------------------------------------------------------------------------
# Inventory programs and release orders
# ---------------------------------------------------------------------------

def create_inventory_program(
    customer_id: str, spec_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_inventory_program(
            create_inventory_program_payload(customer_id, spec_id, **overrides), SALES,
        )
    )


def get_program(program_id: str) -> dict:
    return get_success_data(api_client.get_inventory_program(program_id, PLANT))


def activate_program(program_id: str) -> dict:
    return get_success_data(api_client.activate_program(program_id, SALES))


def create_active_program(
    customer_id: str, spec_id: str, **overrides
) -> dict:
    program = create_inventory_program(customer_id, spec_id, **overrides)
    return activate_program(program["id"])


def replenish_and_complete(
    program_id: str,
    qty: int,
    machine_id: str = REPLENISH_WINDOW[0],
    window_start: str = REPLENISH_WINDOW[1],
    window_end: str = REPLENISH_WINDOW[2],
) -> dict:
    """Manual replenish -> confirm -> start -> complete; the program's
    on_hand_qty and produced_qty increase by qty."""
    order = get_success_data(api_client.replenish_program(program_id, qty, PLANT))
    order = confirm_order(order["id"], machine_id, window_start, window_end)
    order = start_order(order["id"])
    return complete_order(order["id"])


def create_release(
    program_id: str,
    qty: int,
    customer_id: str,
    requested_ship_date: str = "2026-08-10T00:00:00Z",
) -> dict:
    """Release creation is ownership-gated: thread the owning customer's id."""
    return get_success_data(
        api_client.create_release_order(
            create_release_order_payload(program_id, qty, requested_ship_date),
            make_customer_headers(customer_id),
        )
    )


def get_release(release_id: str) -> dict:
    return get_success_data(api_client.get_release_order(release_id, PLANT))


def allocate_release(release_id: str) -> dict:
    return get_success_data(api_client.allocate_release(release_id, PLANT))


def setup_stocked_program(
    pricing_mode: str = "CURRENT",
    max_stock_qty: int = 1000,
    reorder_point_qty: int = 200,
    min_release_qty: int = 50,
    stock_qty: int = 1000,
    method: str = "DIE_CUT",
    machine_id: str = REPLENISH_WINDOW[0],
    window_start: str = REPLENISH_WINDOW[1],
    window_end: str = REPLENISH_WINDOW[2],
) -> dict:
    """Full chain: approved spec + locked cut program + ACTIVE inventory
    program stocked to `stock_qty` units via a completed replenishment order.

    Returns a context dict with customer, material, spec, program (the locked
    cut program), tooling (None for CNC_ROUTE), inventory_program, and the
    completed replenishment production order."""
    customer, material, spec = create_approved_spec()
    if method == "DIE_CUT":
        cut_program, tooling = create_locked_die_program(spec["id"])
    else:
        cut_program, tooling = create_locked_cnc_program(spec["id"]), None
    program = create_active_program(
        customer["id"], spec["id"],
        pricing_mode=pricing_mode,
        max_stock_qty=max_stock_qty,
        reorder_point_qty=reorder_point_qty,
        min_release_qty=min_release_qty,
    )
    stock_order = replenish_and_complete(
        program["id"], stock_qty, machine_id, window_start, window_end,
    )
    return {
        "customer": customer,
        "material": material,
        "spec": get_spec(spec["id"]),
        "cut_program": cut_program,
        "tooling": tooling,
        "program": get_program(program["id"]),
        "stock_order": stock_order,
    }


# ---------------------------------------------------------------------------
# Scrap recycling
# ---------------------------------------------------------------------------

def create_scrap_batch(
    production_order_id: str, gross_weight_lb: float, contamination_pct: float,
) -> dict:
    return get_success_data(
        api_client.create_scrap_batch(
            create_scrap_batch_payload(
                production_order_id, gross_weight_lb, contamination_pct,
            ),
            PLANT,
        )
    )


def process_scrap_batch(batch_id: str) -> dict:
    return get_success_data(api_client.process_scrap_batch(batch_id, PLANT))


def credit_scrap_batch(batch_id: str) -> dict:
    return get_success_data(api_client.credit_scrap_batch(batch_id, PLANT))


def create_completed_scrap_source(
    qty: int = 500, method: str = "CNC_ROUTE", material_overrides: Optional[Dict] = None,
) -> dict:
    """Approved spec + locked program + one COMPLETED customer order, ready
    for offcut collection. Returns a context dict."""
    customer, material, spec = create_approved_spec(
        material=create_material(**(material_overrides or {}))
    )
    if method == "DIE_CUT":
        cut_program, tooling = create_locked_die_program(spec["id"])
    else:
        cut_program, tooling = create_locked_cnc_program(spec["id"]), None
    order = create_completed_customer_order(
        spec["id"], cut_program["id"], qty,
        machine_id="CNC-1" if method == "CNC_ROUTE" else "DIE-1",
    )
    return {
        "customer": customer,
        "material": material,
        "spec": spec,
        "cut_program": cut_program,
        "tooling": tooling,
        "order": order,
    }
