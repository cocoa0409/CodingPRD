"""The plant floor: the capacity plan, machine-day buckets, ink draws and run lifecycles."""

from test_helpers import (
    ApiErrorId,
    CAMPAIGN_MANAGER,
    PRODUCTION_OPERATOR,
    SATURATION_ROUTES_FIVE_PIECES,
    SEVEN_RECORD_ROSTER,
    SINGLE_RECORD_ROSTER,
    assert_ink_volume_conservation,
    assert_machine_day_conservation,
    assert_production_run,
    build_addressed_scenario,
    build_eddm_scenario,
    mail_job_version,
    production_run_payload,
    production_runs_for,
    read_campaign,
    read_ink_lot,
    read_mail_job,
    read_production_run,
    validate_error,
    validate_success,
)


def _committed_single_piece_job(permit_number, **plant):
    return build_addressed_scenario(
        permit_number=permit_number, roster=SINGLE_RECORD_ROSTER, list_name="Mini List",
        dedupe_mode="EXACT", lock=True, stage="committed", with_plant=True, **plant,
    )


def _committed_six_piece_job(permit_number, **plant):
    return build_addressed_scenario(
        permit_number=permit_number, roster=SEVEN_RECORD_ROSTER,
        dedupe_mode="HOUSEHOLD", lock=True, stage="committed", with_plant=True, **plant,
    )


def _reserve(api, world, **overrides):
    return api.create_production_run(
        world["job"]["id"],
        production_run_payload(
            world["machine"]["id"], world["ink_lot"]["id"],
            mail_job_version(world["job"]["id"]), **overrides
        ),
        PRODUCTION_OPERATOR,
    )


def test_a_single_pass_run_charges_one_setup_on_top_of_its_write_minutes(api):
    """PRD §3.8: "From the run's inputs the server derives three numbers. The
    character load is the run's `piece_count` multiplied by the template's
    `character_count`. `planned_write_minutes` is that character load divided by
    the handwriting style's `chars_per_minute`, rounded **up** to a whole minute.
    `planned_slot_minutes` adds setup time to that: each setup pass costs 12
    slot-minutes, and a `SINGLE_PASS` run is charged one setup pass while a
    `SPLIT_RUN` run is charged two. `planned_ink_ul` is the character load
    multiplied by the style's `ink_ul_per_1000_chars` and divided by 1000, rounded
    **up** to a whole microlitre."

    Design: Difficulty/dual_variant_calc/production_capacity_single_pass_vs_split_run_slot_minutes
    """
    world = _committed_single_piece_job("PMT-101")

    run = validate_success(_reserve(api, world, capacity_variant="SINGLE_PASS"), 201)
    assert_production_run(run)

    # One piece of a 400-character template at 4000 characters a minute is a
    # character load of 400, so one write-minute after rounding up; one setup
    # pass of 12 minutes gives 13 slot-minutes.  Ink is 400 * 4.0 / 1000 = 1.6,
    # rounded up to 2 microlitres.
    assert run["planned_write_minutes"] == 1
    assert run["planned_slot_minutes"] == 13
    assert run["planned_ink_ul"] == 2
    assert run["status"] == "RESERVED"
    assert run["spoiled_piece_count"] == 0


