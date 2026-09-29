"""Field, aggregate and priority-ordering guards on the intake and booking paths."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_CONDITIONAL_REQUIRES_CONDITIONS,
    ERR_DECIDER_NOT_INDEPENDENT,
    ERR_DETERMINATION_ALREADY_ISSUED,
    ERR_DUPLICATE_OPEN_APPLICATION,
    ERR_GRANTED_CATEGORY_MISMATCH,
    ERR_HEARING_NOT_REQUESTED,
    ERR_HEARING_REQUIRED,
    ERR_INVALID_APPLICATION_STATE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_NOT_ASSIGNED_REVIEWER,
    ERR_NOT_OUT_OF_AREA,
    ERR_PROCEEDING_STATE_INVALID,
    ERR_REFERRAL_STATE_INVALID,
    ERR_RESPONSE_WINDOW_CLOSED,
    ERR_REVIEWER_NOT_INDEPENDENT,
    ERR_SITE_NOT_ACCESSIBLE,
    ERR_SLOT_FULL,
    ERR_SUSPENSION_UNSUPPORTED,
    ERR_TRIP_DATE_FUTURE,
    ERR_UNCONDITIONAL_FORBIDS_CONDITIONS,
    ERR_VEHICLE_NOT_ACCESSIBLE,
    ERR_VEHICLE_OUT_OF_SERVICE,
)
from test_helpers.assertions import (
    assert_conduct_mirrors,
    assert_slot_mirror,
    assert_sweep_counters,
    assert_vehicle_counters,
)
from test_helpers.fixtures import (
    assessment_required,
    attended_assessment,
    auto_referral,
    create_applicant,
    create_out_of_area_applicant,
    create_slot,
    create_vehicle,
    draft_application,
    ingest_trip_event,
    ingest_trip_events,
    issued_determination,
    run_day_close,
    scheduled_assessment,
    scored_assessment,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    REVIEWER_2_HEADERS,
    REVIEWER_HEADERS,
    SPECIALIST_2_HEADERS,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
)


def test_the_pagination_bounds_are_closed_at_one_and_at_one_hundred(api):
    """Both edges of the limit range are accepted and both misses are one error.

    "`limit` is an integer bounded to the inclusive range 1 through 100 and
    defaults to 10 when omitted. `offset` is an integer that must be zero or
    greater and defaults to 0 when omitted. A `limit` below 1 or above 100, or a
    negative `offset`, or a non-integer value for either, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)"

    Design: Corner/validations/pagination_bounds_are_closed_at_one_and_one_hundred
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Bela Toth",
        date_of_birth="1963-03-23",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = draft_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=200),
    )
    application_id = context["application"]["id"]

    validate_error(
        api.list_applications(CLERK_HEADERS, params={"limit": 0}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_applications(CLERK_HEADERS, params={"limit": 101}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_applications(CLERK_HEADERS, params={"offset": -1}),
        ERR_INVALID_PAGINATION,
        400,
    )

    smallest_page, smallest_meta = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"limit": 1, "offset": 0})
    )
    assert smallest_meta["limit"] == 1
    assert smallest_meta["offset"] == 0
    assert smallest_meta["total_count"] == 1
    assert smallest_meta["has_more"] is False
    assert len(smallest_page) == 1

    largest_page, largest_meta = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"limit": 100})
    )
    assert largest_meta["limit"] == 100
    assert largest_page[0]["id"] == application_id

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["version"] == 1


