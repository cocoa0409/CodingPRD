"""Dedicated tests for difficulty-design instances that don't naturally
fall into another file. Each test cites the PRD sentence underlying the
rule the instance exercises and is tagged with its difficulty rule_id /
instance.name."""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_work_order,
    activate_plan,
    advance_clock,
    api_client,
    complete_payload,
    complete_work_order,
    create_ad_hoc_work_order,
    create_equipment,
    create_plan,
    create_site,
    create_technician,
    create_template,
    create_work_order_payload,
    make_technician_headers,
    place_in_service,
    commission_equipment,
    run_sweep,
    setup_full_workorder_scenario,
    setup_two_periodic_plans_for_sweep_order,
    start_work_order,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Plan-generation evaluation order (Step 1 PERIODIC_TIME wins over Step 2)
# ---------------------------------------------------------------------------
def test_sweep_periodic_time_wins_over_periodic_usage_in_one_tick(
        api, site_manager_headers):
    """PRD §3.4: 'Step 1 — periodic-time plans. All ACTIVE plans of kind
    PERIODIC_TIME are considered, ordered by next_due_at ascending, with
    id ascending as a tie-break. ... Step 2 — periodic-usage plans. All
    ACTIVE plans of kind PERIODIC_USAGE are considered, ordered by id
    ascending. ... Across all four steps, at most one work order is
    created per equipment per sweep-tick invocation; if multiple plans
    for one equipment qualify, the first plan in the ordering above wins
    and the rest defer to the next tick.'

    Two ACTIVE plans on the same equipment: Plan A (PERIODIC_TIME)
    qualifies because clock advanced past next_due_at; Plan B
    (PERIODIC_USAGE) qualifies because usage_counter delta hit
    interval_usage. /sweep/run should create exactly ONE WO from Plan A
    (Step 1 wins).
    # difficulty: combinatorial_formula/plan_generation_mode_c_pinned_evaluation_order
    """
    bag = setup_two_periodic_plans_for_sweep_order()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    plan_a_id = bag["plan_a"]["id"]
    plan_b_id = bag["plan_b"]["id"]
    # Advance clock by exactly interval_days * 86400 = 86400s so Plan A is due.
    advance_clock(site_id, 86400)
    # Run the sweep
    run_sweep(site_id)
    # Equipment now has exactly ONE open WO (Plan A's).
    eq_after = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert eq_after["open_work_order_id"] is not None
    # Fetch the generated WO via the open id and verify source.
    wo = validate_success(
        api.get_work_order(
            site_id, eq_after["open_work_order_id"], site_manager_headers,
        ),
        expected_status=200,
    )
    assert wo["source"] == "PLAN_PERIODIC", \
        "PRD §3.4: plan-generation produces source=PLAN_PERIODIC"

    # Verify Plan A advanced and Plan B did NOT advance.
    plan_a_after = validate_success(
        api.get_plan(site_id, plan_a_id, site_manager_headers),
        expected_status=200,
    )
    plan_b_after = validate_success(
        api.get_plan(site_id, plan_b_id, site_manager_headers),
        expected_status=200,
    )
    assert plan_a_after["last_generated_at"] is not None
    # Plan B's last_generated_usage stays at its activation snapshot (100)
    # because the periodic-usage step never reached B in this tick.
    assert plan_b_after["last_generated_usage"] == 100, (
        "PRD §3.4: 'at most one work order is created per equipment per "
        "sweep-tick invocation; ... the rest defer to the next tick.'"
    )


def test_sweep_second_tick_creates_workorder_from_plan_b_after_first_completes(
        api, site_manager_headers):
    """PRD §3.4: 'Across all four steps, at most one work order is created
    per equipment per sweep-tick invocation; if multiple plans for one
    equipment qualify, the first plan in the ordering above wins and the
    rest defer to the next tick.'

    After completing the first WO and advancing the clock, the SECOND
    /sweep/run should create the deferred Plan B WO.
    # difficulty: combinatorial_formula/plan_generation_mode_c_pinned_evaluation_order
    """
    bag = setup_two_periodic_plans_for_sweep_order()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    plan_b_id = bag["plan_b"]["id"]
    tech_id = bag["technician"]["id"]

    advance_clock(site_id, 86400)
    run_sweep(site_id)
    eq_after_first = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    first_wo_id = eq_after_first["open_work_order_id"]
    # Drive that WO to COMPLETED so open_work_order_id clears.
    start_work_order(site_id, first_wo_id, tech_id)
    complete_work_order(site_id, first_wo_id, tech_id)
    # open_work_order_id now null; second sweep should generate Plan B's WO.
    advance_clock(site_id, 1)
    run_sweep(site_id)
    eq_after_second = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert eq_after_second["open_work_order_id"] is not None
    new_wo_id = eq_after_second["open_work_order_id"]
    assert new_wo_id != first_wo_id, \
        "Second tick must create a NEW WO from the deferred plan"
    plan_b_after = validate_success(
        api.get_plan(site_id, plan_b_id, site_manager_headers),
        expected_status=200,
    )
    assert plan_b_after["last_generated_usage"] == 110, (
        "PRD §3.4 Step 2: 'the plan's last_generated_usage is set to the "
        "equipment's current usage_counter'"
    )