def test_the_split_run_variant_alone_can_overrun_a_tight_machine_day(api):
    """PRD §3.8: "The variant choice is not cosmetic. A six-piece run of a
    400-character template in a style that writes 4000 characters per slot-minute
    has a character load of 2400 and therefore one write-minute; as a
    `SINGLE_PASS` it occupies 13 slot-minutes of the machine-day, and as a
    `SPLIT_RUN` it occupies 25. The same pieces, the same ink, a different
    machine-day footprint — enough to flip the capacity check on a machine
    configured with only 20 minutes of daily capacity."
    PRD §3.8: "The committed minutes on the pairing of this `machine_id` and this
    `run_date` — the sum of `planned_slot_minutes` over runs on that bucket whose
    status is `RESERVED`, `RUNNING`, `COMPLETED` or `FAILED` — plus this run's own
    `planned_slot_minutes` must not exceed the machine's `daily_capacity_minutes`;
    exceeding it is `ERR_MACHINE_CAPACITY_EXCEEDED` (HTTP 409) at rung 39."

    Design: Difficulty/dual_variant_calc/production_capacity_single_pass_vs_split_run_slot_minutes
    """
    world = _committed_single_piece_job(
        "PMT-101B", machine_code="SLOT-TIGHT", machine_capacity_minutes=20
    )

    single = validate_success(_reserve(api, world, capacity_variant="SINGLE_PASS"), 201)
    assert single["planned_slot_minutes"] == 13, "13 fits inside a 20-minute day"

    validate_success(
        api.void_production_run(single["id"], {"reason": "re-plan as split run"},
                                PRODUCTION_OPERATOR)
    )

    response = _reserve(api, world, capacity_variant="SPLIT_RUN")
    validate_error(response, ApiErrorId.ERR_MACHINE_CAPACITY_EXCEEDED.value)

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 20_000, "the refused split run drew no ink"


def test_a_failed_run_can_restart_and_complete_without_a_further_ink_draw(api):
    """PRD §3.8: "Starting a run moves it `RESERVED → RUNNING`, and it is also the
    retry edge `FAILED → RUNNING`."
    PRD §3.8: "Failing a `RUNNING` run moves it `RUNNING → FAILED`, stores the
    supplied `spoiled_piece_count`, and likewise leaves minutes and ink
    committed."
    PRD §3.8: "The first start on a job also drives the job
    `COMMITTED → IN_PRODUCTION`; a start against a job already in
    `IN_PRODUCTION` leaves the job where it is."

    Design: Difficulty/non_linear_state_machine/production_run_fail_then_restart_retry_loop
    """
    world = _committed_single_piece_job("PMT-111")
    run = validate_success(_reserve(api, world), 201)

    validate_success(api.start_production_run(run["id"], PRODUCTION_OPERATOR))
    failed = validate_success(
        api.fail_production_run(run["id"], {"spoiled_piece_count": 1}, PRODUCTION_OPERATOR)
    )
    assert failed["status"] == "FAILED"
    assert failed["spoiled_piece_count"] == 1

    validate_success(api.start_production_run(run["id"], PRODUCTION_OPERATOR))
    completed = validate_success(
        api.complete_production_run(run["id"], PRODUCTION_OPERATOR)
    )
    assert completed["status"] == "COMPLETED"
    assert completed["spoiled_piece_count"] == 1
    assert read_mail_job(world["job"]["id"])["status"] == "IN_PRODUCTION"


def test_the_retry_loop_draws_no_additional_ink_from_the_lot(api):
    """PRD §3.8: "Retrying a failed run draws **no** additional slot-minutes and
    **no** additional ink: the original reservation was never released, which is
    exactly why a failed run still counts against its machine-day bucket and its
    lot."
    PRD §2.10: "An `InkLot`'s `remaining_ul` equals its `initial_volume_ul` minus
    the sum of `planned_ink_ul` over every production run drawing on that lot
    whose status is `RESERVED`, `RUNNING`, `COMPLETED` or `FAILED`."

    Design: Difficulty/non_linear_state_machine/production_run_fail_then_restart_retry_loop
    """
    world = _committed_single_piece_job("PMT-111")
    run = validate_success(_reserve(api, world), 201)
    assert run["planned_ink_ul"] == 2
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 19_998

    validate_success(api.start_production_run(run["id"], PRODUCTION_OPERATOR))
    validate_success(
        api.fail_production_run(run["id"], {"spoiled_piece_count": 1}, PRODUCTION_OPERATOR)
    )
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 19_998

    validate_success(api.start_production_run(run["id"], PRODUCTION_OPERATOR))
    validate_success(api.complete_production_run(run["id"], PRODUCTION_OPERATOR))

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 19_998
    assert lot["status"] == "OPEN"
    assert_ink_volume_conservation(lot, production_runs_for(mail_job_id=world["job"]["id"]))


