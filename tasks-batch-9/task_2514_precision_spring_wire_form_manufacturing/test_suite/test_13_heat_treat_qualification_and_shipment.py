"""
The three machines that carry a finished run out of the shop.

A stress-relief batch is a timed occupation of an oven: it may only be charged
once the logical clock has reached its window, cancelling it hands the basket
mass back to the oven's free capacity, and discharging it writes the run's
heat-treat axis and its peening evidence in one call — with a hold fired when a
peened design was discharged unpeened.

A qualification submission is the customer's own machine: only the buying
program may decide its own package, a soft rejection can be resubmitted for one
more round, and both terminal verdicts reach back into the engineering record.

A shipment lot walks allocation, packing, shipping and either a return or a
quarantine, and every one of those edges moves the tooling amortization ledger
and the program's piece commitment as an exact transfer.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BATCH_INVALID_STATE,
    ERR_BATCH_WINDOW_NOT_REACHED,
    ERR_LOT_INVALID_STATE,
    ERR_PROGRAM_OWNERSHIP_MISMATCH,
    ERR_SUBMISSION_INVALID_STATE,
)
from test_helpers.test_users import (
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_ALT_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    PROGRAM_MANAGER_SECONDARY,
    QUALITY_INSPECTOR_HEADERS,
    make_customer_representative_headers,
)

# One minute short of the canonical 13:00 oven window, so the inclusive lower
# bound of the charging gate is probed from below.
ONE_MINUTE_BEFORE_BATCH_WINDOW = "2026-08-05T12:59:00Z"

# The canonical basket mass of the heat-treat batch, in a 600.0 kg oven.
BATCH_LOAD_KG = 250.0

# The canonical program commits 500 000 pieces and the canonical tool is
# capitalised at 4 800 000 cents, so the frozen per-piece amortization is
# 4 800 000 / 500 000 = 9.6 cents rounded up to 10.
COMMITTED_PIECES = 500_000
TOOLING_COST_CENTS = 4_800_000
AMORT_PER_PIECE_CENTS = 10

# The canonical shipment lot carries the program's minimum order quantity, so a
# forecast-basis shipment recovers 1 000 x 10 = 10 000 cents.
LOT_PIECES = 1_000
FORECAST_RECOVERY_CENTS = 10_000

# A tool capitalised at exactly the recovery one canonical lot posts, so that
# single shipment drives the ledger balance to zero.
SINGLE_LOT_TOOLING_COST_CENTS = 1_000


def _scheduled_batch_world(api: ApiClient, **kwargs) -> X.World:
    """A COMPLETE run whose 250.000 kg peening batch is SCHEDULED in a 600 kg oven.

    The chain stops one step short of charging the oven, so the run's heat-treat
    axis is still at rest while the oven already carries the basket's mass as
    scheduled load. The logical clock is left at the setup-window start, which is
    earlier than the batch window, so a test may move it wherever it needs.
    """
    world = X.build_world(api, "complete", **kwargs)
    world.oven = X.commission_oven(api)
    world.batch = X.schedule_batch(api, world.oven_id, world.run_id)
    world.oven = X.refresh_oven(api, world.oven_id)
    return world


def test_batch_charge_before_its_window_is_reached_is_refused(api):
    """PRD §3.9: "The batch must be `SCHEDULED`, otherwise `ERR_BATCH_INVALID_STATE`
    (HTTP 409), and the logical clock must have reached at least `window_start`,
    otherwise `ERR_BATCH_WINDOW_NOT_REACHED` (HTTP 409)."
    PRD §3.9: "The run's `heat_treat_state` stays `NOT_STARTED` — scheduling a batch is
    not charging one."

    Design: Corner/state_machines/batch_start_before_its_window_is_reached_rejected
    """
    world = _scheduled_batch_world(api)
    assert world.batch["window_start"] == C.CLOCK_BATCH_WINDOW_START, (
        "the batch under test must be the canonical 13:00 window, so one minute "
        f"before it is 12:59, got {world.batch['window_start']}"
    )

    X.pin_clock(api, ONE_MINUTE_BEFORE_BATCH_WINDOW)
    validate_error(
        api.start_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS),
        ERR_BATCH_WINDOW_NOT_REACHED,
    )

    batch = X.refresh_batch(api, world.batch_id)
    assert batch["batch_status"] == C.BATCH_SCHEDULED, (
        "a refused charge leaves the batch SCHEDULED, because the clock has not "
        f"reached window_start, got {batch['batch_status']}"
    )
    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        "scheduling a batch is not charging one, so the run's heat_treat_state "
        f"stays NOT_STARTED, got {run['heat_treat_state']}"
    )


def test_batch_cancel_returns_the_basket_mass_to_the_oven(api):
    """PRD §3.9: "Cancelling a batch is available only from `SCHEDULED`; anything else
    answers `ERR_BATCH_INVALID_STATE`."
    PRD §3.9: "The batch moves to `CANCELLED` and its `load_kg` is removed from the
    oven's `scheduled_load_kg`, so the interval it occupied stops counting toward
    capacity for every later batch booking."
    PRD §3.9: "The run's `heat_treat_state` returns to `NOT_STARTED` when no `RUNNING`
    or `COMPLETE` batch remains for that run."
    PRD §3.7: "A newly opened run starts on both axes at rest — `process_status`
    `FAI_PENDING`, `quality_status` `OPEN`, `fai_disposition` `PENDING`,
    `heat_treat_state` `NOT_STARTED`, `peening_verified` false, `produced_pieces` and
    `scrapped_pieces` at 0, `wire_consumed_kg` at 0.000, and both `min_cpk_observed`
    and `min_ppk_observed` null."

    Design: Corner/state_machines/batch_cancel_releases_the_oven_scheduled_load
    """
    world = _scheduled_batch_world(api)
    assert world.oven["scheduled_load_kg"] == BATCH_LOAD_KG, (
        "a successful booking adds the batch's load_kg to the oven's "
        f"scheduled_load_kg, expected {BATCH_LOAD_KG}, got "
        f"{world.oven['scheduled_load_kg']}"
    )

    batch = validate_success(
        api.cancel_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS)
    )
    assert batch["batch_status"] == C.BATCH_CANCELLED, (
        "cancelling a SCHEDULED batch moves it to CANCELLED, got "
        f"{batch['batch_status']}"
    )

    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == 0.0, (
        "the cancelled batch's load_kg is removed from the oven's "
        f"scheduled_load_kg, expected 0.0, got {oven['scheduled_load_kg']}"
    )
    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        "no RUNNING or COMPLETE batch remains, so the run's heat_treat_state "
        f"returns to NOT_STARTED, got {run['heat_treat_state']}"
    )
    assert run["peening_verified"] is False, (
        "the batch was never discharged, so peening_verified stays at the false "
        f"it was opened with, got {run['peening_verified']}"
    )


def test_batch_discharge_stamps_the_heat_treat_axis_and_the_peening_evidence(api):
    """PRD §3.9: "Discharging takes a `RUNNING` batch to `COMPLETE` — any other
    `batch_status` answers `ERR_BATCH_INVALID_STATE` — and requires the technician to
    state `peening_performed`, whether shot peening actually happened."
    PRD §3.9: "Discharge removes the batch's `load_kg` from the oven's
    `scheduled_load_kg`, sets the run's `heat_treat_state` to `COMPLETE`, and sets the
    run's `peening_verified` to true only when `peening_performed` is true."
    PRD §3.9: "Then comes the trap: **if the design requires shot peening and the batch
    reports that peening was not performed**, that is, `shot_peening_required` on the
    design is true while `peening_performed` on the batch is false, the run's
    `quality_status` transitions `OPEN → SPC_HOLD` and the same cascade as an
    out-of-control safety-critical subgroup fires — the run's `ALLOCATED` and `PACKED`
    lots are quarantined with `quarantine_reason` `SPC_HOLD_CASCADE`, each affected
    program's `quarantined_lot_count`, `allocated_pieces` and `open_commitment_pieces`
    are adjusted, and each affected `delivery_posture` is re-derived."

    Design: Corner/state_machines/batch_complete_stamps_heat_treat_state_and_peening_verified
    """
    world = _scheduled_batch_world(api)
    assert world.design["shot_peening_required"] is True, (
        "the design under test must demand shot peening, so honouring it is what "
        "keeps the quality axis open"
    )

    X.pin_clock(api, C.CLOCK_BATCH_WINDOW_START)
    validate_success(api.start_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS))

    batch = validate_success(
        api.complete_batch(
            world.batch_id, {"peening_performed": True}, PROCESS_TECHNICIAN_HEADERS
        )
    )
    assert batch["batch_status"] == C.BATCH_COMPLETE, (
        "discharging a RUNNING batch takes it to COMPLETE, got "
        f"{batch['batch_status']}"
    )
    assert batch["peening_performed"] is True, (
        "peening_performed is the outcome recorded at discharge, got "
        f"{batch['peening_performed']}"
    )

    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == 0.0, (
        "discharge removes the batch's load_kg from the oven's scheduled_load_kg, "
        f"expected 0.0, got {oven['scheduled_load_kg']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE, (
        "discharge sets the run's heat_treat_state to COMPLETE, got "
        f"{run['heat_treat_state']}"
    )
    assert run["peening_verified"] is True, (
        "peening_verified goes true because peening_performed was true, got "
        f"{run['peening_verified']}"
    )
    assert run["quality_status"] == C.QUALITY_OPEN, (
        "the peening trap only fires when a required peening was not performed, so "
        f"an honoured recipe leaves quality_status OPEN, got {run['quality_status']}"
    )


def test_batch_discharge_without_peening_holds_a_run_whose_design_demands_it(api):
    """PRD §3.9: "Discharge removes the batch's `load_kg` from the oven's
    `scheduled_load_kg`, sets the run's `heat_treat_state` to `COMPLETE`, and sets the
    run's `peening_verified` to true only when `peening_performed` is true."
    PRD §3.9: "Then comes the trap: **if the design requires shot peening and the batch
    reports that peening was not performed**, that is, `shot_peening_required` on the
    design is true while `peening_performed` on the batch is false, the run's
    `quality_status` transitions `OPEN → SPC_HOLD` and the same cascade as an
    out-of-control safety-critical subgroup fires — the run's `ALLOCATED` and `PACKED`
    lots are quarantined with `quarantine_reason` `SPC_HOLD_CASCADE`, each affected
    program's `quarantined_lot_count`, `allocated_pieces` and `open_commitment_pieces`
    are adjusted, and each affected `delivery_posture` is re-derived."
    PRD §3.1: "If no submission of the program is in either granted status, the posture
    is `BLOCKED`."

    Design: Corner/state_machines/batch_complete_without_peening_holds_a_run_whose_design_demands_it
    """
    world = _scheduled_batch_world(api)
    assert world.design["shot_peening_required"] is True, (
        "the trap requires a design whose shot_peening_required is true"
    )

    X.pin_clock(api, C.CLOCK_BATCH_WINDOW_START)
    validate_success(api.start_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS))

    batch = validate_success(
        api.complete_batch(
            world.batch_id, {"peening_performed": False}, PROCESS_TECHNICIAN_HEADERS
        )
    )
    assert batch["batch_status"] == C.BATCH_COMPLETE, (
        "an unpeened discharge still completes the batch, got "
        f"{batch['batch_status']}"
    )
    assert batch["peening_performed"] is False, (
        f"the technician stated peening_performed false, got {batch['peening_performed']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE, (
        "the soak still finished, so heat_treat_state is COMPLETE regardless of "
        f"peening, got {run['heat_treat_state']}"
    )
    assert run["peening_verified"] is False, (
        "peening_verified goes true only when peening_performed is true, got "
        f"{run['peening_verified']}"
    )
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        "a required peening reported as not performed transitions the run's "
        f"quality_status OPEN to SPC_HOLD, got {run['quality_status']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "no submission of this program is in a granted status, so the re-derived "
        f"posture is BLOCKED, got {program['delivery_posture']}"
    )


def test_batch_charge_on_a_cancelled_batch_is_refused(api):
    """PRD §3.9: "Cancelling a batch is available only from `SCHEDULED`; anything else
    answers `ERR_BATCH_INVALID_STATE`."
    PRD §3.9: "The batch must be `SCHEDULED`, otherwise `ERR_BATCH_INVALID_STATE`
    (HTTP 409), and the logical clock must have reached at least `window_start`,
    otherwise `ERR_BATCH_WINDOW_NOT_REACHED` (HTTP 409)."
    PRD §3.9: "The batch moves to `CANCELLED` and its `load_kg` is removed from the
    oven's `scheduled_load_kg`, so the interval it occupied stops counting toward
    capacity for every later batch booking."

    Design: Corner/state_machines/batch_start_on_a_cancelled_batch_rejected
    """
    world = _scheduled_batch_world(api)
    validate_success(api.cancel_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS))

    # The window gate is satisfied before the charge is attempted, so the refusal
    # can only come from the batch's own status.
    X.pin_clock(api, C.CLOCK_BATCH_WINDOW_START)
    validate_error(
        api.start_batch(world.batch_id, PROCESS_TECHNICIAN_HEADERS),
        ERR_BATCH_INVALID_STATE,
    )

    batch = X.refresh_batch(api, world.batch_id)
    assert batch["batch_status"] == C.BATCH_CANCELLED, (
        "CANCELLED is not SCHEDULED, so the refused charge leaves the batch "
        f"CANCELLED, got {batch['batch_status']}"
    )
    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == 0.0, (
        "the cancelled mass has left the oven and a refused charge does not put it "
        f"back, expected 0.0, got {oven['scheduled_load_kg']}"
    )


def test_revision_requested_package_resubmits_into_a_second_round(api):
    """PRD §3.10: "`REQUEST_REVISION` is the soft rejection: the submission moves to
    `REVISION_REQUESTED` and nothing else changes."
    PRD §3.10: "A `ProgramManager` may resubmit a package whose `submission_status` is
    `REVISION_REQUESTED` or `INTERIM_APPROVED`; `SUBMITTED`, `APPROVED` and
    `REJECTED_FINAL` answer `ERR_SUBMISSION_INVALID_STATE`."
    PRD §3.10: "A successful resubmit increments `round_no` by 1, returns
    `submission_status` to `SUBMITTED`, clears `interim_piece_cap` back to null, clears
    `reviewed_by_program_id` and `decided_at` back to null, and re-stamps
    `submitted_by_user_id` from the acting header."
    PRD §3.10: "The design keeps its `PROTOTYPE_RELEASED` status and its tooling stays
    `PENDING`; because no verdict of record is in force, the program's re-derived
    `delivery_posture` falls back to `BLOCKED` unless some other submission on the
    program is still `APPROVED` or `INTERIM_APPROVED`."

    Design: Corner/state_machines/submission_revision_requested_then_resubmit_reopens_round_two
    """
    world = X.build_world(api, "approved", verdict=C.DECISION_REQUEST_REVISION)
    assert world.submission["submission_status"] == C.SUBMISSION_REVISION_REQUESTED, (
        "the soft rejection must have landed before the resubmit is attempted, got "
        f"{world.submission['submission_status']}"
    )
    assert world.submission["round_no"] == 1, (
        f"the first filing opens on round 1, got {world.submission['round_no']}"
    )

    submission = validate_success(
        api.resubmit_submission(world.submission_id, PROGRAM_MANAGER_ALT_HEADERS)
    )
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "a successful resubmit returns submission_status to SUBMITTED, got "
        f"{submission['submission_status']}"
    )
    assert submission["round_no"] == 2, (
        f"a successful resubmit increments round_no by 1, got {submission['round_no']}"
    )
    assert submission["interim_piece_cap"] is None, (
        "a successful resubmit clears interim_piece_cap back to null, got "
        f"{submission['interim_piece_cap']}"
    )
    assert submission["reviewed_by_program_id"] is None, (
        "a successful resubmit clears reviewed_by_program_id back to null, got "
        f"{submission['reviewed_by_program_id']}"
    )
    assert submission["decided_at"] is None, (
        f"a successful resubmit clears decided_at back to null, got {submission['decided_at']}"
    )
    assert submission["submitted_by_user_id"] == PROGRAM_MANAGER_SECONDARY, (
        "a successful resubmit re-stamps submitted_by_user_id from the acting "
        f"header, expected {PROGRAM_MANAGER_SECONDARY}, got "
        f"{submission['submitted_by_user_id']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        "the soft rejection left the design PROTOTYPE_RELEASED and resubmitting "
        f"requires it to still be there, got {design['release_status']}"
    )


def test_final_rejection_pulls_the_prototype_design_back_to_rejected(api):
    """PRD §3.10: "Every verdict stamps `reviewed_by_program_id` from the header and
    `decided_at` from the logical clock, and every verdict re-derives the program's
    `delivery_posture`."
    PRD §3.10: "`REJECT_FINAL` is the hard rejection and, like `APPROVE`, cascades:
    `submission_status` becomes `REJECTED_FINAL`, which is terminal, the design is
    driven `PROTOTYPE_RELEASED → REJECTED`, and the program's `delivery_posture` is
    re-derived to `BLOCKED`."
    PRD §3.4: "The `PENDING → AMORTIZING` promotion fires as a system event when the
    tool's design reaches `PRODUCTION_RELEASED`, and it is the moment the amortization
    basis is frozen: `amortization_basis_pieces` takes the owning program's
    `committed_pieces`, and `amort_per_piece_cents` becomes `original_cost_cents`
    divided by that basis, rounded **up** to the next whole cent."

    Design: Corner/state_machines/submission_reject_final_pulls_the_prototype_design_back_to_rejected
    """
    world = X.submitted_world(api)

    submission = validate_success(
        api.review_submission(
            world.submission_id,
            {"decision": C.DECISION_REJECT_FINAL},
            world.customer,
        )
    )
    assert submission["submission_status"] == C.SUBMISSION_REJECTED_FINAL, (
        "REJECT_FINAL drives submission_status to the terminal REJECTED_FINAL, got "
        f"{submission['submission_status']}"
    )
    assert submission["reviewed_by_program_id"] == world.program_id, (
        "every verdict stamps reviewed_by_program_id from the header, expected "
        f"{world.program_id}, got {submission['reviewed_by_program_id']}"
    )
    assert submission["decided_at"] is not None, (
        "every verdict stamps decided_at from the logical clock, so it is no longer "
        "the null it was filed with"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_REJECTED, (
        "the hard rejection drives the design PROTOTYPE_RELEASED to REJECTED, got "
        f"{design['release_status']}"
    )
    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        "the hard rejection re-derives the program's delivery_posture to BLOCKED, "
        f"got {program['delivery_posture']}"
    )
    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["amortization_status"] == C.AMORT_PENDING, (
        "amortization is armed only when the design reaches PRODUCTION_RELEASED, "
        f"and a rejected design never does, got {tooling['amortization_status']}"
    )
    assert tooling["amort_per_piece_cents"] is None, (
        "the basis is frozen only on the PENDING to AMORTIZING promotion, got "
        f"{tooling['amort_per_piece_cents']}"
    )


def test_verdict_from_a_foreign_program_representative_is_forbidden(api):
    """PRD §2.1: "Any customer-representative request that targets a program, design,
    submission or lot belonging to a different program is rejected with
    `ERR_PROGRAM_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §3.10: "The verdict belongs to the `CustomerRepresentative` alone, and only for
    its own program: because that role is entity-backed, its `X-User-ID` must equal the
    submission's `program_id` or the request is refused with
    `ERR_PROGRAM_OWNERSHIP_MISMATCH`."
    PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status`
    `SUBMITTED` with `submitted_by_user_id` stamped from the header,
    `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."

    Design: Corner/state_machines/submission_review_by_a_foreign_program_representative_is_forbidden
    """
    world = X.submitted_world(api)
    other_program = X.open_program(api, program_code="PGM-FOREIGN")
    assert other_program["id"] != world.program_id, (
        "the foreign representative must be backed by a different program row"
    )

    validate_error(
        api.review_submission(
            world.submission_id,
            {"decision": C.DECISION_APPROVE},
            make_customer_representative_headers(other_program["id"]),
        ),
        ERR_PROGRAM_OWNERSHIP_MISMATCH,
    )

    submission = X.refresh_submission(api, world.submission_id)
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "the refused verdict leaves the submission SUBMITTED, got "
        f"{submission['submission_status']}"
    )
    assert submission["reviewed_by_program_id"] is None, (
        "no verdict was recorded, so reviewed_by_program_id stays at the null it "
        f"was filed with, got {submission['reviewed_by_program_id']}"
    )
    assert submission["decided_at"] is None, (
        f"no verdict was recorded, so decided_at stays null, got {submission['decided_at']}"
    )


def test_approved_submission_is_terminal_and_refuses_a_second_verdict(api):
    """PRD §3.10: "The submission must be `SUBMITTED`; any other status answers
    `ERR_SUBMISSION_INVALID_STATE` (HTTP 409)."
    PRD §3.10: "Hop one sets `submission_status` to `APPROVED`, a terminal status."
    PRD §3.10: "Hop two promotes the design `PROTOTYPE_RELEASED → PRODUCTION_RELEASED`."

    Design: Corner/state_machines/submission_approved_is_terminal_and_a_second_verdict_rejected
    """
    world = X.approved_world(api)
    assert world.submission["submission_status"] == C.SUBMISSION_APPROVED, (
        "the full release must be on file before the second verdict is attempted, "
        f"got {world.submission['submission_status']}"
    )

    validate_error(
        api.review_submission(
            world.submission_id,
            {"decision": C.DECISION_REQUEST_REVISION},
            world.customer,
        ),
        ERR_SUBMISSION_INVALID_STATE,
    )

    submission = X.refresh_submission(api, world.submission_id)
    assert submission["submission_status"] == C.SUBMISSION_APPROVED, (
        "APPROVED is terminal, so the refused second verdict leaves it APPROVED, "
        f"got {submission['submission_status']}"
    )
    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PRODUCTION, (
        "the refused verdict does not walk hop two back, so the design stays "
        f"PRODUCTION_RELEASED, got {design['release_status']}"
    )


def test_lot_pack_ship_and_return_walks_the_whole_shipment_lifecycle(api):
    """PRD §3.11: "Success records the method and moves the lot `ALLOCATED → PACKED`."
    PRD §3.11: "Shipping then posts the tooling recovery computed under the program's
    `amortization_method` as described in section 3.4, writes it to the lot's
    `tooling_recovery_cents`, adds it to the tool's `recovered_cents` and subtracts it
    from `unamortized_cents`, and takes the tool `AMORTIZING → FULLY_AMORTIZED` if that
    leaves `unamortized_cents` at zero."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and
    `shipped_pieces` increases by it — `open_commitment_pieces` is untouched, because
    the commitment was consumed at allocation."
    PRD §3.11: "The lot becomes `SHIPPED` with `shipped_at` stamped from the logical
    clock, and `delivery_posture` is re-derived."
    PRD §3.11: "Only a `SHIPPED` lot may be returned."
    PRD §3.11: "The stored `tooling_recovery_cents` is subtracted from the tool's
    `recovered_cents` and added back to `unamortized_cents` **verbatim**, using the
    historical posting amount rather than a recomputation, which is what keeps
    `original_cost_cents` conserved even when the tool's balance has moved since."
    PRD §3.11: "On the program, `shipped_pieces` decreases by `piece_count` and
    `open_commitment_pieces` increases by it, so returned pieces go back on the
    commitment rather than back into allocation."
    PRD §3.11: "The lot becomes `RETURNED`, which is terminal, `shipped_at` is cleared
    to null, `tooling_recovery_cents` is left as the historical posting amount, and
    `delivery_posture` is re-derived."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount
    is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`,
    capped at the tool's live `unamortized_cents`; whichever of the two is smaller is
    posted."

    Design: Corner/state_machines/lot_pack_ship_return_walks_the_whole_shipment_lifecycle
    """
    world = X.allocated_world(api)
    assert world.tooling["amort_per_piece_cents"] == AMORT_PER_PIECE_CENTS, (
        f"the frozen basis must be {AMORT_PER_PIECE_CENTS} cents a piece for the "
        f"posting arithmetic to hold, got {world.tooling['amort_per_piece_cents']}"
    )
    assert world.lot["piece_count"] == LOT_PIECES, (
        f"the lot under test carries {LOT_PIECES} pieces, got {world.lot['piece_count']}"
    )

    packed = validate_success(
        api.pack_lot(
            world.lot_id,
            {"packaging_method": C.PACK_TANGLE_FREE_TRAY},
            PROCESS_TECHNICIAN_HEADERS,
        )
    )
    assert packed["lot_status"] == C.LOT_PACKED, (
        f"packing moves the lot ALLOCATED to PACKED, got {packed['lot_status']}"
    )
    assert packed["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        f"packing records the stated method, got {packed['packaging_method']}"
    )

    shipped = validate_success(api.ship_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))
    assert shipped["lot_status"] == C.LOT_SHIPPED, (
        f"shipping a PACKED lot makes it SHIPPED, got {shipped['lot_status']}"
    )
    assert shipped["shipped_at"] is not None, (
        "the shipped lot carries shipped_at stamped from the logical clock"
    )
    assert shipped["tooling_recovery_cents"] == FORECAST_RECOVERY_CENTS, (
        f"the forecast posting is {LOT_PIECES} pieces times "
        f"{AMORT_PER_PIECE_CENTS} cents, expected {FORECAST_RECOVERY_CENTS}, got "
        f"{shipped['tooling_recovery_cents']}"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["recovered_cents"] == FORECAST_RECOVERY_CENTS, (
        "the posting is added to the tool's recovered_cents, expected "
        f"{FORECAST_RECOVERY_CENTS}, got {tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == TOOLING_COST_CENTS - FORECAST_RECOVERY_CENTS, (
        "the posting is subtracted from unamortized_cents, expected "
        f"{TOOLING_COST_CENTS - FORECAST_RECOVERY_CENTS}, got "
        f"{tooling['unamortized_cents']}"
    )
    assert tooling["amortization_status"] == C.AMORT_AMORTIZING, (
        "the posting left unamortized_cents above zero, so the tool stays "
        f"AMORTIZING, got {tooling['amortization_status']}"
    )
    A.assert_tooling_ledger_conserved(tooling)

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 0, (
        "shipping decreases allocated_pieces by piece_count, expected 0, got "
        f"{program['allocated_pieces']}"
    )
    assert program["shipped_pieces"] == LOT_PIECES, (
        f"shipping increases shipped_pieces by piece_count, expected {LOT_PIECES}, "
        f"got {program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == COMMITTED_PIECES - LOT_PIECES, (
        "open_commitment_pieces is untouched by shipping because the commitment was "
        f"consumed at allocation, expected {COMMITTED_PIECES - LOT_PIECES}, got "
        f"{program['open_commitment_pieces']}"
    )

    returned = validate_success(api.return_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))
    assert returned["lot_status"] == C.LOT_RETURNED, (
        f"returning a SHIPPED lot makes it RETURNED, got {returned['lot_status']}"
    )
    assert returned["shipped_at"] is None, (
        f"the return clears shipped_at to null, got {returned['shipped_at']}"
    )
    assert returned["tooling_recovery_cents"] == FORECAST_RECOVERY_CENTS, (
        "tooling_recovery_cents is left as the historical posting amount, expected "
        f"{FORECAST_RECOVERY_CENTS}, got {returned['tooling_recovery_cents']}"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["recovered_cents"] == 0, (
        "the historical posting is subtracted from recovered_cents verbatim, "
        f"expected 0, got {tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == TOOLING_COST_CENTS, (
        "the historical posting is added back to unamortized_cents verbatim, "
        f"expected {TOOLING_COST_CENTS}, got {tooling['unamortized_cents']}"
    )
    assert tooling["amortization_status"] == C.AMORT_AMORTIZING, (
        "the tool never reached FULLY_AMORTIZED, so the reversal leaves it "
        f"AMORTIZING, got {tooling['amortization_status']}"
    )
    A.assert_tooling_ledger_conserved(tooling)

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == 0, (
        "the return decreases shipped_pieces by piece_count, expected 0, got "
        f"{program['shipped_pieces']}"
    )
    assert program["open_commitment_pieces"] == COMMITTED_PIECES, (
        "returned pieces go back on the commitment rather than back into "
        f"allocation, expected {COMMITTED_PIECES}, got "
        f"{program['open_commitment_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        "the return does not put pieces back into allocation, expected 0, got "
        f"{program['allocated_pieces']}"
    )
    A.assert_commitment_conserved(program)


def test_shipping_a_lot_that_was_never_packed_is_refused(api):
    """PRD §3.11: "A `ProgramManager` ships a `PACKED` lot; any other `lot_status`
    answers `ERR_LOT_INVALID_STATE` (HTTP 409)."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with
    `packaging_method` null, and it snapshots the commercial terms at creation:
    `unit_price_cents` from the program's `quoted_unit_price_cents`,
    `tooling_amort_per_piece_cents` from the program's
    `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count`
    multiplied by `unit_price_cents`."
    PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING` with
    `recovered_cents` at 0 and `unamortized_cents` equal to `original_cost_cents`."

    Design: Corner/state_machines/lot_ship_directly_from_allocated_rejected
    """
    world = X.allocated_world(api)
    assert world.lot["lot_status"] == C.LOT_ALLOCATED, (
        f"the lot under test must still be ALLOCATED, got {world.lot['lot_status']}"
    )

    validate_error(
        api.ship_lot(world.lot_id, PROGRAM_MANAGER_HEADERS), ERR_LOT_INVALID_STATE
    )

    lot = X.refresh_lot(api, world.lot_id)
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        "only a PACKED lot may ship, so the refused shipment leaves the lot "
        f"ALLOCATED, got {lot['lot_status']}"
    )
    assert lot["packaging_method"] is None, (
        "the lot opened with packaging_method null and no packing act intervened, "
        f"got {lot['packaging_method']}"
    )
    assert lot["tooling_recovery_cents"] == 0, (
        "no recovery was posted, so tooling_recovery_cents stays at the 0 it opened "
        f"with, got {lot['tooling_recovery_cents']}"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["recovered_cents"] == 0, (
        "a refused shipment posts nothing, so recovered_cents stays 0, got "
        f"{tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == TOOLING_COST_CENTS, (
        "a refused shipment posts nothing, so unamortized_cents stays at the "
        f"capitalised cost, expected {TOOLING_COST_CENTS}, got "
        f"{tooling['unamortized_cents']}"
    )
    A.assert_tooling_ledger_conserved(tooling)


def test_quarantine_from_packed_retains_the_packaging_method(api):
    """PRD §3.11: "A `QualityInspector` may quarantine any `ALLOCATED` or `PACKED` lot
    manually, supplying a `quarantine_reason`; the manual reason is `INSPECTOR_ACTION`,
    while `SPC_HOLD_CASCADE` is what the automatic cascades of sections 3.7, 3.8 and 3.9
    stamp."
    PRD §3.11: "The lot becomes `QUARANTINED` and retains its `packaging_method`."
    PRD §3.11: "The program's `quarantined_lot_count` increases by 1,
    `allocated_pieces` decreases by `piece_count` and `open_commitment_pieces` increases
    by the same amount — the pieces go back on the commitment — and `delivery_posture`
    is re-derived, which is what drops a healthy program to `AT_RISK`."
    PRD §3.1: "Otherwise, if `quarantined_lot_count` is at least 1 **or** such a held
    run exists, the posture is `AT_RISK`."

    Design: Corner/state_machines/lot_quarantine_from_packed_retains_the_packaging_method
    """
    world = X.packed_world(api)
    assert world.lot["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        "the lot under test must carry a recorded packaging method for the "
        f"retention claim to bite, got {world.lot['packaging_method']}"
    )

    lot = validate_success(
        api.quarantine_lot(
            world.lot_id,
            {"quarantine_reason": C.QUARANTINE_INSPECTOR_ACTION},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    assert lot["lot_status"] == C.LOT_QUARANTINED, (
        f"a manual hold makes the lot QUARANTINED, got {lot['lot_status']}"
    )
    assert lot["quarantine_reason"] == C.QUARANTINE_INSPECTOR_ACTION, (
        "the manual reason is INSPECTOR_ACTION, not the cascade's SPC_HOLD_CASCADE, "
        f"got {lot['quarantine_reason']}"
    )
    assert lot["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        "the quarantined lot retains its packaging_method — only a release clears "
        f"it, got {lot['packaging_method']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 1, (
        "the program's quarantined_lot_count increases by 1, got "
        f"{program['quarantined_lot_count']}"
    )
    assert program["allocated_pieces"] == 0, (
        "allocated_pieces decreases by the lot's piece_count, expected 0, got "
        f"{program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == COMMITTED_PIECES, (
        "the pieces go back on the commitment, expected "
        f"{COMMITTED_PIECES}, got {program['open_commitment_pieces']}"
    )
    assert program["delivery_posture"] == C.POSTURE_AT_RISK, (
        "a granted approval is on file but quarantined_lot_count is now 1, so the "
        f"re-derived posture is AT_RISK, got {program['delivery_posture']}"
    )
    A.assert_commitment_conserved(program)


def test_release_from_quarantine_clears_the_packaging_and_demands_a_repack(api):
    """PRD §3.11: "Releasing runs the mirror image: the lot must be `QUARANTINED`, the
    run's `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT` so a lot cannot be
    released while its run is still held, and `piece_count` must not exceed the
    program's live `open_commitment_pieces`, otherwise `ERR_COMMITMENT_EXCEEDED`."
    PRD §3.11: "Success returns the lot to `ALLOCATED`, clears `quarantine_reason` back
    to null and clears `packaging_method` to null — **the lot must be packed again**,
    and the packaging rules are re-applied from scratch."
    PRD §3.11: "The program's `quarantined_lot_count` decreases by 1,
    `allocated_pieces` increases by `piece_count`, `open_commitment_pieces` decreases by
    it, and `delivery_posture` is re-derived, returning to `ON_TRACK` only when the last
    quarantined lot has been released and no run of the program is on hold."

    Design: Corner/state_machines/lot_release_from_quarantine_clears_packaging_and_demands_a_repack
    """
    world = X.packed_world(api)
    held = validate_success(
        api.quarantine_lot(
            world.lot_id,
            {"quarantine_reason": C.QUARANTINE_INSPECTOR_ACTION},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    assert held["packaging_method"] == C.PACK_TANGLE_FREE_TRAY, (
        "the quarantined lot still carries its packaging method, so the release is "
        f"what clears it, got {held['packaging_method']}"
    )

    lot = validate_success(
        api.release_lot_from_quarantine(world.lot_id, QUALITY_INSPECTOR_HEADERS)
    )
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"a successful release returns the lot to ALLOCATED, got {lot['lot_status']}"
    )
    assert lot["quarantine_reason"] is None, (
        f"the release clears quarantine_reason back to null, got {lot['quarantine_reason']}"
    )
    assert lot["packaging_method"] is None, (
        "the release clears packaging_method to null because the lot must be packed "
        f"again, got {lot['packaging_method']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quarantined_lot_count"] == 0, (
        "the program's quarantined_lot_count decreases by 1, expected 0, got "
        f"{program['quarantined_lot_count']}"
    )
    assert program["allocated_pieces"] == LOT_PIECES, (
        "allocated_pieces increases by the lot's piece_count, expected "
        f"{LOT_PIECES}, got {program['allocated_pieces']}"
    )
    assert program["open_commitment_pieces"] == COMMITTED_PIECES - LOT_PIECES, (
        "open_commitment_pieces decreases by the lot's piece_count, expected "
        f"{COMMITTED_PIECES - LOT_PIECES}, got {program['open_commitment_pieces']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        "the last quarantined lot has been released and no run is on hold, so the "
        f"re-derived posture returns to ON_TRACK, got {program['delivery_posture']}"
    )
    A.assert_commitment_conserved(program)


def test_tooling_reaches_fully_amortized_when_the_balance_hits_zero(api):
    """PRD §3.4: "Once armed, each shipment posts a recovery into `recovered_cents` and
    out of `unamortized_cents`; when a posting drives `unamortized_cents` to exactly 0,
    the tool transitions `AMORTIZING → FULLY_AMORTIZED`."
    PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the amount
    is the lot's `piece_count` multiplied by the tool's frozen `amort_per_piece_cents`,
    capped at the tool's live `unamortized_cents`; whichever of the two is smaller is
    posted."
    PRD §3.11: "Shipping then posts the tooling recovery computed under the program's
    `amortization_method` as described in section 3.4, writes it to the lot's
    `tooling_recovery_cents`, adds it to the tool's `recovered_cents` and subtracts it
    from `unamortized_cents`, and takes the tool `AMORTIZING → FULLY_AMORTIZED` if that
    leaves `unamortized_cents` at zero."
    PRD §3.11: "On the program, `allocated_pieces` decreases by `piece_count` and
    `shipped_pieces` increases by it — `open_commitment_pieces` is untouched, because
    the commitment was consumed at allocation."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with
    `packaging_method` null, and it snapshots the commercial terms at creation:
    `unit_price_cents` from the program's `quoted_unit_price_cents`,
    `tooling_amort_per_piece_cents` from the program's
    `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count`
    multiplied by `unit_price_cents`."

    Design: Corner/state_machines/tooling_reaches_fully_amortized_when_the_balance_hits_zero
    """
    world = X.packed_world(
        api, tooling={"original_cost_cents": SINGLE_LOT_TOOLING_COST_CENTS}
    )
    assert world.tooling["amort_per_piece_cents"] == 1, (
        f"{SINGLE_LOT_TOOLING_COST_CENTS} cents over {COMMITTED_PIECES} committed "
        "pieces rounds up to 1 cent a piece, got "
        f"{world.tooling['amort_per_piece_cents']}"
    )
    assert world.program["quoted_unit_price_cents"] == 21, (
        "the canonical quote on a 1000-cent tool prices the piece at 21 cents, got "
        f"{world.program['quoted_unit_price_cents']}"
    )
    assert world.lot["unit_price_cents"] == world.program["quoted_unit_price_cents"], (
        "the lot snapshots unit_price_cents from the program's "
        f"quoted_unit_price_cents, got {world.lot['unit_price_cents']} against "
        f"{world.program['quoted_unit_price_cents']}"
    )
    assert world.lot["extended_price_cents"] == LOT_PIECES * 21, (
        "extended_price_cents is piece_count multiplied by unit_price_cents, "
        f"expected {LOT_PIECES * 21}, got {world.lot['extended_price_cents']}"
    )

    lot = validate_success(api.ship_lot(world.lot_id, PROGRAM_MANAGER_HEADERS))
    assert lot["lot_status"] == C.LOT_SHIPPED, (
        f"the PACKED lot ships, got {lot['lot_status']}"
    )
    assert lot["tooling_recovery_cents"] == SINGLE_LOT_TOOLING_COST_CENTS, (
        f"the forecast ask is {LOT_PIECES} pieces times 1 cent, which the live "
        f"unamortized_cents of {SINGLE_LOT_TOOLING_COST_CENTS} does not cut down, "
        f"got {lot['tooling_recovery_cents']}"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["recovered_cents"] == SINGLE_LOT_TOOLING_COST_CENTS, (
        "the posting is added to recovered_cents, expected "
        f"{SINGLE_LOT_TOOLING_COST_CENTS}, got {tooling['recovered_cents']}"
    )
    assert tooling["unamortized_cents"] == 0, (
        "the posting is subtracted from unamortized_cents and consumes it exactly, "
        f"expected 0, got {tooling['unamortized_cents']}"
    )
    assert tooling["amortization_status"] == C.AMORT_FULLY_AMORTIZED, (
        "a posting that drives unamortized_cents to exactly 0 takes the tool "
        f"AMORTIZING to FULLY_AMORTIZED, got {tooling['amortization_status']}"
    )
    A.assert_tooling_ledger_conserved(tooling)

    program = X.refresh_program(api, world.program_id)
    assert program["shipped_pieces"] == LOT_PIECES, (
        "shipping increases shipped_pieces by piece_count, expected "
        f"{LOT_PIECES}, got {program['shipped_pieces']}"
    )
    assert program["allocated_pieces"] == 0, (
        "shipping decreases allocated_pieces by piece_count, expected 0, got "
        f"{program['allocated_pieces']}"
    )
    A.assert_commitment_conserved(program)