def test_a_second_packet_is_refused_while_the_first_is_draft_or_submitted(api):
    """The one-open-packet rule counts DRAFT as open, and SUBMITTED too.

    "If the rider already holds an application whose `status` is anything other
    than `DETERMINED`, opening another is rejected with
    `ERR_DUPLICATE_OPEN_APPLICATION`."

    "It sets `completeness_established_at` equal to `submitted_at`, which is the
    moment the statutory determination window begins. It sets
    `determination_due_date` to the calendar date of
    `completeness_established_at` plus 21 days."

    Design: Corner/validations/a_second_open_application_is_refused_until_the_first_is_determined
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Cato Rivers",
        date_of_birth="1974-04-14",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    answers = factories.functional_answers(max_walk_distance_meters=210)
    first = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"], application_type="NEW", functional_answers=answers
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    validate_error(
        api.create_application(
            factories.application_payload(
                rider["id"], application_type="NEW", functional_answers=answers
            ),
            CLERK_HEADERS,
        ),
        ERR_DUPLICATE_OPEN_APPLICATION,
        409,
    )

    submitted = validate_success(
        api.submit_application(first["id"], factories.submit_payload(), CLERK_HEADERS)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["determination_due_date"] == "2026-08-22"
    assert submitted["completeness_established_at"] == "2026-08-01T00:00:00.000Z"

    validate_error(
        api.create_application(
            factories.application_payload(
                rider["id"],
                application_type="RECERTIFICATION",
                functional_answers=answers,
            ),
            CLERK_HEADERS,
        ),
        ERR_DUPLICATE_OPEN_APPLICATION,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_applications(CLERK_HEADERS, params={"applicant_id": rider["id"]})
    )
    assert meta["total_count"] == 1


def test_a_trip_may_be_reported_on_its_own_day_but_never_a_day_early(api):
    """The future bound is on the calendar date, so same-day reporting is legal.

    "History may be backfilled but the future may not be anticipated: a
    `trip_date` later than today's date is refused with `ERR_TRIP_DATE_FUTURE`
    (422)."

    "The event is stored with `recorded_at` stamped from the logical clock,
    `excused` false, `excuse_reason` null, and `points_assessed` set to 2 for an
    unexcused `NO_SHOW`, 1 for an unexcused `LATE_CANCEL`, and 0 for every other
    event type."

    Design: Corner/validations/trip_event_date_may_not_be_later_than_the_logical_clock_date
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Delia Marsh",
        date_of_birth="1979-09-29",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )

    validate_error(
        api.create_trip_event(
            factories.trip_event_payload(
                rider["id"], trip_date="2026-08-02", event_type="NO_SHOW"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_TRIP_DATE_FUTURE,
        422,
    )
    _rejected, rejected_meta = validate_paginated(
        api.list_trip_events(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert rejected_meta["total_count"] == 0

    accepted = ingest_trip_event(
        api, rider["id"], trip_date="2026-08-01", event_type="NO_SHOW"
    )
    assert accepted["points_assessed"] == 2
    assert accepted["excused"] is False

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert_conduct_mirrors(
        rider, event_basis=2, miss_count=1, scheduled_count=1, ratio_pct=100.0
    )

    _events, event_meta = validate_paginated(
        api.list_trip_events(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert event_meta["total_count"] == 1

    _proceedings, proceeding_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert proceeding_meta["total_count"] == 0


def test_a_capacity_one_slot_takes_one_assessment_and_sends_the_next_elsewhere(api):
    """Each request is legal alone; the collective breaches the slot's capacity.

    "The chosen slot must be `OPEN` — a slot at capacity is `ERR_SLOT_FULL`
    (409) — and must start strictly after the current instant, else
    `ERR_SLOT_IN_PAST` (422)."

    "it increments the slot's `booked_count` by one and flips the slot's `status`
    to `FULL` when `booked_count` reaches `capacity`; and it increments the
    packet's `version`."

    Design: Corner/validations/a_capacity_one_slot_rejects_the_second_assessment_booking
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    first_rider = create_applicant(
        api,
        full_name="Emil Sorensen",
        date_of_birth="1966-06-06",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    second_rider = create_applicant(
        api,
        full_name="Fern Whitlock",
        date_of_birth="1970-10-30",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    first = assessment_required(
        api,
        applicant=first_rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=190),
        claimed_conditions=["angina"],
    )
    second = assessment_required(
        api,
        applicant=second_rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=240),
        claimed_conditions=["vertigo"],
    )

    small_slot = create_slot(
        api,
        site_name="West Annex",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=1,
        site_is_wheelchair_accessible=True,
    )
    alternate_slot = create_slot(
        api,
        site_name="West Annex",
        evaluator_user_id="eval-2",
        starts_at="2026-08-06T09:00:00Z",
        ends_at="2026-08-06T10:00:00Z",
        capacity=1,
        site_is_wheelchair_accessible=True,
    )

    validate_success(
        api.book_assessment(
            first["application"]["id"],
            factories.assessment_booking_payload(
                small_slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert_slot_mirror(
        validate_success(api.get_assessment_slot(small_slot["id"], CLERK_HEADERS)),
        booked_count=1,
        status="FULL",
    )

    validate_error(
        api.book_assessment(
            second["application"]["id"],
            factories.assessment_booking_payload(
                small_slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        ERR_SLOT_FULL,
        409,
    )
    refused_packet = validate_success(
        api.get_application(second["application"]["id"], CLERK_HEADERS)
    )
    assert refused_packet["status"] == "ASSESSMENT_REQUIRED"
    assert_slot_mirror(
        validate_success(api.get_assessment_slot(small_slot["id"], CLERK_HEADERS)),
        booked_count=1,
        status="FULL",
    )

    retried = validate_success(
        api.book_assessment(
            second["application"]["id"],
            factories.assessment_booking_payload(
                alternate_slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert retried["attendance_status"] == "SCHEDULED"
    rebooked_packet = validate_success(
        api.get_application(second["application"]["id"], CLERK_HEADERS)
    )
    assert rebooked_packet["status"] == "ASSESSMENT_SCHEDULED"

    _assessments, meta = validate_paginated(
        api.list_assessments(CLERK_HEADERS, params={"slot_id": small_slot["id"]})
    )
    assert meta["total_count"] == 1


def test_the_same_inaccessible_site_refuses_only_the_wheelchair_booking(api):
    """The accessibility guard reads the request flag, not the rider's aid.

    "When `requires_wheelchair_position` is true the chosen slot must have
    `site_is_wheelchair_accessible` true, else `ERR_SITE_NOT_ACCESSIBLE` (422)."

    Design: Corner/validations/a_wheelchair_assessment_requires_a_wheelchair_accessible_site
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Gus Ferreira",
        date_of_birth="1959-05-19",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="POWER_WHEELCHAIR",
    )
    context = assessment_required(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=40),
        claimed_conditions=["paraplegia"],
    )
    slot = create_slot(
        api,
        site_name="Old Garage Office",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=2,
        site_is_wheelchair_accessible=False,
    )

    validate_error(
        api.book_assessment(
            context["application"]["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=True
            ),
            CLERK_HEADERS,
        ),
        ERR_SITE_NOT_ACCESSIBLE,
        422,
    )
    assert_slot_mirror(
        validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS)),
        booked_count=0,
        status="OPEN",
    )

    booked = validate_success(
        api.book_assessment(
            context["application"]["id"],
            factories.assessment_booking_payload(
                slot["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert booked["requires_wheelchair_position"] is False
    assert booked["attendance_status"] == "SCHEDULED"

    assert_slot_mirror(
        validate_success(api.get_assessment_slot(slot["id"], CLERK_HEADERS)),
        booked_count=1,
        status="OPEN",
    )
    packet = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert packet["status"] == "ASSESSMENT_SCHEDULED"


def test_the_sign_off_gate_answers_before_the_category_condition_coupling(api):
    """State preconditions run at stage 11, the coupling only at stage 13.

    "**State preconditions.** The addressed record is in a status from which the
    requested transition is declared, yielding the 409 family described alongside
    each workflow in §3."

    "Only an `EligibilitySpecialist` may draft a determination, and only against a
    packet that has reached `ASSESSMENT_COMPLETE`; drafting against a packet in any
    other status is `ERR_INVALID_APPLICATION_STATE` (409)."

    "a `CONDITIONAL` draft must carry at least one `trip_conditions` entry, else
    `ERR_CONDITIONAL_REQUIRES_CONDITIONS` (422); and an `UNCONDITIONAL` or
    `INELIGIBLE` draft must carry either no `trip_conditions` key at all or an
    empty array, else `ERR_UNCONDITIONAL_FORBIDS_CONDITIONS` (422)."

    Design: Corner/validations/determination_draft_checks_signoff_before_the_category_condition_rules
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Hedda Lindgren",
        date_of_birth="1964-04-24",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = scored_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True, max_walk_distance_meters=350
        ),
        claimed_conditions=["rheumatoid arthritis"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
        score_overrides={
            "board_alight_score": 2,
            "wayfinding_score": 3,
            "distance_meters_walked": 350,
            "heat_sensitivity_flag": True,
        },
    )
    application_id = context["application"]["id"]
    assessment_id = context["assessment"]["id"]
    assert context["assessment"]["scoring_status"] == "SCORED"

    before = validate_success(api.get_application(application_id, CLERK_HEADERS))
    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                before["version"],
                category="CONDITIONAL",
                effective_date="2026-08-06",
                rationale="heat sensitive",
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    signed = validate_success(
        api.sign_off_assessment(
            assessment_id, factories.sign_off_payload(), SPECIALIST_2_HEADERS
        )
    )
    assert signed["scoring_status"] == "SIGNED_OFF"
    after = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert after["status"] == "ASSESSMENT_COMPLETE"

    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                after["version"],
                category="CONDITIONAL",
                effective_date="2026-08-06",
                rationale="heat sensitive",
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_CONDITIONAL_REQUIRES_CONDITIONS,
        422,
    )
    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                after["version"],
                category="UNCONDITIONAL",
                effective_date="2026-08-06",
                rationale="full eligibility",
                trip_conditions=[
                    factories.boolean_trip_condition_payload(
                        "PRECIPITATION", note="rain only"
                    )
                ],
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_UNCONDITIONAL_FORBIDS_CONDITIONS,
        422,
    )

    _determinations, meta = validate_paginated(
        api.list_determinations(
            SPECIALIST_HEADERS, params={"application_id": application_id}
        )
    )
    assert meta["total_count"] == 0
    unchanged = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert unchanged["status"] == "ASSESSMENT_COMPLETE"


def test_four_appeal_guards_fire_where_the_screening_order_puts_them(api):
    """Reviewer independence, assignment authorization, the hearing flag, pairing.

    "the `reviewer_user_id` being assigned must differ both from the contested
    determination's `determined_by_user_id` and from the `scored_by_user_id` of
    the assessment that produced the scores, and a violation of either comparison
    is `ERR_REVIEWER_NOT_INDEPENDENT` (HTTP 422)."

    "**Assigned-reviewer authorization.** On opening a review and on recording an
    appeal decision, the actor is the appeal's assigned reviewer, else
    `ERR_NOT_ASSIGNED_REVIEWER` (403)."

    "On the **hearing branch**, where `request_hearing` is true, the reviewer must
    supply `hearing_at`; omitting it is `ERR_HEARING_REQUIRED` (422)."

    "`OVERTURNED` and `MODIFIED` both require a non-null `granted_category` of
    `UNCONDITIONAL`, `CONDITIONAL` or `TEMPORARY`, while `UPHELD` requires
    `granted_category` to be null. Any mismatch is
    `ERR_GRANTED_CATEGORY_MISMATCH` (422)."

    Design: Corner/validations/appeal_reviewer_independence_hearing_flag_and_outcome_pairing_guards
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ilse Vogel",
        date_of_birth="1957-07-17",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = issued_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=110),
        claimed_conditions=["degenerative disc disease"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 2,
            "distance_meters_walked": 110,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board fixed-route steps",
        },
    )
    determination_id = context["determination"]["id"]
    rider_headers = make_applicant_headers(rider["id"])

    first_appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(
                determination_id, grounds="term length disputed", request_hearing=True
            ),
            rider_headers,
        ),
        201,
    )

    validate_error(
        api.assign_appeal_reviewer(
            first_appeal["id"], factories.assign_reviewer_payload("spec-1"), ADMIN_HEADERS
        ),
        ERR_REVIEWER_NOT_INDEPENDENT,
        422,
    )
    validate_error(
        api.assign_appeal_reviewer(
            first_appeal["id"], factories.assign_reviewer_payload("eval-1"), ADMIN_HEADERS
        ),
        ERR_REVIEWER_NOT_INDEPENDENT,
        422,
    )
    assigned = validate_success(
        api.assign_appeal_reviewer(
            first_appeal["id"], factories.assign_reviewer_payload("rev-1"), ADMIN_HEADERS
        )
    )
    assert assigned["reviewer_user_id"] == "rev-1"
    assert assigned["status"] == "REVIEWER_ASSIGNED"

    validate_error(
        api.open_appeal_hearing(
            first_appeal["id"], factories.paper_hearing_payload(), REVIEWER_HEADERS
        ),
        ERR_HEARING_REQUIRED,
        422,
    )
    validate_error(
        api.open_appeal_hearing(
            first_appeal["id"], factories.paper_hearing_payload(), REVIEWER_2_HEADERS
        ),
        ERR_NOT_ASSIGNED_REVIEWER,
        403,
    )
    scheduled = validate_success(
        api.open_appeal_hearing(
            first_appeal["id"],
            factories.scheduled_hearing_payload("2026-08-10T10:00:00Z"),
            REVIEWER_HEADERS,
        )
    )
    assert scheduled["status"] == "HEARING_SCHEDULED"

    set_clock(api, "2026-08-10T10:00:00Z")
    sweep = run_day_close(api)
    assert_sweep_counters(sweep, appeals_heard_count=1, presumptive_granted_count=0)
    heard = validate_success(api.get_appeal(first_appeal["id"], ADMIN_HEADERS))
    assert heard["status"] == "HEARD"
    assert heard["heard_at"] == "2026-08-10T10:00:00.000Z"
    assert heard["decision_due_date"] == "2026-09-09"

    validate_error(
        api.decide_appeal(
            first_appeal["id"],
            factories.appeal_decision_payload(
                "UPHELD", granted_category="CONDITIONAL"
            ),
            REVIEWER_HEADERS,
        ),
        ERR_GRANTED_CATEGORY_MISMATCH,
        422,
    )
    validate_error(
        api.decide_appeal(
            first_appeal["id"],
            {
                "outcome": "OVERTURNED",
                "decision_note": "the record does not name a replacement category",
            },
            REVIEWER_HEADERS,
        ),
        ERR_GRANTED_CATEGORY_MISMATCH,
        422,
    )
    decided = validate_success(
        api.decide_appeal(
            first_appeal["id"],
            factories.appeal_decision_payload(
                "UPHELD", decision_note="record supports the original determination"
            ),
            REVIEWER_HEADERS,
        )
    )
    assert decided["status"] == "DECIDED"
    determination = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )
    assert determination["status"] == "ISSUED"
    assert determination["under_appeal"] is False

    second_appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(
                determination_id, grounds="new medical evidence", request_hearing=False
            ),
            rider_headers,
        ),
        201,
    )
    validate_success(
        api.assign_appeal_reviewer(
            second_appeal["id"], factories.assign_reviewer_payload("rev-2"), ADMIN_HEADERS
        )
    )
    validate_error(
        api.open_appeal_hearing(
            second_appeal["id"],
            factories.scheduled_hearing_payload("2026-08-20T10:00:00Z"),
            REVIEWER_2_HEADERS,
        ),
        ERR_HEARING_NOT_REQUESTED,
        422,
    )


