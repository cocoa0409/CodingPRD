"""Depth-3 cascades (storm close -> assignment -> vehicle; assignment cancel ->
application -> depot), the material- and labor-conservation compensating invariants,
and immediate debit visibility.

Difficulty queue: transitive_cascade, compensating_invariant.
Corner queue: consistency_model.
"""
from test_helpers import (
    validate_success, TEST_USERS,
    new_operator, new_storm, new_callout, complete_callout,
    setup_started_assignment, setup_recorded_application, setup_completed_callout,
    new_application, make_operator_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]
YARD = TEST_USERS["yard_headers"]


# --- Difficulty: transitive_cascade / storm_close_releases_vehicle --------

def test_storm_close_completes_assignment_and_releases_vehicle(api):
    """PRD §3.2: "In the first hop, every route assignment of this storm that is currently
    `IN_PROGRESS` transitions to `COMPLETED`, and every route assignment that is currently
    `PLANNED` transitions to `CANCELLED`. In the further hops, each assignment that reaches
    `COMPLETED` this way releases its vehicle back to `AVAILABLE` — the same vehicle release
    that a direct completion produces."

    Design: Difficulty/transitive_cascade/storm_close_releases_vehicle
    """
    scene = setup_started_assignment(planned_material_tons=2.0)  # IN_PROGRESS, vehicle ASSIGNED
    storm = validate_success(api.close_storm_event(scene["storm"]["id"], DISPATCH), 200)
    assert storm["operational_status"] == "CLOSED", storm
    asg = validate_success(api.get_assignment(scene["assignment"]["id"], DISPATCH), 200)
    assert asg["status"] == "COMPLETED", asg
    veh = validate_success(api.get_vehicle(scene["vehicle"]["id"], DISPATCH), 200)
    assert veh["status"] == "AVAILABLE", veh


def test_storm_close_vehicle_reserved_before_released_after(api):
    """PRD §3.2: "In the further hops, each assignment that reaches `COMPLETED` this way
    releases its vehicle back to `AVAILABLE` — the same vehicle release that a direct
    completion produces."

    Design: Difficulty/transitive_cascade/storm_close_releases_vehicle
    """
    scene = setup_started_assignment(planned_material_tons=2.0)
    before = validate_success(api.get_vehicle(scene["vehicle"]["id"], DISPATCH), 200)
    assert before["status"] == "ASSIGNED", before  # reserved while IN_PROGRESS
    validate_success(api.close_storm_event(scene["storm"]["id"], DISPATCH), 200)
    after = validate_success(api.get_vehicle(scene["vehicle"]["id"], DISPATCH), 200)
    assert after["status"] == "AVAILABLE", after


# --- Difficulty: transitive_cascade / assignment_cancel_credits_depot -----

def test_cancel_in_progress_assignment_voids_app_and_credits_depot(api):
    """PRD §3.5: "Cancelling an `IN_PROGRESS` assignment sets its `status` to `CANCELLED`,
    releases the reserved vehicle back to `AVAILABLE`, and in the first cascade hop
    transitions every material application of this assignment that is currently `RECORDED`
    to `VOIDED`; each such void, in the further hops, credits the voided material back to
    the depot it was drawn from, restoring the conservation invariant."

    Design: Difficulty/transitive_cascade/assignment_cancel_credits_depot
    """
    scene = setup_recorded_application(salt_tons=10.0)  # depot 100 -> 90
    asg = validate_success(api.cancel_assignment(scene["assignment"]["id"], DISPATCH), 200)
    assert asg["status"] == "CANCELLED", asg
    app = validate_success(api.get_application(scene["application"]["id"], DISPATCH), 200)
    assert app["status"] == "VOIDED", app
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 100.00, depot
    veh = validate_success(api.get_vehicle(scene["vehicle"]["id"], DISPATCH), 200)
    assert veh["status"] == "AVAILABLE", veh


def test_cancel_assignment_voids_all_recorded_applications(api):
    """PRD §3.5: "in the first cascade hop transitions every material application of this
    assignment that is currently `RECORDED` to `VOIDED`; each such void, in the further
    hops, credits the voided material back to the depot it was drawn from, restoring the
    conservation invariant."

    Design: Difficulty/transitive_cascade/assignment_cancel_credits_depot
    """
    scene = setup_started_assignment(planned_material_tons=0)  # depot 100 salt
    op_id = scene["operator"]["id"]
    app1 = new_application(scene["assignment"]["id"], op_id, scene["depot"]["id"],
                           material_type="SALT", salt_tons=5.0, lane_miles_treated=2.0, pavement_temp_f=15)
    app2 = new_application(scene["assignment"]["id"], op_id, scene["depot"]["id"],
                           material_type="SALT", salt_tons=3.0, lane_miles_treated=2.0, pavement_temp_f=15)
    validate_success(api.cancel_assignment(scene["assignment"]["id"], DISPATCH), 200)
    for app in (app1, app2):
        after = validate_success(api.get_application(app["id"], DISPATCH), 200)
        assert after["status"] == "VOIDED", after
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 100.00, depot  # 100 - 5 - 3 + 5 + 3


