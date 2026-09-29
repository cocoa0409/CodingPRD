"""Term tables, trip-by-trip evaluation, visitor day accounting and the ladder."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_DETERMINATION_NOT_ACTIVE,
    ERR_SERVICE_DATE_OUT_OF_RANGE,
    ERR_VISITOR_DAYS_EXHAUSTED,
)
from test_helpers.assertions import assert_sweep_counters
from test_helpers.fixtures import (
    attended_assessment,
    create_applicant,
    create_slot,
    drafted_determination,
    heard_appeal_on_paper,
    ingest_trip_events,
    run_day_close,
    set_clock,
    visitor_record,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
)


def test_a_temporary_grant_runs_one_hundred_eighty_days_from_its_effective_date(api):
    """A non-permanent attestation forces branch 1 and the 180-day term.

    "If the packet's `attests_permanent` is false, the recommendation is
    `TEMPORARY`."

    "`recommended_term_days` is then set from the recommended category using the
    same term table the determination itself uses: 1,825 days (five years) for
    `UNCONDITIONAL`, 1,095 days (three years) for `CONDITIONAL`, 180 days for
    `TEMPORARY`, and 0 days for `INELIGIBLE`."

    "It stamps `issued_at` with the logical clock and computes the term:
    `term_days` is 1,825 for `UNCONDITIONAL`, 1,095 for `CONDITIONAL`, 180 for
    `TEMPORARY` and 0 for `INELIGIBLE`, and `expires_at` is the `effective_date`
    advanced by `term_days` calendar days"

    Design: Corner/calculations/temporary_term_is_one_hundred_eighty_days_from_the_effective_date
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Tobias Renner",
        date_of_birth="1983-03-13",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = drafted_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=600,
            uses_mobility_aid_outdoors=False,
        ),
        claimed_conditions=["post-surgical recovery, 4 months"],
        attests_permanent=False,
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 3,
            "wayfinding_score": 3,
            "distance_meters_walked": 600,
            "heat_sensitivity_flag": True,
        },
        draft_overrides={
            "category": "TEMPORARY",
            "effective_date": "2026-08-06",
            "rationale": "temporary functional limitation pending recovery",
        },
    )
    assert context["application"]["attests_permanent"] is False
    assert context["assessment"]["recommended_category"] == "TEMPORARY"
    assert context["assessment"]["recommended_term_days"] == 180

    issued = validate_success(
        api.issue_determination(
            context["determination"]["id"], factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    assert issued["status"] == "ISSUED"
    assert issued["term_days"] == 180
    assert issued["expires_at"] == "2027-02-02"
    assert issued["issued_at"] == "2026-08-05T09:30:00.000Z"
    assert issued["effective_date"] == "2026-08-06"

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["current_eligibility_status"] == "ELIGIBLE"
    assert reread["eligibility_category"] == "TEMPORARY"

    _referrals, meta = validate_paginated(
        api.list_travel_training_referrals(
            TRAINER_HEADERS, params={"applicant_id": rider["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_an_ineligible_grant_denies_a_trip_with_a_body_not_an_error(api):
    """Two shapes of refusal: a 409 while DRAFT and a structured denial once ISSUED.

    "The determination must be in `ISSUED`; a check against a `DRAFT`,
    `SUPERSEDED`, `VACATED` or `EXPIRED` determination is refused outright with
    `ERR_DETERMINATION_NOT_ACTIVE` (409) rather than answered with a structured
    denial"

    "If the determination is `ISSUED` but its `category` is `INELIGIBLE`, the
    answer is a successful response reporting `eligible` false with
    `denial_reason` `CATEGORY_INELIGIBLE`."

    "except for an `INELIGIBLE` determination, whose `expires_at` stays null
    because a denial does not expire"

    Design: Corner/calculations/ineligible_determination_denies_trips_without_raising_an_error
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Uma Kirchner",
        date_of_birth="1990-10-20",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = drafted_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=900,
            uses_mobility_aid_outdoors=False,
        ),
        claimed_conditions=["chronic condition, ambulatory"],
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 4,
            "wayfinding_score": 4,
            "distance_meters_walked": 900,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "INELIGIBLE",
            "effective_date": "2026-08-06",
            "rationale": "can use fixed route independently",
        },
    )
    determination_id = context["determination"]["id"]
    assert context["assessment"]["recommended_category"] == "INELIGIBLE"
    assert context["assessment"]["recommended_term_days"] == 0

    validate_error(
        api.trip_eligibility_check(
            determination_id,
            factories.trip_eligibility_check_payload(trip_date="2026-08-10"),
            SPECIALIST_HEADERS,
        ),
        ERR_DETERMINATION_NOT_ACTIVE,
        409,
    )

    issued = validate_success(
        api.issue_determination(
            determination_id, factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    assert issued["term_days"] == 0
    assert issued["expires_at"] is None

    answer = validate_success(
        api.trip_eligibility_check(
            determination_id,
            factories.trip_eligibility_check_payload(trip_date="2026-08-10"),
            SPECIALIST_HEADERS,
        )
    )
    assert answer["eligible"] is False
    assert answer["denial_reason"] == "CATEGORY_INELIGIBLE"
    assert answer["applied_condition_ids"] == []
    assert answer["evaluated_condition_count"] == 0
    assert answer["category"] == "INELIGIBLE"

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["current_eligibility_status"] == "INELIGIBLE"
    assert reread["eligibility_category"] == "INELIGIBLE"


def test_a_trip_check_is_satisfied_by_any_one_condition_in_created_at_order(api):
    """Conditions are OR-ed, walked in created_at order, and never mutated.

    "Only when none of those short-circuits applies does the server walk the
    determination's trip conditions, in `created_at` ascending order — never in
    identifier order."

    "In all three numeric cases the `comparator` decides the test: `GTE` is
    satisfied when the supplied value is greater than or equal to the threshold,
    `GT` when it is strictly greater, `LTE` when it is less than or equal, and
    `LT` when it is strictly less."

    "The response reports `applied_condition_ids` as the identifiers of the
    satisfied conditions in the order they were evaluated, `eligible` as true when
    that list holds at least one entry, `denial_reason` as null when eligible and
    `NO_CONDITION_MET` when the list is empty, `evaluated_condition_count` as the
    number of the determination's conditions that were examined, and `category` as
    the determination's own category."

    Design: Corner/calculations/trip_check_applies_only_satisfied_conditions_in_created_at_order
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Viktor Salas",
        date_of_birth="1968-06-08",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = drafted_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=500,
        ),
        claimed_conditions=["multiple sclerosis, heat sensitive"],
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 3,
            "wayfinding_score": 3,
            "distance_meters_walked": 500,
            "heat_sensitivity_flag": True,
        },
        draft_overrides={
            "category": "CONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "heat and distance conditions",
            "trip_conditions": [
                factories.trip_condition_payload(
                    condition_type="HEAT_INDEX_ABOVE",
                    comparator="GTE",
                    threshold_value=90,
                    note="heat index at or above 90",
                ),
                factories.trip_condition_payload(
                    condition_type="DISTANCE_OVER_METERS",
                    comparator="GT",
                    threshold_value=400,
                    note="more than 400 m to the stop",
                ),
            ],
        },
    )
    determination_id = context["determination"]["id"]
    assert context["determination"]["trip_condition_count"] == 2

    validate_success(
        api.issue_determination(
            determination_id, factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    conditions, condition_meta = validate_paginated(
        api.list_trip_conditions(determination_id, SPECIALIST_HEADERS)
    )
    assert condition_meta["total_count"] == 2
    assert conditions[0]["condition_type"] == "HEAT_INDEX_ABOVE"
    assert conditions[1]["condition_type"] == "DISTANCE_OVER_METERS"
    heat_id, distance_id = conditions[0]["id"], conditions[1]["id"]

    before = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )

    first = validate_success(
        api.trip_eligibility_check(
            determination_id,
            factories.trip_eligibility_check_payload(
                trip_date="2026-08-10",
                forecast_heat_index_f=95,
                origin_distance_to_stop_meters=300,
            ),
            SPECIALIST_HEADERS,
        )
    )
    assert first["eligible"] is True
    assert first["applied_condition_ids"] == [heat_id]
    assert first["denial_reason"] is None
    assert first["evaluated_condition_count"] == 2
    assert first["category"] == "CONDITIONAL"

    second = validate_success(
        api.trip_eligibility_check(
            determination_id,
            factories.trip_eligibility_check_payload(
                trip_date="2026-08-10",
                forecast_heat_index_f=89,
                origin_distance_to_stop_meters=400,
            ),
            SPECIALIST_HEADERS,
        )
    )
    assert second["eligible"] is False
    assert second["applied_condition_ids"] == []
    assert second["denial_reason"] == "NO_CONDITION_MET"
    assert second["evaluated_condition_count"] == 2

    third = validate_success(
        api.trip_eligibility_check(
            determination_id,
            factories.trip_eligibility_check_payload(
                trip_date="2026-08-10",
                forecast_heat_index_f=90,
                origin_distance_to_stop_meters=401,
            ),
            SPECIALIST_HEADERS,
        )
    )
    assert third["eligible"] is True
    assert third["applied_condition_ids"] == [heat_id, distance_id]
    assert third["evaluated_condition_count"] == 2

    after = validate_success(api.get_determination(determination_id, SPECIALIST_HEADERS))
    assert after["version"] == before["version"]


def test_three_re_scores_walk_the_recommendation_across_its_thresholds(api):
    """Each re-score overwrites the recommendation rather than accumulating.

    "Re-scoring is explicitly allowed while the assessment is still `SCORED` and
    not yet signed off: it is a self-loop that overwrites the four observations,
    recomputes the recommendation, and rewrites `scored_by_user_id` to whoever
    performed the latest scoring."

    "2. Otherwise, if the lower of `board_alight_score` and `wayfinding_score` is
    at most 1, the recommendation is `UNCONDITIONAL`."

    "5. Otherwise, if `distance_meters_walked` is 800 meters or more and
    `heat_sensitivity_flag` is false, the recommendation is `INELIGIBLE`."

    "6. Otherwise the recommendation is `CONDITIONAL`."

    Design: Corner/calculations/recommended_category_threshold_walk_across_min_score_and_distance_ceiling
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Winona Frost",
        date_of_birth="1977-07-27",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = attended_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=500,
            uses_mobility_aid_outdoors=False,
        ),
        claimed_conditions=["chronic fatigue"],
        slot=create_slot(api, capacity=2),
    )
    assessment_id = context["assessment"]["id"]
    application_id = context["application"]["id"]

    first = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=1,
                wayfinding_score=4,
                distance_meters_walked=500,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert first["recommended_category"] == "UNCONDITIONAL"
    assert first["recommended_term_days"] == 1825
    assert first["scoring_status"] == "SCORED"

    second = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=4,
                distance_meters_walked=500,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert second["recommended_category"] == "CONDITIONAL"
    assert second["recommended_term_days"] == 1095
    assert second["scoring_status"] == "SCORED"

    third = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=4,
                distance_meters_walked=900,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert third["recommended_category"] == "INELIGIBLE"
    assert third["recommended_term_days"] == 0
    assert third["scoring_status"] == "SCORED"
    assert third["distance_meters_walked"] == 900

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_SCHEDULED"


_DESCENDING_OCTOBER_DAYS = [
    "2026-10-30",
    "2026-10-29",
    "2026-10-28",
    "2026-10-27",
    "2026-10-26",
    "2026-10-25",
    "2026-10-24",
    "2026-10-23",
    "2026-10-22",
    "2026-10-21",
    "2026-10-20",
    "2026-10-19",
    "2026-10-18",
    "2026-10-17",
    "2026-10-16",
    "2026-10-15",
    "2026-10-14",
    "2026-10-13",
    "2026-10-12",
    "2026-10-11",
    "2026-10-10",
]


def test_the_visitor_window_is_fixed_by_the_requested_date_alone(api):
    """Days booked in descending order never crowd their own window.

    "First, the window is fixed from the **request**: it ends on the requested
    `service_date` and opens 364 days earlier, so it spans 365 calendar days
    inclusive of both ends. Second, the server counts the distinct dates already
    present in `service_dates` that fall inside that window; the date being
    requested is not yet among them. Third, the day is granted only when that
    count is below 21, and otherwise the request is refused with
    `ERR_VISITOR_DAYS_EXHAUSTED` (409)."

    "Fifth, `days_used_365` is recomputed as the number of distinct dates in
    `service_dates` inside the window fixed in step one, and `days_remaining_365`
    becomes 21 minus that figure, reported as zero rather than a negative number."

    Design: Corner/calculations/visitor_window_is_pinned_to_the_requested_date_not_the_grant_outcome
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Xavier Boone",
        date_of_birth="1952-02-12",
        residence_zone="OUT_OF_SERVICE_AREA",
        mobility_aid="WALKER",
        home_agency_name="Harbor Transit",
    )
    visitor = visitor_record(
        api,
        applicant=rider,
        home_agency_name="Harbor Transit",
        home_agency_certification_provided=True,
        visit_start_date="2026-08-01",
    )
    record_id = visitor["visitor_record"]["id"]

    last = None
    for service_date in _DESCENDING_OCTOBER_DAYS:
        last = validate_success(
            api.record_visitor_service_day(
                record_id, factories.service_day_payload(service_date), CLERK_HEADERS
            )
        )
    assert last["status"] == "ACTIVE"
    assert last["days_used_365"] == 1
    assert last["days_remaining_365"] == 20
    assert len(last["service_dates"]) == 21

    set_clock(api, "2026-08-02T00:00:00Z")
    validate_error(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-10-31"), CLERK_HEADERS
        ),
        ERR_VISITOR_DAYS_EXHAUSTED,
        409,
    )
    unchanged = validate_success(api.get_visitor_eligibility(record_id, CLERK_HEADERS))
    assert unchanged["status"] == "ACTIVE"
    assert len(unchanged["service_dates"]) == 21

    earlier = validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-10-09"), CLERK_HEADERS
        )
    )
    assert earlier["status"] == "ACTIVE"
    assert earlier["days_used_365"] == 1
    assert len(earlier["service_dates"]) == 22