def test_the_decide_ladder_answers_state_then_independence_then_conduct(api):
    """One under-supported proceeding walks the whole declared decide order.

    "Deciding a proceeding is a `ConductOfficer` action, and when several of its
    guards fail at once they are evaluated in this order. The proceeding must be
    in `RIDER_RESPONDED` or `RESPONSE_LAPSED`, else
    `ERR_PROCEEDING_STATE_INVALID` (409). The deciding `X-User-ID` must differ
    from `proposed_by_user_id`, else `ERR_DECIDER_NOT_INDEPENDENT` (422). Due
    process must be complete"

    "The response must arrive on or before `response_deadline_date`; a later one
    is `ERR_RESPONSE_WINDOW_CLOSED` (422)."

    "A `ConductOfficer` or an `AccessibilityOfficeAdmin` may rescind a proceeding
    in `UPHELD_PENDING` or `ACTIVE`, moving it to `VOID`; from any other status it
    is `ERR_PROCEEDING_STATE_INVALID` (409)."

    Design: Corner/validations/suspension_decide_guards_fire_in_declared_priority_order
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Jules Amadi",
        date_of_birth="1986-06-26",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_events(
        api,
        rider["id"],
        [("2026-07-10", "NO_SHOW"), ("2026-07-17", "NO_SHOW")],
    )
    scored = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert scored["no_show_points_event_basis"] == 4

    proceeding = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                scored["version"],
                review_window_end_date="2026-08-01",
                grounds_note="pattern of missed trips",
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )
    proceeding_id = proceeding["id"]

    set_clock(api, "2026-08-05T00:00:00Z")
    noticed = validate_success(
        api.send_suspension_notice(
            proceeding_id, factories.send_notice_payload(), CONDUCT_OFFICER_HEADERS
        )
    )
    assert noticed["response_deadline_date"] == "2026-08-19"

    validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )

    set_clock(api, "2026-08-20T00:00:00Z")
    validate_error(
        api.respond_to_suspension(
            proceeding_id,
            factories.rider_response_payload(rider_response_note="late reply"),
            make_applicant_headers(rider["id"]),
        ),
        ERR_RESPONSE_WINDOW_CLOSED,
        422,
    )
    still_noticed = validate_success(
        api.get_suspension_proceeding(proceeding_id, CONDUCT_OFFICER_HEADERS)
    )
    assert still_noticed["status"] == "NOTICE_SENT"

    set_clock(api, "2026-08-19T00:00:00Z")
    responded = validate_success(
        api.respond_to_suspension(
            proceeding_id,
            factories.rider_response_payload(
                rider_response_note="on the last permitted day"
            ),
            make_applicant_headers(rider["id"]),
        )
    )
    assert responded["status"] == "RIDER_RESPONDED"
    assert responded["rider_response_at"] == "2026-08-19T00:00:00.000Z"

    validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        ERR_DECIDER_NOT_INDEPENDENT,
        422,
    )
    validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-08-18"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_SUSPENSION_UNSUPPORTED,
        422,
    )
    validate_error(
        api.decide_suspension(
            proceeding_id,
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_SUSPENSION_UNSUPPORTED,
        422,
    )
    validate_error(
        api.rescind_suspension(
            proceeding_id, factories.rescind_payload(), CONDUCT_OFFICER_2_HEADERS
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )

    final = validate_success(
        api.get_suspension_proceeding(proceeding_id, CONDUCT_OFFICER_HEADERS)
    )
    assert final["status"] == "RIDER_RESPONDED"
    assert final["decision"] is None
    assert final["duration_days"] == 0
    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["service_status"] == "ACTIVE"
    assert reread["prior_upheld_suspension_count"] == 0


def test_the_referral_state_guard_outranks_its_own_response_deadline(api):
    """Completing a REFERRED referral is a 409 whatever the date says.

    "The referral is created in `REFERRED`, with `referral_response_deadline_date`
    set to the calendar date of `created_at` plus 14 days, and with
    `fixed_route_competency_score`, `completed_at` and `withdrawal_reason` all
    null."

    "Completion is a `TravelTrainer` action on a referral in `ENROLLED`;
    attempting it on any other status is `ERR_REFERRAL_STATE_INVALID` (409)."

    "The referral must still be in `REFERRED`; a response to a referral already
    resolved is `ERR_REFERRAL_STATE_INVALID` (409). The response must arrive on or
    before `referral_response_deadline_date`; a later response is
    `ERR_RESPONSE_WINDOW_CLOSED` (422). A decision of `ENROLLED` moves the
    referral `REFERRED → ENROLLED`"

    Design: Corner/validations/referral_state_guard_precedes_the_referral_response_window
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Kira Lindqvist",
        date_of_birth="1981-01-21",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = auto_referral(
        api,
        applicant=rider,
        conditions=[
            factories.boolean_trip_condition_payload(
                "COGNITIVE_UNFAMILIAR_ROUTE", note="unfamiliar routes only"
            )
        ],
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=450,
            uses_mobility_aid_outdoors=False,
            has_cognitive_impairment=True,
        ),
        claimed_conditions=["traumatic brain injury"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
        score_overrides={
            "board_alight_score": 4,
            "wayfinding_score": 2,
            "distance_meters_walked": 450,
            "heat_sensitivity_flag": False,
        },
    )
    referral = context["referral"]
    determination_id = context["determination"]["id"]
    rider_headers = make_applicant_headers(rider["id"])

    assert referral["status"] == "REFERRED"
    assert referral["referral_response_deadline_date"] == "2026-08-19"
    assert referral["fixed_route_competency_score"] is None
    assert referral["completed_at"] is None

    validate_error(
        api.complete_referral(
            referral["id"],
            factories.referral_completion_payload(fixed_route_competency_score=90),
            TRAINER_HEADERS,
        ),
        ERR_REFERRAL_STATE_INVALID,
        409,
    )

    set_clock(api, "2026-08-20T00:00:00Z")
    validate_error(
        api.respond_to_referral(
            referral["id"], factories.referral_response_payload("ENROLLED"), rider_headers
        ),
        ERR_RESPONSE_WINDOW_CLOSED,
        422,
    )
    still_referred = validate_success(
        api.get_travel_training_referral(referral["id"], TRAINER_HEADERS)
    )
    assert still_referred["status"] == "REFERRED"

    set_clock(api, "2026-08-19T00:00:00Z")
    declined = validate_success(
        api.respond_to_referral(
            referral["id"], factories.referral_response_payload("DECLINED"), rider_headers
        )
    )
    assert declined["status"] == "DECLINED"

    validate_error(
        api.respond_to_referral(
            referral["id"], factories.referral_response_payload("ENROLLED"), rider_headers
        ),
        ERR_REFERRAL_STATE_INVALID,
        409,
    )

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["fixed_route_competency_confirmed"] is False
    determination = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )
    assert determination["fixed_route_competency_confirmed"] is False