# ---------------------------------------------------------------------------
# Equipment-open-work-order conservation (state-pair invariant)
# ---------------------------------------------------------------------------
def test_full_workorder_lifecycle_restores_equipment_state_pair(
        api, site_manager_headers):
    """PRD §3.6: 'On a successful start, `WorkOrder.started_at` is set to
    the current site clock if it was null, the equipment transitions
    from `IN_SERVICE` to `UNDER_MAINTENANCE`, `Equipment.open_work_order_id`
    is pinned to the work order's id, and an audit entry with `action`
    `WORK_ORDER_STATE_CHANGE` is appended.'
    PRD §3.6: 'the equipment transitions from `UNDER_MAINTENANCE` to
    `IN_SERVICE`, `Equipment.open_work_order_id` is cleared to null, and
    `Equipment.last_repair_completed_at` is set to the current site
    clock'.

    Conservation: start → complete → accept restores the equipment to
    (lifecycle_status='IN_SERVICE', open_work_order_id=null), exactly
    its pre-start state. The persistent residue is
    last_repair_completed_at.
    # difficulty: compensating_invariant/equipment_open_work_order_conservation
    """
    bag = setup_full_workorder_scenario(
        responsible_user_id="owner-conservation",
    )
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    tech_id = bag["technician"]["id"]
    template_id = bag["template"]["id"]

    pre = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert pre["lifecycle_status"] == "IN_SERVICE"
    assert pre["open_work_order_id"] is None

    wo = create_ad_hoc_work_order(site_id, eq_id, template_id)
    start_work_order(site_id, wo["id"], tech_id)
    complete_work_order(site_id, wo["id"], tech_id)
    accept_work_order(site_id, wo["id"], "owner-conservation")

    post = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert post["lifecycle_status"] == "IN_SERVICE", \
        "PRD §3.6 conservation: lifecycle restored to IN_SERVICE after CLOSED"
    assert post["open_work_order_id"] is None, \
        "PRD §3.6 conservation: open_work_order_id cleared by completion"
    # Persistent residue
    assert post["last_repair_completed_at"] is not None


# ---------------------------------------------------------------------------
# Additional coverage for under-tested difficulty instances
# ---------------------------------------------------------------------------
def test_workorder_cyclic_pause_resume_keeps_pause_reason_cleared(api):
    """PRD §3.6: 'On a successful resume, the active-minute timer
    restarts from the current site clock, and `pause_reason` is cleared
    to null.'

    This is the second test for the WO-cyclic instance: confirms that
    after several pause/resume rounds, pause_reason is null while status
    is IN_PROGRESS.
    # difficulty: non_linear_state_machine/work_order_pause_resume_cycle
    """
    from test_helpers import (
        pause_work_order, resume_work_order, setup_started_workorder,
    )
    bag = setup_started_workorder()
    site_id = bag["site"]["id"]
    wo_id = bag["work_order"]["id"]
    tech_id = bag["technician"]["id"]
    pause_work_order(site_id, wo_id, tech_id, "WAIT_INFO")
    resumed_a = resume_work_order(site_id, wo_id, tech_id)
    assert resumed_a["status"] == "IN_PROGRESS"
    assert resumed_a["pause_reason"] is None

    pause_work_order(site_id, wo_id, tech_id, "WAIT_VENDOR")
    resumed_b = resume_work_order(site_id, wo_id, tech_id)
    assert resumed_b["status"] == "IN_PROGRESS"
    assert resumed_b["pause_reason"] is None


