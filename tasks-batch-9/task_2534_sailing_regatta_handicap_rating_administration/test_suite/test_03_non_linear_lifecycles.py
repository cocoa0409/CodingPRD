"""Cyclic lifecycles: the recall-and-restart loop that escalates to a black flag,
the single permitted rehearing of a protest, and the inspection dimension that
cycles without ever touching the registration dimension.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    MEASUREMENT_D,
    ApiErrorId,
    build_accepted_fleet_world,
    create_protest_payload,
    decide_payload,
    evidence_payload,
    inspect_entry,
    read_division,
    read_entry,
    read_protest,
    read_race,
    read_result,
    read_standing,
    recall_payload,
    record_result,
    sail_and_score_race,
    schedule_hearing_payload,
    score_race,
    set_clock,
    start_race_payload,
)

RACE_START = "2026-08-05T14:00:00Z"


def _pending_race_world(entrants):
    """A racing regatta with the committee on station and race 1 still PENDING."""
    return build_accepted_fleet_world(
        entrants=entrants,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": RACE_START},),
    )


THREE_ENTRANTS = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
    {"key": "D", "helm": "helm_3", "measurement": MEASUREMENT_D},
)


def _recall_cycle_to_black_flag(api, world, start_race=True):
    """Two general recalls and two restarts, then optionally the valid start.

    With `start_race` false the race is left in `SEQUENCE_STARTED` under the
    armed black flag, which is the state PRD 3.7 describes an individual recall
    from: "While `black_flag_active` is false, the race stays in
    `SEQUENCE_STARTED` and no result is minted at all."
    """
    race_id = world["races"][1]["id"]
    pro = world["h"]["pro"]
    events = []
    for signal in ("2026-08-05T13:56:00Z", "2026-08-05T13:58:00Z"):
        validate_success(api.start_sequence(race_id, pro))
        events.append(
            validate_success(
                api.recall_race(race_id, recall_payload("GENERAL", signal), pro),
                expected_status=201,
            )
        )
    validate_success(api.start_sequence(race_id, pro))
    if start_race:
        validate_success(api.start_race(race_id, start_race_payload(RACE_START), pro))
    return race_id, events


def test_two_general_recalls_arm_the_black_flag_without_resetting_the_counter(api):
    """PRD 3.7: "A `GENERAL` recall sends the whole fleet back: `start_status`
    moves `SEQUENCE_STARTED → GENERAL_RECALLED`, `general_recall_count` grows by
    one, and once that cumulative count reaches 2, `black_flag_active` becomes
    true."

    PRD 3.7 also fixes what the restart leaves alone: "What the re-start
    deliberately does **not** do is reset the recall counters".

    Design: Difficulty/non_linear_state_machine/race_general_recall_cycle_reaches_black_flag_then_ocs
    """
    world = _pending_race_world(THREE_ENTRANTS)
    race_id, events = _recall_cycle_to_black_flag(api, world)

    race = read_race(race_id)
    assert race["start_status"] == "STARTED"
    assert race["general_recall_count"] == 2, "the cumulative count survives both restarts"
    assert race["black_flag_active"] is True
    for event in events:
        assert event["recall_type"] == "GENERAL"
        assert event["entry_id"] is None
        assert event["resulting_start_status"] == "GENERAL_RECALLED"
        assert event["black_flag_applied"] is False, (
            "each general recall records the flag state as it stood at signal time"
        )
        assert event["recorded_by_member_id"] == world["ids"]["pro"]


def test_individual_recall_under_the_black_flag_mints_a_non_discardable_ocs(api):
    """PRD 3.7: "While `black_flag_active` is true, the same signal mints a result
    for the named entry with `finish_status` `OCS`, and that result is marked
    non-discardable — its `discardable` flag is false — which moves the race's
    `scoring_status` `NOT_SCORED → PROVISIONAL` and stamps `results_closed_utc`
    from the logical clock, opening the protest window as a side effect of a
    recall."

    Design: Difficulty/non_linear_state_machine/race_general_recall_cycle_reaches_black_flag_then_ocs
    """
    world = _pending_race_world(THREE_ENTRANTS)
    race_id, _ = _recall_cycle_to_black_flag(api, world, start_race=False)
    set_clock("2026-08-05T13:59:00Z")

    event = validate_success(
        api.recall_race(
            race_id,
            recall_payload(
                "INDIVIDUAL", "2026-08-05T13:59:00Z",
                entry_id=world["entries"]["A"]["id"],
            ),
            world["h"]["pro"],
        ),
        expected_status=201,
    )

    assert event["resulting_start_status"] == "SEQUENCE_STARTED", (
        "an individual recall leaves the start standing"
    )
    assert event["black_flag_applied"] is True
    race = read_race(race_id)
    assert race["scoring_status"] == "PROVISIONAL"
    assert race["results_closed_utc"] is not None, (
        "the minted OCS opens the protest window"
    )

    ocs_rows, _ = validate_paginated(
        api.list_race_results(world["h"]["pro"], {"race_id": race_id})
    )
    ocs = [row for row in ocs_rows if row["entry_id"] == world["entries"]["A"]["id"]][0]
    assert ocs["finish_status"] == "OCS"
    assert ocs["discardable"] is False
    assert ocs["corrected_seconds"] is None

    validate_success(
        api.start_race(race_id, start_race_payload(RACE_START), world["h"]["pro"])
    )
    set_clock("2026-08-05T15:00:00Z")
    record_result(race_id, world["entries"]["B"]["id"], world["ids"]["pro"], elapsed_seconds=5312.8)
    record_result(race_id, world["entries"]["D"]["id"], world["ids"]["pro"], elapsed_seconds=5105.4)
    scored = score_race(race_id, world["ids"]["pro"])
    assert scored["scoring_status"] == "FINAL"
    assert read_result(ocs["id"])["points"] == 4.0, (
        "an OCS scores the fleet size of three plus one"
    )
    assert scored["points_pool_total"] == 7.0, "1.0 plus 2.0 plus the 4.0 of the OCS"


TIED_PAIR = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_A},
)


def _decided_protest_world(api):
    """A two-boat race in which both boats correct to the same second, scored to
    FINAL, then protested and carried through a hearing so a decision may run.
    """
    world = build_accepted_fleet_world(
        entrants=TIED_PAIR,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": RACE_START},),
    )
    sail_and_score_race(world, 1, {"A": 4800.0, "B": 4800.0})

    protest = validate_success(
        api.create_protest(
            create_protest_payload(
                world["races"][1]["id"],
                world["entries"]["A"]["id"],
                world["entries"]["B"]["id"],
                "2026-08-05T14:15:00Z",
            ),
            world["h"]["helm_1"],
        ),
        expected_status=201,
    )
    validate_success(
        api.file_evidence(
            protest["id"],
            evidence_payload(world["entries"]["A"]["id"]),
            world["h"]["helm_1"],
        )
    )
    validate_success(
        api.schedule_hearing(
            protest["id"],
            schedule_hearing_payload(world["panel"]["id"], "2026-08-05T15:00:00Z"),
            world["h"]["jury"],
        )
    )
    set_clock("2026-08-05T15:00:00Z")
    validate_success(api.hear_protest(protest["id"], world["h"]["jury"]))
    world["protest"] = protest
    return world


def test_reopening_a_decision_walks_the_scoring_chain_back_to_its_pre_decision_state(api):
    """PRD 3.10: "Performed by the chair of the bound panel from `DECIDED`, hop
    one moves the status to `REOPENED`, sets `reopen_count` to 1, returns
    `decision` to `NONE` and clears `hearing_utc` to null. Hop two restores the
    result the reversed decision had rewritten to the `finish_status` it carried
    before that decision, with `discardable` true and `penalty_percent` 0. Hop
    three re-runs the race points and places and then the series standing,
    restoring every entry's `series_points_gross` to its pre-decision value with
    no drift."

    A two-boat tie group scores 1.5 apiece. A twenty-percent penalty adds the
    fleet size of two times 0.20 to the penalised boat, taking it to 1.9 and the
    pool to 3.4; reopening must put both boats back on 1.5 and the pool back on
    3.0.

    Design: Difficulty/non_linear_state_machine/protest_reopen_cycle_then_second_reopen_rejected
    """
    world = _decided_protest_world(api)
    penalised_id = world["results"][1]["B"]["id"]

    decided = validate_success(
        api.decide_protest(
            world["protest"]["id"],
            decide_payload(
                "PENALTY_SCORING_20",
                penalty_target_entry_id=world["entries"]["B"]["id"],
            ),
            world["h"]["jury"],
        )
    )
    assert decided["status"] == "DECIDED" and decided["decision"] == "PENALTY_SCORING_20"
    penalised = read_result(penalised_id)
    assert penalised["finish_status"] == "FINISHED", (
        "a scoring penalty keeps the finish it earned"
    )
    assert penalised["penalty_percent"] == 20
    assert penalised["points"] == 1.9, "1.5 plus two boats times twenty percent"
    scored = read_race(world["races"][1]["id"])
    assert scored["scoring_status"] == "FINAL" and scored["rescore_count"] == 1
    assert scored["points_pool_total"] == 3.4
    assert read_standing(world["entries"]["B"]["id"])["gross_points"] == 1.9

    reopened = validate_success(api.reopen_protest(world["protest"]["id"], world["h"]["jury"]))

    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["decision"] == "NONE"
    assert reopened["hearing_utc"] is None
    restored = read_result(penalised_id)
    assert restored["finish_status"] == "FINISHED"
    assert restored["penalty_percent"] == 0
    assert restored["discardable"] is True
    assert restored["points"] == 1.5, "the group score returns undrifted"
    assert restored["place"] == 1
    assert read_result(world["results"][1]["A"]["id"])["points"] == 1.5
    assert read_race(world["races"][1]["id"])["points_pool_total"] == 3.0
    for key in ("A", "B"):
        assert read_standing(world["entries"][key]["id"])["gross_points"] == 1.5


def test_the_rehearing_is_the_only_way_out_and_a_second_reopen_is_refused(api):
    """PRD 3.10: "Reopening is the compensating action for a decision, and it is
    available once and only once per protest: a protest whose `reopen_count` is
    already 1 is refused with `ERR_REOPEN_LIMIT_REACHED`."

    PRD 3.10 also names the re-entry edge that gets the cycle back to a decision:
    "The same operation is also the re-entry edge after a reopening, moving
    `REOPENED → HEARING_SCHEDULED` under a seated panel and a future hearing
    time."

    Design: Difficulty/non_linear_state_machine/protest_reopen_cycle_then_second_reopen_rejected
    """
    world = _decided_protest_world(api)
    protest_id = world["protest"]["id"]
    jury = world["h"]["jury"]
    validate_success(
        api.decide_protest(
            protest_id,
            decide_payload(
                "PENALTY_SCORING_20",
                penalty_target_entry_id=world["entries"]["B"]["id"],
            ),
            jury,
        )
    )
    validate_success(api.reopen_protest(protest_id, jury))

    rescheduled = validate_success(
        api.schedule_hearing(
            protest_id,
            schedule_hearing_payload(world["panel"]["id"], "2026-08-05T18:00:00Z"),
            jury,
        )
    )
    assert rescheduled["status"] == "HEARING_SCHEDULED"
    assert rescheduled["hearing_utc"] == "2026-08-05T18:00:00Z"
    assert rescheduled["reopen_count"] == 1, "the reopen counter is not cleared"

    set_clock("2026-08-05T18:00:00Z")
    assert validate_success(api.hear_protest(protest_id, jury))["status"] == "HEARD"
    dismissed = validate_success(
        api.decide_protest(protest_id, decide_payload("DISMISSED"), jury)
    )
    assert dismissed["status"] == "DECIDED" and dismissed["decision"] == "DISMISSED"
    assert dismissed["penalty_target_entry_id"] is None
    assert read_result(world["results"][1]["B"]["id"])["points"] == 1.5, (
        "a dismissal rewrites no result"
    )

    validate_error(
        api.reopen_protest(protest_id, jury),
        ApiErrorId.ERR_REOPEN_LIMIT_REACHED,
        expected_status=409,
    )
    assert read_protest(protest_id)["status"] == "DECIDED"
    assert read_protest(protest_id)["reopen_count"] == 1


def _two_dimension_world():
    """One accepted entry that has passed inspection and one submitted entry that
    has failed it, both assigned to the same confirmed division."""
    return build_accepted_fleet_world(
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
            {
                "key": "B",
                "helm": "helm_2",
                "measurement": MEASUREMENT_B,
                "inspect": "FAIL",
                "inspect_payload": {"equipment_deficiency_code": "LIFERAFT_OVERDUE"},
                "accept": False,
            },
        ),
    )


def test_the_inspection_dimension_cycles_without_rewriting_the_registration_dimension(api):
    """PRD 3.5: "The two dimensions of an entry advance without gating each other:
    an entry that is already `ACCEPTED` and then fails inspection **keeps**
    `registration_status` `ACCEPTED` and stays in its division's counts, because a
    later inspection failure never rewrites the paperwork dimension."

    PRD 3.5 also fixes the deficiency code on each hop of the cycle: "A boat that
    fixes its deficiency is re-inspected: from `FAILED → PASSED`, which again
    clears `equipment_deficiency_code` to null. A boat that breaks something after
    passing goes `PASSED → FAILED`, again requiring an `equipment_deficiency_code`,
    which is stored."

    Design: Difficulty/non_linear_state_machine/entry_inspection_dimension_cycles_without_touching_registration
    """
    world = _two_dimension_world()
    accepted = world["entries"]["A"]
    division_id = world["divisions"]["A"]["id"]
    assert accepted["registration_status"] == "ACCEPTED"
    assert accepted["inspection_status"] == "PASSED"
    assert accepted["equipment_deficiency_code"] is None

    broke = inspect_entry(
        accepted["id"], world["ids"]["pro"], outcome="FAIL",
        equipment_deficiency_code="LIFELINE_TENSION",
    )
    assert broke["inspection_status"] == "FAILED"
    assert broke["equipment_deficiency_code"] == "LIFELINE_TENSION"
    assert broke["registration_status"] == "ACCEPTED", (
        "a later inspection failure never rewrites the paperwork dimension"
    )
    assert broke["division_id"] == division_id

    fixed = inspect_entry(accepted["id"], world["ids"]["pro"], outcome="PASS")
    assert fixed["inspection_status"] == "PASSED"
    assert fixed["equipment_deficiency_code"] is None, "a re-inspection clears the code"
    assert fixed["registration_status"] == "ACCEPTED"

    broke_again = inspect_entry(
        accepted["id"], world["ids"]["pro"], outcome="FAIL",
        equipment_deficiency_code="FLARES_EXPIRED",
    )
    assert broke_again["inspection_status"] == "FAILED"
    assert broke_again["equipment_deficiency_code"] == "FLARES_EXPIRED"
    assert broke_again["registration_status"] == "ACCEPTED"
    assert broke_again["division_id"] == division_id

    division = read_division(division_id)
    assert division["assigned_entry_count"] == 2
    assert division["accepted_entry_count"] == 1, (
        "the inspection cycle moved neither count"
    )
    assert division["status"] == "CONFIRMED"


def test_acceptance_is_the_one_edge_that_reads_across_the_two_dimensions(api):
    """PRD 3.5: "The `inspection_status` must be `PASSED`, otherwise
    `ERR_EQUIPMENT_INSPECTION_NOT_PASSED`."

    PRD 3.5 states the asymmetry that makes this the only cross-dimension edge:
    "Only one edge in the whole entry lifecycle reads across the two dimensions,
    and that is acceptance."

    Design: Difficulty/non_linear_state_machine/entry_inspection_dimension_cycles_without_touching_registration
    """
    world = _two_dimension_world()
    failed = world["entries"]["B"]
    assert failed["registration_status"] == "SUBMITTED"
    assert failed["inspection_status"] == "FAILED"
    assert failed["division_id"] == world["divisions"]["A"]["id"]

    validate_error(
        api.accept_entry(failed["id"], world["h"]["chair"]),
        ApiErrorId.ERR_EQUIPMENT_INSPECTION_NOT_PASSED,
        expected_status=422,
    )

    unchanged = read_entry(failed["id"])
    assert unchanged["registration_status"] == "SUBMITTED"
    assert unchanged["inspection_status"] == "FAILED"
    assert unchanged["equipment_deficiency_code"] == "LIFERAFT_OVERDUE"

    repaired = inspect_entry(failed["id"], world["ids"]["pro"], outcome="PASS")
    assert repaired["inspection_status"] == "PASSED"
    admitted = validate_success(api.accept_entry(failed["id"], world["h"]["chair"]))
    assert admitted["registration_status"] == "ACCEPTED"
    assert read_division(world["divisions"]["A"]["id"])["accepted_entry_count"] == 2
