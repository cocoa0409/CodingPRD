"""Derived safety posture: multi-input branching, the FROZEN gate on pickups, and
the fixed validation order between state preconditions and the frozen gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_lab,
    get_pickup,
    make_inspector_headers,
    make_pi_headers,
    set_clock,
    setup_frozen_lab_with_pickup,
    setup_lab_with_completed_inspection,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_open_corrective_action_drives_restricted(api):
    """PRD §2.6: "Otherwise, if at least one corrective action of the lab is in
    `OPEN`, `SUBMITTED`, or `REOPENED` status, posture is `RESTRICTED`."
    PRD §3.5: "Every finding spawns exactly one corrective action in `OPEN` status"

    Design: Difficulty/combinatorial_formula/posture_derivation_multi_input_branching
    """
    ctx = setup_lab_with_completed_inspection(
        [{"severity": "MINOR", "description": "missing signage"}], name="Phys C", room="303"
    )
    assert ctx["corrective_actions"][0]["status"] == "OPEN"
    assert get_lab(ctx["lab"]["id"])["posture"] == "RESTRICTED", (
        "one OPEN (not overdue) corrective action drives RESTRICTED via the open-CA branch"
    )


def test_overdue_corrective_action_drives_frozen(api):
    """PRD §2.6: "Otherwise, if at least one corrective action of the lab is in `OPEN`
    or `REOPENED` status with a `due_date` strictly earlier than the logical now,
    posture is `FROZEN`."
    PRD §2.5: "Advancing the clock triggers a sweep with three effects" including
    "the safety posture of every lab is recomputed from the new now."

    Design: Difficulty/combinatorial_formula/posture_derivation_multi_input_branching
    """
    ctx = setup_lab_with_completed_inspection(
        [{"severity": "MINOR", "description": "missing signage"}], name="Phys C2", room="303"
    )
    assert get_lab(ctx["lab"]["id"])["posture"] == "RESTRICTED"

    # the MINOR corrective action is due 2026-08-31T00:00:00Z; advance past it
    set_clock("2026-09-01T00:00:00Z")
    assert get_lab(ctx["lab"]["id"])["posture"] == "FROZEN", (
        "the same corrective action, once overdue, drives FROZEN via the overdue branch"
    )


def test_frozen_lab_blocks_pickup_submit(api):
    """PRD §2.6: "While a lab is `FROZEN`, four mutations are gated and fail with
    `ERR_LAB_FROZEN` (HTTP 409): registering a new container in the lab, tagging a
    container as waste, creating a waste pickup request for the lab, and submitting
    a waste pickup request for the lab."

    Design: Difficulty/cross_entity_state_dependency/frozen_lab_blocks_pickup_submit
    """
    ctx = setup_frozen_lab_with_pickup(pickup_stage="DRAFT")
    lab, pi, pickup = ctx["lab"], ctx["pi"], ctx["pickup"]
    assert get_lab(lab["id"])["posture"] == "FROZEN"

    res = api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_LAB_FROZEN)
    assert get_pickup(pickup["id"])["status"] == "DRAFT", "rejected submit leaves status DRAFT"


def test_submit_allowed_again_once_posture_restored(api):
    """PRD §2.6: "While a lab is `FROZEN`, four mutations are gated and fail with
    `ERR_LAB_FROZEN` (HTTP 409): registering a new container in the lab, tagging a
    container as waste, creating a waste pickup request for the lab, and submitting
    a waste pickup request for the lab."
    PRD §3.5: "Every submit and every verify recomputes the lab's posture and
    increments the action's `version` by 1, so posture lifts out of `RESTRICTED` only
    when the last open action leaves the open statuses."

    Design: Difficulty/cross_entity_state_dependency/frozen_lab_blocks_pickup_submit
    """
    ctx = setup_frozen_lab_with_pickup(pickup_stage="DRAFT")
    lab, pi, pickup, ca = ctx["lab"], ctx["pi"], ctx["pickup"], ctx["corrective_action"]
    assert get_lab(lab["id"])["posture"] == "FROZEN"

    # resolve the overdue corrective action; a different inspector verifies (SoD)
    validate_success(
        api.submit_corrective_action(
            ca["id"], {"resolution_note": "signage restored"}, make_pi_headers(pi["id"])
        ),
        200,
    )
    verified = validate_success(
        api.verify_corrective_action(
            ca["id"], {"decision": "APPROVE"}, make_inspector_headers("insp-2")
        ),
        200,
    )
    assert verified["status"] == "VERIFIED"
    assert get_lab(lab["id"])["posture"] == "NORMAL", (
        "with the last open corrective action verified, posture lifts back to NORMAL"
    )

    submitted = validate_success(
        api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"])), 200
    )
    assert submitted["status"] == "SUBMITTED"


def test_state_error_precedes_frozen_gate_on_submit(api):
    """PRD §2.8: "Every mutating request is screened against the applicable checks in
    a fixed priority order, and the first failing check determines the rejection — a
    later check never masks an earlier one." with "State preconditions for the
    requested transition, surfaced through the state-specific errors `ERR_LAB_STATE`,
    `ERR_CONTAINER_STATE`, `ERR_PICKUP_STATE`, `ERR_INSPECTION_STATE`,
    `ERR_CORRECTIVE_ACTION_STATE`, `ERR_REGISTRATION_STATE`, `ERR_TRAINING_STATE`,
    or `ERR_INCIDENT_STATE`." listed before "The frozen-posture gate on the four
    gated mutations, else `ERR_LAB_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/state_error_precedes_frozen_safety_on_submit
    """
    ctx = setup_frozen_lab_with_pickup(pickup_stage="SCHEDULED")
    lab, pi, pickup = ctx["lab"], ctx["pi"], ctx["pickup"]
    assert get_lab(lab["id"])["posture"] == "FROZEN"
    assert get_pickup(pickup["id"])["status"] == "SCHEDULED"

    res = api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_PICKUP_STATE)
    assert get_pickup(pickup["id"])["status"] == "SCHEDULED", (
        "state-precondition failure fires first; the SCHEDULED status is unchanged"
    )


def test_frozen_gate_fires_when_state_precondition_passes(api):
    """PRD §2.8: "Every mutating request is screened against the applicable checks in
    a fixed priority order, and the first failing check determines the rejection — a
    later check never masks an earlier one." with "7. The frozen-posture gate on the
    four gated mutations, else `ERR_LAB_FROZEN`."
    (A DRAFT pickup satisfies the submit state precondition, so the frozen gate is
    the check that fires — isolating the two rules of the priority pair.)

    Design: Difficulty/priority_pair_validation_conflict/state_error_precedes_frozen_safety_on_submit
    """
    ctx = setup_frozen_lab_with_pickup(pickup_stage="DRAFT")
    lab, pi, pickup = ctx["lab"], ctx["pi"], ctx["pickup"]
    assert get_lab(lab["id"])["posture"] == "FROZEN"

    res = api.submit_pickup_request(pickup["id"], make_pi_headers(pi["id"]))
    validate_error(res, ApiErrorId.ERR_LAB_FROZEN)
    assert get_pickup(pickup["id"])["status"] == "DRAFT"
