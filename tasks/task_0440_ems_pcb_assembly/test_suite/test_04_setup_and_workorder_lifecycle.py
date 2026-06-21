"""Work-order setup, program gating, initial state, idempotency, and ship OCC.

Covers queue-B corner instances on initial state, setup action, wrong-BOM program,
already-kitted invalid transition, and ship OCC, plus the queue-A cross-entity
dependency requiring a VERIFIED line program at setup.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


# ---------------------------------------------------------------------------
# Initial state (queue B)
# ---------------------------------------------------------------------------

def test_new_work_order_initial_state(api):
    """PRD §3.5: "A new work order starts `PLANNED` with its computed counters —
    `kit_shortage_count`, `built_qty`, `passed_qty`, `first_pass_yield_pct`, and
    `material_cost_cents` — all at zero, and its `line_program_id` null until setup."

    Design: Corner/state_machines/new_workorder_initial_state_planned
    """
    part = fx.create_part(standard_cost_cents=20)
    fx.create_approved_avl(part["id"])
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    wo = validate_success(api.create_work_order(
        f.create_work_order_payload(bom["id"], planned_qty=3), PP), expected_status=201)
    assert wo["status"] == "PLANNED", wo
    assert wo["built_qty"] == 0, wo
    assert wo["material_cost_cents"] == 0, wo


# ---------------------------------------------------------------------------
# Setup action and program gating (queue B + queue A)
# ---------------------------------------------------------------------------

def test_setup_assigns_verified_program(api):
    """PRD §3.6: "On success the work order records the assigned `line_program_id` and
    transitions from `KITTED` to `SETUP`."

    Design: Corner/endpoints/setup_assigns_line_program
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    program = fx.create_verified_program(bom["id"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=1)
    result = validate_success(api.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    assert result["status"] == "SETUP", result
    assert result["line_program_id"] == program["id"], result


def test_setup_unverified_program_rejected(api):
    """PRD §3.6: "A `ProductionPlanner` may set up a work order only while it is
    `KITTED`, naming a `line_program_id` whose program is `VERIFIED` and whose own
    `bom_id` matches the work order's `bom_id`. If the named program is unverified or
    targets a different bill of materials, setup is rejected with
    `ERR_PROGRAM_NOT_READY` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/workorder_setup_requires_verified_lineprogram
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    program = fx.create_unverified_program(bom["id"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=1)
    validate_error(api.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP),
                   ApiErrorId.ERR_PROGRAM_NOT_READY.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "KITTED", fetched


def test_setup_program_wrong_bom_rejected(api):
    """PRD §3.6: "naming a `line_program_id` whose program is `VERIFIED` and whose own
    `bom_id` matches the work order's `bom_id`. If the named program is unverified or
    targets a different bill of materials, setup is rejected with
    `ERR_PROGRAM_NOT_READY` (HTTP 422)."

    Design: Corner/endpoints/setup_program_wrong_bom_rejected
    """
    # WO on BOM-X; a VERIFIED program on a different BOM-Y.
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom_x = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    bom_y = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    program_y = fx.create_verified_program(bom_y["id"])
    wo = fx.create_kitted_work_order(part["id"], bom_x["id"], planned_qty=1)
    validate_error(api.setup_work_order(wo["id"], f.setup_payload(program_y["id"]), PP),
                   ApiErrorId.ERR_PROGRAM_NOT_READY.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "KITTED", fetched


def test_setup_verified_matching_program_with_separate_program(api):
    """PRD §3.6: "naming a `line_program_id` whose program is `VERIFIED` and whose own
    `bom_id` matches the work order's `bom_id`. ... On success the work order records
    the assigned `line_program_id` and transitions from `KITTED` to `SETUP`."

    Companion to the wrong-BOM rejection: a VERIFIED program that DOES match the WO's
    bom_id is accepted, confirming the dependency gates on the matching VERIFIED state.

    Design: Difficulty/cross_entity_state_dependency/workorder_setup_requires_verified_lineprogram
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    program = fx.create_verified_program(bom["id"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=1)
    result = validate_success(api.setup_work_order(wo["id"], f.setup_payload(program["id"]), PP))
    assert result["status"] == "SETUP", result


# ---------------------------------------------------------------------------
# Already-kitted invalid transition (queue B)
# ---------------------------------------------------------------------------

def test_kit_already_kitted_rejected(api):
    """PRD §3.5: "A `ProductionPlanner` may kit a work order only while it is
    `PLANNED` and only when its anchoring bill of materials is `RELEASED`."
    PRD §2.7: "for any state-transition operation, the target must currently be in a
    state from which the requested transition is defined; otherwise the request fails
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/kit_already_kitted_returns_invalid_state
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=20,
                                                  standard_cost_cents=20)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=1)
    validate_error(api.kit_work_order(wo["id"], PP), ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "KITTED", fetched


# ---------------------------------------------------------------------------
# Ship OCC (queue B)
# ---------------------------------------------------------------------------

def test_ship_stale_work_order_version_rejected(api):
    """PRD §2.6: "Shipping the finished units of a work order requires the request to
    carry `expected_work_order_version`, which must equal the target work order's
    current `version`. If another writer has advanced the work order's version since
    the client last read it ... the ship request is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_ship_stale_work_order_version
    """
    _part, _bom, _prog, wo, units = fx.setup_at_test_work_order(planned_qty=1,
                                                                received_qty=10,
                                                                unit_cost_cents=10,
                                                                standard_cost_cents=10)
    fx.record_result(units[0]["id"], "PASS")
    finalized = get_success_data(api.finalize_test(wo["id"], QE))
    stale_version = finalized["version"] - 1
    validate_error(api.ship_work_order(wo["id"], f.ship_payload(stale_version), PP),
                   ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value)
