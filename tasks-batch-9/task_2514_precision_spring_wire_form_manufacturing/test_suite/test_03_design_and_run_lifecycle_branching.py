"""
Three lifecycles that are not simple forward chains.

A production run carries two axes at once, and the combined state — not either
axis alone — decides what is admissible: the same `RUNNING` run refuses to close
while its quality axis sits on `SPC_HOLD` and closes once the axis returns to
`OPEN`. A qualification package loops between `SUBMITTED` and
`REVISION_REQUESTED`, and the loop is bounded by a counter rather than by a
status, so the resubmit attempted on the third round is refused while the row
stays exactly where it was. And a spring design walks *backwards*: a revision cut
against a released prototype drops it to `DRAFT`, records which revision it
superseded, and re-runs the whole engineering stack on the new geometry.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_ALT_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

_SAFETY_PROGRAM = dict(
    program_code="PGM-AUTO-1",
    customer_name="Northwind Drivetrain",
    application_class=C.CLASS_AUTOMOTIVE_SAFETY,
    ppap_level=3,
    committed_pieces=500_000,
    minimum_order_quantity=25_000,
    required_salt_spray_hours=96,
    biocompatibility_required=False,
    min_fatigue_margin=1.2,
    required_ppk=1.33,
    amortization_method=C.FORECAST_BASIS,
)

_HEAT = dict(heat_number="HT-500", received_kg=500.0)
_PLANNED_PIECES = 1_000

# A subgroup that stays inside the print limits yet spreads too far for the
# 1.333 floor: mean 60.0, sigma 0.2, so the index lands at 0.833.
_OUT_OF_CONTROL_SUBGROUP = [59.8, 60.0, 60.2]
_OUT_OF_CONTROL_CPK = 0.833

_CONSUMED_KG = 21.185
_ON_HAND_AFTER_COMPLETION_KG = 478.815


def _running_run(api: ApiClient):
    """A 1 000-piece run of D1 whose first article was accepted."""
    return X.build_world(
        api,
        "running",
        program=_SAFETY_PROGRAM,
        wire_lot=_HEAT,
        run={"planned_pieces": _PLANNED_PIECES},
    )


def _hold_the_quality_axis(api: ApiClient, world):
    """One in-process subgroup that fails the floor on a safety-critical print."""
    return X.record_spc_subgroup(
        api,
        world.run_id,
        world.characteristics[0],
        _OUT_OF_CONTROL_SUBGROUP,
        QUALITY_INSPECTOR_HEADERS,
    )


def test_out_of_control_subgroup_holds_the_quality_axis_and_leaves_the_process_axis_running(api):
    """PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the
    characteristic's `usl` minus the unrounded mean, and the unrounded mean minus
    the characteristic's `lsl`, keep whichever of those two distances is
    **smaller**, divide it by three times the unrounded standard deviation, and
    round half up to three decimal places."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value`
    is below the characteristic's `cpk_floor`, or when any single measurement in the
    subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."
    PRD §3.7: "The two status axes are genuinely independent: `process_status` walks
    `FAI_PENDING → RUNNING → COMPLETE` with `CANCELLED` as an early exit,
    `quality_status` moves between `OPEN` and `SPC_HOLD` and then to either
    `DISPOSITIONED_ACCEPT` or `SCRAPPED`, and neither axis gates the other's
    transitions except where a rule below says so explicitly."

    Design: Difficulty/non_linear_state_machine/production_run_parallel_axes_move_independently
    """
    world = _running_run(api)
    assert world.run["process_status"] == C.PROCESS_RUNNING
    assert world.run["quality_status"] == C.QUALITY_OPEN

    record = _hold_the_quality_axis(api, world)

    assert record["cpk_value"] == _OUT_OF_CONTROL_CPK, (
        "a subgroup of 59.8 / 60.0 / 60.2 against 59.5-60.5 indexes at "
        f"{_OUT_OF_CONTROL_CPK}, got {record['cpk_value']}"
    )
    assert record["cpk_value"] == A.expected_cpk_value(
        _OUT_OF_CONTROL_SUBGROUP, 59.5, 60.5
    ), "the record must carry the pinned capability figure of this subgroup"
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        "0.833 falls below the 1.333 floor, so the subgroup is out of control, got "
        f"{record['control_state']!r}"
    )
    assert record["record_kind"] == C.RECORD_KIND_SPC

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        "the escalation moves the quality axis to SPC_HOLD, got "
        f"{run['quality_status']!r}"
    )
    assert run["process_status"] == C.PROCESS_RUNNING, (
        "the process axis is untouched by a quality escalation, got "
        f"{run['process_status']!r}"
    )
    assert run["min_cpk_observed"] == _OUT_OF_CONTROL_CPK, (
        "the run's observed minimum drops to the new record's index, got "
        f"{run['min_cpk_observed']}"
    )


def test_a_running_run_cannot_be_closed_while_the_quality_axis_is_held(api):
    """PRD §3.7: "A `ProcessTechnician` completes a `RUNNING` run by supplying
    `produced_pieces` and `scrapped_pieces`."
    PRD §3.7: "The run must not be on `SPC_HOLD` — a held run cannot be closed and
    answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409) — and its `process_status` must be
    `RUNNING`, otherwise `ERR_RUN_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/production_run_parallel_axes_move_independently
    """
    world = _running_run(api)
    _hold_the_quality_axis(api, world)

    held = X.refresh_run(api, world.run_id)
    assert held["process_status"] == C.PROCESS_RUNNING
    assert held["quality_status"] == C.QUALITY_SPC_HOLD

    response = api.complete_run(
        world.run_id,
        F.completion_payload(950, 50),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, E.ERR_RUN_ON_SPC_HOLD, 409)

    after = X.refresh_run(api, world.run_id)
    assert after["process_status"] == C.PROCESS_RUNNING, (
        "the refused close must leave the process axis where it was, got "
        f"{after['process_status']!r}"
    )
    assert after["produced_pieces"] == 0, (
        "no counts are recorded by a refused close, got "
        f"{after['produced_pieces']}"
    )
    assert after["wire_consumed_kg"] == 0.000, (
        "no consumption is posted by a refused close, got "
        f"{after['wire_consumed_kg']}"
    )


def _release_the_hold(api: ApiClient, world):
    """Show the process back in control, then lift the run-level hold."""
    X.record_spc_subgroup(
        api,
        world.run_id,
        world.characteristics[0],
        C.IN_CONTROL_SUBGROUP,
        QUALITY_INSPECTOR_HEADERS,
    )
    return get_success_data(
        api.quality_disposition(
            world.run_id,
            {"decision": C.DECISION_RELEASE},
            QUALITY_INSPECTOR_ALT_HEADERS,
        )
    )


def test_release_returns_the_quality_axis_to_open_while_the_process_axis_stays_running(api):
    """PRD §3.8: "`RELEASE` returns the run `SPC_HOLD → OPEN` and is the cyclic edge
    on the quality axis — a run can be held and released repeatedly over its life."
    PRD §3.8: "It requires evidence that the process has come back: for **every**
    safety-critical characteristic of the run's design, the newest inspection record
    by `created_at` must have a `control_state` of `IN_CONTROL`."
    PRD §3.8: "The hold only fires while the run's `quality_status` is `OPEN`; a run
    already on `SPC_HOLD` simply accumulates further records."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest
    `cpk_value` across all of the run's inspection records, while `min_ppk_observed`
    is refreshed to the lowest `ppk_value` across only those of the run's records
    whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical`
    true."

    Design: Difficulty/non_linear_state_machine/production_run_parallel_axes_move_independently
    """
    world = _running_run(api)
    _hold_the_quality_axis(api, world)

    released = _release_the_hold(api, world)

    assert released["quality_status"] == C.QUALITY_OPEN, (
        "RELEASE walks the quality axis back to OPEN, got "
        f"{released['quality_status']!r}"
    )
    assert released["process_status"] == C.PROCESS_RUNNING, (
        "the process axis never moved during the hold and release, got "
        f"{released['process_status']!r}"
    )
    assert released["min_cpk_observed"] == _OUT_OF_CONTROL_CPK, (
        "lifting the hold does not erase the observed minimum, which stays at "
        f"{_OUT_OF_CONTROL_CPK}, got {released['min_cpk_observed']}"
    )


def test_completion_moves_only_the_process_axis_and_settles_the_wire_ledger(api):
    """PRD §3.7: "On success both counts are recorded and `process_status` becomes
    `COMPLETE`."
    PRD §3.7: "Consumption is then computed as the design's stored six-decimal
    `wire_mass_per_piece_kg` multiplied by the sum of `produced_pieces` and
    `scrapped_pieces` — scrap burns wire exactly like good product does — rounded
    half up to three decimal places, and written to `wire_consumed_kg`."
    PRD §3.7: "Three ledger postings follow in this exact order, each rounded half
    up to three decimal places: the run's stored `wire_reserved_kg` is subtracted
    from the heat's `reserved_kg`; `wire_consumed_kg` is added to the heat's
    `consumed_kg`; and the difference between the stored `wire_reserved_kg` and
    `wire_consumed_kg` is added back to the heat's `on_hand_kg`, returning whatever
    the scrap allowance over-reserved."

    Design: Difficulty/non_linear_state_machine/production_run_parallel_axes_move_independently
    """
    world = _running_run(api)
    _hold_the_quality_axis(api, world)
    _release_the_hold(api, world)

    completed = X.complete_run(api, world.run_id, 950, 50)

    assert completed["process_status"] == C.PROCESS_COMPLETE, (
        "the close moves the process axis to COMPLETE, got "
        f"{completed['process_status']!r}"
    )
    assert completed["quality_status"] == C.QUALITY_OPEN, (
        "the quality axis is where the release left it, got "
        f"{completed['quality_status']!r}"
    )
    assert completed["produced_pieces"] == 950
    assert completed["scrapped_pieces"] == 50
    assert completed["wire_consumed_kg"] == _CONSUMED_KG, (
        "0.021185 kg across all 1 000 pieces coiled, scrap included, is "
        f"{_CONSUMED_KG} kg, got {completed['wire_consumed_kg']}"
    )
    assert completed["wire_consumed_kg"] == A.expected_wire_consumed_kg(
        C.D1_WIRE_MASS_PER_PIECE_KG, 950, 50
    ), "consumption reads the stored six-decimal mass, not a recomputed one"
    assert completed["min_cpk_observed"] == _OUT_OF_CONTROL_CPK, (
        "the observed minimum survives the close, got "
        f"{completed['min_cpk_observed']}"
    )

    lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert lot["consumed_kg"] == _CONSUMED_KG, (
        f"the heat must show {_CONSUMED_KG} kg burned, got {lot['consumed_kg']}"
    )
    assert lot["reserved_kg"] == 0.000, (
        "the whole reservation is discharged by the close, got "
        f"{lot['reserved_kg']}"
    )
    assert lot["on_hand_kg"] == _ON_HAND_AFTER_COMPLETION_KG, (
        "the scrap allowance the run did not burn comes back on hand, leaving "
        f"{_ON_HAND_AFTER_COMPLETION_KG} kg, got {lot['on_hand_kg']}"
    )
    A.assert_wire_ledger_conserved(lot)


# ── The approval loop, bounded by a counter rather than by a status ───────────
def _submitted_package(api: ApiClient):
    """A round-1 PPAP package on a design whose first article was accepted."""
    world = _running_run(api)
    submission = X.file_submission(
        api,
        world.program_id,
        world.design_id,
        PROGRAM_MANAGER_HEADERS,
        ppap_level=3,
    )
    return world, submission


def _request_revision(api: ApiClient, world, submission_id: str) -> dict:
    return X.customer_verdict(
        api, submission_id, world.program_id, C.DECISION_REQUEST_REVISION
    )


def _resubmit(api: ApiClient, submission_id: str) -> dict:
    return get_success_data(
        api.resubmit_submission(submission_id, PROGRAM_MANAGER_HEADERS)
    )


def test_request_revision_holds_the_package_on_its_current_round(api):
    """PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status`
    `SUBMITTED` with `submitted_by_user_id` stamped from the header,
    `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."
    PRD §3.10: "`REQUEST_REVISION` is the soft rejection: the submission moves to
    `REVISION_REQUESTED` and nothing else changes."
    PRD §3.10: "The design keeps its `PROTOTYPE_RELEASED` status and its tooling
    stays `PENDING`; because no verdict of record is in force, the program's
    re-derived `delivery_posture` falls back to `BLOCKED` unless some other
    submission on the program is still `APPROVED` or `INTERIM_APPROVED`."

    Design: Difficulty/non_linear_state_machine/qualification_submission_revision_cycle_capped_at_three_rounds
    """
    world, submission = _submitted_package(api)
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED
    assert submission["round_no"] == 1

    reviewed = _request_revision(api, world, submission["id"])

    assert reviewed["submission_status"] == C.SUBMISSION_REVISION_REQUESTED, (
        "the soft rejection moves the package to REVISION_REQUESTED, got "
        f"{reviewed['submission_status']!r}"
    )
    assert reviewed["round_no"] == 1, (
        "a verdict never advances the round counter, got " f"{reviewed['round_no']}"
    )
    assert reviewed["reviewed_by_program_id"] == world.program_id, (
        "the verdict stamps the reviewing program, got "
        f"{reviewed['reviewed_by_program_id']!r}"
    )
    assert reviewed["decided_at"] is not None, (
        "the verdict stamps decided_at from the logical clock"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "a revision request leaves the design where it was, got "
        f"{design['release_status']!r}"
    )


def test_each_resubmit_advances_the_round_and_clears_the_previous_verdict(api):
    """PRD §3.10: "Resubmission is how the cycle closes."
    PRD §3.10: "A `ProgramManager` may resubmit a package whose `submission_status`
    is `REVISION_REQUESTED` or `INTERIM_APPROVED`; `SUBMITTED`, `APPROVED` and
    `REJECTED_FINAL` answer `ERR_SUBMISSION_INVALID_STATE`."
    PRD §3.10: "A successful resubmit increments `round_no` by 1, returns
    `submission_status` to `SUBMITTED`, clears `interim_piece_cap` back to null,
    clears `reviewed_by_program_id` and `decided_at` back to null, and re-stamps
    `submitted_by_user_id` from the acting header."

    Design: Difficulty/non_linear_state_machine/qualification_submission_revision_cycle_capped_at_three_rounds
    """
    world, submission = _submitted_package(api)
    _request_revision(api, world, submission["id"])

    round_two = _resubmit(api, submission["id"])

    assert round_two["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "the resubmit closes the loop back to SUBMITTED, got "
        f"{round_two['submission_status']!r}"
    )
    assert round_two["round_no"] == 2, (
        "the round counter advances only on resubmit, got "
        f"{round_two['round_no']}"
    )
    assert round_two["reviewed_by_program_id"] is None, (
        "the previous verdict's reviewer is cleared, got "
        f"{round_two['reviewed_by_program_id']!r}"
    )
    assert round_two["decided_at"] is None, (
        "the previous verdict's timestamp is cleared, got "
        f"{round_two['decided_at']!r}"
    )
    assert round_two["interim_piece_cap"] is None

    _request_revision(api, world, submission["id"])
    round_three = _resubmit(api, submission["id"])

    assert round_three["round_no"] == 3, (
        "the same edge traversed a second time reaches round 3, got "
        f"{round_three['round_no']}"
    )
    assert round_three["submission_status"] == C.SUBMISSION_SUBMITTED
    assert round_three["round_no"] == C.MAX_SUBMISSION_ROUNDS


def test_the_third_round_is_terminal_for_the_loop_and_the_row_stays_where_it_was(api):
    """PRD §3.10: "The round budget is three: `round_no` must be strictly less than
    `MAX_SUBMISSION_ROUNDS`, which is 3, so a package already on round 3 answers
    `ERR_MAX_SUBMISSION_ROUNDS_EXCEEDED` (HTTP 422) and the customer relationship
    has to be repaired outside the API."
    PRD §3.10: "`REQUEST_REVISION` is the soft rejection: the submission moves to
    `REVISION_REQUESTED` and nothing else changes."

    Design: Difficulty/non_linear_state_machine/qualification_submission_revision_cycle_capped_at_three_rounds
    """
    world, submission = _submitted_package(api)

    _request_revision(api, world, submission["id"])
    _resubmit(api, submission["id"])
    _request_revision(api, world, submission["id"])
    _resubmit(api, submission["id"])
    third_verdict = _request_revision(api, world, submission["id"])

    assert third_verdict["round_no"] == C.MAX_SUBMISSION_ROUNDS
    assert third_verdict["submission_status"] == C.SUBMISSION_REVISION_REQUESTED

    response = api.resubmit_submission(submission["id"], PROGRAM_MANAGER_HEADERS)
    validate_error(response, E.ERR_MAX_SUBMISSION_ROUNDS_EXCEEDED, 422)

    after = X.refresh_submission(api, submission["id"])
    assert after["submission_status"] == C.SUBMISSION_REVISION_REQUESTED, (
        "the exhausted loop leaves the row in REVISION_REQUESTED rather than moving "
        f"it to a rejection state, got {after['submission_status']!r}"
    )
    assert after["round_no"] == C.MAX_SUBMISSION_ROUNDS, (
        "the refused resubmit must not advance the counter, got "
        f"{after['round_no']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "a revision loop never releases the design, got "
        f"{design['release_status']!r}"
    )


# ── The branch that walks backwards: a revision on a released prototype ───────
_REVISED_ACTIVE_COILS = 10
_REVISED_SPRING_RATE = 7.225
_REVISED_WIRE_MASS_PER_PIECE_KG = 0.025422


def _revise_the_prototype(api: ApiClient):
    """D1 released as a prototype, then re-cut at ten active coils."""
    world = X.build_world(api, "prototype", program=_SAFETY_PROGRAM)
    version_before = world.design_version
    revised = get_success_data(
        api.revise_design(
            world.design_id,
            F.revision_payload(version_before, active_coils=_REVISED_ACTIVE_COILS),
            DESIGN_ENGINEER_HEADERS,
        )
    )
    return world, revised, version_before


def test_a_revision_walks_a_released_prototype_back_to_draft(api):
    """PRD §3.3: "Consider a design that has been rejected, or a prototype that has
    been released and now needs another engineering loop."
    PRD §3.3: "An accepted revision does the following bookkeeping:
    `superseded_revision_no` is set to the value `current_revision_no` held before
    the revision, `current_revision_no` is increased by 1, `release_status` returns
    to `DRAFT`, `reviewed_by_user_id` is cleared to null, and `created_by_user_id` is
    re-stamped with the revising engineer's `X-User-ID` — so the
    segregation-of-duties gate on the next review is measured against whoever cut the
    latest revision."

    Design: Difficulty/non_linear_state_machine/spring_design_revision_reverts_prototype_release_to_draft
    """
    world, revised, version_before = _revise_the_prototype(api)
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE

    assert revised["release_status"] == C.RELEASE_DRAFT, (
        "the revision edge runs backwards to DRAFT rather than forwards, got "
        f"{revised['release_status']!r}"
    )
    assert revised["current_revision_no"] == 2, (
        "the revision counter advances to 2, got "
        f"{revised['current_revision_no']}"
    )
    assert revised["superseded_revision_no"] == 1, (
        "the revision it replaced is recorded as 1, got "
        f"{revised['superseded_revision_no']}"
    )
    assert revised["reviewed_by_user_id"] is None, (
        "the prior engineering verdict is cleared to null, got "
        f"{revised['reviewed_by_user_id']!r}"
    )
    assert revised["created_by_user_id"] == "de-01", (
        "the revising engineer is re-stamped as the author, got "
        f"{revised['created_by_user_id']!r}"
    )
    assert revised["version"] == version_before + 1, (
        "the guarded write bumps the design version by exactly 1, got "
        f"{revised['version']} against {version_before}"
    )


def test_the_revision_recalculates_the_geometry_dependent_engineering_fields(api):
    """PRD §3.3: "Every computed engineering field is then recalculated from the
    post-revision geometry: spring rate, all four stress fields, the fatigue
    criterion and margin, the life tier, the per-piece wire mass, and the
    tangle-risk index and class."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear
    modulus multiplied by the wire diameter raised to the fourth power, divided by
    the product of eight, the mean coil diameter cubed, and the active coil count,
    with the result rounded half up to three decimal places."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from
    millimetres to metres by dividing by one thousand, multiplied by that area,
    multiplied by the material's `density_kg_per_m3`, rounded half up to exactly six
    decimal places."

    Design: Difficulty/non_linear_state_machine/spring_design_revision_reverts_prototype_release_to_draft
    """
    world, revised, _ = _revise_the_prototype(api)
    assert world.design["spring_rate_n_per_mm"] == C.D1_SPRING_RATE
    assert world.design["wire_mass_per_piece_kg"] == C.D1_WIRE_MASS_PER_PIECE_KG

    assert revised["active_coils"] == _REVISED_ACTIVE_COILS
    assert revised["spring_rate_n_per_mm"] == _REVISED_SPRING_RATE, (
        "two more active coils soften the spring from 9.031 to "
        f"{_REVISED_SPRING_RATE} N/mm, got {revised['spring_rate_n_per_mm']}"
    )
    assert revised["spring_rate_n_per_mm"] == A.expected_spring_rate(
        79.3, 2.5, 20.0, _REVISED_ACTIVE_COILS
    ), "the rate must be recomputed from the post-revision coil count"
    assert revised["wire_mass_per_piece_kg"] == _REVISED_WIRE_MASS_PER_PIECE_KG, (
        "two more coils of developed length raise the per-piece mass to "
        f"{_REVISED_WIRE_MASS_PER_PIECE_KG} kg, got "
        f"{revised['wire_mass_per_piece_kg']}"
    )
    assert revised["wire_mass_per_piece_kg"] == A.expected_wire_mass_per_piece_kg(
        2.5, 20.0, _REVISED_ACTIVE_COILS, C.END_CLOSED_GROUND, 7850
    ), "the per-piece mass must be recomputed from the post-revision geometry"
    A.assert_decimal_places(
        revised["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg"
    )


def test_the_revision_leaves_the_stress_driven_fatigue_verdict_where_it_was(api):
    """PRD §3.3: "Every computed engineering field is then recalculated from the
    post-revision geometry: spring rate, all four stress fields, the fatigue
    criterion and margin, the life tier, the per-piece wire mass, and the
    tangle-risk index and class."
    PRD §3.2: "Which one binds is decided by the owning program's
    `application_class`: the design's `fatigue_criterion` is set to `SODERBERG` when
    the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN` for
    `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`tangle_risk_index` is the free length divided by the outer diameter,
    rounded half up to three decimal places."

    Design: Difficulty/non_linear_state_machine/spring_design_revision_reverts_prototype_release_to_draft
    """
    _, revised, _ = _revise_the_prototype(api)

    assert revised["fatigue_criterion"] == C.CRITERION_SODERBERG, (
        "the owning safety program still binds the Soderberg line, got "
        f"{revised['fatigue_criterion']!r}"
    )
    assert revised["fatigue_margin_ratio"] == C.D1_FATIGUE_MARGIN_SODERBERG, (
        "the loads and the wire section did not change, so the margin stays at "
        f"{C.D1_FATIGUE_MARGIN_SODERBERG}, got {revised['fatigue_margin_ratio']}"
    )
    assert revised["stress_amplitude_mpa"] == C.D1_STRESS_AMPLITUDE
    assert revised["mean_stress_mpa"] == C.D1_MEAN_STRESS
    assert revised["predicted_fatigue_life_cycles"] == A.expected_life_tier(
        C.D1_FATIGUE_MARGIN_SODERBERG
    ), "the life tier follows the unchanged margin"
    assert revised["tangle_risk_index"] == C.D1_TANGLE_RISK_INDEX, (
        "the free length and outer diameter did not change, got "
        f"{revised['tangle_risk_index']}"
    )
    assert revised["tangle_risk_class"] == C.TANGLE_LOW