def test_a_repeated_service_date_costs_nothing_and_the_range_is_closed(api):
    """Appending is idempotent and the acceptance range is inclusive at both ends.

    "Fourth, and only after granting, the requested `service_date` is appended to
    `service_dates` — appending is idempotent, so a date already present is not
    stored twice and does not consume a day of the allowance."

    "The requested date must fall on or after `visit_start_date` and no later than
    today's date plus 90 days, else `ERR_SERVICE_DATE_OUT_OF_RANGE` (422)."

    Design: Corner/calculations/duplicate_visitor_service_date_consumes_no_day_and_range_is_enforced
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Yara Nasser",
        date_of_birth="1985-05-15",
        residence_zone="OUT_OF_SERVICE_AREA",
        mobility_aid="NONE",
        home_agency_name="Desert Regional",
    )
    visitor = visitor_record(
        api,
        applicant=rider,
        home_agency_name="Desert Regional",
        home_agency_certification_provided=True,
        visit_start_date="2026-08-01",
    )
    record_id = visitor["visitor_record"]["id"]

    validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-08-01"), CLERK_HEADERS
        )
    )
    two_days = validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-08-02"), CLERK_HEADERS
        )
    )
    assert two_days["days_used_365"] == 2

    duplicate = validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-08-02"), CLERK_HEADERS
        )
    )
    assert duplicate["days_used_365"] == 2
    assert duplicate["days_remaining_365"] == 19
    assert len(duplicate["service_dates"]) == 2

    validate_error(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-07-31"), CLERK_HEADERS
        ),
        ERR_SERVICE_DATE_OUT_OF_RANGE,
        422,
    )
    validate_error(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-10-31"), CLERK_HEADERS
        ),
        ERR_SERVICE_DATE_OUT_OF_RANGE,
        422,
    )
    edge = validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-10-30"), CLERK_HEADERS
        )
    )
    assert edge["days_used_365"] == 3
    assert edge["status"] == "ACTIVE"


def test_the_second_upheld_suspension_draws_fourteen_days_not_seven(api):
    """The ladder index is the prior count as it stood before this decision.

    "An `UPHELD` decision moves the proceeding to `UPHELD_PENDING`, records
    `decision` and `decided_by_user_id`, and computes the length of the suspension
    from an escalating ladder of 7, 14, 21 and 30 days. The index into that ladder
    is the rider's `prior_upheld_suspension_count` **as it stands before this
    decision increments it**: a first offence draws 7 days, a second 14, a third
    21, and a fourth or any subsequent offence draws 30 days."

    "`suspension_end_date` is then the `suspension_start_date` advanced by
    `duration_days` and pulled back one day, because the end date is the last
    suspended date and is itself suspended. Finally the rider's
    `prior_upheld_suspension_count` increases by one and
    `suspension_days_ledger_total` grows by `duration_days`."

    "Creating it also consolidates the record: every *other* proceeding of that
    rider still in `PROPOSED` moves `PROPOSED → VOID`"

    Design: Corner/calculations/suspension_ladder_second_upheld_decision_is_fourteen_days
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Zane Petrov",
        date_of_birth="1988-08-28",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_events(
        api,
        rider["id"],
        [
            ("2026-07-10", "NO_SHOW"),
            ("2026-07-17", "NO_SHOW"),
            ("2026-07-24", "NO_SHOW"),
        ],
    )
    proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 1
    first_id = proceedings[0]["id"]
    assert proceedings[0]["origin"] == "AUTO_THRESHOLD"

    set_clock(api, "2026-08-05T00:00:00Z")
    noticed = validate_success(
        api.send_suspension_notice(
            first_id, factories.send_notice_payload(), CONDUCT_OFFICER_HEADERS
        )
    )
    assert noticed["response_deadline_date"] == "2026-08-19"
    validate_success(
        api.respond_to_suspension(
            first_id,
            factories.rider_response_payload(
                rider_response_note="I mistook the pickup window"
            ),
            make_applicant_headers(rider["id"]),
        )
    )
    first_decision = validate_success(
        api.decide_suspension(
            first_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        )
    )
    assert first_decision["status"] == "UPHELD_PENDING"
    assert first_decision["duration_days"] == 7
    assert first_decision["suspension_end_date"] == "2026-09-07"

    set_clock(api, "2026-08-10T00:00:00Z")
    reread = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert reread["prior_upheld_suspension_count"] == 1
    assert reread["suspension_days_ledger_total"] == 7

    second = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                reread["version"],
                review_window_end_date="2026-08-10",
                grounds_note="conduct unchanged after the first notice",
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )
    validate_success(
        api.send_suspension_notice(
            second["id"], factories.send_notice_payload(), CONDUCT_OFFICER_HEADERS
        )
    )
    validate_success(
        api.respond_to_suspension(
            second["id"],
            factories.rider_response_payload(rider_response_note="second response"),
            make_applicant_headers(rider["id"]),
        )
    )
    second_decision = validate_success(
        api.decide_suspension(
            second["id"],
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-20"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        )
    )
    assert second_decision["duration_days"] == 14
    assert second_decision["suspension_end_date"] == "2026-10-03"

    final = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert final["prior_upheld_suspension_count"] == 2
    assert final["suspension_days_ledger_total"] == 21

    untouched = validate_success(
        api.get_suspension_proceeding(first_id, CONDUCT_OFFICER_HEADERS)
    )
    assert untouched["status"] == "UPHELD_PENDING"
    assert untouched["days_served"] == 0


def test_an_appeal_becomes_overdue_only_the_day_after_its_deadline(api):
    """Step 5 uses a strict comparison, so the due date itself is still on time.

    "**Step 5 — overdue appeals.** Every `Appeal` in `HEARD` whose
    `decision_due_date` falls strictly before today's date and whose `outcome` is
    still null has `continued_service_extended` set to true, and the rider's
    `current_eligibility_status` becomes `PRESUMPTIVE`."

    "Its response body reports six counters — `appeals_heard_count`,
    `proceedings_advanced_count`, `determinations_expired_count`,
    `referrals_withdrawn_count`, `presumptive_granted_count` and
    `appeals_overdue_count` — corresponding respectively to step 1 advances, step 2
    advances, step 3 expiries, referrals withdrawn by the step 3 cascade, step 4
    grants and step 5 extensions."

    Design: Corner/calculations/overdue_appeal_decision_extends_continued_service_at_day_close
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ada Kowalski",
        date_of_birth="1956-06-16",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = heard_appeal_on_paper(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=120),
        claimed_conditions=["hip replacement complications"],
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 120,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board steps",
        },
        appeal_overrides={"grounds": "requests unconditional with a wider term"},
    )
    appeal_id = context["appeal"]["id"]
    determination_id = context["determination"]["id"]
    assert context["appeal"]["decision_due_date"] == "2026-09-04"

    set_clock(api, "2026-09-04T00:00:00Z")
    on_the_due_date = run_day_close(api)
    assert_sweep_counters(on_the_due_date, appeals_overdue_count=0)
    still_on_time = validate_success(api.get_appeal(appeal_id, ADMIN_HEADERS))
    assert still_on_time["continued_service_extended"] is False

    set_clock(api, "2026-09-05T00:00:00Z")
    day_after = run_day_close(api)
    assert_sweep_counters(
        day_after,
        appeals_overdue_count=1,
        determinations_expired_count=0,
        presumptive_granted_count=0,
    )

    overdue = validate_success(api.get_appeal(appeal_id, ADMIN_HEADERS))
    assert overdue["status"] == "HEARD"
    assert overdue["outcome"] is None
    assert overdue["continued_service_extended"] is True

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["current_eligibility_status"] == "PRESUMPTIVE"
    assert reread["active_determination_id"] == determination_id

    determination = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )
    assert determination["status"] == "ISSUED"
    assert determination["under_appeal"] is True
