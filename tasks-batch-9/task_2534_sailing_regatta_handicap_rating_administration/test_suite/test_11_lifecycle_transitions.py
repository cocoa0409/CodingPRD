"""Declared transitions exercised one at a time: opening states, valid hops and
their cascades, invalid hops, terminal lockdowns, non-idempotent verbs, bubble-ups
and the lossy edge of a cycle.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    DEFAULT_FLEET_MINIMUM,
    MEASUREMENT_A,
    MEASUREMENT_B,
    ApiErrorId,
    build_accepted_fleet_world,
    create_jury_panel_payload,
    create_race_document_payload,
    create_regatta_payload,
    current_regatta_version,
    file_and_issue_certificate,
    file_certificate,
    issue_certificate,
    make_measurer_headers,
    make_regatta_chair_headers,
    open_regatta,
    publish_nor,
    publish_si,
    read_boat,
    read_certificate,
    read_division,
    read_document,
    read_entry,
    read_panel,
    read_regatta,
    record_result,
    register_boat,
    seat_judge_payload,
    set_clock,
    submit_entry,
    suspend_certificate_payload,
    withdraw_entry,
)


def test_issuing_a_second_certificate_supersedes_the_first_in_the_same_request(api, roster):
    """PRD 3.2: "That first hop causes a second: if the same boat already held an
    `ISSUED` certificate, that older row moves `ISSUED → SUPERSEDED` and the newly
    issued row records the older row's identifier in its own
    `supersedes_certificate_id`. `SUPERSEDED` is terminal — a certificate never
    returns from it."

    Design: Corner/state_machines/certificate_issue_supersedes_prior_issued_certificate_of_same_boat
    """
    measurer_id = roster["measurer"]["id"]
    boat = register_boat(roster["helm_1"]["id"])
    old = file_and_issue_certificate(boat["id"], measurer_id)
    assert read_boat(boat["id"])["version"] == 3

    new = file_certificate(boat["id"], measurer_id, rule_code="TOT_ORC")
    issued = issue_certificate(new["id"], measurer_id)

    assert issued["status"] == "ISSUED"
    assert issued["supersedes_certificate_id"] == old["id"]
    assert issued["rule_code"] == "TOT_ORC"
    assert issued["rating_value"] == 0.8582
    assert issued["band_key_spm"] == 171.3, "the projection puts both rules on one scale"

    superseded = read_certificate(old["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["supersedes_certificate_id"] is None
    assert read_boat(boat["id"])["version"] == 5, (
        "two creates and two issues on top of the registration"
    )

    rows, pagination = validate_paginated(
        api.list_certificates(
            make_measurer_headers(measurer_id),
            {"boat_id": boat["id"], "status": "ISSUED"},
        )
    )
    assert pagination["total_count"] == 1
    assert rows[0]["id"] == new["id"]


def test_a_new_regatta_opens_in_draft_with_every_derived_counter_at_zero(api, roster):
    """PRD 3.3: "On creation, `nor_revision`, `si_revision`,
    `confirmed_division_count` and `final_race_count` are all 0 and `version` is 1."

    PRD 3.3 also fixes the five optional policy fields the request omitted:
    "`discard_policy`, one of `NONE`, `ONE_PER_FIVE` or `ONE_PER_FOUR`, defaulting to
    `NONE`; `handicap_basis`, either `PER_CERTIFICATE` or `UNIFIED_TOD`, defaulting
    to `PER_CERTIFICATE`, which selects the corrected-time variant for every result
    of the event".

    Design: Corner/state_machines/regatta_initial_state_is_draft_with_zero_derived_counters
    """
    created = validate_success(
        api.create_regatta(
            create_regatta_payload(
                name="Autumn Handicap Series", host_club_name="Harbor Yacht Club",
            ),
            make_regatta_chair_headers(roster["chair"]["id"]),
        ),
        expected_status=201,
    )

    assert created["status"] == "DRAFT"
    assert created["version"] == 1
    assert created["nor_revision"] == 0
    assert created["si_revision"] == 0
    assert created["confirmed_division_count"] == 0
    assert created["final_race_count"] == 0
    assert created["discard_policy"] == "NONE"
    assert created["handicap_basis"] == "PER_CERTIFICATE"
    assert created["fleet_minimum"] == DEFAULT_FLEET_MINIMUM
    assert created["protest_time_limit_minutes"] == 90
    assert created["jury_quorum_required"] == 3


def test_the_issue_verb_is_not_idempotent(api, roster):
    """PRD 2.7 item 11: "The target row is in a state from which the requested
    transition exists, on the dimension that endpoint advances, else
    `ERR_INVALID_STATE`. This check applies to every action endpoint — that is, every
    operation that names a verb on a single resource."

    Design: Corner/state_machines/certificate_second_issue_returns_409_invalid_state
    """
    measurer_id = roster["measurer"]["id"]
    boat = register_boat(roster["helm_1"]["id"])
    certificate = file_and_issue_certificate(boat["id"], measurer_id)
    assert read_boat(boat["id"])["version"] == 3

    validate_error(
        api.issue_certificate(certificate["id"], make_measurer_headers(measurer_id)),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    unchanged = read_certificate(certificate["id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["version"] == 2, "the filing and the one accepted issue"
    assert unchanged["supersedes_certificate_id"] is None
    assert read_boat(boat["id"])["version"] == 3, (
        "a rejected certificate action leaves no version bump behind"
    )


def test_a_withdrawn_entry_admits_neither_acceptance_nor_a_second_withdrawal(api, roster, headers):
    """PRD 3.5: "Withdrawal is available to the chair and to the helming
    `Competitor`, and it is terminal: `registration_status` becomes `WITHDRAWN` from
    either `SUBMITTED` or `ACCEPTED`."

    The state check outranks every precondition the accept endpoint carries of its
    own, so the answer is `ERR_INVALID_STATE` rather than the missing-division or
    inspection complaint the row would also earn.

    Design: Corner/state_machines/withdrawn_entry_cannot_be_accepted_or_withdrawn_again
    """
    regatta = open_regatta(roster["chair"]["id"])
    publish_nor(regatta["id"], roster["chair"]["id"])
    boat = register_boat(roster["helm_1"]["id"])
    certificate = file_certificate(boat["id"], roster["measurer"]["id"])
    entry = submit_entry(
        regatta["id"], boat["id"], certificate["id"], roster["helm_1"]["id"]
    )
    withdrawn = withdraw_entry(entry["id"], roster["helm_1"]["id"])
    assert withdrawn["registration_status"] == "WITHDRAWN"

    validate_error(
        api.accept_entry(entry["id"], headers["chair"]),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.withdraw_entry(entry["id"], headers["chair"]),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    final = read_entry(entry["id"])
    assert final["registration_status"] == "WITHDRAWN"
    assert final["version"] == 2, "submission and the one accepted withdrawal"
    assert final["division_id"] is None, (
        "withdrawal kept the assignment field exactly as it stood"
    )


def test_the_confirm_floor_is_the_greater_of_the_two_declared_minima(api, roster, headers):
    """PRD 3.4: "It is permitted only from `PROVISIONAL`, only while the regatta is
    in `NOR_PUBLISHED` or `SI_PUBLISHED`, and only when the division's
    `assigned_entry_count` has reached the greater of its own `min_entries` and the
    regatta's `fleet_minimum`; a division short of that floor is refused with
    `ERR_FLEET_MINIMUM_NOT_MET`."

    Design: Corner/state_machines/division_confirm_under_effective_floor_returns_fleet_minimum_not_met
    """
    world = build_accepted_fleet_world(
        regatta_overrides={"fleet_minimum": 2},
        divisions=(
            {"code": "A", "boat_type_filter": "MONOHULL",
             "rating_band_low": 150.0, "rating_band_high": 230.0, "min_entries": 3},
        ),
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A,
             "inspect": None, "accept": False},
        ),
        confirm_division_codes=(),
    )
    division_id = world["divisions"]["A"]["id"]
    assert read_division(division_id)["assigned_entry_count"] == 1

    validate_error(
        api.confirm_division(division_id, headers["chair"]),
        ApiErrorId.ERR_FLEET_MINIMUM_NOT_MET,
        expected_status=409,
    )

    unchanged = read_division(division_id)
    assert unchanged["status"] == "PROVISIONAL"
    assert unchanged["assigned_entry_count"] == 1
    assert unchanged["min_entries"] == 3, (
        "the division's own floor of three outranks the regatta's two"
    )
    regatta = read_regatta(world["regatta_id"])
    assert regatta["confirmed_division_count"] == 0
    assert regatta["fleet_minimum"] == 2


def test_opening_racing_is_defined_only_out_of_the_si_published_phase(api, roster, headers):
    """PRD 3.3: "Once the sailing instructions are out, the chair opens racing,
    which moves the regatta `SI_PUBLISHED → RACING`."

    PRD 2.7 item 11 puts the state check ahead of that transition's own aggregate
    preconditions: "The target row is in a state from which the requested transition
    exists, on the dimension that endpoint advances, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/open_racing_from_draft_returns_409_invalid_state
    """
    regatta = open_regatta(roster["chair"]["id"])
    assert regatta["status"] == "DRAFT"

    validate_error(
        api.open_racing(regatta["id"], headers["chair"]),
        ApiErrorId.ERR_INVALID_STATE,
        expected_status=409,
    )

    unchanged = read_regatta(regatta["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == 1, "the refusal wrote nothing"
    assert unchanged["si_revision"] == 0
    assert unchanged["confirmed_division_count"] == 0


def test_an_si_amendment_supersedes_its_target_and_raises_only_the_si_revision(api, roster, headers):
    """PRD 3.3: "When the amendment lands, the amended row moves `PUBLISHED →
    SUPERSEDED`, the new row takes the amended row's revision plus one, and the
    regatta's `nor_revision` or `si_revision` is set to the new revision."

    PRD 3.3 also fixes that the amendment is a revision rather than a phase move:
    "An amendment published with an `effective_utc` in the future is an entirely
    legitimate act — and it is precisely the situation that stops a start sequence,
    as section 3.7 explains."

    Design: Corner/state_machines/race_document_amendment_supersedes_prior_revision_and_bumps_si_revision
    """
    chair_id = roster["chair"]["id"]
    regatta = open_regatta(chair_id)
    notice = publish_nor(regatta["id"], chair_id)
    instructions = publish_si(regatta["id"], chair_id)
    assert read_regatta(regatta["id"])["version"] == 3

    amendment = validate_success(
        api.create_race_document(
            create_race_document_payload(
                regatta["id"], current_regatta_version(regatta["id"]),
                doc_type="SI",
                body_summary="Sailing instructions amendment 1: start line moved",
                effective_utc="2026-07-20T00:00:00Z",
                amends_document_id=instructions["id"],
            ),
            headers["chair"],
        ),
        expected_status=201,
    )

    assert amendment["revision"] == 2
    assert amendment["status"] == "PUBLISHED"
    assert amendment["amends_document_id"] == instructions["id"]

    amended = read_document(instructions["id"])
    assert amended["status"] == "SUPERSEDED"
    assert amended["revision"] == 1
    assert read_document(notice["id"])["status"] == "PUBLISHED", (
        "the notice-of-race chain is untouched by an amendment to the instructions"
    )

    final = read_regatta(regatta["id"])
    assert final["si_revision"] == 2
    assert final["nor_revision"] == 1
    assert final["status"] == "SI_PUBLISHED", "an amendment is a revision, not a phase"
    assert final["version"] == 4


def test_a_panel_bubbles_up_to_seated_when_the_count_reaches_the_quorum(api, roster, headers):
    """PRD 3.10: "A panel is created with the chair alone: its `seats` array holds
    one element whose `member_id` is the chair, whose `seat_role` is `CHAIR`, whose
    `recused` flag is false and whose `seated_utc` records when the seat was taken,
    giving `seated_member_count` of 1 and status `FORMING`."

    PRD 3.10 then fixes what the second seat does: "Each seating appends a `seats`
    element with `seat_role` `MEMBER`, `recused` false and its own `seated_utc`,
    increments `seated_member_count`, and advances the panel's `version`; a member
    already holding a seat on that panel is refused with `ERR_DUPLICATE_RECORD`.
    Once `seated_member_count` reaches the regatta's `jury_quorum_required`, the
    panel bubbles up `FORMING → SEATED`."

    Design: Corner/state_machines/jury_panel_seats_bubble_up_to_seated_at_quorum
    """
    judge_chair_id = roster["judge_chair"]["id"]
    judge_member_id = roster["judge_member"]["id"]
    regatta = open_regatta(roster["chair"]["id"], jury_quorum_required=2)

    formed = validate_success(
        api.create_jury_panel(
            create_jury_panel_payload(regatta["id"], judge_chair_id), headers["chair"]
        ),
        expected_status=201,
    )

    assert formed["status"] == "FORMING"
    assert formed["seated_member_count"] == 1
    assert formed["chair_member_id"] == judge_chair_id
    assert formed["version"] == 1
    assert [seat["member_id"] for seat in formed["seats"]] == [judge_chair_id]
    assert [seat["seat_role"] for seat in formed["seats"]] == ["CHAIR"]
    assert formed["seats"][0]["recused"] is False
    assert is_iso8601_timestamp(formed["seats"][0]["seated_utc"])

    seated = validate_success(
        api.seat_judge(
            formed["id"], seat_judge_payload(judge_member_id), headers["chair"]
        )
    )

    assert seated["status"] == "SEATED", (
        "the refreshed count reaching the quorum is what moved the status"
    )
    assert seated["seated_member_count"] == 2
    assert seated["chair_member_id"] == judge_chair_id, "the seating did not re-chair it"
    assert seated["version"] == 2
    assert [seat["member_id"] for seat in seated["seats"]] == [
        judge_chair_id, judge_member_id,
    ]
    assert [seat["seat_role"] for seat in seated["seats"]] == ["CHAIR", "MEMBER"]
    assert all(seat["recused"] is False for seat in seated["seats"])
    assert read_panel(formed["id"])["status"] == "SEATED"


ONE_RACE_START = "2026-08-05T14:00:00Z"
RESULTS_CLOCK = "2026-08-05T15:00:00Z"


def _last_planned_race_world():
    """A one-race regatta carried to a started race, with division A confirmed on
    two assigned entries of which only the first was ever accepted."""
    return build_accepted_fleet_world(
        regatta_overrides={"planned_race_count": 1},
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
            {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_A,
             "inspect": None, "accept": False},
        ),
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": ONE_RACE_START},),
        start_races=(1,),
    )


def test_scoring_the_last_planned_race_bubbles_the_regatta_up_to_scored(api):
    """PRD 3.3: "At the end of a successful race scoring, the regatta moves `RACING
    → SCORED` — a terminal state — if and only if two aggregate conditions hold:
    `final_race_count` has, after that scoring run, become equal to
    `planned_race_count`; and no protest of the regatta is still open, meaning none
    is in `FILED`, `HEARING_SCHEDULED`, `HEARD` or `REOPENED`."

    PRD 3.9 fixes the numbers the same request writes: "Places and points are
    computed per division, over the divisions of the race's regatta whose
    `accepted_entry_count` is at least 1. Two things are read from the division: the
    division itself supplies the fleet size used in every non-finisher formula,
    namely its `accepted_entry_count` at scoring time; and the candidate results are
    those results of this race that are not voided and whose entry sits in that
    division."

    Design: Corner/state_machines/regatta_bubbles_up_to_scored_when_last_planned_race_is_final
    """
    world = _last_planned_race_world()
    race_id = world["races"][1]["id"]
    pro = world["h"]["pro"]
    set_clock(RESULTS_CLOCK)
    result = record_result(
        race_id, world["entries"]["A"]["id"], world["ids"]["pro"], elapsed_seconds=4800.0
    )
    assert result["voided"] is False

    scored = validate_success(api.score_race(race_id, pro))

    assert scored["scoring_status"] == "FINAL"
    assert scored["points_pool_total"] == 1.0, (
        "the division carries exactly one accepted entry, so the pool is one place"
    )
    assert scored["rescore_count"] == 0
    final_result = validate_success(api.get_race_result(result["id"], pro))
    assert final_result["corrected_seconds"] == 3772.2, (
        "4800.0 elapsed less 171.3 seconds per mile over 6.0 miles"
    )
    assert final_result["place"] == 1
    assert final_result["points"] == 1.0

    regatta = read_regatta(world["regatta_id"])
    assert regatta["final_race_count"] == 1
    assert regatta["status"] == "SCORED", "the one planned race is now FINAL"


def test_the_unaccepted_entry_is_outside_the_scored_set_of_that_bubble_up(api):
    """PRD 3.9: "Hop one mints a result with `finish_status` `DNC` for every
    `ACCEPTED` entry of the regatta that has no result in this race — the
    did-not-compete rows nobody enters by hand."

    PRD 3.9 also excludes the unaccepted entry from every figure the run computes:
    "Entries whose `registration_status` is `SUBMITTED`, `RATING_INVALID` or
    `WITHDRAWN` are excluded both from the fleet size and from the candidate set, and
    any rows they may hold keep `points` 0."

    PRD 3.5 fixes the values such an entry therefore still carries: "Its
    `crew_manifest` starts empty, with `registered_crew_count` 0, `crew_weight_kg`
    0, `division_id` null, `equipment_deficiency_code` null, `series_points_gross`
    and `series_points_net` 0, `discarded_race_numbers` empty and `series_rank`
    null."

    Design: Corner/state_machines/regatta_bubbles_up_to_scored_when_last_planned_race_is_final
    """
    world = _last_planned_race_world()
    race_id = world["races"][1]["id"]
    pro = world["h"]["pro"]
    set_clock(RESULTS_CLOCK)
    record_result(
        race_id, world["entries"]["A"]["id"], world["ids"]["pro"], elapsed_seconds=4800.0
    )
    validate_success(api.score_race(race_id, pro))

    rows, pagination = validate_paginated(api.list_race_results(pro, {"race_id": race_id}))
    assert pagination["total_count"] == 1, (
        "the entry that was never accepted earned no did-not-compete row"
    )
    assert rows[0]["entry_id"] == world["entries"]["A"]["id"]

    winner = read_entry(world["entries"]["A"]["id"])
    assert winner["series_points_gross"] == 1.0
    assert winner["series_points_net"] == 1.0
    assert winner["discarded_race_numbers"] == []
    assert winner["series_rank"] == 1

    outsider = read_entry(world["entries"]["B"]["id"])
    assert outsider["registration_status"] == "SUBMITTED"
    assert outsider["series_points_gross"] == 0
    assert outsider["series_rank"] is None, "an unscored entry holds no series rank"


def test_the_reinstatement_cycle_is_lossy_and_returns_the_entry_only_to_submitted(api, roster):
    """PRD 3.2: "Reinstatement closes the cycle `ISSUED → SUSPENDED → ISSUED`. The
    measurer reinstates a `SUSPENDED` certificate provided the logical clock is still
    inside the inclusive validity window; hop one restores status `ISSUED` and clears
    `suspension_reason_code` back to null. Hop two returns every entry pinning this
    certificate whose `registration_status` is `RATING_INVALID` to `SUBMITTED` —
    deliberately not to `ACCEPTED`, so the chair must admit each one again — and hop
    three has the divisions of those entries re-derive both counts. Because the
    entries land in `SUBMITTED`, `accepted_entry_count` does not recover here, and a
    division that regains enough assigned entries is **not** auto-confirmed: the
    chair must confirm it a second time."

    PRD 2.6 fixes the version arithmetic the cycle leaves on the boat: "Every
    certificate create, issue, suspend and reinstate increments `Boat.version` by 1"

    Design: Corner/state_machines/certificate_reinstate_returns_entries_to_submitted_not_accepted
    """
    world = build_accepted_fleet_world(
        entrants=(
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
            {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
        ),
    )
    measurer = make_measurer_headers(world["ids"]["measurer"])
    certificate_id = world["certificates"]["A"]["id"]
    boat_id = world["boats"]["A"]["id"]
    division_id = world["divisions"]["A"]["id"]
    assert read_division(division_id)["status"] == "CONFIRMED"

    suspended = validate_success(
        api.suspend_certificate(certificate_id, suspend_certificate_payload(), measurer)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason_code"] == "MEASUREMENT_IRREGULARITY"
    assert read_entry(world["entries"]["A"]["id"])["registration_status"] == "RATING_INVALID"
    assert read_division(division_id)["status"] == "PROVISIONAL"
    assert read_boat(boat_id)["version"] == 4

    reinstated = validate_success(api.reinstate_certificate(certificate_id, measurer))

    assert reinstated["status"] == "ISSUED"
    assert reinstated["suspension_reason_code"] is None

    returned = read_entry(world["entries"]["A"]["id"])
    assert returned["registration_status"] == "SUBMITTED", (
        "the cycle is deliberately lossy: the chair must admit the entry again"
    )
    assert returned["division_id"] == division_id, "the assignment itself was never lost"
    assert read_entry(world["entries"]["B"]["id"])["registration_status"] == "ACCEPTED"

    division = read_division(division_id)
    assert division["assigned_entry_count"] == 2
    assert division["accepted_entry_count"] == 1, "acceptance does not recover here"
    assert division["status"] == "PROVISIONAL", (
        "regaining the assigned entries does not re-confirm the division"
    )
    assert read_boat(boat_id)["version"] == 5, (
        "the registration, the filing, the issue, the suspension and the reinstatement"
    )