def test_a_stale_job_version_pre_empts_the_machine_capacity_rung(api):
    """PRD §2.7: "**Reserving a production run.** `POST
    /mail/mail-jobs/{mail_job_id}/production-runs` requires
    `expected_mail_job_version` matching the target `MailJob`'s current `version`."
    PRD §2.7: "A mismatch is `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.6: "**For any request, the first rung whose condition fails produces the
    response, and no later rung is evaluated.**"

    Design: Difficulty/priority_pair_validation_conflict/stale_version_preempts_machine_capacity
    """
    world = _committed_single_piece_job(
        "PMT-131", machine_code="SLOT-TIGHT", machine_capacity_minutes=20
    )
    stale_version = mail_job_version(world["job"]["id"]) - 1

    response = api.create_production_run(
        world["job"]["id"],
        production_run_payload(world["machine"]["id"], world["ink_lot"]["id"],
                               stale_version, capacity_variant="SPLIT_RUN"),
        PRODUCTION_OPERATOR,
    )
    error = validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert error["error_id"] != ApiErrorId.ERR_MACHINE_CAPACITY_EXCEEDED.value


def test_the_stale_reservation_creates_nothing_and_draws_nothing(api):
    """PRD §2.7: "If the value does not equal the parent's current `version`, the
    write is rejected at rung 11 with `ERR_STALE_VERSION` (HTTP 412), and nothing
    is created or modified."
    PRD §3.8: "A new lot's `remaining_ul` is initialised to its `initial_volume_ul`
    and its `status` to `SEALED`."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_preempts_machine_capacity
    """
    world = _committed_single_piece_job(
        "PMT-131", machine_code="SLOT-TIGHT", machine_capacity_minutes=20
    )
    stale_version = mail_job_version(world["job"]["id"]) - 1

    api.create_production_run(
        world["job"]["id"],
        production_run_payload(world["machine"]["id"], world["ink_lot"]["id"],
                               stale_version, capacity_variant="SPLIT_RUN"),
        PRODUCTION_OPERATOR,
    )

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 20_000
    assert lot["status"] == "SEALED"
    assert read_mail_job(world["job"]["id"])["status"] == "COMMITTED"
    assert production_runs_for(mail_job_id=world["job"]["id"]) == []


def test_reserving_against_an_offline_machine_is_refused(api):
    """PRD §3.8: "The named machine must be `ONLINE` — an offline machine is
    `ERR_MACHINE_OFFLINE` (HTTP 409) at rung 22."
    PRD §3.8: "A `ProductionOperator` registers a robot-pen machine with a
    globally unique `machine_code`, an optional `daily_capacity_minutes` of at
    least 1 slot-minute defaulting to 480 — eight hours of pen time per calendar
    day — and an optional `status` of `ONLINE` or `OFFLINE`, defaulting to
    `ONLINE`."

    Design: Difficulty/cross_entity_state_dependency/run_reservation_requires_online_machine
    """
    world = _committed_single_piece_job(
        "PMT-151", machine_code="SLOT-DOWN", machine_status="OFFLINE"
    )

    response = _reserve(api, world)
    validate_error(response, ApiErrorId.ERR_MACHINE_OFFLINE.value)


def test_the_offline_refusal_leaves_the_lot_sealed_and_the_job_committed(api):
    """PRD §3.8: "On acceptance the run is created at `status` `RESERVED` with
    `spoiled_piece_count` 0, `planned_ink_ul` is drawn from the lot's
    `remaining_ul`, `planned_slot_minutes` is committed against the machine-day
    bucket, and the owning job's `version` increments by one."
    PRD §3.8: "It opens on first use, moving `SEALED → OPEN` when a run first draws
    on it."

    Design: Difficulty/cross_entity_state_dependency/run_reservation_requires_online_machine
    """
    world = _committed_single_piece_job(
        "PMT-151", machine_code="SLOT-DOWN", machine_status="OFFLINE"
    )

    _reserve(api, world)

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 20_000
    assert lot["status"] == "SEALED"
    assert read_mail_job(world["job"]["id"])["status"] == "COMMITTED"


