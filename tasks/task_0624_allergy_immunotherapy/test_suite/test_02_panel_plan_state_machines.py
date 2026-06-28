"""Panel and plan state machines: finalize preconditions, activation gating,
the ACTIVE<->HELD revert cycle, completion guards, lot recall idempotency.

Each test translates exactly one design-index instance (see the Design: line).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_plan_payload,
    create_patient,
    create_open_panel,
    add_skin_test,
    finalize_panel,
    create_lot,
    mix_vial,
    administer_shot,
    release_visit,
    record_reaction,
    resume_payload,
    create_finalized_panel,
    create_draft_plan,
    create_red_active_plan,
    create_green_active_plan,
    create_yellow_active_plan,
    get_plan,
    set_clock,
    TEST_USERS,
)

ALLERGIST = TEST_USERS["allergist_headers"]
PHARMACIST = TEST_USERS["pharmacist_headers"]
NURSE = TEST_USERS["nurse_headers"]


def test_plan_held_then_resume_reverts_to_active(api):
    """PRD §3.6: "A systemic reaction triggers a three-hop cascade: the owning
    plan moves `ACTIVE → HELD`". PRD §3.7: "On resume the plan moves
    `HELD → ACTIVE`, the reaction-reduction described in Section 3.8 is applied".
    PRD §3.8: "In the same step the ladder is moved back one rung: if
    `current_step_index` is greater than 1, it decreases by one".

    Plan at RED step2 (after one released step1 shot advanced it) is held by a
    systemic reaction on the step2 shot; resume reverts to ACTIVE and steps the
    index back from 2 to 1, color staying RED.

    Design: Difficulty/non_linear_state_machine/plan_held_active_revert_cycle
    """
    ctx = create_red_active_plan(prepared_volume_ml=5.0)
    plan_id, vial_id = ctx["plan"]["id"], ctx["vial"]["id"]

    v1 = administer_shot(plan_id, vial_id, ctx["version"])
    set_clock("2026-01-01T01:00:00Z")
    release_visit(v1["id"], "2026-01-01T01:00:00Z", reaction_grade="NONE")
    plan_after_release = get_plan(plan_id)
    assert plan_after_release["current_step_index"] == 2, plan_after_release["current_step_index"]

    v2 = administer_shot(plan_id, vial_id, plan_after_release["version"])
    record_reaction(v2["id"], "SYSTEMIC", epinephrine_administered=True)

    held = get_plan(plan_id)
    resumed = validate_success(
        api.resume_plan(plan_id, resume_payload(held["version"]), ALLERGIST), 200
    )
    assert resumed["status"] == "ACTIVE", resumed["status"]
    assert resumed["current_vial_color"] == "RED", resumed["current_vial_color"]
    assert resumed["current_step_index"] == 1, resumed["current_step_index"]


def test_plan_create_from_open_panel_rejected(api):
    """PRD §3.3: "An `Allergist` authors an immunotherapy plan from a finalized
    panel by supplying the `patient_id` and the `panel_id` of the `FINALIZED`
    panel that justifies it." PRD §3.2: "A panel must be `FINALIZED` before any
    immunotherapy plan may reference it." PRD §3.3 / §5: activating against a
    non-finalized panel yields `ERR_PANEL_NOT_FINALIZED`.

    Creating a plan against an OPEN (never finalized) panel surfaces the
    cross-entity dependency with ERR_PANEL_NOT_FINALIZED (HTTP 409).

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_panel_finalized
    """
    patient = create_patient(epinephrine_on_file=True)
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="OpenPanel")
    add_skin_test(patient["id"], panel["id"], wheal_mm=6, clinically_relevant=True, allergen_code="OAK")
    res = api.create_plan(create_plan_payload(patient["id"], panel["id"]), ALLERGIST)
    validate_error(res, "ERR_PANEL_NOT_FINALIZED", expected_status=409)


def test_add_test_to_finalized_panel_rejected(api):
    """PRD §3.2: "On finalization the panel transitions `OPEN → FINALIZED` ... and
    no further tests are accepted." PRD §3.2: "Adding a test to a panel that is
    not `OPEN` is rejected with `ERR_PANEL_NOT_OPEN`."

    Design: Corner/state_machines/add_test_to_finalized_panel_returns_invalid_state
    """
    patient, panel = create_finalized_panel(wheal_mm=7, clinically_relevant=True)
    res = api.add_test(
        patient["id"], panel["id"],
        {"allergen_code": "DUST", "method": "SKIN", "wheal_mm": 6, "clinically_relevant": True},
        ALLERGIST,
    )
    validate_error(res, "ERR_PANEL_NOT_OPEN", expected_status=409)


def test_finalize_panel_with_no_positive_test_rejected(api):
    """PRD §3.2: "a panel that has tests but none positive is rejected with
    `ERR_NO_POSITIVE_TEST`." PRD §3.2: "the test `is_positive` when that
    difference is at least 3 millimetres."

    A single SKIN wheal 4 over control 3 -> diff 1 < 3 -> not positive.

    Design: Corner/state_machines/finalize_panel_no_positive_test_returns_error
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Neg")
    test = add_skin_test(patient["id"], panel["id"], wheal_mm=4, clinically_relevant=True, allergen_code="OAK")
    assert test["is_positive"] is False, test["is_positive"]
    res = api.finalize_panel(patient["id"], panel["id"], ALLERGIST)
    validate_error(res, "ERR_NO_POSITIVE_TEST", expected_status=422)


