"""State-machine corners: legal hops, cyclic review, terminal lockdown and non-idempotent axes."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close
from test_helpers.factories import (
    abort_payload,
    advance_payload,
    capacity_result_payload,
    env_hold_payload,
    lead_design_payload,
    review_action_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import validate_error, validate_success


def test_submitting_a_draft_records_the_submitter_and_leaves_the_revision_alone(make_world):
    """SUBMIT is the only hop out of DRAFT and it touches nothing but the review axis.

    "`SUBMIT` requires `DRAFT` and moves the design `DRAFT` to `UNDER_REVIEW`, stamping
    `submitted_by_worker_id` with the acting worker." Approval is what later copies the revision, so
    `revision` stays 1 and `approved_revision` stays null through the submission.

    Design: Corner/state_machines/design_submit_moves_draft_to_under_review_and_records_the_submitter
    """
    world = make_world(with_design=False)
    design = world.draft_design(lead_design_payload())

    submitted = validate_success(
        world.api.review_cell_design(
            design["id"],
            review_action_payload("SUBMIT", review_comment="ready for peer review"),
            world.eng_a,
        ),
        200,
    )

    assert submitted["approval_state"] == C.DESIGN_UNDER_REVIEW
    assert submitted["submitted_by_worker_id"] == world.eng_a_id
    assert submitted["approved_by_worker_id"] is None
    assert submitted["revision"] == 1
    assert submitted["approved_revision"] is None
    assert submitted["version"] == design["version"] + 1


def test_request_changes_keeps_the_submitter_and_cannot_fire_twice(make_world):
    """The review cycle reopens through an edit, and REQUEST_CHANGES needs UNDER_REVIEW to fire.

    "`REQUEST_CHANGES` requires `UNDER_REVIEW`, requires that the acting worker is not the
    submitter, and moves the design `UNDER_REVIEW` to `CHANGES_REQUESTED` without touching
    `revision`; `submitted_by_worker_id` is retained precisely so the segregation-of-duties bar
    still applies on the next approval attempt." The edit that follows is the reopening hop: "A
    `CHANGES_REQUESTED` design edited in place moves `CHANGES_REQUESTED` to `DRAFT`, and that edit
    is the only mechanism that reopens it for a further submission."

    Design: Corner/state_machines/design_request_changes_loops_back_to_changes_requested_and_keeps_the_submitter
    """
    world = make_world(with_design=False)
    design = world.draft_design(lead_design_payload())
    validate_success(
        world.api.review_cell_design(
            design["id"], review_action_payload("SUBMIT"), world.eng_a
        ),
        200,
    )

    changes = validate_success(
        world.api.review_cell_design(
            design["id"],
            review_action_payload(
                "REQUEST_CHANGES", review_comment="raise the formation charge factor"
            ),
            world.eng_b,
        ),
        200,
    )
    assert changes["approval_state"] == C.DESIGN_CHANGES_REQUESTED
    assert changes["submitted_by_worker_id"] == world.eng_a_id
    assert changes["revision"] == 1

    edited = validate_success(
        world.api.update_cell_design(
            design["id"], {"formation_charge_factor": 1.60}, world.eng_a
        ),
        200,
    )
    assert edited["revision"] == 2
    assert_close(edited["formation_charge_factor"], 1.60, "formation_charge_factor", 2)
    assert edited["approval_state"] == C.DESIGN_DRAFT

    validate_error(
        world.api.review_cell_design(
            design["id"], review_action_payload("REQUEST_CHANGES"), world.eng_b
        ),
        E.ERR_DESIGN_STATE_INVALID,
    )

    unchanged = validate_success(world.api.get_cell_design(design["id"], world.eng_a), 200)
    assert unchanged["approval_state"] == C.DESIGN_DRAFT
    assert unchanged["revision"] == 2


def test_a_planned_lot_cannot_jump_straight_to_assembly(world: World):
    """The ladder is single-step, so naming a later stage is a state error not a shortcut.

    "Manufacturing progress is a single-step ladder" and "`to_state` must be the immediate successor
    of the current state -- skipping a stage is refused with `ERR_LOT_STATE_INVALID`."

    Design: Corner/state_machines/lot_advance_skipping_plate_production_is_rejected
    """
    lot = world.lot_in_state(C.LOT_PLANNED, "LOT-A", 9)

    validate_error(
        world.api.advance_lot(lot["id"], advance_payload(C.LOT_ASSEMBLY), world.sup_a),
        E.ERR_LOT_STATE_INVALID,
    )

    assert world.read_lot(lot["id"])["process_state"] == C.LOT_PLANNED


def test_a_completed_run_is_terminal_and_a_later_abort_changes_no_figure(
    formation_world: World,
):
    """COMPLETED locks the run down, so the settled ledger cannot be released a second time.

    "Attempting to abort a run already `COMPLETED` or `ABORTED` is `ERR_RUN_STATE_INVALID`", and
    since the completion already converted the reservation the refusal must leave the plant's
    emission ledger exactly where the completion put it.

    Design: Corner/state_machines/completed_formation_run_cannot_be_aborted
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)
    assert_close(run["estimated_energy_kwh"], 102.00, "estimated_energy_kwh", 2)
    assert run["provisional_charge_cents"] == 2210
    assert_close(run["reserved_emission_g"], 255.00, "reserved_emission_g", 2)

    world.set_clock("2026-09-02T06:00:00Z")
    world.start_run(run["id"])
    world.set_clock("2026-09-02T12:00:00Z")
    completed = world.complete_run(run["id"], 60.00, 95.00)
    assert completed["run_state"] == C.RUN_STATE_COMPLETED
    assert completed["final_charge_cents"] == 1300
    assert_close(completed["consumed_emission_g"], 150.00, "consumed_emission_g", 2)
    assert completed["capacity_validation_result"] == C.CAPACITY_RESULT_PASS

    validate_error(
        world.api.abort_formation_run(
            run["id"], abort_payload(C.ABORT_OPERATOR), world.sup_a
        ),
        E.ERR_RUN_STATE_INVALID,
    )

    after = world.read_run(run["id"])
    assert after["run_state"] == C.RUN_STATE_COMPLETED
    assert after["abort_reason"] is None
    assert after["final_charge_cents"] == 1300
    assert_close(after["consumed_emission_g"], 150.00, "consumed_emission_g", 2)

    ledger = world.read_ledger()
    assert_close(ledger["emission_reserved_g"], 0.00, "emission_reserved_g", 2)
    assert_close(ledger["emission_consumed_g"], 150.00, "emission_consumed_g", 2)