# --- Difficulty: compensating_invariant / material_conservation_void ------

def test_void_restores_depot_and_initial_anchor_unchanged(api):
    """PRD §2.8: "At creation the depot's opening `salt_tons_on_hand` and
    `brine_gallons_on_hand` are snapshotted into `initial_salt_tons` and
    `initial_brine_gallons`, which never change thereafter." PRD §3.6: "Voiding sets the
    application's `status` to `VOIDED` and credits the material back to the depot — salt
    applications add `salt_tons` back to `salt_tons_on_hand`".

    Design: Difficulty/compensating_invariant/material_conservation_void
    """
    scene = setup_recorded_application(salt_tons=10.0)  # depot 100 -> 90
    validate_success(api.void_application(scene["application"]["id"], DISPATCH), 200)
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 100.00, depot
    assert depot["initial_salt_tons"] == 100.00, depot


def test_conserved_salt_quantity_holds_across_debit_and_void(api):
    """PRD §2.8: "Recording a salt application debits `salt_tons_on_hand`; recording a
    brine application debits `brine_gallons_on_hand`. Voiding an application credits the
    same amount back to the same depot." PRD §2.8: "At creation the depot's opening
    `salt_tons_on_hand` and `brine_gallons_on_hand` are snapshotted into `initial_salt_tons`
    and `initial_brine_gallons`, which never change thereafter."

    Design: Difficulty/compensating_invariant/material_conservation_void
    """
    scene = setup_recorded_application(salt_tons=30.0)  # depot 100 -> 70
    mid = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    # conserved quantity: on_hand + recorded tonnage == initial
    assert mid["salt_tons_on_hand"] == 70.00, mid
    assert mid["salt_tons_on_hand"] + 30.0 == mid["initial_salt_tons"], mid
    validate_success(api.void_application(scene["application"]["id"], DISPATCH), 200)
    after = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert after["salt_tons_on_hand"] == 100.00, after


# --- Difficulty: compensating_invariant / labor_hours_conservation_cancel -

def test_cancel_completed_callout_reverses_accrued_hours_standard(api):
    """PRD §3.7: "If a `COMPLETED` callout is later cancelled, the operator's
    `regular_hours_accrued` is decreased by that callout's `regular_hours` and
    `overtime_hours_accrued` by its `overtime_hours`, returning the accrued totals to
    their pre-completion values."

    Design: Difficulty/compensating_invariant/labor_hours_conservation_cancel
    """
    scene = setup_completed_callout(severity="MODERATE", hours_worked=10)  # +8 reg, +2 ot
    validate_success(api.cancel_callout(scene["callout"]["id"], DISPATCH), 200)
    op = validate_success(api.get_operator(scene["operator"]["id"], DISPATCH), 200)
    assert op["regular_hours_accrued"] == 0, op
    assert op["overtime_hours_accrued"] == 0, op


def test_completion_credits_then_cancel_reverses_storm_mode(api):
    """PRD §3.7: "Completion then credits the operator's ledger: `regular_hours_accrued` is
    increased by this callout's `regular_hours` and `overtime_hours_accrued` by its
    `overtime_hours`." PRD §3.7: "If a `COMPLETED` callout is later cancelled, the
    operator's `regular_hours_accrued` is decreased by that callout's `regular_hours` and
    `overtime_hours_accrued` by its `overtime_hours`, returning the accrued totals to their
    pre-completion values."

    Design: Difficulty/compensating_invariant/labor_hours_conservation_cancel
    """
    op = new_operator(hourly_rate_cents=4000)
    storm = new_storm(severity="SEVERE")  # STORM_MODE: threshold 6
    co = new_callout(storm["id"], op["id"])
    complete_callout(co["id"], op["id"], 10)  # regular 6, overtime 4
    credited = validate_success(api.get_operator(op["id"], DISPATCH), 200)
    assert credited["regular_hours_accrued"] == 6, credited
    assert credited["overtime_hours_accrued"] == 4, credited
    validate_success(api.cancel_callout(co["id"], DISPATCH), 200)
    reversed_op = validate_success(api.get_operator(op["id"], DISPATCH), 200)
    assert reversed_op["regular_hours_accrued"] == 0, reversed_op
    assert reversed_op["overtime_hours_accrued"] == 0, reversed_op


# --- Corner: consistency_model / application_debit_visible_immediately ----

def test_application_debit_visible_immediately(api):
    """PRD §2.8: "Recording a salt application debits `salt_tons_on_hand`; recording a
    brine application debits `brine_gallons_on_hand`." PRD §1: "material is conserved
    (every ton debited from a yard is either consumed or credited back on a void)".

    Design: Corner/consistency_model/application_debit_visible_immediately
    """
    scene = setup_started_assignment(planned_material_tons=5.0)  # depot 100 salt
    new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                    material_type="SALT", salt_tons=3.5, lane_miles_treated=2.0, pavement_temp_f=15)
    depot = validate_success(api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == 96.5, depot