def test_two_runs_on_the_same_machine_day_contend_for_one_capacity_pool(api):
    """PRD §2.10: "For every pairing of a machine and a `run_date`, the committed
    minutes are the sum of `planned_slot_minutes` over production runs on that
    machine and that date whose status is `RESERVED`, `RUNNING`, `COMPLETED` or
    `FAILED`; `VOIDED` runs are excluded. That sum must never exceed the machine's
    `daily_capacity_minutes`."
    PRD §3.8: "The committed minutes on the pairing of this `machine_id` and this
    `run_date` — the sum of `planned_slot_minutes` over runs on that bucket whose
    status is `RESERVED`, `RUNNING`, `COMPLETED` or `FAILED` — plus this run's own
    `planned_slot_minutes` must not exceed the machine's `daily_capacity_minutes`;
    exceeding it is `ERR_MACHINE_CAPACITY_EXCEEDED` (HTTP 409) at rung 39."

    Design: Difficulty/resource_temporal_overlap/machine_day_aggregate_capacity_contention
    """
    world = _committed_six_piece_job(
        "PMT-160", machine_code="SLOT-MED", machine_capacity_minutes=25
    )
    assert world["job"]["billable_piece_count"] == 6

    first = validate_success(
        _reserve(api, world, run_date="2026-06-05", piece_count=3), 201
    )
    # Three pieces of a 400-character template is a load of 1200 characters, one
    # write-minute after rounding up, plus one 12-minute setup pass.
    assert first["planned_slot_minutes"] == 13

    response = _reserve(api, world, run_date="2026-06-05", piece_count=3)
    validate_error(response, ApiErrorId.ERR_MACHINE_CAPACITY_EXCEEDED.value)

    assert_machine_day_conservation(
        world["machine"], production_runs_for(machine_id=world["machine"]["id"]),
        "2026-06-05",
    )


def test_the_same_reservation_succeeds_on_the_next_machine_day_bucket(api):
    """PRD §2.10: "The `run_date` is a discrete bucket, not an interval — two runs
    on the same date always contend for the same capacity regardless of any clock
    time — and voiding a run must restore the committed total to its exact
    pre-reservation value."
    PRD §3.8: "`planned_ink_ul` is the character load multiplied by the style's
    `ink_ul_per_1000_chars` and divided by 1000, rounded **up** to a whole
    microlitre."

    Design: Difficulty/resource_temporal_overlap/machine_day_aggregate_capacity_contention
    """
    world = _committed_six_piece_job(
        "PMT-160", machine_code="SLOT-MED", machine_capacity_minutes=25
    )

    first = validate_success(
        _reserve(api, world, run_date="2026-06-05", piece_count=3), 201
    )
    _reserve(api, world, run_date="2026-06-05", piece_count=3)
    second = validate_success(
        _reserve(api, world, run_date="2026-06-06", piece_count=3), 201
    )

    assert second["run_date"] == "2026-06-06"
    assert second["planned_slot_minutes"] == 13
    # 1200 characters * 4.0 / 1000 = 4.8, rounded up to 5 microlitres each.
    assert first["planned_ink_ul"] == 5
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 19_990
    assert read_mail_job(world["job"]["id"])["billable_piece_count"] == 6


def test_voiding_a_run_returns_its_ink_to_the_lot_exactly(api):
    """PRD §2.10: "Runs in `VOIDED` status release their draw and are excluded from
    the sum. Reserving a run and then voiding it must return `remaining_ul` to
    exactly its pre-draw value."
    PRD §3.8: "Voiding a run — permitted from `RESERVED` or `FAILED`, never from
    `RUNNING` or `COMPLETED`, with an optional `reason` — moves it
    `RESERVED → VOIDED` or `FAILED → VOIDED`, returns its `planned_ink_ul` to the
    lot, releases its `planned_slot_minutes` on the machine-day bucket, restores a
    depleted lot to `OPEN` if the return lifts `remaining_ul` strictly above the
    safety reserve, and increments the run's `version`."

    Design: Difficulty/compensating_invariant/void_run_restores_ink_volume_and_machine_slot_minutes
    """
    world = _committed_single_piece_job(
        "PMT-171", machine_code="SLOT-EXACT", machine_capacity_minutes=13
    )
    run = validate_success(_reserve(api, world), 201)
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 19_998

    voided = validate_success(
        api.void_production_run(run["id"], {"reason": "machine re-plan"},
                                PRODUCTION_OPERATOR)
    )
    assert voided["status"] == "VOIDED"
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 20_000