def test_a_result_filed_before_its_window_closes_leaves_the_test_scheduled(
    testing_world: World,
):
    """The clock has to reach the scheduled end before a reading may be recorded.

    "The test must be `SCHEDULED` and the logical clock must have reached or passed
    `scheduled_end_at` -- a result cannot be filed before the window it describes has closed -- and
    any violation of either is `ERR_CAPACITY_TEST_STATE_INVALID`."

    Design: Corner/state_machines/capacity_test_result_recorded_before_the_window_closes_is_rejected
    """
    world = testing_world
    assert world.assembly["certification_status"] == C.CERT_CERTIFIED

    test = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
    )

    validate_error(
        world.api.record_test_result(
            test["id"], capacity_result_payload(441.8), world.qa_a
        ),
        E.ERR_CAPACITY_TEST_STATE_INVALID,
    )

    after = world.read_test(test["id"])
    assert after["test_state"] == C.TEST_STATE_SCHEDULED
    assert after["result"] is None
    assert after["measured_capacity_ah"] is None
    assert after["yield_pct"] is None
    assert after["recorded_by_worker_id"] is None

    summary = validate_success(
        world.api.get_quality_summary(world.lot_id, world.qa_a), 200
    )
    assert summary["completed_test_count"] == 0
    assert summary["lot_capacity_yield_pct"] is None


def test_holding_an_already_held_lot_is_refused_and_the_axis_stays_live(world: World):
    """The hold axis is deliberately not idempotent, and a refused hold rewrites nothing.

    "A hold action that would not change anything -- holding an already `HELD` lot, or releasing an
    already `CLEAR` one -- is refused with `ERR_LOT_STATE_INVALID`." The axis remains orthogonal to
    the ladder, so the lot is still `PLANNED` throughout.

    Design: Corner/state_machines/second_environmental_hold_on_an_already_held_lot_is_rejected
    """
    lot = world.lot_in_state(C.LOT_PLANNED, "LOT-A", 9)

    held = world.hold_lot(lot["id"])
    assert held["env_hold_status"] == C.ENV_HOLD_HELD
    assert held["hold_reason"] == C.HOLD_REASON_OPERATOR
    assert held["process_state"] == C.LOT_PLANNED

    validate_error(
        world.api.env_hold_lot(
            lot["id"],
            env_hold_payload("HOLD", C.HOLD_REASON_OPERATOR),
            world.saf_a,
        ),
        E.ERR_LOT_STATE_INVALID,
    )

    unchanged = world.read_lot(lot["id"])
    assert unchanged["env_hold_status"] == C.ENV_HOLD_HELD
    assert unchanged["hold_reason"] == C.HOLD_REASON_OPERATOR

    released = world.release_hold(lot["id"])
    assert released["env_hold_status"] == C.ENV_HOLD_CLEAR
    assert released["hold_reason"] is None
