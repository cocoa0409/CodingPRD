"""Survey rounds: the closed-window contention algebra whose capacity depends on
`round_type`, the strictly linear round machine, and the gates every observation
must pass before a round may be locked."""
from test_helpers import (
    as_instant,
    assert_survey_observation,
    create_candidate_nurse,
    create_certified_nurse,
    create_patient,
    create_round,
    create_unit,
    file_observation,
    get_success_data,
    lock_round,
    open_round,
    publish_round,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_nurse_headers


DIRECTOR = make_director_headers()


def _round(api, round_id):
    """The round as the server currently holds it."""
    return get_success_data(api.get_survey_round(round_id, DIRECTOR))


def _unit(api, unit_id):
    return get_success_data(api.get_unit(unit_id, DIRECTOR))


def _observation_payload(survey_round, unit, patient, observer, **overrides):
    """The full observation payload in the order §1.5 declares its fields."""
    payload = {
        "survey_round_id": survey_round["id"],
        "unit_id": unit["id"],
        "patient_id": patient["id"],
        "observer_nurse_id": observer["id"],
        "observed_at": "2026-08-02T00:00:00Z",
        "injury_present": False,
        "classification": "NONE",
        "at_risk": True,
    }
    payload.update(overrides)
    return payload


def test_two_prevalence_windows_that_merely_touch_cannot_both_be_open(api):
    """One instant of overlap is overlap; one day of clearance is not.

    PRD §3.7: "Two rounds collide when their closed windows touch at all:
    collision holds exactly when the first round's `window_start` is at or before
    the second round's `window_end` and the second round's `window_start` is at or
    before the first round's `window_end`."
    PRD §3.7: "A `PREVALENCE` round may not open when any other `PREVALENCE` round
    whose `status` is `OPEN`, `LOCKED` or `PUBLISHED` collides on a shared unit —
    the aggregate capacity for prevalence work on a ward is exactly one round."
    PRD §3.7: "A planned round starts with `status` `PLANNED`, `observation_count`
    0 and `published_at` null."

    Design: Difficulty/resource_temporal_overlap/unit_prevalence_window_conflict_closed_interval_capacity
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    running = create_round(
        [unit["id"]],
        api=api,
        round_type="PREVALENCE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
    )
    touching = create_round(
        [unit["id"]],
        api=api,
        round_type="PREVALENCE",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-09T00:00:00Z",
    )
    one_day_clear = create_round(
        [unit["id"]],
        api=api,
        round_type="PREVALENCE",
        window_start="2026-08-06T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
    )
    for planned in (running, touching, one_day_clear):
        assert planned["status"] == "PLANNED"
        assert planned["observation_count"] == 0
        assert planned["published_at"] is None

    assert open_round(running, api=api)["status"] == "OPEN"

    validate_error(
        api.open_survey_round(touching["id"], {}, DIRECTOR),
        "ERR_SURVEY_WINDOW_CONFLICT",
        expected_status=409,
    )
    refused = _round(api, touching["id"])
    assert refused["status"] == "PLANNED", (
        "a window_start equal to the open round's window_end is inside a closed "
        "interval, so the second round never opens"
    )
    assert refused["version"] == touching["version"], "the refusal versioned nothing"

    accepted = validate_success(
        api.open_survey_round(one_day_clear["id"], {}, DIRECTOR)
    )
    assert accepted["status"] == "OPEN", (
        "2026-08-06T00:00:00Z is strictly after the open round's window_end, and "
        "the still-PLANNED round in between is in none of the blocking states"
    )
    assert _unit(api, unit["id"])["survey_posture"] == "OPEN", (
        "window contention is not a posture gate and never writes to the unit"
    )


def test_incidence_surveillance_admits_two_concurrent_rounds_and_refuses_a_third(api):
    """The capacity counter is per `round_type`, and for incidence it is two.

    PRD §3.7: "An `INCIDENCE` round may not open when two or more other
    `INCIDENCE` rounds whose `status` is `OPEN` or `LOCKED` already collide on a
    shared unit — the aggregate capacity for incidence surveillance is two
    concurrent rounds, so a third is refused."
    PRD §3.7: "Contention is then assessed per `round_type` and only against
    rounds that share at least one unit identifier with this round's
    `participating_unit_ids`."
    PRD §2.10 rung 44: "Survey window contention on a shared unit —
    `ERR_SURVEY_WINDOW_CONFLICT` (409), on
    `POST /survey-rounds/{round_id}/open`; the arithmetic is given in §3.7."

    Design: Difficulty/resource_temporal_overlap/unit_prevalence_window_conflict_closed_interval_capacity
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    prevalence = create_round(
        [unit["id"]],
        api=api,
        round_type="PREVALENCE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
    )
    first, second, third = (
        create_round(
            [unit["id"]],
            api=api,
            round_type="INCIDENCE",
            window_start=window_start,
            window_end=window_end,
        )
        for window_start, window_end in (
            ("2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z"),
            ("2026-08-06T00:00:00Z", "2026-08-10T00:00:00Z"),
            ("2026-08-07T00:00:00Z", "2026-08-11T00:00:00Z"),
        )
    )
    open_round(prevalence, api=api)

    crossing_the_prevalence_window = validate_success(
        api.open_survey_round(first["id"], {}, DIRECTOR)
    )
    assert crossing_the_prevalence_window["status"] == "OPEN", (
        "this window touches the open PREVALENCE round at 2026-08-05T00:00:00Z, "
        "and a round of the other type is not a competitor"
    )

    assert validate_success(api.open_survey_round(second["id"], {}, DIRECTOR))[
        "status"
    ] == "OPEN", "one colliding incidence round is still short of the capacity of two"

    validate_error(
        api.open_survey_round(third["id"], {}, DIRECTOR),
        "ERR_SURVEY_WINDOW_CONFLICT",
        expected_status=409,
    )
    assert _round(api, third["id"])["status"] == "PLANNED", (
        "both open incidence rounds collide with this window, so the third is "
        "refused on the aggregate count rather than on any single pairing"
    )
    assert as_instant(_round(api, third["id"])["window_start"]) > as_instant(
        _round(api, prevalence["id"])["window_end"]
    ), "the refusal cannot be blamed on the prevalence round, which it clears"
    assert _unit(api, unit["id"])["survey_posture"] == "OPEN"


def test_a_filed_observation_carries_no_version_and_cannot_be_touched_again(api):
    """The one entity in the system with nothing but an id and a created_at.

    PRD §2.4: "The one exception is the survey observation: a survey observation
    is an immutable audit record and carries only `id` and `created_at` — it has
    neither `updated_at` nor `version`, and there is no operation that mutates one
    after it is filed."
    PRD §3.7: "The observation itself is an audit record: as noted in §2.4 it
    carries only `id` and `created_at`, has neither `updated_at` nor `version`, and
    no operation modifies it afterwards."
    PRD §3.7: "`onset_at` is the documented onset instant of the injury and is
    required when `classification` is `HAPI` and must be null otherwise."

    Design: Corner/entities/survey_observation_is_immutable_with_no_version_field
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    observer = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit, api=api, mrn="MRN-O1", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )

    filed = validate_success(
        api.create_survey_observation(
            _observation_payload(
                survey_round,
                unit,
                patient,
                observer,
                injury_present=True,
                classification="POA",
                observed_stage="STAGE_2",
            ),
            make_nurse_headers(observer["id"]),
        ),
        expected_status=201,
    )
    assert_survey_observation(filed)
    assert filed["onset_at"] is None, "a present-on-admission row documents no onset"

    reread = validate_success(
        api.get_survey_observation(filed["id"], DIRECTOR)
    )
    assert reread == filed, (
        "the only two endpoints that touch an existing observation are reads, so "
        "the row cannot have changed between them"
    )

    after = _round(api, survey_round["id"])
    assert after["observation_count"] == 1
    assert after["status"] == "OPEN", "filing does not advance the round"

    rows, meta = validate_paginated(
        api.list_survey_observations(DIRECTOR, params={"survey_round_id": survey_round["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0] == filed


def test_a_round_cannot_skip_the_lock_on_its_way_to_publication(api):
    """Publish is refused from OPEN, then granted from LOCKED, on one round.

    PRD §3.7: "The director publishes a locked round, moving it
    `LOCKED → PUBLISHED` and stamping `published_at` from the logical clock."
    PRD §2.10 rung 15: "The survey round's `status` is a legal starting state for
    the requested transition, and filing an observation additionally requires the
    round to be `OPEN` — `ERR_SURVEY_ROUND_NOT_OPEN` (409), on
    `POST /survey-rounds/{round_id}/open`, `/lock`, `/publish`, `/cancel` and on
    `POST /survey-observations`."
    PRD §3.7: "For **prevalence**, the numerator is the count of that unit's
    observations in the round whose `injury_present` is true, regardless of
    `classification`, so injuries the patient arrived with are counted; the
    denominator is the count of all of that unit's observations in the round,
    regardless of `at_risk`."

    Design: Corner/state_machines/survey_round_publish_from_open_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    observer = create_certified_nurse(unit, api=api, full_name="Nina Stage")
    patient = create_patient(
        unit, api=api, mrn="MRN-H2", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    file_observation(
        survey_round,
        unit,
        patient,
        observer,
        api=api,
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
        at_risk=True,
    )
    opened = _round(api, survey_round["id"])

    validate_error(
        api.publish_survey_round(survey_round["id"], {}, DIRECTOR),
        "ERR_SURVEY_ROUND_NOT_OPEN",
        expected_status=409,
    )
    still_open = _round(api, survey_round["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["published_at"] is None
    assert still_open["version"] == opened["version"], "the refusal versioned nothing"
    assert _unit(api, unit["id"])["last_prevalence_rate"] is None, (
        "no metric may be written by a round that has not passed through LOCKED"
    )

    assert lock_round(survey_round, api=api)["status"] == "LOCKED"

    published = validate_success(
        api.publish_survey_round(survey_round["id"], {}, DIRECTOR)
    )
    assert published["status"] == "PUBLISHED"
    assert as_instant(published["published_at"]) == as_instant("2026-08-01T00:00:00Z"), (
        "the stamp is read off the logical clock, which no test has repositioned"
    )
    assert published["observation_count"] == 1

    measured = _unit(api, unit["id"])
    assert measured["last_prevalence_rate"] == 100.00, "one injury row over one row"
    assert measured["last_incidence_rate"] is None, (
        "a PREVALENCE round writes only the rate matching its own round_type"
    )


def test_both_ends_of_the_survey_window_are_inside_it_and_onset_may_equal_it(api):
    """Two temporal predicates, one error code, four boundary probes.

    PRD §3.7: "The window is a **closed** interval running from `window_start`
    through `window_end` inclusive, and `window_end` must be strictly later than
    `window_start`."
    PRD §3.7: "The `observed_at` instant must lie inside the round's closed
    window, and a supplied `onset_at` must be at or before `observed_at`; either
    failure is an `ERR_OBSERVATION_OUTSIDE_WINDOW`."
    PRD §3.7: "Filing an observation raises the round's `observation_count` by 1
    and versions the round."

    Design: Corner/validations/observation_outside_closed_survey_window_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(unit, api=api, full_name="Nina Stage")
    first, second, third = (
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-Q1", "MRN-Q2", "MRN-Q3")
    )
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    set_clock("2026-08-06T00:00:00Z", api=api)
    observer_headers = make_nurse_headers(observer["id"])

    def file(patient, **overrides):
        return api.create_survey_observation(
            _observation_payload(survey_round, unit, patient, observer, **overrides),
            observer_headers,
        )

    validate_error(
        file(first, observed_at="2026-08-01T23:59:59Z"),
        "ERR_OBSERVATION_OUTSIDE_WINDOW",
        expected_status=422,
    )
    assert validate_success(
        file(first, observed_at="2026-08-02T00:00:00Z"), expected_status=201
    )["patient_id"] == first["id"], "window_start itself is inside a closed interval"
    assert validate_success(
        file(second, observed_at="2026-08-05T00:00:00Z"), expected_status=201
    )["patient_id"] == second["id"], "and so is window_end"

    validate_error(
        file(third, observed_at="2026-08-06T00:00:00Z"),
        "ERR_OBSERVATION_OUTSIDE_WINDOW",
        expected_status=422,
    )
    validate_error(
        file(
            third,
            observed_at="2026-08-03T00:00:00Z",
            injury_present=True,
            classification="HAPI",
            observed_stage="STAGE_2",
            onset_at="2026-08-04T00:00:00Z",
        ),
        "ERR_OBSERVATION_OUTSIDE_WINDOW",
        expected_status=422,
    )
    on_the_bound = validate_success(
        file(
            third,
            observed_at="2026-08-03T00:00:00Z",
            injury_present=True,
            classification="HAPI",
            observed_stage="STAGE_2",
            onset_at="2026-08-03T00:00:00Z",
        ),
        expected_status=201,
    )
    assert as_instant(on_the_bound["onset_at"]) == as_instant(
        on_the_bound["observed_at"]
    ), "the second predicate is satisfied at equality"

    assert _round(api, survey_round["id"])["observation_count"] == 3, (
        "three of the six attempts were accepted, and only those three moved the "
        "counter"
    )


def test_the_same_patient_may_be_walked_only_once_per_round(api):
    """The uniqueness key is the pair, so a new instant does not buy a second row.

    PRD §3.7: "At most one observation may exist for a given combination of
    `survey_round_id` and `patient_id`, and a second attempt is refused with
    `ERR_DUPLICATE_OBSERVATION`."
    PRD §2.10 rung 54: "At most one survey observation exists per combination of
    `survey_round_id` and `patient_id` — `ERR_DUPLICATE_OBSERVATION` (409), on
    `POST /survey-observations`."

    Design: Corner/validations/duplicate_observation_per_round_patient_pair_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(unit, api=api, full_name="Nina Stage")
    walked, unwalked = (
        create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-T1", "MRN-T2")
    )
    survey_round = open_round(
        create_round(
            [unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    first_pass = file_observation(
        survey_round, unit, walked, observer, api=api, observed_at="2026-08-02T00:00:00Z"
    )
    observer_headers = make_nurse_headers(observer["id"])

    validate_error(
        api.create_survey_observation(
            _observation_payload(
                survey_round,
                unit,
                walked,
                observer,
                observed_at="2026-08-03T00:00:00Z",
                injury_present=True,
                classification="POA",
                observed_stage="STAGE_2",
            ),
            observer_headers,
        ),
        "ERR_DUPLICATE_OBSERVATION",
        expected_status=409,
    )
    assert validate_success(
        api.create_survey_observation(
            _observation_payload(
                survey_round,
                unit,
                unwalked,
                observer,
                observed_at="2026-08-03T00:00:00Z",
                injury_present=True,
                classification="POA",
                observed_stage="STAGE_2",
            ),
            observer_headers,
        ),
        expected_status=201,
    )["patient_id"] == unwalked["id"], (
        "a different patient in the same round is not a duplicate"
    )

    assert _round(api, survey_round["id"])["observation_count"] == 2
    surviving = validate_success(
        api.get_survey_observation(first_pass["id"], DIRECTOR)
    )
    assert surviving["injury_present"] is False, (
        "the refused write must not overwrite the row it collided with"
    )
    assert surviving["observed_at"] == first_pass["observed_at"]


def test_a_round_locks_on_per_unit_coverage_and_not_on_a_row_count(api):
    """Two observations on one ward leave a two-ward round unlockable.

    PRD §3.7: "The director locks an open round, moving it `OPEN → LOCKED`, and
    this is the compound guard of the survey machine: the round may only lock when
    *every* unit identifier in `participating_unit_ids` has at least one
    observation attached to this round."
    PRD §2.10 rung 60: "Every unit id in the round's `participating_unit_ids` has
    at least one observation for that round before the round may be locked —
    `ERR_SURVEY_UNIT_COVERAGE_INCOMPLETE` (409), on
    `POST /survey-rounds/{round_id}/lock`."
    PRD §3.7: "When the denominator is 0 the rate is exactly 0.00 and no error is
    raised."

    Design: Corner/validations/survey_lock_rejected_until_every_participating_unit_observed
    """
    walked_unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    missing_unit = create_unit(
        api,
        unit_code="4W",
        name="Four West",
        bed_count=22,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(walked_unit, api=api, full_name="Nina Stage")
    injured, clean = (
        create_patient(walked_unit, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
        for mrn in ("MRN-W1", "MRN-W2")
    )
    elsewhere = create_patient(
        missing_unit, api=api, mrn="MRN-W3", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = open_round(
        create_round(
            [walked_unit["id"], missing_unit["id"]],
            api=api,
            round_type="PREVALENCE",
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-05T00:00:00Z",
        ),
        api=api,
    )
    file_observation(
        survey_round,
        walked_unit,
        injured,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
        injury_present=True,
        classification="POA",
        observed_stage="STAGE_2",
    )
    file_observation(
        survey_round,
        walked_unit,
        clean,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
    )
    two_rows = _round(api, survey_round["id"])
    assert two_rows["observation_count"] == 2

    validate_error(
        api.lock_survey_round(survey_round["id"], {}, DIRECTOR),
        "ERR_SURVEY_UNIT_COVERAGE_INCOMPLETE",
        expected_status=409,
    )
    refused = _round(api, survey_round["id"])
    assert refused["status"] == "OPEN"
    assert refused["version"] == two_rows["version"], (
        "a row count of two would have passed; the per-unit quantifier did not"
    )

    file_observation(
        survey_round,
        missing_unit,
        elsewhere,
        observer,
        api=api,
        observed_at="2026-08-02T00:00:00Z",
    )
    assert _round(api, survey_round["id"])["observation_count"] == 3

    assert validate_success(api.lock_survey_round(survey_round["id"], {}, DIRECTOR))[
        "status"
    ] == "LOCKED", "one observation per participating unit is the whole requirement"

    assert publish_round(survey_round, api=api)["status"] == "PUBLISHED"
    assert _unit(api, walked_unit["id"])["last_prevalence_rate"] == 50.00, (
        "one injury row out of the two rows attached to this ward"
    )
    assert _unit(api, missing_unit["id"])["last_prevalence_rate"] == 0.00, (
        "the late-walked ward contributed one clean row"
    )


def test_a_foreign_unit_outranks_an_unopened_round_on_the_same_request(api):
    """One request breaks rung 6 and rung 15 at once, and the lower number wins.

    PRD §2.10: "When more than one rule could reject a request, the rules are
    evaluated in the fixed ascending order below, the first failing rule wins, and
    no later rule is evaluated."
    PRD §2.5: "Once all references resolve individually, the server checks that
    they belong together, rejecting any disagreement with
    `ERR_ENTITY_LINK_MISMATCH` (HTTP 422)."
    PRD §3.7: "The round must be `OPEN` — filing against a `PLANNED`, `LOCKED`,
    `PUBLISHED` or `CANCELLED` round is refused with `ERR_SURVEY_ROUND_NOT_OPEN`."

    Design: Corner/validations/link_mismatch_outranks_round_state_and_rejects_foreign_unit
    """
    participating = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    foreign = create_unit(
        api,
        unit_code="4W",
        name="Four West",
        bed_count=22,
        rental_budget_cap_cents=0,
    )
    observer = create_candidate_nurse(participating, api=api, full_name="Nina Stage")
    patient = create_patient(
        participating, api=api, mrn="MRN-AB1", admitted_at="2026-07-31T00:00:00Z"
    )
    survey_round = create_round(
        [participating["id"]],
        api=api,
        round_type="PREVALENCE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
    )
    assert survey_round["status"] == "PLANNED"
    observer_headers = make_nurse_headers(observer["id"])

    def file(unit):
        return api.create_survey_observation(
            _observation_payload(survey_round, unit, patient, observer),
            observer_headers,
        )

    both_broken = file(foreign)
    validate_error(both_broken, "ERR_ENTITY_LINK_MISMATCH", expected_status=422)
    assert both_broken.json()["data"]["error_id"] != "ERR_SURVEY_ROUND_NOT_OPEN", (
        "the coherence rung is numbered 6 and the state rung 15, so the 422 wins "
        "over the 409 even though the round is also unopened"
    )
    assert both_broken.status_code != 409

    validate_error(file(participating), "ERR_SURVEY_ROUND_NOT_OPEN", expected_status=409)

    open_round(survey_round, api=api)
    validate_error(file(foreign), "ERR_ENTITY_LINK_MISMATCH", expected_status=422)

    accepted = validate_success(file(participating), expected_status=201)
    assert accepted["unit_id"] == participating["id"]
    assert _round(api, survey_round["id"])["observation_count"] == 1, (
        "none of the three refusals moved the counter"
    )
