"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All six roles use opaque operator identity, so
the shared header constants are used for every call.

OCC note: adding a component mutates a recipe and advances its version
(PRD §2.8), so approve helpers always re-read the recipe and approve with the
current version rather than the create-time version.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_SCHEDULED_AT
from .factories import (
    add_blend_component_payload,
    create_blend_recipe_payload,
    create_customer_order_payload,
    create_dye_lot_payload,
    create_fiber_lot_payload,
    create_finished_roll_payload,
    create_lab_dip_payload,
    create_machine_assignment_payload,
    create_quality_test_payload,
    create_shade_band_payload,
    create_spinning_machine_payload,
    create_yarn_lot_payload,
)
from .test_users import TEST_USERS

PLANNER = TEST_USERS["mill_planner_headers"]
SUPERVISOR = TEST_USERS["spinning_supervisor_headers"]
OPERATOR = TEST_USERS["dye_house_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
REP = TEST_USERS["customer_service_rep_headers"]
ADMIN = TEST_USERS["mill_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5,
                     fiber_type="COTTON"):
    """Receive a fiber lot (born RECEIVED). Returns the FiberLot."""
    payload = create_fiber_lot_payload(
        fiber_type=fiber_type,
        received_weight_lbs=received_weight_lbs,
        unit_cost_per_lb=unit_cost_per_lb,
    )
    return get_success_data(api_client.create_fiber_lot(payload, PLANNER))


def create_draft_recipe(recipe_code=None, target_yarn_count_ne=20.0):
    """Create a DRAFT blend recipe. Returns the BlendRecipe."""
    payload = create_blend_recipe_payload(
        target_yarn_count_ne=target_yarn_count_ne
    )
    if recipe_code is not None:
        payload["recipe_code"] = recipe_code
    return get_success_data(api_client.create_blend_recipe(payload, PLANNER))


def add_component(recipe_id, fiber_lot_id, component_weight_lbs=100.0):
    """Add a fiber component to a DRAFT recipe. Returns the BlendComponent."""
    payload = add_blend_component_payload(fiber_lot_id, component_weight_lbs)
    return get_success_data(
        api_client.add_blend_component(recipe_id, payload, PLANNER)
    )


def get_recipe_version(recipe_id):
    """Read the recipe's current version (component adds advance it)."""
    recipe = get_success_data(api_client.get_blend_recipe(recipe_id, PLANNER))
    return recipe["version"]


def approve_recipe(recipe_id):
    """Approve a DRAFT recipe using its CURRENT version (OCC, PRD §2.8)."""
    version = get_recipe_version(recipe_id)
    return get_success_data(
        api_client.approve_blend_recipe(
            recipe_id, {"expected_recipe_version": version}, PLANNER
        )
    )


def reject_recipe(recipe_id):
    """Reject a DRAFT recipe. Returns the rejected BlendRecipe."""
    return get_success_data(api_client.reject_blend_recipe(recipe_id, PLANNER))


def create_spinning_machine(machine_code=None, min_ne=10.0, max_ne=30.0):
    """Register a spinning machine (born ACTIVE). Returns the SpinningMachine."""
    payload = create_spinning_machine_payload(
        supported_count_min_ne=min_ne, supported_count_max_ne=max_ne
    )
    if machine_code is not None:
        payload["machine_code"] = machine_code
    return get_success_data(api_client.create_spinning_machine(payload, ADMIN))


def create_shade_band(customer_code="ACME", color_code="NAVY-2B",
                      delta_e_tolerance=1.5):
    """Create a shade band (born ACTIVE). Returns the ShadeBand."""
    payload = create_shade_band_payload(
        customer_code=customer_code,
        color_code=color_code,
        delta_e_tolerance=delta_e_tolerance,
    )
    return get_success_data(api_client.create_shade_band(payload, REP))


def create_lab_dip(shade_band_id, measured_delta_e=1.0):
    """Submit a lab dip (born PENDING). Returns the LabDip."""
    payload = create_lab_dip_payload(
        shade_band_id, measured_delta_e=measured_delta_e
    )
    return get_success_data(api_client.create_lab_dip(payload, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 2: recipe + fiber hierarchies
# ---------------------------------------------------------------------------

def setup_approved_recipe(received_weight_lbs=500.0, unit_cost_per_lb=1.5,
                          component_weight_lbs=200.0, target_yarn_count_ne=20.0,
                          recipe_code=None):
    """Fiber lot + DRAFT recipe + one component + approval.

    Returns dict: fiber_lot, recipe (post-approval read), component.
    """
    fiber_lot = create_fiber_lot(
        received_weight_lbs=received_weight_lbs,
        unit_cost_per_lb=unit_cost_per_lb,
    )
    recipe = create_draft_recipe(
        recipe_code=recipe_code, target_yarn_count_ne=target_yarn_count_ne
    )
    component = add_component(recipe["id"], fiber_lot["id"], component_weight_lbs)
    approve_recipe(recipe["id"])
    approved = get_success_data(api_client.get_blend_recipe(recipe["id"], PLANNER))
    return {"fiber_lot": fiber_lot, "recipe": approved, "component": component}


def create_yarn_lot(recipe_id, spun_weight_lbs=180.0, actual_yarn_count_ne=20.0):
    """Record a spun yarn lot (born GREIGE). Returns the YarnLot."""
    payload = create_yarn_lot_payload(
        recipe_id,
        spun_weight_lbs=spun_weight_lbs,
        actual_yarn_count_ne=actual_yarn_count_ne,
    )
    return get_success_data(api_client.create_yarn_lot(payload, SUPERVISOR))


def setup_yarn_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5,
                   component_weight_lbs=200.0, spun_weight_lbs=180.0,
                   target_yarn_count_ne=20.0, actual_yarn_count_ne=20.0,
                   recipe_code=None):
    """Approved recipe + yarn lot + shade band, ready for dye submission.

    Returns dict: fiber_lot, recipe, component, yarn_lot, shade_band.
    """
    base = setup_approved_recipe(
        received_weight_lbs=received_weight_lbs,
        unit_cost_per_lb=unit_cost_per_lb,
        component_weight_lbs=component_weight_lbs,
        target_yarn_count_ne=target_yarn_count_ne,
        recipe_code=recipe_code,
    )
    yarn_lot = create_yarn_lot(
        base["recipe"]["id"],
        spun_weight_lbs=spun_weight_lbs,
        actual_yarn_count_ne=actual_yarn_count_ne,
    )
    shade_band = create_shade_band()
    return {**base, "yarn_lot": yarn_lot, "shade_band": shade_band}


# ---------------------------------------------------------------------------
# Tier 3: dye lot lifecycle
# ---------------------------------------------------------------------------

def create_dye_lot(yarn_lot_id, shade_band_id, vat_id="VAT-01",
                   scheduled_at=DEFAULT_SCHEDULED_AT, requested_yards=5000.0):
    """Submit a yarn lot for dyeing (born SUBMITTED). Returns the DyeLot."""
    payload = create_dye_lot_payload(
        yarn_lot_id,
        shade_band_id,
        vat_id=vat_id,
        scheduled_at=scheduled_at,
        requested_yards=requested_yards,
    )
    return get_success_data(api_client.create_dye_lot(payload, OPERATOR))


def start_dye_lot(dye_lot_id):
    return get_success_data(api_client.start_dye_lot(dye_lot_id, OPERATOR))


def record_quality_test(dye_lot_id, shrinkage_pct_provisional=3.0, hand_score=5,
                        shrinkage_pct_final=None):
    """Record a quality test; grade is computed at recording (PRD §3.5)."""
    payload = create_quality_test_payload(
        shrinkage_pct_provisional=shrinkage_pct_provisional,
        hand_score=hand_score,
    )
    if shrinkage_pct_final is not None:
        payload["shrinkage_pct_final"] = shrinkage_pct_final
    return get_success_data(
        api_client.create_quality_test(dye_lot_id, payload, INSPECTOR)
    )


def submit_shade(dye_lot_id):
    return get_success_data(api_client.submit_shade(dye_lot_id, OPERATOR))


def approve_dye_lot(dye_lot_id):
    return get_success_data(api_client.approve_dye_lot(dye_lot_id, INSPECTOR))


def reject_dye_lot(dye_lot_id):
    return get_success_data(api_client.reject_dye_lot(dye_lot_id, INSPECTOR))


def setup_dye_lot_in_dyeing(shrinkage_pct_provisional=None, hand_score=None,
                            requested_yards=5000.0, vat_id="VAT-01",
                            spun_weight_lbs=180.0):
    """Full chain through a DYEING dye lot (created + started).

    If shrinkage args are given, also records the quality test.
    Returns dict with the whole lineage.
    """
    ctx = setup_yarn_lot(spun_weight_lbs=spun_weight_lbs)
    dye_lot = create_dye_lot(
        ctx["yarn_lot"]["id"],
        ctx["shade_band"]["id"],
        vat_id=vat_id,
        requested_yards=requested_yards,
    )
    ctx["dye_lot"] = start_dye_lot(dye_lot["id"])
    ctx["quality_test"] = None
    if shrinkage_pct_provisional is not None:
        ctx["quality_test"] = record_quality_test(
            dye_lot["id"],
            shrinkage_pct_provisional=shrinkage_pct_provisional,
            hand_score=hand_score if hand_score is not None else 5,
        )
    return ctx


def setup_dye_lot_shade_pending(shrinkage_pct_provisional=3.0, hand_score=5,
                                shrinkage_pct_final=3.0,
                                requested_yards=5000.0, vat_id="VAT-01"):
    """Full chain through SHADE_PENDING with a recorded quality test.

    Defaults grade FIRST_QUALITY (3.0 < 5.0, hand 5 >= 3). The optional final
    shrinkage is recorded at test-creation time (PRD §3.5 allows it).
    Returns dict with the whole lineage.
    """
    ctx = setup_yarn_lot()
    dye_lot = create_dye_lot(
        ctx["yarn_lot"]["id"],
        ctx["shade_band"]["id"],
        vat_id=vat_id,
        requested_yards=requested_yards,
    )
    ctx["dye_lot"] = start_dye_lot(dye_lot["id"])
    payload = create_quality_test_payload(
        shrinkage_pct_provisional=shrinkage_pct_provisional,
        hand_score=hand_score,
    )
    if shrinkage_pct_final is not None:
        payload["shrinkage_pct_final"] = shrinkage_pct_final
    ctx["quality_test"] = get_success_data(
        api_client.create_quality_test(ctx["dye_lot"]["id"], payload, INSPECTOR)
    )
    ctx["dye_lot"] = submit_shade(ctx["dye_lot"]["id"])
    return ctx


def setup_approved_dye_lot(shrinkage_pct_provisional=3.0, hand_score=5,
                           shrinkage_pct_final=3.0, requested_yards=5000.0,
                           vat_id="VAT-01"):
    """Full chain through an APPROVED dye lot; the yarn lot is FINISHED.

    Returns dict with the whole lineage.
    """
    ctx = setup_yarn_lot()
    dye_lot = create_dye_lot(
        ctx["yarn_lot"]["id"],
        ctx["shade_band"]["id"],
        vat_id=vat_id,
        requested_yards=requested_yards,
    )
    ctx["dye_lot"] = start_dye_lot(dye_lot["id"])
    payload = create_quality_test_payload(
        shrinkage_pct_provisional=shrinkage_pct_provisional,
        hand_score=hand_score,
    )
    if shrinkage_pct_final is not None:
        payload["shrinkage_pct_final"] = shrinkage_pct_final
    ctx["quality_test"] = get_success_data(
        api_client.create_quality_test(ctx["dye_lot"]["id"], payload, INSPECTOR)
    )
    ctx["dye_lot"] = submit_shade(ctx["dye_lot"]["id"])
    ctx["dye_lot"] = approve_dye_lot(ctx["dye_lot"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: rolls and orders
# ---------------------------------------------------------------------------

def create_finished_roll(dye_lot_id, put_up_yards=1000.0, actual_yards=1000.0):
    """Cut a finished roll from an APPROVED dye lot (born AVAILABLE)."""
    payload = create_finished_roll_payload(
        dye_lot_id, put_up_yards=put_up_yards, actual_yards=actual_yards
    )
    return get_success_data(api_client.create_finished_roll(payload, OPERATOR))


def setup_available_roll(second_quality=False, put_up_yards=2000.0,
                         actual_yards=2000.0):
    """An AVAILABLE finished roll off an APPROVED dye lot.

    second_quality=True grades the dye lot SECOND_QUALITY (shrinkage 6.0,
    hand 4) so the roll inherits is_second_quality=true (PRD §3.6).
    Returns dict with the whole lineage plus "roll".
    """
    if second_quality:
        ctx = setup_approved_dye_lot(
            shrinkage_pct_provisional=6.0, hand_score=4, shrinkage_pct_final=6.0
        )
    else:
        ctx = setup_approved_dye_lot()
    ctx["roll"] = create_finished_roll(
        ctx["dye_lot"]["id"], put_up_yards=put_up_yards, actual_yards=actual_yards
    )
    return ctx


def create_customer_order(customer_code="ACME", color_code="NAVY-2B",
                          requested_yards=5000.0, yardage_tolerance_pct=None):
    """Open a customer order (born OPEN). Returns the CustomerOrder."""
    payload = create_customer_order_payload(
        customer_code=customer_code,
        color_code=color_code,
        requested_yards=requested_yards,
    )
    if yardage_tolerance_pct is not None:
        payload["yardage_tolerance_pct"] = yardage_tolerance_pct
    return get_success_data(api_client.create_customer_order(payload, REP))


def allocate_roll(order, roll_id):
    """Allocate a roll into an order with the order's CURRENT version (OCC).

    `order` may be a stale snapshot; the current version is re-read so the
    call isolates the behavior under test from version drift.
    Returns the allocate response's data (the updated CustomerOrder).
    """
    current = get_success_data(api_client.get_customer_order(order["id"], REP))
    return get_success_data(
        api_client.allocate_roll(
            order["id"],
            {"roll_id": roll_id, "expected_order_version": current["version"]},
            REP,
        )
    )


def setup_order_with_allocated_roll(requested_yards=5000.0,
                                    yardage_tolerance_pct=None,
                                    put_up_yards=2000.0, actual_yards=2000.0,
                                    second_quality=False):
    """OPEN/PARTIALLY_ALLOCATED order with one roll ALLOCATED.

    Returns dict with the whole lineage plus "order" (post-allocation read).
    """
    ctx = setup_available_roll(
        second_quality=second_quality,
        put_up_yards=put_up_yards,
        actual_yards=actual_yards,
    )
    order = create_customer_order(
        requested_yards=requested_yards,
        yardage_tolerance_pct=yardage_tolerance_pct,
    )
    allocate_roll(order, ctx["roll"]["id"])
    ctx["order"] = get_success_data(api_client.get_customer_order(order["id"], REP))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: spinning schedules
# ---------------------------------------------------------------------------

def setup_machine_with_yarn_lots(num_lots=2, target_yarn_count_ne=20.0,
                                 machine_min_ne=10.0, machine_max_ne=30.0,
                                 spun_weights=None):
    """Approved recipe + N yarn lots + one spinning machine.

    Returns dict: fiber_lot, recipe, machine, yarn_lots (list).
    """
    base = setup_approved_recipe(target_yarn_count_ne=target_yarn_count_ne)
    weights = spun_weights or [100.0 + 20.0 * i for i in range(num_lots)]
    yarn_lots = [
        create_yarn_lot(
            base["recipe"]["id"],
            spun_weight_lbs=weights[i],
            actual_yarn_count_ne=target_yarn_count_ne,
        )
        for i in range(num_lots)
    ]
    machine = create_spinning_machine(
        min_ne=machine_min_ne, max_ne=machine_max_ne
    )
    return {**base, "machine": machine, "yarn_lots": yarn_lots}


def schedule_assignment(machine_id, yarn_lot_id,
                        window_start="2026-08-14T08:00:00Z",
                        window_end="2026-08-14T12:00:00Z"):
    """Schedule a yarn lot onto a machine (born SCHEDULED)."""
    payload = create_machine_assignment_payload(
        machine_id, yarn_lot_id,
        window_start=window_start, window_end=window_end,
    )
    return get_success_data(
        api_client.create_machine_assignment(payload, SUPERVISOR)
    )