def test_voiding_a_run_frees_the_whole_machine_day_for_an_identical_run(api):
    """PRD §2.10: "For every pairing of a machine and a `run_date`, the committed
    minutes are the sum of `planned_slot_minutes` over production runs on that
    machine and that date whose status is `RESERVED`, `RUNNING`, `COMPLETED` or
    `FAILED`; `VOIDED` runs are excluded. That sum must never exceed the machine's
    `daily_capacity_minutes`."
    PRD §3.8: "It opens on first use, moving `SEALED → OPEN` when a run first draws
    on it."

    Design: Difficulty/compensating_invariant/void_run_restores_ink_volume_and_machine_slot_minutes
    """
    world = _committed_single_piece_job(
        "PMT-171", machine_code="SLOT-EXACT", machine_capacity_minutes=13
    )
    first = validate_success(_reserve(api, world), 201)
    validate_success(
        api.void_production_run(first["id"], {"reason": "machine re-plan"},
                                PRODUCTION_OPERATOR)
    )

    second = validate_success(_reserve(api, world), 201)
    assert second["planned_slot_minutes"] == 13, "the 13-minute day was fully freed"
    assert second["status"] == "RESERVED"

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 19_998
    assert lot["status"] == "OPEN"


def test_completing_a_reserved_run_is_refused_by_the_run_state_gate(api):
    """PRD §3.8: "Completing a `RUNNING` run moves it `RUNNING → COMPLETED` and its
    minutes and ink stay committed permanently."
    PRD §3.8: "Any status outside those the operation permits is
    `ERR_RUN_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/production_run_complete_from_reserved_returns_run_invalid_state
    """
    world = _committed_single_piece_job("PMT-215")
    run = validate_success(_reserve(api, world), 201)

    response = api.complete_production_run(run["id"], PRODUCTION_OPERATOR)
    validate_error(response, ApiErrorId.ERR_RUN_INVALID_STATE.value)

    assert read_production_run(run["id"])["status"] == "RESERVED"
    assert read_mail_job(world["job"]["id"])["status"] == "COMMITTED"


def test_a_quarantined_lot_blocks_a_reservation_until_it_is_released(api):
    """PRD §3.8: "The named ink lot must be in `SEALED` or `OPEN` — a
    `QUARANTINED` or `DEPLETED` lot is `ERR_INK_LOT_UNAVAILABLE` (HTTP 409) at rung
    21."
    PRD §3.8: "Independently of volume, an operator may quarantine a lot that is in
    `SEALED` or `OPEN`, moving it along `OPEN → QUARANTINED`, and may release it
    along `QUARANTINED → OPEN`; each of those increments the lot's `version` by
    one, and the quarantine endpoint accepts an optional `reason`."

    Design: Corner/state_machines/quarantined_ink_lot_blocks_reservation_then_release_restores_it
    """
    world = _committed_single_piece_job("PMT-217")
    validate_success(
        api.quarantine_ink_lot(world["ink_lot"]["id"],
                               {"reason": "viscosity out of spec"}, PRODUCTION_OPERATOR)
    )

    blocked = _reserve(api, world)
    validate_error(blocked, ApiErrorId.ERR_INK_LOT_UNAVAILABLE.value)

    validate_success(api.release_ink_lot(world["ink_lot"]["id"], PRODUCTION_OPERATOR))
    run = validate_success(_reserve(api, world), 201)

    assert run["status"] == "RESERVED"
    assert run["planned_ink_ul"] == 2
    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 19_998
    assert lot["status"] == "OPEN"