def test_finalize_empty_panel_rejected(api):
    """PRD §3.2: "a panel with zero tests is rejected with `ERR_PANEL_EMPTY`."

    Design: Corner/state_machines/finalize_empty_panel_returns_panel_empty
    """
    patient = create_patient()
    panel = create_open_panel(patient["id"], control_wheal_mm=3, panel_name="Empty")
    res = api.finalize_panel(patient["id"], panel["id"], ALLERGIST)
    validate_error(res, "ERR_PANEL_EMPTY", expected_status=422)


def test_activate_already_active_plan_rejected(api):
    """PRD §3.3: "An `Allergist` activates a plan only when the plan is in `DRAFT`
    (otherwise `ERR_PLAN_NOT_DRAFT`)".

    A second activate on an already-ACTIVE plan returns ERR_PLAN_NOT_DRAFT.

    Design: Corner/state_machines/activate_plan_not_draft_returns_invalid
    """
    ctx = create_red_active_plan()
    res = api.activate_plan(ctx["plan"]["id"], ALLERGIST)
    validate_error(res, "ERR_PLAN_NOT_DRAFT", expected_status=409)


def test_activate_plan_without_starting_vial_rejected(api):
    """PRD §3.3: "at least one in-use serum vial whose color equals the plan's
    `starting_vial_color` already exists on this plan (otherwise
    `ERR_NO_STARTING_VIAL`)." PRD §3.3: "a `HIGH` tier starts at `GREEN`".

    HIGH-tier plan (wheal 10 -> composite 7) starts GREEN, but only a RED vial
    is mixed, so activation fails with ERR_NO_STARTING_VIAL.

    Design: Corner/state_machines/activate_plan_no_starting_vial_returns_error
    """
    patient, panel, plan = create_draft_plan(wheal_mm=10, control_wheal_mm=3)
    assert plan["starting_vial_color"] == "GREEN", plan["starting_vial_color"]
    lot = create_lot("RED")
    mix_vial(plan["id"], lot["id"], plan["version"], prepared_volume_ml=5.0)
    res = api.activate_plan(plan["id"], ALLERGIST)
    validate_error(res, "ERR_NO_STARTING_VIAL", expected_status=422)


def test_complete_plan_not_at_maintenance_rejected(api):
    """PRD §3.7: "Completion requires the plan to be `ACTIVE` (otherwise
    `ERR_PLAN_NOT_ACTIVE`), the plan's `phase` to be `MAINTENANCE` (otherwise
    `ERR_NOT_AT_MAINTENANCE`)".

    An ACTIVE plan still in BUILD_UP phase cannot be completed.

    Design: Corner/state_machines/complete_plan_not_at_maintenance_returns_error
    """
    ctx = create_red_active_plan()
    res = api.complete_plan(ctx["plan"]["id"], ALLERGIST)
    validate_error(res, "ERR_NOT_AT_MAINTENANCE", expected_status=409)


def test_recall_already_recalled_lot_rejected(api):
    """PRD §3.4: "The lot must be `AVAILABLE`; recalling a lot that is not
    available is rejected with `ERR_LOT_NOT_AVAILABLE`." PRD §3.4: "On recall the
    lot transitions `AVAILABLE → RECALLED`".

    Design: Corner/state_machines/lot_recall_idempotent_second_recall_rejected
    """
    lot = create_lot("RED")
    validate_success(api.recall_lot(lot["id"], PHARMACIST), 200)
    res = api.recall_lot(lot["id"], PHARMACIST)
    validate_error(res, "ERR_LOT_NOT_AVAILABLE", expected_status=409)
