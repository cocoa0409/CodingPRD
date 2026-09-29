"""Endpoints exercised as complete round trips: a crew manifest built up and taken
apart again, a duty released straight out of PROPOSED, a seat that must name a real
member, a computed standing read before any race has been scored, and the one
protest transition from which nothing leads back.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    TWO_BOAT_DIVISION,
    UNKNOWN_UUID,
    ApiErrorId,
    add_crew,
    add_crew_payload,
    build_racing_world,
    build_started_race_world,
    charter_mark_boat,
    create_jury_panel_payload,
    create_protest_payload,
    file_and_issue_certificate,
    invalidate_payload,
    make_competitor_headers,
    make_regatta_chair_headers,
    open_regatta,
    propose_duty,
    publish_nor,
    read_division,
    read_duty,
    read_entry,
    read_mark_boat,
    read_member,
    read_panel,
    read_protest,
    read_regatta,
    record_result,
    register_boat,
    release_duty_payload,
    schedule_hearing_payload,
    seat_judge_payload,
    set_clock,
    submit_entry,
)

HELM_WEIGHT_KG = 84.5
TRIM_WEIGHT_KG = 79.25


def test_the_manifest_subtracts_the_element_it_removes_and_nothing_else(api, roster):
    """PRD 3.5: "Each addition appends an element to `crew_manifest`, increments
    `registered_crew_count` by one, adds the declared `weight_kg` into `crew_weight_kg`
    — which is maintained rounded half-up to one decimal place — and advances the
    entry's `version`. A manifest holds at most one element with `position` `HELM`, and
    a given member appears at most once on a given entry; a repeat naming of the same
    member is refused with `ERR_DUPLICATE_RECORD`."

    PRD 3.5 fixes the removal leg as a subtraction rather than a recount: "A crew
    member may be taken off again, but only by the `Competitor` who helms the entry:
    removal names the member in the path, drops that manifest element, decrements
    `registered_crew_count` by one, subtracts that element's `weight_kg` from
    `crew_weight_kg`, and advances the entry's `version`."

    Design: Corner/endpoints/crew_manifest_add_and_delete_round_trip_adjusts_count_and_weight
    """
    chair_id = roster["chair"]["id"]
    regatta = open_regatta(chair_id)
    publish_nor(regatta["id"], chair_id)
    helm_id = roster["helm_1"]["id"]
    trimmer_id = roster["helm_2"]["id"]
    stranger_id = roster["helm_3"]["id"]
    boat = register_boat(helm_id)
    certificate = file_and_issue_certificate(boat["id"], roster["measurer"]["id"])
    entry = submit_entry(
        regatta["id"], boat["id"], certificate["id"], helm_id, declared_crew_count=3
    )
    helm = make_competitor_headers(helm_id)
    add_crew(entry["id"], helm_id, helm_id, position="HELM", weight_kg=HELM_WEIGHT_KG)
    crewed = add_crew(
        entry["id"], helm_id, trimmer_id, position="TRIM", weight_kg=TRIM_WEIGHT_KG
    )

    assert crewed["registered_crew_count"] == 2
    assert crewed["crew_weight_kg"] == 163.8, "84.5 plus 79.25 rounds half-up to 163.8"
    assert crewed["version"] == 3, "one increment per addition on top of the submission"

    validate_error(
        api.add_crew(
            entry["id"],
            add_crew_payload(trimmer_id, position="BOW", weight_kg=70.0),
            helm,
        ),
        ApiErrorId.ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    validate_error(
        api.remove_crew(entry["id"], stranger_id, helm),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        expected_status=404,
    )
    assert read_entry(entry["id"])["registered_crew_count"] == 2, "neither refusal landed"

    stripped = validate_success(api.remove_crew(entry["id"], trimmer_id, helm))

    assert stripped["registered_crew_count"] == 1
    assert stripped["crew_weight_kg"] == HELM_WEIGHT_KG, (
        "the removed element's own 79.25 kg came off, not a recount from the declaration"
    )
    assert stripped["version"] == 4
    assert [element["member_id"] for element in stripped["crew_manifest"]] == [helm_id]
    assert stripped["crew_manifest"][0]["position"] == "HELM"
    assert stripped["declared_crew_count"] == 3, (
        "the manifest is never reconciled against the declaration until acceptance"
    )
    assert stripped["registration_status"] == "SUBMITTED"


EIGHT_HOURS = 480
RELEASE_REASON = "CREW_ILLNESS"


def test_a_proposed_duty_releases_straight_to_terminal_and_settles_both_ledgers_once(api, roster):
    """PRD 3.6: "Release is the compensating action and the terminal state. A duty may
    be released from `PROPOSED` or from `CONFIRMED`, carrying a `release_reason_code`
    that is stored on the row."

    PRD 3.6 fixes the arithmetic of the single settlement: "Release subtracts
    `duty_minutes` from the volunteer's `assigned_duty_minutes` and, where a mark boat
    was named, the same figure from that boat's `committed_minutes`, leaving both ledgers
    exactly at their pre-creation values with no residue."

    PRD 2.7 item 11 fixes what the repeat answers: "The target row is in a state from
    which the requested transition exists, on the dimension that endpoint advances, else
    `ERR_INVALID_STATE`. This check applies to every action endpoint — that is, every
    operation that names a verb on a single resource."

    Design: Corner/endpoints/duty_release_from_proposed_zeroes_both_ledgers_then_second_release_rejected
    """
    chair_id = roster["chair"]["id"]
    driver_id = roster["helm_1"]["id"]
    regatta = open_regatta(chair_id)
    mark_boat = charter_mark_boat(regatta["id"], chair_id)
    duty = propose_duty(
        regatta["id"], chair_id, driver_id, "MARK_BOAT_DRIVER",
        mark_boat_id=mark_boat["id"],
    )
    assert duty["status"] == "PROPOSED"
    assert duty["duty_minutes"] == EIGHT_HOURS
    assert read_member(driver_id)["assigned_duty_minutes"] == EIGHT_HOURS
    assert read_mark_boat(mark_boat["id"])["committed_minutes"] == EIGHT_HOURS
    chair = make_regatta_chair_headers(chair_id)

    released = validate_success(
        api.release_duty_assignment(
            duty["id"], release_duty_payload(release_reason_code=RELEASE_REASON), chair
        )
    )

    assert released["status"] == "RELEASED", "reached without ever passing through CONFIRMED"
    assert released["release_reason_code"] == RELEASE_REASON
    assert released["duty_minutes"] == EIGHT_HOURS, "the row keeps its magnitude"
    assert read_member(driver_id)["assigned_duty_minutes"] == 0
    assert read_mark_boat(mark_boat["id"])["committed_minutes"] == 0

    validate_error(
        api.release_duty_assignment(
            duty["id"], release_duty_payload(release_reason_code=RELEASE_REASON), chair
        ),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    assert read_member(driver_id)["assigned_duty_minutes"] == 0, (
        "the refused repeat did not subtract 480 a second time"
    )
    assert read_mark_boat(mark_boat["id"])["committed_minutes"] == 0
    assert read_duty(duty["id"])["status"] == "RELEASED"


DEFAULT_QUORUM = 3


def test_a_seat_must_name_a_real_unseated_member_and_two_of_three_is_still_forming(api, roster):
    """PRD 3.10: "Quorum is reached by seating additional judges, one `member_id` at a
    time. Each seating appends a `seats` element with `seat_role` `MEMBER`, `recused`
    false and its own `seated_utc`, increments `seated_member_count`, and advances the
    panel's `version`; a member already holding a seat on that panel is refused with
    `ERR_DUPLICATE_RECORD`. Once `seated_member_count` reaches the regatta's
    `jury_quorum_required`, the panel bubbles up `FORMING → SEATED`."

    PRD 3.10 fixes the panel the seats are added to: "A panel is created with the chair
    alone: its `seats` array holds one element whose `member_id` is the chair, whose
    `seat_role` is `CHAIR`, whose `recused` flag is false and whose `seated_utc` records
    when the seat was taken, giving `seated_member_count` of 1 and status `FORMING`."

    PRD 2.7 item 8: "Every `id` in the path resolves, checked left to right, and then
    every foreign key in the body resolves, checked in the order the endpoint declares
    its inputs, else `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/endpoints/jury_seat_requires_existing_member_and_stays_forming_under_quorum
    """
    chair_id = roster["chair"]["id"]
    judge_chair_id = roster["judge_chair"]["id"]
    second_judge_id = roster["judge_member"]["id"]
    regatta = open_regatta(chair_id)
    assert regatta["jury_quorum_required"] == DEFAULT_QUORUM
    chair = make_regatta_chair_headers(chair_id)
    panel = validate_success(
        api.create_jury_panel(create_jury_panel_payload(regatta["id"], judge_chair_id), chair),
        expected_status=201,
    )

    assert panel["status"] == "FORMING"
    assert panel["seated_member_count"] == 1
    assert len(panel["seats"]) == 1
    assert panel["seats"][0]["member_id"] == judge_chair_id
    assert panel["seats"][0]["seat_role"] == "CHAIR"
    assert panel["seats"][0]["recused"] is False
    assert is_iso8601_timestamp(panel["seats"][0]["seated_utc"])

    validate_error(
        api.seat_judge(panel["id"], seat_judge_payload(UNKNOWN_UUID), chair),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.seat_judge(panel["id"], seat_judge_payload(judge_chair_id), chair),
        ApiErrorId.ERR_DUPLICATE_RECORD,
        expected_status=409,
    )
    assert read_panel(panel["id"])["seated_member_count"] == 1, "neither refusal seated anyone"

    seated = validate_success(
        api.seat_judge(panel["id"], seat_judge_payload(second_judge_id), chair)
    )

    assert seated["seated_member_count"] == 2
    added = [row for row in seated["seats"] if row["member_id"] == second_judge_id]
    assert len(added) == 1
    assert added[0]["seat_role"] == "MEMBER"
    assert added[0]["recused"] is False
    assert seated["status"] == "FORMING", "two seats are under a quorum of three"
    assert seated["version"] == 2, "only the successful seat bumped the panel"


def test_the_standing_read_of_an_accepted_entry_before_any_race_is_defined_and_zeroed(api):
    """PRD 3.9: "The same computation is available as a read for a single entry, and it
    answers with the `entry_id`, the `division_id`, the `gross_points` and `net_points`,
    the `discarded_race_numbers`, the number of counted races as `races_counted`, the
    division `rank`, and a `tie_break_trace` explaining which tie-break decided the
    rank."

    PRD 3.9 fixes that an empty counted set is still a defined answer: "The counted
    races are the races of the entry's regatta whose `scoring_status` is `FINAL` and
    whose `start_status` is not `ABANDONED`, taken in ascending `race_number` order;
    races in `PROVISIONAL` or `NOT_SCORED` contribute nothing, and a voided result is
    skipped even inside a counted race."

    PRD 3.9 fixes the null rank and the idle discard policy: "The result is written to
    `series_rank` as a 1-based rank, and `series_rank` is null for every entry of a
    division while that division's regatta has no counted races at all." and "Under
    `ONE_PER_FIVE` one result is discarded once at least 5 races have been counted, and
    never more than one."

    Design: Corner/endpoints/series_standing_of_accepted_entry_with_no_final_race_reads_zeroed
    """
    world = build_racing_world(
        regatta_overrides={"fleet_minimum": 2, "discard_policy": "ONE_PER_FIVE"},
        publish="nor",
        divisions=TWO_BOAT_DIVISION,
        entrants=({"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},),
        confirm_division_codes=(),
    )
    entry_id = world["entries"]["A"]["id"]
    division_id = world["divisions"]["A"]["id"]

    standing = validate_success(api.get_series_standing(entry_id, world["h"]["helm_1"]))

    assert standing["entry_id"] == entry_id
    assert standing["division_id"] == division_id, "the read still carries the division"
    assert standing["gross_points"] == 0
    assert standing["net_points"] == 0
    assert standing["races_counted"] == 0
    assert standing["discarded_race_numbers"] == [], (
        "ONE_PER_FIVE discards nothing at nought counted races"
    )
    assert standing["rank"] is None, (
        "a null rank is what separates nothing scored yet from ranked last"
    )

    accepted = read_entry(entry_id)
    assert accepted["registration_status"] == "ACCEPTED"
    assert accepted["series_points_gross"] == 0
    assert accepted["series_points_net"] == 0
    assert accepted["series_rank"] is None
    assert read_division(division_id)["accepted_entry_count"] == 1


RESULTS_CLOCK = "2026-08-05T15:00:00Z"
INCIDENT_UTC = "2026-08-05T14:30:00Z"
HEARING_UTC = "2026-08-05T18:00:00Z"
PROTEST_FLEET = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
)


def test_ruling_a_protest_invalid_is_terminal_and_no_later_verb_reaches_it(api):
    """PRD 3.10: "Invalidation is the terminal procedural exit. From `FILED` or from
    `REOPENED`, the jury chair rules the protest `INVALID`, supplying a `reason_code`
    that is stored as `invalid_reason_code`. Nothing in the scoring chain is touched,
    the protest's `version` advances, and because the protest is no longer open the
    regatta may bubble up `RACING → SCORED`."

    PRD 2.7 item 6: "The body parses, every required input field of the endpoint is
    present and non-null, no unknown field is present, every enum-valued field carries a
    declared member, and every numeric field satisfies its declared range, else
    `ERR_INVALID_REQUEST`."

    PRD 3.10 fixes what the read must still show: "A new protest opens in status
    `FILED` with an empty `evidence_log`, `evidence_count` 0, `reopen_count` 0,
    `decision` `NONE`, and `jury_panel_id`, `hearing_utc`, `penalty_target_entry_id`,
    `redress_race_number` and `invalid_reason_code` all null."

    Design: Corner/endpoints/protest_invalidate_is_terminal_and_rejects_every_later_action
    """
    world = build_started_race_world(entrants=PROTEST_FLEET)
    race_id = world["races"][1]["id"]
    set_clock(RESULTS_CLOCK)
    record_result(race_id, world["entries"]["A"]["id"], world["ids"]["pro"])
    filed = validate_success(
        api.create_protest(
            create_protest_payload(
                race_id, world["entries"]["A"]["id"], world["entries"]["B"]["id"],
                INCIDENT_UTC,
            ),
            world["h"]["helm_1"],
        ),
        expected_status=201,
    )
    assert filed["status"] == "FILED"
    jury = world["h"]["jury"]

    validate_error(
        api.invalidate_protest(filed["id"], {}, jury),
        ApiErrorId.ERR_INVALID_REQUEST,
        expected_status=400,
    )
    assert read_protest(filed["id"])["status"] == "FILED", "reason_code is required"

    invalid = validate_success(
        api.invalidate_protest(filed["id"], invalidate_payload(reason_code="OUT_OF_TIME"), jury)
    )

    assert invalid["status"] == "INVALID"
    assert invalid["invalid_reason_code"] == "OUT_OF_TIME"

    validate_error(
        api.invalidate_protest(
            filed["id"], invalidate_payload(reason_code="NO_VALID_HAIL"), jury
        ),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.schedule_hearing(
            filed["id"], schedule_hearing_payload(world["panel"]["id"], HEARING_UTC), jury
        ),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.reopen_protest(filed["id"], jury),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    settled = validate_success(api.get_protest(filed["id"], jury))

    assert settled["status"] == "INVALID", "no transition leaves INVALID"
    assert settled["invalid_reason_code"] == "OUT_OF_TIME", "not overwritten by the repeat"
    assert settled["decision"] == "NONE"
    assert settled["jury_panel_id"] is None, "the refused hearing bound no panel"
    assert settled["hearing_utc"] is None
    assert settled["reopen_count"] == 0
    assert settled["evidence_count"] == 0
    assert settled["evidence_log"] == []

    regatta = read_regatta(world["regatta_id"])
    assert regatta["status"] == "RACING", (
        "closing the last open protest bubbles nothing while final_race_count is 0"
    )
    assert regatta["final_race_count"] == 0
    assert regatta["planned_race_count"] == 6