def test_priority_pair_state_vs_evidence_second_case(api):
    """PRD §2.9: priority 5 (state, ERR_INVALID_STATE) precedes priority 8
    (evidence, ERR_EVIDENCE_MISSING). Second instance: /accept on an
    IN_PROGRESS WO (also wrong state for /accept) without a RepairRecord
    must surface ERR_INVALID_STATE.
    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_evidence
    """
    from test_helpers import (
        make_site_manager_headers, setup_started_workorder,
    )
    responsible_user_id = "owner-priority-pair"
    bag = setup_started_workorder(responsible_user_id=responsible_user_id)
    headers = make_site_manager_headers(responsible_user_id)
    res = api.accept_work_order(
        bag["site"]["id"], bag["work_order"]["id"], headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_priority_pair_cross_site_vs_busy_second_case(api,
                                                       dispatcher_headers):
    """PRD §2.9: priority 4 (cross-site reference) precedes priority 7
    (equipment-busy). Second instance: cross-site equipment_id with a
    template from another site, where the equipment also is NOT busy —
    the cross-site check still triggers.
    # difficulty: priority_pair_validation_conflict/business_safety_busy_vs_business_referential_cross_site
    """
    from test_helpers import (
        create_site, create_template, setup_full_workorder_scenario,
    )
    bag_a = setup_full_workorder_scenario()
    site_b = create_site()
    template_b = create_template(site_b["id"])
    res = api.create_work_order(
        bag_a["site"]["id"],
        create_work_order_payload(
            bag_a["equipment"]["id"], template_b["id"],  # cross-site template
        ),
        dispatcher_headers,
    )
    validate_error(res, "ERR_CROSS_SITE_REFERENCE", expected_status=422)


def test_requisition_issue_blocked_after_workorder_cancelled(api,
                                                              storekeeper_headers):
    """PRD §3.8: 'The work order must be in status PENDING, IN_PROGRESS,
    or PAUSED'. (Issuing on a CANCELLED WO is blocked at the state check.)

    Second instance for cross_entity_state_dependency /
    requisition_issue_requires_workorder_status. The first instance tested
    issuing a CANCELLED requisition; this one tests issuing a still-RESERVED
    requisition after its parent WO was cancelled — the WO-cancel cascade
    moves the requisition to CANCELLED, so the issue request fails on the
    requisition state check (ERR_INVALID_STATE).
    # difficulty: cross_entity_state_dependency/requisition_issue_requires_workorder_status
    """
    from test_helpers import (
        create_requisition, create_spare_part, setup_pending_workorder,
        TEST_USERS,
    )
    bag = setup_pending_workorder()
    spare = create_spare_part(bag["site"]["id"], stock_on_hand=10)
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 2,
    )
    api.cancel_work_order(
        bag["site"]["id"], bag["work_order"]["id"], {},
        TEST_USERS["dispatcher_headers"],
    )
    res = api.issue_requisition(
        bag["site"]["id"], bag["work_order"]["id"], req["id"],
        storekeeper_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_technician_selector_prefers_oldest_when_load_equal_second(
        api, dispatcher_headers):
    """PRD §3.4: 'Candidates are ranked by open_load ascending ..., with
    created_at ascending as the secondary key, and lexicographic ascending
    order of id as the final tie-break.'

    Second instance for technician_workload_aggregate_capacity: with both
    technicians at open_load=0, the older technician is selected.
    # difficulty: resource_temporal_overlap/technician_workload_aggregate_capacity
    """
    from test_helpers import setup_two_techs_for_aggregate_capacity
    bag = setup_two_techs_for_aggregate_capacity()
    res = api.create_work_order(
        bag["site"]["id"],
        create_work_order_payload(
            bag["equipment_1"]["id"], bag["template"]["id"],
        ),
        dispatcher_headers,
    )
    wo = validate_success(res, expected_status=201)
    # Both techs at open_load=0 → tie broken by created_at ASC, T_A wins.
    assert wo["assigned_technician_id"] == bag["technician_a"]["id"]


def test_stock_conservation_under_partial_returns(api, storekeeper_headers):
    """PRD §3.8: 'On a successful return, Requisition.returned_qty is
    increased by the body's returned_qty, SparePart.stock_on_hand is
    increased by the same'.

    Second instance for spare_part_stock_conservation: a partial-return
    sequence (return 2, then return 2) restores stock_on_hand to its
    pre-issue value.
    # difficulty: compensating_invariant/spare_part_stock_conservation
    """
    from test_helpers import (
        create_requisition, create_spare_part, issue_requisition,
        return_requisition, setup_pending_workorder, start_work_order,
    )
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"], stock_on_hand=10, reorder_point=0,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 4,
    )
    issue_requisition(bag["site"]["id"], bag["work_order"]["id"], req["id"])
    # PRD §3.8: return requires WO in IN_PROGRESS/PAUSED/COMPLETED-not-CLOSED.
    start_work_order(
        bag["site"]["id"], bag["work_order"]["id"], bag["technician"]["id"],
    )
    return_requisition(bag["site"]["id"], bag["work_order"]["id"],
                        req["id"], 2)
    return_requisition(bag["site"]["id"], bag["work_order"]["id"],
                        req["id"], 2)
    spare_after = validate_success(
        api.get_spare_part(bag["site"]["id"], spare["id"],
                            storekeeper_headers),
        expected_status=200,
    )
    assert spare_after["stock_on_hand"] == 10
    assert spare_after["stock_reserved"] == 0


