"""Rework close costing and cascade, ECO lifecycle, segregation-of-duties, and the
validation-priority conflicts that surface on these flows.

Covers queue-A difficulty instances on tiered rework surcharge, the depth-4 rework
cascade, the cyclic ECO machine, the unit's parallel quality/disposition dimensions,
and the state-vs-safety / SoD-vs-shortage priority conflicts; plus queue-B corner
instances on close-blocked-by-open-rework, ECO-not-approved, self-approval SoD,
approve-without-submit, and the rework mid-tier surcharge boundary.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_process_engineer_headers, make_quality_engineer_headers,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]


# ---------------------------------------------------------------------------
# Tiered rework surcharge (queue A combinatorial mode a + queue B boundary)
# ---------------------------------------------------------------------------

def test_rework_high_tier_surcharge(api):
    """PRD §3.9: "when the base part cost exceeds 20,000 cents, the surcharge is 30
    percent of the base part cost, rounded half-up to whole cents. ... The
    `added_material_cost_cents` is the base part cost plus the selected surcharge."

    base 25000 (qty 10 @ 2500) -> HIGH_RATE 0.30 -> surcharge 7500 -> added 32500.

    Design: Difficulty/combinatorial_formula/rework_cost_tiered_handling_surcharge_mode_a
    """
    part, _bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=100, unit_cost_cents=2500, standard_cost_cents=2500)
    rwo = fx.open_rework_order(unit["id"], defect_code="SOLDER-BRIDGE")
    closed = validate_success(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 10, "pp-1"), PP))
    assert closed["added_material_cost_cents"] == 32500, closed


def test_rework_high_tier_marks_unit_reworked(api):
    """PRD §3.9: "sets the target unit's `quality_status` to `REWORKED` and increments
    its `rework_count` by one".

    Design: Difficulty/combinatorial_formula/rework_cost_tiered_handling_surcharge_mode_a
    """
    part, _bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=100, unit_cost_cents=2500, standard_cost_cents=2500)
    rwo = fx.open_rework_order(unit["id"], defect_code="SOLDER-BRIDGE")
    get_success_data(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 10, "pp-1"), PP))
    fetched = validate_success(api.get_unit(unit["id"], PP))
    assert fetched["quality_status"] == "REWORKED", fetched


def test_rework_low_tier_boundary_flat_surcharge(api):
    """PRD §3.9: "when the base part cost is 5,000 cents or less, the surcharge is a
    flat 1,500 cents ... The tier boundaries are inclusive on their upper edge: a base
    part cost of exactly 5,000 cents takes the flat surcharge".

    base exactly 5000 (qty 25 @ 200) -> flat 1500 -> added 6500.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_rework_mid_tier_boundary
    """
    part, _bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=100, unit_cost_cents=200, standard_cost_cents=200)
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN")
    closed = validate_success(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 25, "pp-1"), PP))
    assert closed["added_material_cost_cents"] == 6500, closed


# ---------------------------------------------------------------------------
# Depth-4 rework cascade (queue A transitive_cascade)
# ---------------------------------------------------------------------------

def _depth_four_setup(api):
    """1-unit WO, lot qty 10 @ 200; start consumes 1 (remaining 9, material_cost 200).
    Returns (part, work_order, unit, lot_id, rework_order)."""
    from test_helpers import validate_paginated
    part, _bom, _prog, wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=10, unit_cost_cents=200, standard_cost_cents=200)
    # Fetch the single lot for this part via the list endpoint.
    lots, _m = validate_paginated(
        api.list_inventory_lots(PP, params={"part_id": part["id"]}))
    lot_id = lots[0]["id"]
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN")
    return part, wo, unit, lot_id, rwo


def test_rework_close_cascade_lot_and_part_qty(api):
    """PRD §3.9: "consumes the replacement material from the replacement part's lots
    in first-in-first-out order, decrementing each drawn lot's `remaining_qty`; sets
    any lot whose `remaining_qty` reaches zero to `DEPLETED` and recomputes the
    affected parts' `available_qty`".

    Rework draws 5 from a lot that had 9 remaining after the build draw -> lot 4,
    part available_qty 4.

    Design: Difficulty/transitive_cascade/rework_close_depth_four_cascade
    """
    part, _wo, _unit, lot_id, rwo = _depth_four_setup(api)
    get_success_data(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 5, "pp-1"), PP))
    fetched_lot = validate_success(api.get_inventory_lot(lot_id, PP))
    assert fetched_lot["remaining_qty"] == 4, fetched_lot
    fetched_part = validate_success(api.get_part(part["id"], PP))
    assert fetched_part["available_qty"] == 4, fetched_part


def test_rework_close_cascade_cost_and_unit(api):
    """PRD §3.9: "rolls the `added_material_cost_cents` into the parent work order's
    `material_cost_cents`; sets the target unit's `quality_status` to `REWORKED` and
    increments its `rework_count` by one".

    Pre-rework material_cost 200 (1 @ 200); rework base 1000 (5 @ 200) -> flat 1500 ->
    added 2500 -> rolled WO material_cost 2700; unit REWORKED, rework_count 1.

    Design: Difficulty/transitive_cascade/rework_close_depth_four_cascade
    """
    part, wo, unit, _lot_id, rwo = _depth_four_setup(api)
    get_success_data(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 5, "pp-1"), PP))
    fetched_wo = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched_wo["material_cost_cents"] == 2700, fetched_wo
    fetched_unit = validate_success(api.get_unit(unit["id"], PP))
    assert fetched_unit["quality_status"] == "REWORKED", fetched_unit
    assert fetched_unit["rework_count"] == 1, fetched_unit


# ---------------------------------------------------------------------------
# Unit parallel quality / disposition dimensions (queue A non_linear_state_machine)
# ---------------------------------------------------------------------------

def test_rework_keeps_disposition_in_process(api):
    """PRD §3.7: "A unit carries two independent dimensions that evolve in parallel on
    the same record: `quality_status`, which tracks test and rework outcomes across
    `BUILT`, `PASS`, `FAIL`, and `REWORKED`, and `disposition`, which tracks where the
    physical board is across `IN_PROCESS`, `SHIPPED`, `SCRAPPED`, and `RETURNED`."
    PRD §3.9: "sets the target unit's `quality_status` to `REWORKED` and increments its
    `rework_count` by one".

    After rework close the unit is quality_status REWORKED while disposition stays
    IN_PROCESS — the two axes move independently.

    Design: Difficulty/non_linear_state_machine/unit_parallel_quality_and_disposition_dimensions
    """
    part, _bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=50, unit_cost_cents=100, standard_cost_cents=100,
        defect_code="TOMBSTONE")
    rwo = fx.open_rework_order(unit["id"], defect_code="TOMBSTONE")
    get_success_data(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 1, "pp-1"), PP))
    fetched = validate_success(api.get_unit(unit["id"], PP))
    assert fetched["quality_status"] == "REWORKED", fetched
    assert fetched["disposition"] == "IN_PROCESS", fetched


def test_abandon_scraps_unit_without_touching_quality(api):
    """PRD §3.9: "Abandoning sets the target unit's `disposition` to `SCRAPPED` and
    moves the rework order to `ABANDONED`, its other terminal state."

    Abandon drives disposition to SCRAPPED while quality_status stays FAIL — again the
    two dimensions evolve independently.

    Design: Difficulty/non_linear_state_machine/unit_parallel_quality_and_disposition_dimensions
    """
    part, _bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=50, unit_cost_cents=100, standard_cost_cents=100)
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN")
    abandoned = validate_success(api.abandon_rework_order(rwo["id"], PP))
    assert abandoned["status"] == "ABANDONED", abandoned
    fetched = validate_success(api.get_unit(unit["id"], PP))
    assert fetched["disposition"] == "SCRAPPED", fetched
    assert fetched["quality_status"] == "FAIL", fetched


# ---------------------------------------------------------------------------
# Cyclic ECO machine (queue A non_linear_state_machine)
# ---------------------------------------------------------------------------

def test_eco_reject_resubmit_approve_cycle(api):
    """PRD §3.9: "A rejected change is not dead: its author may resubmit it, moving it
    back from `REJECTED` to `SUBMITTED` under the same authorship check, forming the
    revise-and-resubmit cycle."
    PRD §3.9: "Approval moves it from `SUBMITTED` to `APPROVED`, recording the
    approver's `acting_user_id` as `approved_by_user_id`, and is permitted only when
    that acting identity differs from `authored_by_user_id`".

    Design: Difficulty/non_linear_state_machine/eco_reject_resubmit_cycle
    """
    bom = fx.create_draft_bom()
    eco = fx.author_eco(bom["id"], author_user_id="pe-1")
    fx.submit_eco(eco["id"], author_user_id="pe-1")
    get_success_data(api.reject_eco(eco["id"], QE))
    # Resubmit then approve by a different actor.
    fx.submit_eco(eco["id"], author_user_id="pe-1")
    approved = validate_success(api.approve_eco(
        eco["id"], f.eco_action_payload("qe-1"), make_quality_engineer_headers("qe-1")))
    assert approved["status"] == "APPROVED", approved
    assert approved["approved_by_user_id"] == "qe-1", approved


def test_eco_reject_returns_to_rejected(api):
    """PRD §3.9: "Rejection moves it from `SUBMITTED` to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/eco_reject_resubmit_cycle
    """
    bom = fx.create_draft_bom()
    submitted = fx.submitted_eco(bom["id"], author_user_id="pe-1")
    assert submitted["status"] == "SUBMITTED", submitted
    rejected = validate_success(api.reject_eco(submitted["id"], QE))
    assert rejected["status"] == "REJECTED", rejected


# ---------------------------------------------------------------------------
# ECO SoD and state guards (queue B)
# ---------------------------------------------------------------------------

def test_eco_self_approval_sod_violation(api):
    """PRD §3.9: "an approver who is the author is rejected with `ERR_SOD_VIOLATION`
    (HTTP 409)."

    Design: Corner/errors/eco_sod_violation_self_approve
    """
    bom = fx.create_draft_bom()
    eco = fx.submitted_eco(bom["id"], author_user_id="pe-1")
    # Approve with acting_user_id equal to the author.
    validate_error(api.approve_eco(eco["id"], f.eco_action_payload("pe-1"),
                                   make_quality_engineer_headers("pe-1")),
                   ApiErrorId.ERR_SOD_VIOLATION.value)
    fetched = validate_success(api.get_eco(eco["id"], QE))
    assert fetched["status"] == "SUBMITTED", fetched


def test_eco_approve_without_submit_invalid_state(api):
    """PRD §3.9: "The author submits it, moving it from `DRAFT` to `SUBMITTED`".
    PRD §3.9: "A `QualityEngineer` then either approves or rejects the submitted
    change. Approval moves it from `SUBMITTED` to `APPROVED`".
    PRD §2.7: "for any state-transition operation, the target must currently be in a
    state from which the requested transition is defined; otherwise the request fails
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/eco_approve_without_submit_invalid_state
    """
    bom = fx.create_draft_bom()
    eco = fx.author_eco(bom["id"], author_user_id="pe-1")  # still DRAFT
    validate_error(api.approve_eco(eco["id"], f.eco_action_payload("qe-1"),
                                   make_quality_engineer_headers("qe-1")),
                   ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_eco(eco["id"], QE))
    assert fetched["status"] == "DRAFT", fetched


def test_rework_close_eco_not_approved_rejected(api):
    """PRD §3.9: "when the rework names an `eco_id` — only when that engineering change
    is `APPROVED` (otherwise `ERR_REWORK_ECO_NOT_APPROVED`, HTTP 422)".

    Design: Corner/errors/rework_close_eco_not_approved_rejected
    """
    part, bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=10, unit_cost_cents=100, standard_cost_cents=100)
    eco = fx.submitted_eco(bom["id"], author_user_id="pe-1")  # SUBMITTED, not APPROVED
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN", eco_id=eco["id"])
    validate_error(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 1, "pp-1"), PP),
        ApiErrorId.ERR_REWORK_ECO_NOT_APPROVED.value)
    fetched = validate_success(api.get_rework_order(rwo["id"], PP))
    assert fetched["status"] == "OPEN", fetched


# ---------------------------------------------------------------------------
# Close blocked by open rework (queue B)
# ---------------------------------------------------------------------------

def test_close_work_order_blocked_by_open_rework(api):
    """PRD §3.8: "A `ProductionPlanner` may close a work order only while it is
    `PASSED`, and only when no rework order under that work order remains `OPEN`. If an
    open rework order still exists, closing is rejected with
    `ERR_OPEN_REWORK_BLOCKS_CLOSE` (HTTP 409)."

    Design: Corner/state_machines/workorder_close_blocked_by_open_rework
    """
    # 4-unit WO: 3 PASS, 1 FAIL -> reworked-closed -> REWORKED (FPY 3/4 = 75 >= 70).
    part, _bom, _prog, wo, units = fx.setup_at_test_work_order(planned_qty=4,
                                                               received_qty=50,
                                                               unit_cost_cents=100,
                                                               standard_cost_cents=100)
    fx.record_result(units[0]["id"], "PASS")
    fx.record_result(units[1]["id"], "PASS")
    fx.record_result(units[2]["id"], "PASS")
    fx.record_result(units[3]["id"], "FAIL", defect_code="OPEN")
    rwo1 = fx.open_rework_order(units[3]["id"], defect_code="OPEN")
    get_success_data(api.close_rework_order(
        rwo1["id"], f.close_rework_payload(part["id"], 1, "pp-1"), PP))
    get_success_data(api.finalize_test(wo["id"], QE))  # -> PASSED
    # A new rework against the now-REWORKED unit leaves an OPEN rework at PASSED.
    fx.open_rework_order(units[3]["id"], defect_code="RECHECK")

    validate_error(api.close_work_order(wo["id"], PP),
                   ApiErrorId.ERR_OPEN_REWORK_BLOCKS_CLOSE.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "PASSED", fetched


# ---------------------------------------------------------------------------
# Validation-priority conflicts (queue A priority_pair_validation_conflict)
# ---------------------------------------------------------------------------

def test_state_check_beats_rohs_on_start(api):
    """PRD §2.7: "Then, for any state-transition operation, the target must currently
    be in a state from which the requested transition is defined; otherwise the
    request fails with `ERR_INVALID_STATE` (HTTP 409). ... Business and safety rules —
    segregation of duties, RoHS, conflict minerals, approved-source gating, and the
    rest — follow."

    A start on a PLANNED (not SETUP) work order whose only lot is non-RoHS for a
    RoHS-required part returns ERR_INVALID_STATE (state precedes the RoHS gate).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_rohs_safety_on_start
    """
    # RoHS-required part with only a non-RoHS lot; WO left PLANNED (never kitted/setup).
    part = fx.create_part(is_rohs_required=True, standard_cost_cents=50)
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], received_qty=50, unit_cost_cents=50,
                       is_rohs_compliant=False, has_cmrt=False)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    wo = fx.create_work_order(bom["id"], planned_qty=1)  # PLANNED
    validate_error(api.start_work_order(wo["id"], PP), ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "PLANNED", fetched


def test_rohs_gate_fires_in_isolation_on_kit(api):
    """PRD §3.5: "The RoHS gate also applies here: if any lot that would be reserved
    for a part whose `is_rohs_required` flag is set is not RoHS compliant, kitting
    fails with `ERR_ROHS_VIOLATION` before the work order advances."

    Companion to the state-vs-RoHS conflict: with the work order in a valid PLANNED
    state (so the state check passes), a RoHS-required part backed only by a
    non-compliant lot makes kitting fail with ERR_ROHS_VIOLATION — confirming the RoHS
    rule (the conflict's lower-priority loser) genuinely fires when no state error
    pre-empts it.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_rohs_safety_on_start
    """
    part = fx.create_part(is_rohs_required=True, standard_cost_cents=50)
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], received_qty=50, unit_cost_cents=50,
                       is_rohs_compliant=False, has_cmrt=False)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    wo = fx.create_work_order(bom["id"], planned_qty=1)  # PLANNED, valid for kit
    validate_error(api.kit_work_order(wo["id"], PP), ApiErrorId.ERR_ROHS_VIOLATION.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "PLANNED", fetched


def test_sod_beats_shortage_on_rework_close(api):
    """PRD §3.9: "when the rework names an `eco_id` — ... only when the acting
    `acting_user_id` differs from the linked change's `authored_by_user_id` (otherwise
    `ERR_SOD_VIOLATION`, HTTP 409)."
    PRD §2.7: "Business and safety rules — segregation of duties, RoHS, conflict
    minerals, approved-source gating, and the rest — follow. Finally, basic
    request-shape validation ... yields `ERR_INVALID_REQUEST` (HTTP 400) when
    violated, and a generic business-rule violation not covered by a more specific code
    (such as a non-positive received quantity) yields `ERR_VALIDATION` (HTTP 422)."

    Closing a rework whose acting_user_id equals the linked ECO author returns
    ERR_SOD_VIOLATION even when the requested replacement_qty also exceeds stock —
    the SoD safety check pre-empts any later quantity check.

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_fiscal_kit_shortage_on_rework_close
    """
    # FAILED unit; an ECO authored by pp-1; replacement part lot with only qty 4 left.
    part, bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=5, unit_cost_cents=100, standard_cost_cents=100)
    # ECO authored by the same identity (pp-1) that will act as the rework closer.
    eco = fx.author_eco(bom["id"], author_user_id="pp-1")
    get_success_data(api.submit_eco(eco["id"], f.eco_action_payload("pp-1"),
                                    make_process_engineer_headers("pp-1")))
    get_success_data(api.approve_eco(eco["id"], f.eco_action_payload("qe-1"),
                                     make_quality_engineer_headers("qe-1")))
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN", eco_id=eco["id"])
    # acting_user_id pp-1 == author pp-1 (SoD) AND replacement_qty 100 > stock 4.
    validate_error(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 100, "pp-1"), PP),
        ApiErrorId.ERR_SOD_VIOLATION.value)
    fetched = validate_success(api.get_rework_order(rwo["id"], PP))
    assert fetched["status"] == "OPEN", fetched


def test_eco_rework_close_succeeds_when_sod_satisfied(api):
    """PRD §3.9: "when the rework names an `eco_id` — only when that engineering change
    is `APPROVED` ... and only when the acting `acting_user_id` differs from the linked
    change's `authored_by_user_id` ... On close, the system: computes the rework's
    `added_material_cost_cents` ... sets the target unit's `quality_status` to
    `REWORKED` and increments its `rework_count` by one; and finally sets the rework
    order's `status` to `CLOSED`."

    Companion to the SoD-vs-shortage conflict: with the acting user distinct from the
    ECO author (SoD satisfied) and stock sufficient, the same ECO-linked close
    succeeds — confirming the SoD check was the conflict's blocker, not the quantity.

    Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_fiscal_kit_shortage_on_rework_close
    """
    part, bom, _prog, _wo, unit = fx.setup_failed_unit_at_test(
        planned_qty=1, received_qty=10, unit_cost_cents=100, standard_cost_cents=100)
    # ECO authored by pe-1; the rework closer acts as pp-1 (distinct from the author).
    eco = fx.approved_eco(bom["id"], author_user_id="pe-1", approver_user_id="qe-1")
    rwo = fx.open_rework_order(unit["id"], defect_code="OPEN", eco_id=eco["id"])
    closed = validate_success(api.close_rework_order(
        rwo["id"], f.close_rework_payload(part["id"], 1, "pp-1"), PP))
    assert closed["status"] == "CLOSED", closed
    fetched_unit = validate_success(api.get_unit(unit["id"], PP))
    assert fetched_unit["quality_status"] == "REWORKED", fetched_unit
    assert fetched_unit["rework_count"] == 1, fetched_unit