def test_an_out_of_service_vehicle_answers_before_its_missing_securement(api):
    """One vehicle breaks both rules; the first rule in the list wins.

    "Four rules guard a reservation, and when more than one is violated they are
    evaluated in this order. First, the chosen vehicle must be `IN_SERVICE`; a
    vehicle marked `OUT_OF_SERVICE` is refused with `ERR_VEHICLE_OUT_OF_SERVICE`
    (409). Second, a ride that needs a securement position requires the vehicle to
    have at least one `wheelchair_positions`, else `ERR_VEHICLE_NOT_ACCESSIBLE`
    (422)."

    "Fourth, the ride must actually get the rider there in time:
    `pickup_window_end` must fall at or before the assessment slot's `starts_at`,
    and a later window is refused with `ERR_PICKUP_WINDOW_LATE` (422)."

    Design: Corner/validations/an_out_of_service_vehicle_is_refused_before_the_accessibility_check
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Lars Mbeki",
        date_of_birth="1960-11-10",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="MANUAL_WHEELCHAIR",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=30),
        claimed_conditions=["spina bifida"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
        booking_overrides={"requires_wheelchair_position": True},
    )
    assessment_id = context["assessment"]["id"]

    out_of_service = create_vehicle(
        api,
        vehicle_number="V-8001",
        wheelchair_positions=0,
        ambulatory_seats=6,
        status="OUT_OF_SERVICE",
    )
    no_securement = create_vehicle(
        api,
        vehicle_number="V-8002",
        wheelchair_positions=0,
        ambulatory_seats=6,
        status="IN_SERVICE",
    )
    accessible = create_vehicle(
        api,
        vehicle_number="V-8003",
        wheelchair_positions=1,
        ambulatory_seats=4,
        status="IN_SERVICE",
    )

    def ride(vehicle_id):
        return factories.transportation_booking_payload(
            assessment_id,
            vehicle_id,
            pickup_window_start="2026-08-05T08:00:00Z",
            pickup_window_end="2026-08-05T09:00:00Z",
            requires_wheelchair_position=True,
        )

    validate_error(
        api.create_transportation_booking(ride(out_of_service["id"]), CLERK_HEADERS),
        ERR_VEHICLE_OUT_OF_SERVICE,
        409,
    )
    validate_error(
        api.create_transportation_booking(ride(no_securement["id"]), CLERK_HEADERS),
        ERR_VEHICLE_NOT_ACCESSIBLE,
        422,
    )
    booking = validate_success(
        api.create_transportation_booking(ride(accessible["id"]), CLERK_HEADERS), 201
    )
    assert booking["status"] == "RESERVED"
    assert booking["pickup_window_end"] == "2026-08-05T09:00:00.000Z"

    assert_vehicle_counters(
        validate_success(api.get_vehicle(accessible["id"], ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )
    assert_vehicle_counters(
        validate_success(api.get_vehicle(out_of_service["id"], ADMIN_HEADERS)),
        wheelchair=0,
        ambulatory=0,
    )
    assert_vehicle_counters(
        validate_success(api.get_vehicle(no_securement["id"], ADMIN_HEADERS)),
        wheelchair=0,
        ambulatory=0,
    )

    _bookings, meta = validate_paginated(
        api.list_transportation_bookings(
            CLERK_HEADERS, params={"assessment_id": assessment_id}
        )
    )
    assert meta["total_count"] == 1


def test_out_of_range_scores_are_refused_before_the_scoring_edge_is_taken(api):
    """Request shape is stage 9, so the scoring transition never starts.

    "**Request shape.** All required fields present; every enum-typed field
    carrying one of its declared values; every numeric field inside its declared
    range (observed scores in 0 through 4, `distance_meters_walked` zero or
    greater, `threshold_value` zero or greater, `fixed_route_competency_score` in
    0 through 100); every instant a well-formed ISO 8601 UTC value; and every
    interval satisfying a start strictly earlier than its end. Failures are
    `ERR_INVALID_REQUEST` (400)."

    "Otherwise, if the lower of `board_alight_score` and `wayfinding_score` is at
    most 1, the recommendation is `UNCONDITIONAL`."

    Design: Corner/validations/out_of_range_scores_are_rejected_before_the_scoring_transition_runs
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Miriam Adeyemi",
        date_of_birth="1972-02-12",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = attended_assessment(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=200,
        ),
        claimed_conditions=["peripheral neuropathy"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
    )
    assessment_id = context["assessment"]["id"]

    for overrides in (
        {"board_alight_score": 5, "wayfinding_score": 2, "distance_meters_walked": 200},
        {"board_alight_score": 2, "wayfinding_score": -1, "distance_meters_walked": 200},
        {"board_alight_score": 2, "wayfinding_score": 2, "distance_meters_walked": -5},
    ):
        validate_error(
            api.record_scores(
                assessment_id,
                factories.scores_payload(heat_sensitivity_flag=False, **overrides),
                EVALUATOR_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

    untouched = validate_success(api.get_assessment(assessment_id, EVALUATOR_HEADERS))
    assert untouched["scoring_status"] == "NOT_STARTED"
    assert untouched["scored_by_user_id"] is None

    scored = validate_success(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=4,
                wayfinding_score=0,
                distance_meters_walked=0,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert scored["scoring_status"] == "SCORED"
    assert scored["recommended_category"] == "UNCONDITIONAL"
    assert scored["recommended_term_days"] == 1825


def test_visitor_service_needs_both_clauses_and_answers_each_miss_alike(api):
    """A conjunction, so either single-clause failure carries the same code.

    "The rider must genuinely be a visitor: their `residence_zone` must be
    `OUT_OF_SERVICE_AREA` and `home_agency_certification_provided` must be true,
    else the request is refused with `ERR_NOT_OUT_OF_AREA` (422)."

    "A new visitor record starts in `ACTIVE` with an empty `service_dates` list,
    `days_used_365` at 0 and `days_remaining_365` at 21."

    Design: Corner/validations/visitor_eligibility_requires_both_out_of_area_residence_and_certification
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    visitor = create_out_of_area_applicant(
        api,
        full_name="Noor Haddad",
        date_of_birth="1969-09-19",
        mobility_aid="POWER_WHEELCHAIR",
        home_agency_name="Northport Transit",
    )
    local_rider = create_applicant(
        api,
        full_name="Otto Brenner",
        date_of_birth="1974-04-04",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )

    validate_error(
        api.create_visitor_eligibility(
            visitor["id"],
            factories.visitor_eligibility_payload(
                home_agency_name="Northport Transit",
                home_agency_certification_provided=False,
                visit_start_date="2026-08-01",
            ),
            CLERK_HEADERS,
        ),
        ERR_NOT_OUT_OF_AREA,
        422,
    )
    validate_error(
        api.create_visitor_eligibility(
            local_rider["id"],
            factories.visitor_eligibility_payload(
                home_agency_name="Northport Transit",
                home_agency_certification_provided=True,
                visit_start_date="2026-08-01",
            ),
            CLERK_HEADERS,
        ),
        ERR_NOT_OUT_OF_AREA,
        422,
    )

    record = validate_success(
        api.create_visitor_eligibility(
            visitor["id"],
            factories.visitor_eligibility_payload(
                home_agency_name="Northport Transit",
                home_agency_certification_provided=True,
                visit_start_date="2026-08-01",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert record["status"] == "ACTIVE"
    assert record["days_used_365"] == 0
    assert record["days_remaining_365"] == 21
    assert record["service_dates"] == []

    _records, local_meta = validate_paginated(
        api.list_visitor_eligibilities(local_rider["id"], CLERK_HEADERS)
    )
    assert local_meta["total_count"] == 0
    _visitor_records, visitor_meta = validate_paginated(
        api.list_visitor_eligibilities(visitor["id"], CLERK_HEADERS)
    )
    assert visitor_meta["total_count"] == 1


def test_one_error_answers_four_premature_or_replayed_packet_transitions(api):
    """The application state rule is declared over five endpoints at once.

    "When an `IntakeClerk` reviews a submitted packet and finds it deficient, the
    packet goes from `SUBMITTED` to `RETURNED_INCOMPLETE`."

    "Once a packet is `SUBMITTED`, an `IntakeClerk` asks a licensed professional to
    verify the claimed functional limitations, which moves the packet from
    `SUBMITTED` to `PENDING_VERIFICATION` and creates a verification record."

    "Only an `EligibilitySpecialist` may draft a determination, and only against a
    packet that has reached `ASSESSMENT_COMPLETE`; drafting against a packet in any
    other status is `ERR_INVALID_APPLICATION_STATE` (409)."

    "Attempting to submit from a status that has no declared submit edge — from
    `PENDING_VERIFICATION`, say, or from the terminal `DETERMINED` — is
    `ERR_INVALID_APPLICATION_STATE` (409)."

    "`resubmission_count` increases by one on this edge and only on this edge, so
    it reads as the number of completed return-and-resubmit cycles, and
    `missing_items` is cleared."

    Design: Corner/validations/application_transition_replays_are_refused_by_the_application_state_rule
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Pilar Fonseca",
        date_of_birth="1955-05-15",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = draft_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True, max_walk_distance_meters=90
        ),
    )
    application_id = context["application"]["id"]

    validate_error(
        api.return_application_incomplete(
            application_id,
            factories.return_incomplete_payload(missing_items=["provider signature"]),
            CLERK_HEADERS,
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )
    validate_error(
        api.request_verification(
            application_id,
            factories.verification_request_payload(
                provider_name="Dr. L Sorensen",
                provider_type="PHYSICIAN",
                provider_license_number="MD-90023",
            ),
            CLERK_HEADERS,
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    draft_state = validate_success(api.get_application(application_id, CLERK_HEADERS))
    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                draft_state["version"],
                category="UNCONDITIONAL",
                effective_date="2026-08-06",
                rationale="premature",
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    submitted = validate_success(
        api.submit_application(
            application_id, factories.submit_payload(), CLERK_HEADERS
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["determination_due_date"] == "2026-08-22"

    validate_error(
        api.submit_application(
            application_id, factories.submit_payload(), CLERK_HEADERS
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    returned = validate_success(
        api.return_application_incomplete(
            application_id,
            factories.return_incomplete_payload(
                missing_items=["provider signature", "photo id"]
            ),
            CLERK_HEADERS,
        )
    )
    assert returned["status"] == "RETURNED_INCOMPLETE"
    assert returned["determination_due_date"] is None

    resubmitted = validate_success(
        api.submit_application(
            application_id, factories.submit_payload(), CLERK_HEADERS
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["missing_items"] == []


def test_a_second_issue_and_a_second_draft_return_two_different_codes(api):
    """One keys on the determination's own status, the other on the parent packet.

    "The determination must still be in `DRAFT`, and no other determination of the
    same packet may already be `ISSUED`; either violation is
    `ERR_DETERMINATION_ALREADY_ISSUED` (409)."

    "Only an `EligibilitySpecialist` may draft a determination, and only against a
    packet that has reached `ASSESSMENT_COMPLETE`; drafting against a packet in any
    other status is `ERR_INVALID_APPLICATION_STATE` (409)."

    "It advances the parent packet to the terminal `DETERMINED` and increments its
    `version`, freezing `days_pending_statutory` and `days_pending_net_agency` at
    the values they held at issuance."

    Design: Corner/validations/a_second_issue_and_a_second_draft_split_into_two_different_errors
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Quentin Ruiz",
        date_of_birth="1963-03-23",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = issued_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=120),
        claimed_conditions=["rheumatoid arthritis"],
        slot=create_slot(api, capacity=2, site_is_wheelchair_accessible=True),
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 1,
            "distance_meters_walked": 120,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board steps",
        },
    )
    determination_id = context["determination"]["id"]
    application_id = context["application"]["id"]
    assert context["determination"]["status"] == "ISSUED"
    assert context["application"]["status"] == "DETERMINED"

    validate_error(
        api.issue_determination(
            determination_id, factories.issue_payload(), SPECIALIST_HEADERS
        ),
        ERR_DETERMINATION_ALREADY_ISSUED,
        409,
    )

    determined = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert determined["status"] == "DETERMINED"
    validate_error(
        api.draft_determination(
            application_id,
            factories.determination_draft_payload(
                determined["version"],
                category="CONDITIONAL",
                effective_date="2026-08-07",
                rationale="second bite",
                trip_conditions=[factories.trip_condition_payload()],
            ),
            SPECIALIST_HEADERS,
        ),
        ERR_INVALID_APPLICATION_STATE,
        409,
    )

    _determinations, meta = validate_paginated(
        api.list_determinations(
            SPECIALIST_HEADERS, params={"application_id": application_id}
        )
    )
    assert meta["total_count"] == 1
    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["active_determination_id"] == determination_id