def test_equipment_state_pair_after_cancel_path_restores_state(api,
                                                                site_manager_headers,
                                                                dispatcher_headers):
    """PRD §3.7: 'On a successful PENDING → CANCELLED cancellation, all
    RESERVED requisitions move to CANCELLED, decreasing
    SparePart.stock_reserved by the cancelled quantity, replenishment is
    re-evaluated for each affected part, and an audit entry is appended.'

    Second instance for equipment_open_work_order_conservation: cancel
    from PENDING also restores Equipment.open_work_order_id to null and
    leaves lifecycle_status unchanged at IN_SERVICE.
    # difficulty: compensating_invariant/equipment_open_work_order_conservation
    """
    from test_helpers import setup_pending_workorder
    bag = setup_pending_workorder()
    site_id = bag["site"]["id"]
    eq_id = bag["equipment"]["id"]
    pre = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert pre["lifecycle_status"] == "IN_SERVICE"
    assert pre["open_work_order_id"] == bag["work_order"]["id"]
    api.cancel_work_order(
        site_id, bag["work_order"]["id"], {}, dispatcher_headers,
    )
    post = validate_success(
        api.get_equipment(site_id, eq_id, site_manager_headers),
        expected_status=200,
    )
    assert post["lifecycle_status"] == "IN_SERVICE"
    assert post["open_work_order_id"] is None


def test_requisition_issue_depth_2_replenish_cascade(api, storekeeper_headers):
    """PRD §3.8: 'On a successful issue, ... stock_on_hand decreases by
    qty, and stock_reserved decreases by qty (the reservation is released
    because the parts are physically issued). The replenishment evaluator
    then runs: if available stock (stock_on_hand − stock_reserved) is at
    most reorder_point and replenish_pending was false, replenish_pending
    is set to true and the replenishment notification described in §2.10
    is emitted.'

    Cascade depth 2: Requisition RESERVED → ISSUED triggers
    SparePart.stock_on_hand and stock_reserved updates AND fires
    replenish_evaluator which may flip replenish_pending.
    # difficulty: transitive_cascade/parts_issue_depth_2_cascade
    """
    from test_helpers import (
        create_requisition, create_spare_part, issue_requisition,
        setup_pending_workorder,
    )
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"], stock_on_hand=12, reorder_point=5,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 4,
    )
    # Pre-issue: available = 12 - 4 = 8 > 5 → replenish_pending=false.
    issue_requisition(bag["site"]["id"], bag["work_order"]["id"], req["id"])
    # Post-issue: stock_on_hand=8, stock_reserved=0, available=8 > 5
    spare_after = validate_success(
        api.get_spare_part(bag["site"]["id"], spare["id"],
                            storekeeper_headers),
        expected_status=200,
    )
    assert spare_after["stock_on_hand"] == 8
    assert spare_after["stock_reserved"] == 0
    assert spare_after["replenish_pending"] is False


def test_requisition_issue_depth_2_below_threshold_flips_replenish(
        api, storekeeper_headers):
    """PRD §3.8: 'When available stock is at most reorder_point and
    replenish_pending is currently false, replenish_pending is set to
    true'.

    Second instance for parts_issue_depth_2_cascade: issue drops available
    to AT or below reorder_point, flipping replenish_pending to true.
    # difficulty: transitive_cascade/parts_issue_depth_2_cascade
    """
    from test_helpers import (
        create_requisition, create_spare_part, issue_requisition,
        setup_pending_workorder,
    )
    bag = setup_pending_workorder()
    spare = create_spare_part(
        bag["site"]["id"], stock_on_hand=12, reorder_point=5,
    )
    req = create_requisition(
        bag["site"]["id"], bag["work_order"]["id"], spare["id"], 10,
    )
    # Pre-issue: available = 12 - 10 = 2 ≤ 5; replenish_pending=true at reservation.
    issue_requisition(bag["site"]["id"], bag["work_order"]["id"], req["id"])
    spare_after = validate_success(
        api.get_spare_part(bag["site"]["id"], spare["id"],
                            storekeeper_headers),
        expected_status=200,
    )
    assert spare_after["stock_on_hand"] == 2
    assert spare_after["stock_reserved"] == 0
    # available = 2 ≤ 5 → replenish_pending stays true.
    assert spare_after["replenish_pending"] is True