def test_a_lot_of_the_wrong_formulation_cannot_feed_the_style(api):
    """PRD §3.8: "The lot's `ink_type` must equal the `ink_type` of the handwriting
    style behind the job's template, because the arm cannot write navy ink from a
    lot of blue; a mismatch is `ERR_INK_TYPE_MISMATCH` (HTTP 422) at rung 32."

    Design: Corner/validations/ink_type_mismatch_between_lot_and_handwriting_style
    """
    world = _committed_single_piece_job(
        "PMT-240", lot_code="LOT-BLACK", lot_ink_type="INK_BLACK_B"
    )
    assert world["style"]["ink_type"] == "INK_BLUE_A"

    response = _reserve(api, world)
    validate_error(response, ApiErrorId.ERR_INK_TYPE_MISMATCH.value)

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 20_000
    assert lot["status"] == "SEALED"


def test_the_piece_budget_and_the_ink_reserve_are_two_separate_refusals(api):
    """PRD §3.8: "The run's `piece_count` must not exceed the job's
    `billable_piece_count` less the pieces already reserved by that job's runs
    which are not `VOIDED`; asking for more is `ERR_RUN_PIECES_EXCEED_JOB` (HTTP
    422) at rung 36."
    PRD §3.8: "Then the lot's `remaining_ul` less this run's `planned_ink_ul` must
    not fall below the 500-microlitre safety reserve; falling below it is
    `ERR_INK_INSUFFICIENT` (HTTP 409) at rung 40."

    Design: Corner/validations/run_piece_count_above_job_budget_and_ink_below_reserve
    """
    world = _committed_single_piece_job(
        "PMT-241", lot_code="LOT-THIN", lot_volume_ul=501
    )
    assert world["job"]["billable_piece_count"] == 1

    too_many = _reserve(api, world, piece_count=5)
    validate_error(too_many, ApiErrorId.ERR_RUN_PIECES_EXCEED_JOB.value)

    # A single piece draws 2 microlitres, and 501 - 2 = 499 sits below the
    # 500-microlitre safety reserve.
    too_thin = _reserve(api, world, piece_count=1)
    validate_error(too_thin, ApiErrorId.ERR_INK_INSUFFICIENT.value)

    lot = read_ink_lot(world["ink_lot"]["id"])
    assert lot["remaining_ul"] == 501
    assert lot["status"] == "SEALED"


def test_an_eddm_job_refuses_a_robot_pen_run_yet_still_reaches_mailed(api):
    """PRD §2.9: "Where a caller **actively requests** a recipient-level operation
    through an EDDM job, the request is refused at rung 13 with
    `ERR_EDDM_NOT_APPLICABLE` (HTTP 422). Exactly four operations refuse in this
    way: reserving a robot-pen production run against the job, recording a return
    against a record whose last mail job is that job, applying a move update
    reached through such a record, and creating a reprint request reached through
    it."
    PRD §3.8: "An EDDM job never enters production at all and moves
    `COMMITTED → MAILED` directly."

    Design: Corner/state_machines/eddm_job_reaches_mailed_without_any_production_run
    """
    world = build_eddm_scenario(
        permit_number="PMT-219", stage="committed", with_plant=True,
        routes=SATURATION_ROUTES_FIVE_PIECES,
    )

    refused = api.create_production_run(
        world["job"]["id"],
        production_run_payload(world["machine"]["id"], world["ink_lot"]["id"],
                               mail_job_version(world["job"]["id"]),
                               run_date="2026-06-03", piece_count=5),
        PRODUCTION_OPERATOR,
    )
    validate_error(refused, ApiErrorId.ERR_EDDM_NOT_APPLICABLE.value)
    assert read_ink_lot(world["ink_lot"]["id"])["remaining_ul"] == 20_000

    mailed = validate_success(api.mail_mail_job(world["job"]["id"], PRODUCTION_OPERATOR))
    assert mailed["status"] == "MAILED"
    # EDDM transit is 12 days, so a 2026-06-15 in-home target drops on 2026-06-03.
    assert mailed["mail_date"] == "2026-06-03"

    route = validate_success(
        api.get_eddm_route(world["routes"][0]["id"], CAMPAIGN_MANAGER)
    )
    assert route["selected_piece_count"] == 3
    assert float(route["saturation_pct"]) == 100.00
    assert read_campaign(world["campaign"]["id"])["mailed_piece_count"] == 5
