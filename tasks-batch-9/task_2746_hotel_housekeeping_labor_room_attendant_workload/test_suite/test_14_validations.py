"""The validation ladder: priority ordering, conditional gates, aggregates and budgets."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    ASSIGN_COMPLETED,
    ASSIGN_IN_PROGRESS,
    CLEAN_IN_SERVICE,
    COMPLIANCE_COMPLIANT,
    DEFAULT_CLOCK,
    DIRECTOR_HEADERS,
    ENROLLMENT_ACTIVE,
    FORECAST_PUBLISHED,
    FRONT_DESK_HEADERS,
    LAUNDRY_LEAD_HEADERS,
    NON_EXISTENT_UUID,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_STAYOVER,
    OCCUPANCY_VACANT,
    ORDINANCE_NONE,
    ORDINANCE_SQFT_CAP_2200,
    PROGRAM_EVERY_OTHER_DAY,
    PROGRAM_OPT_OUT,
    ROSTER_CLOCKED_IN,
    ROSTER_CLOSED,
    ROSTER_PLANNED,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    SERVICE_STAYOVER,
    SHORTAGE_OK,
    WAIVER_NONE,
    WAIVER_REQUESTED,
    ApiErrorId,
    assert_credits,
    assert_is_null,
    assert_linen_buckets,
    assert_roster_totals,
    assert_whole_minutes,
    build_enrollment,
    build_scenario,
    complete_payload,
    dispatch_cycle,
    enrollment_payload,
    headers_no_identity,
    laundry_cycle_payload,
    make_room_attendant_headers,
    make_supervisor_headers,
    read_assignment,
    read_day,
    read_enrollment,
    read_linen_item,
    read_property,
    read_room,
    read_roster,
    request_waiver,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_request_payload,
)

ONE_DEPARTURE_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}


# --------------------------------------------------------------------------
# The head of the ladder
# --------------------------------------------------------------------------


def test_a_request_without_identity_headers_is_unauthenticated(api):
    """An empty body never surfaces, because the missing identity is refused first.

    PRD 2.10: "**First**, header presence: both `X-User-ID` and `X-User-Role`
    must be present and non-empty, or `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/v_missing_identity_headers_are_unauthenticated
    """
    set_clock(api, DEFAULT_CLOCK)

    response = api.create_property({}, headers_no_identity())

    error = validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)
    assert error["error_id"] != "ERR_INVALID_REQUEST", (
        "the empty body must not be reported before the missing identity"
    )
    validate_error(
        api.get_property(NON_EXISTENT_UUID, headers_no_identity()),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )


def test_a_forbidden_role_outranks_the_empty_body(api):
    """A room attendant posting an empty property body is refused on the role, not the body.

    PRD 2.10: "**Third**, role permission: the recognised role must appear in the
    target operation's authorised list, or `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/validations/v_role_denial_outranks_the_invalid_body_and_is_rejected
    """
    set_clock(api, DEFAULT_CLOCK)

    response = api.create_property({}, make_room_attendant_headers(NON_EXISTENT_UUID))

    error = validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    assert error["error_id"] != "ERR_INVALID_REQUEST", (
        "priority 3 is evaluated before priority 4, so the body shape never reports"
    )
    assert error["message"], "the error envelope must carry a human-readable message"


# --------------------------------------------------------------------------
# Every gate satisfied at once
# --------------------------------------------------------------------------


def test_a_deep_clean_that_satisfies_every_gate_is_created(api):
    """A vacant room, an unrestricted attendant, healthy linen and ample headroom pass.

    PRD 3.4: "Once the request's references resolve, its scope coheres and its
    `expected_roster_version` matches, the assignment passes through eight domain
    gates that are evaluated in a strictly pinned order."

    Design: Corner/validations/v_deep_clean_create_passes_every_gate_when_all_conditions_hold
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "103", "occupancy_state": OCCUPANCY_VACANT}],
        linen={"total_owned_sets": 20},
        forecast={
            "forecast_occupied_rooms": 0,
            "forecast_arrivals": 0,
            "forecast_departures": 0,
            "planned_deep_clean_rooms": 1,
        },
        clocked_in=False,
    )
    assert read_linen_item(api, scenario.linen_id)["shortage_status"] == SHORTAGE_OK

    assignment = validate_success(
        scenario.assign_raw(
            "103", SERVICE_DEEP_CLEAN, headers=scenario.supervisor_headers()
        ),
        201,
    )

    assert assignment["status"] == ASSIGN_ASSIGNED
    assert_credits(assignment["credits"], 2.00, "credits")
    assert assignment["square_feet_snapshot"] == 420
    roster = read_roster(api, scenario.roster_id)
    assert_roster_totals(roster, 2.00, 420)
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_credits(roster["effective_credit_cap"], 16.00, "effective_credit_cap")
    assert roster["effective_sqft_cap"] == 2200


# --------------------------------------------------------------------------
# Guest-facing programme gates
# --------------------------------------------------------------------------


def test_a_stayover_on_an_opted_out_room_is_refused(api):
    """The same stayover request is taken on the daily room and refused on the opted-out one.

    PRD 3.4: "A room whose `service_program` is `OPT_OUT` accepts neither a
    `CHECKOUT` nor a `STAYOVER` assignment; the refusal is `ERR_SERVICE_OPTED_OUT`
    (HTTP 422)."

    Design: Corner/validations/v_stayover_on_an_opt_out_room_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[
            {
                "number": "102",
                "occupancy_state": OCCUPANCY_STAYOVER,
                "service_program": PROGRAM_OPT_OUT,
            },
            {"number": "104", "occupancy_state": OCCUPANCY_STAYOVER},
        ],
        forecast={
            "forecast_occupied_rooms": 2,
            "forecast_arrivals": 0,
            "forecast_departures": 0,
            "planned_deep_clean_rooms": 0,
        },
        clocked_in=False,
    )
    accepted = scenario.assign("104", SERVICE_STAYOVER)
    assert_credits(accepted["credits"], 0.50, "credits")

    response = scenario.assign_raw("102", SERVICE_STAYOVER)

    validate_error(response, ApiErrorId.SERVICE_OPTED_OUT, 422)
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        0.50,
        "assigned_credits",
    )
    _, meta = validate_paginated(
        api.list_room_assignments(
            {"room_id": scenario.room_id("102")}, DIRECTOR_HEADERS
        )
    )
    assert meta["total_count"] == 0, "the refused request must leave no assignment"


def test_an_alternating_day_room_serviced_yesterday_is_not_yet_due(api):
    """A one-day gap is short of the two the cadence demands, so the stayover is refused.

    PRD 3.4: "A room whose `service_program` is `EVERY_OTHER_DAY` accepts a
    `STAYOVER` assignment only when its `last_serviced_business_date` is null, or is
    at least two calendar days before the forecast day's `business_date`."

    Design: Corner/validations/v_every_other_day_room_serviced_yesterday_is_not_due
    """
    scenario = build_scenario(
        api,
        rooms=[
            {
                "number": "102",
                "occupancy_state": OCCUPANCY_STAYOVER,
                "service_program": PROGRAM_EVERY_OTHER_DAY,
                "last_serviced_business_date": "2026-08-02",
            }
        ],
        forecast={
            "forecast_occupied_rooms": 1,
            "forecast_arrivals": 0,
            "forecast_departures": 0,
            "planned_deep_clean_rooms": 0,
        },
        clocked_in=False,
    )
    version_before = read_roster(api, scenario.roster_id)["version"]

    response = scenario.assign_raw("102", SERVICE_STAYOVER)

    validate_error(response, ApiErrorId.SERVICE_NOT_DUE, 422)
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["assigned_credits"], 0.00, "assigned_credits")
    assert roster["version"] == version_before, (
        "a refused create must not move the roster version"
    )
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        0.00,
        "allocated_credits_total",
    )


def test_a_checkout_booked_on_a_stayover_room_is_an_occupancy_mismatch(api):
    """The room is perfectly serviceable; only the service type is wrong for its posture.

    PRD 3.4: "The `service_type` must match the room's `occupancy_state` under a
    pinned pairing: `CHECKOUT` requires `DUE_OUT`, `STAYOVER` requires `STAYOVER`,
    and `DEEP_CLEAN` requires `VACANT`."

    Design: Corner/validations/v_checkout_service_on_a_stayover_room_is_an_occupancy_mismatch
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "102", "occupancy_state": OCCUPANCY_STAYOVER}],
        forecast={
            "forecast_occupied_rooms": 1,
            "forecast_arrivals": 0,
            "forecast_departures": 0,
            "planned_deep_clean_rooms": 0,
        },
        clocked_in=False,
    )

    response = scenario.assign_raw("102", SERVICE_CHECKOUT)

    validate_error(response, ApiErrorId.OCCUPANCY_MISMATCH, 422)
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        0.00,
        "assigned_credits",
    )
    permitted = scenario.assign("102", SERVICE_STAYOVER)
    assert_credits(permitted["credits"], 0.50, "credits")


# --------------------------------------------------------------------------
# Eligibility read off the parent attendant
# --------------------------------------------------------------------------


def test_a_restricted_attendant_may_clean_but_never_deep_clean(api):
    """The very same attendant takes the departure clean and is barred from the deep clean.

    PRD 3.4: "An attendant whose `restricted_duty` flag is true may not be given a
    `DEEP_CLEAN` room under any circumstances, regardless of remaining credit
    headroom, and the refusal is `ERR_RESTRICTED_DUTY_INELIGIBLE` (HTTP 422)."

    Design: Corner/validations/v_restricted_duty_attendant_cannot_be_given_a_deep_clean
    """
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "103", "occupancy_state": OCCUPANCY_VACANT},
        ],
        linen={"total_owned_sets": 20},
        worker_overrides={"restricted_duty": True},
        forecast={
            "forecast_occupied_rooms": 1,
            "forecast_arrivals": 0,
            "forecast_departures": 1,
            "planned_deep_clean_rooms": 1,
        },
        clocked_in=False,
    )
    cleaning = scenario.assign("101", SERVICE_CHECKOUT)
    assert_credits(cleaning["credits"], 1.00, "credits")

    response = scenario.assign_raw("103", SERVICE_DEEP_CLEAN)

    validate_error(response, ApiErrorId.RESTRICTED_DUTY_INELIGIBLE, 422)
    roster = read_roster(api, scenario.roster_id)
    assert_credits(roster["effective_credit_cap"], 12.00, "effective_credit_cap")
    assert_credits(roster["assigned_credits"], 1.00, "assigned_credits")
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT


# --------------------------------------------------------------------------
# Stock depth versus plant capacity
# --------------------------------------------------------------------------


def test_a_batch_larger_than_the_soiled_queue_is_refused(api):
    """Eight sets cannot leave a queue of three, though three sets can.

    PRD 3.8: "A dispatch that would drive `soiled_queue` below zero is separately
    refused with `ERR_LINEN_STOCK_INSUFFICIENT`."

    Design: Corner/validations/v_dispatch_larger_than_the_soiled_queue_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=["101"],
        linen={"total_owned_sets": 20, "initial_soiled_sets": 3},
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )
    before = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(before, 17, 0, 3)

    response = api.create_laundry_cycle(
        laundry_cycle_payload(
            scenario.linen_id,
            8,
            "2026-08-03T08:00:00.000Z",
            "2026-08-03T12:00:00.000Z",
            before["version"],
        ),
        LAUNDRY_LEAD_HEADERS,
    )

    validate_error(response, ApiErrorId.LINEN_STOCK_INSUFFICIENT, 409)
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 17, 0, 3)
    assert line["version"] == before["version"], (
        "a refused dispatch must not move the linen line's version"
    )
    _, meta = validate_paginated(
        api.list_laundry_cycles(
            {"linen_item_id": scenario.linen_id}, LAUNDRY_LEAD_HEADERS
        )
    )
    assert meta["total_count"] == 0, "the refused dispatch must leave no cycle"
    permitted = dispatch_cycle(
        api,
        scenario.linen_id,
        3,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        line["version"],
    )
    assert permitted["batch_sets"] == 3, (
        "the refusal is about the queue depth, so three sets must be accepted"
    )


# --------------------------------------------------------------------------
# Settling the shift
# --------------------------------------------------------------------------


def test_break_minutes_beyond_worked_minutes_are_refused(api):
    """Two hundred worked minutes are plausible; two hundred and fifty of break are not.

    PRD 3.7: "And `break_minutes` must not exceed `worked_minutes`, or
    `ERR_BREAK_EXCEEDS_WORKED` (HTTP 422), so that productive time can never go
    negative."

    Design: Corner/validations/v_break_minutes_exceeding_worked_minutes_are_rejected
    """
    scenario = build_scenario(api, rooms=["101"], forecast=ONE_DEPARTURE_DAY)
    before = read_roster(api, scenario.roster_id)
    assert before["status"] == ROSTER_CLOCKED_IN

    response = scenario.close_roster_raw(200, 250)

    validate_error(response, ApiErrorId.BREAK_EXCEEDS_WORKED, 422)
    roster = read_roster(api, scenario.roster_id)
    assert roster["status"] == ROSTER_CLOCKED_IN
    assert roster["version"] == before["version"], (
        "a refused close must not move the roster version"
    )
    assert_is_null(roster["worked_minutes"], "worked_minutes")
    assert_is_null(roster["paid_minutes"], "paid_minutes")


def test_a_shift_with_a_room_still_being_cleaned_cannot_be_settled(api):
    """The in-progress room blocks the close, and the sampling obligation is not the reason.

    PRD 3.7: "No assignment on the roster may still be `IN_PROGRESS`, or the close
    is refused with `ERR_ASSIGNMENT_IN_PROGRESS` (HTTP 409) — a room being cleaned
    right now cannot be settled around."

    Design: Corner/validations/v_roster_close_with_an_in_progress_assignment_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
    )
    assignment = scenario.assign("101", SERVICE_CHECKOUT)
    scenario.start(assignment["id"], "2026-08-03T09:00:00.000Z")

    response = scenario.close_roster_raw(200, 20)

    validate_error(response, ApiErrorId.ASSIGNMENT_IN_PROGRESS, 409)
    roster = read_roster(api, scenario.roster_id)
    assert roster["status"] == ROSTER_CLOCKED_IN
    assert roster["required_inspection_samples"] == 0, (
        "nothing is COMPLETED, so the sampling obligation cannot be the blocker"
    )
    refused = read_assignment(api, assignment["id"])
    assert refused["status"] == ASSIGN_IN_PROGRESS, (
        f"the refused close must not sweep the room, got {refused['status']}"
    )


def test_a_shift_with_an_undischarged_sample_cannot_be_settled(api):
    """Finishing the one room raises the sampling duty that then blocks the settlement.

    PRD 3.7: "The sampling obligation must be discharged: `inspections_completed`
    must be at least `required_inspection_samples`, or the close is refused with
    `ERR_INSPECTION_SAMPLE_INCOMPLETE` (HTTP 409)."

    Design: Corner/validations/v_roster_close_with_an_outstanding_inspection_sample_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_DEPARTURE_DAY,
    )
    cleaned = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )
    assert cleaned["status"] == ASSIGN_COMPLETED
    pending = read_roster(api, scenario.roster_id)
    assert pending["required_inspection_samples"] == 1
    assert pending["inspections_completed"] == 0

    response = scenario.close_roster_raw(200, 20)

    validate_error(response, ApiErrorId.INSPECTION_SAMPLE_INCOMPLETE, 409)
    roster = read_roster(api, scenario.roster_id)
    assert roster["status"] == ROSTER_CLOCKED_IN
    assert_is_null(roster["total_labor_cost_cents"], "total_labor_cost_cents")
    scenario.inspect(cleaned["id"])
    settled = scenario.close_roster(200, 20)
    assert settled["status"] == ROSTER_CLOSED, (
        "once the sample is recorded the same close must succeed"
    )


def test_a_day_with_an_open_roster_cannot_be_closed(api):
    """One roster still in PLANNED is enough to hold the day's reconciliation open.

    PRD 3.2: "It is blocked while any roster of the day is still `PLANNED` or
    `CLOCKED_IN`: every roster of the day must have reached `CLOSED` first, or the
    close is refused with `ERR_ROSTER_STILL_OPEN`."

    Design: Corner/validations/v_forecast_close_with_an_open_roster_is_rejected
    """
    scenario = build_scenario(
        api, rooms=["101"], forecast=ONE_DEPARTURE_DAY, clocked_in=False
    )
    before = read_day(api, scenario.day_id)
    assert before["status"] == FORECAST_PUBLISHED

    response = api.close_forecast_day(scenario.day_id, DIRECTOR_HEADERS)

    validate_error(response, ApiErrorId.ROSTER_STILL_OPEN, 409)
    day = read_day(api, scenario.day_id)
    assert day["status"] == FORECAST_PUBLISHED
    assert day["version"] == before["version"], (
        "a refused close must not move the day's version"
    )
    assert_is_null(day["actual_reconciled_credits"], "actual_reconciled_credits")
    assert_is_null(day["credit_variance_pct"], "credit_variance_pct")
    assert read_roster(api, scenario.roster_id)["status"] == ROSTER_PLANNED


# --------------------------------------------------------------------------
# Temporal sanity
# --------------------------------------------------------------------------


def test_a_completion_that_does_not_advance_the_clock_is_refused(api):
    """A zero-length window is refused; a single millisecond of work is accepted.

    PRD 3.5: "The first is simple sanity: `completed_at` — supplied in the body, or
    defaulted from the logical clock — must be **strictly after** `started_at`, or
    the completion is refused with `ERR_INVALID_TIME_WINDOW` (HTTP 422)."

    Design: Corner/validations/v_completion_window_that_does_not_advance_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        linen={"total_owned_sets": 20},
        forecast=ONE_DEPARTURE_DAY,
    )
    assignment = scenario.assign("101", SERVICE_CHECKOUT)
    scenario.start(assignment["id"], "2026-08-03T09:00:00.000Z")

    response = api.complete_assignment(
        assignment["id"],
        complete_payload("2026-08-03T09:00:00.000Z"),
        scenario.attendant_headers(),
    )

    validate_error(response, ApiErrorId.INVALID_TIME_WINDOW, 422)
    refused = read_assignment(api, assignment["id"])
    assert refused["status"] == ASSIGN_IN_PROGRESS
    assert_is_null(refused["completed_at"], "completed_at")
    assert_is_null(refused["actual_minutes"], "actual_minutes")
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_IN_SERVICE
    )
    finished = validate_success(
        api.complete_assignment(
            assignment["id"],
            complete_payload("2026-08-03T09:00:00.001Z"),
            scenario.attendant_headers(),
        ),
        200,
    )
    assert finished["status"] == ASSIGN_COMPLETED
    assert_whole_minutes(finished["actual_minutes"], 0, "actual_minutes")


# --------------------------------------------------------------------------
# The statutory aggregate
# --------------------------------------------------------------------------


def test_the_sixth_room_breaches_the_square_footage_ordinance_in_aggregate(api):
    """No single room is oversized and the credit ceiling is untouched; the running total breaches.

    PRD 3.4: "Under `ordinance_profile` `SQFT_CAP_2200` only, the roster's
    `assigned_square_feet` including the incoming room must not exceed
    `effective_sqft_cap`."

    Design: Corner/validations/v_square_footage_ordinance_is_breached_only_by_the_aggregate_of_rooms
    """
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_SQFT_CAP_2200,
            "max_daily_square_feet": 2200,
            "max_daily_credits": 16.00,
        },
        rooms=[
            {"number": number, "occupancy_state": OCCUPANCY_DUE_OUT}
            for number in ("101", "102", "103", "104", "105", "106")
        ],
        forecast={
            "forecast_occupied_rooms": 6,
            "forecast_arrivals": 0,
            "forecast_departures": 6,
            "planned_deep_clean_rooms": 0,
        },
        clocked_in=False,
    )
    for number in ("101", "102", "103", "104", "105"):
        scenario.assign(number, SERVICE_CHECKOUT)
    filled = read_roster(api, scenario.roster_id)
    assert_roster_totals(filled, 5.00, 2100)
    assert filled["effective_sqft_cap"] == 2200
    assert_credits(filled["effective_credit_cap"], 16.00, "effective_credit_cap")

    response = scenario.assign_raw("106", SERVICE_CHECKOUT)

    validate_error(response, ApiErrorId.ORDINANCE_SQFT_EXCEEDED, 409)
    roster = read_roster(api, scenario.roster_id)
    assert_roster_totals(roster, 5.00, 2100)
    assert roster["compliance_state"] == COMPLIANCE_COMPLIANT
    _, meta = validate_paginated(
        api.list_room_assignments(
            {"roster_id": scenario.roster_id}, DIRECTOR_HEADERS
        )
    )
    assert meta["total_count"] == 5, (
        f"only the five lawful rooms may survive, got {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# The ordinance headroom on a waiver
# --------------------------------------------------------------------------


def test_a_waiver_above_the_ordinance_headroom_is_refused(api):
    """A 4.00-credit cap permits a request of exactly 5.00 and nothing beyond it.

    PRD 3.3: "The requested figure is then tested against the ordinance headroom:
    it must not exceed `effective_credit_cap` multiplied by the property's headroom
    factor, which is 1.25 under the `NONE` and `SQFT_CAP_2200` profiles and exactly
    1.00 — no headroom whatsoever — under `CREDIT_CAP_STRICT`."

    Design: Corner/validations/v_waiver_request_above_the_ordinance_ceiling_is_rejected
    """
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=["101"],
        forecast=ONE_DEPARTURE_DAY,
        clocked_in=False,
    )
    before = read_roster(api, scenario.roster_id)
    assert_credits(before["effective_credit_cap"], 4.00, "effective_credit_cap")
    assert before["waiver_state"] == WAIVER_NONE

    response = api.request_waiver(
        scenario.roster_id,
        waiver_request_payload(5.20),
        make_supervisor_headers(scenario.inspector_id),
    )

    validate_error(response, ApiErrorId.WAIVER_EXCEEDS_ORDINANCE_MAX, 422)
    roster = read_roster(api, scenario.roster_id)
    assert roster["waiver_state"] == WAIVER_NONE
    assert_is_null(roster["waiver_requested_credits"], "waiver_requested_credits")
    assert_is_null(roster["waiver_requested_by_user_id"], "waiver_requested_by_user_id")
    assert roster["version"] == before["version"], (
        "a refused filing must not move the roster version"
    )
    filed = request_waiver(api, scenario.roster_id, 5.00, scenario.inspector_id)
    assert filed["waiver_state"] == WAIVER_REQUESTED, (
        "exactly on the ordinance ceiling must be admitted"
    )


# --------------------------------------------------------------------------
# Guest enrolments
# --------------------------------------------------------------------------


def test_a_second_active_enrolment_on_the_same_room_is_refused(api):
    """The losing request neither files nor rewrites the room, and voiding clears the way.

    PRD 3.9: "A room may not hold two `ACTIVE` enrolments at once; a second is
    refused with `ERR_ENROLLMENT_ACTIVE_EXISTS` (HTTP 409)."

    Design: Corner/validations/v_second_active_enrollment_on_the_same_room_is_rejected
    """
    context = build_enrollment(api, program=PROGRAM_OPT_OUT, nights=2)
    room_id = context.room["id"]
    second = enrollment_payload(
        room_id, PROGRAM_EVERY_OTHER_DAY, 2, reservation_code="RSV-70002"
    )

    response = api.create_service_enrollment(second, FRONT_DESK_HEADERS)

    validate_error(response, ApiErrorId.ENROLLMENT_ACTIVE_EXISTS, 409)
    assert read_room(api, room_id)["service_program"] == PROGRAM_OPT_OUT, (
        "the refused enrolment must not rewrite the room's programme"
    )
    rows, meta = validate_paginated(
        api.list_service_enrollments({"room_id": room_id}, FRONT_DESK_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == context.enrollment_id
    context.void()
    admitted = validate_success(
        api.create_service_enrollment(second, FRONT_DESK_HEADERS), 201
    )
    assert admitted["status"] == ENROLLMENT_ACTIVE
    assert read_room(api, room_id)["service_program"] == PROGRAM_EVERY_OTHER_DAY


def test_an_alternating_day_enrolment_exhausts_its_skip_budget(api):
    """Three nights buy only two skips on the alternating-day programme, and the third is refused.

    PRD 3.9: "The accrual is also bounded by a **skip budget**, which is not the
    same as the night count for both programmes: the budget equals `nights` under
    `OPT_OUT`, but equals `nights` divided by two and rounded **up** to a whole
    number under `EVERY_OTHER_DAY` — an every-other-day guest cannot, by
    definition, skip every night of their stay."

    Design: Corner/validations/v_every_other_day_enrollment_exhausts_its_skip_budget
    """
    context = build_enrollment(
        api,
        program=PROGRAM_EVERY_OTHER_DAY,
        nights=3,
        room_overrides={"occupancy_state": OCCUPANCY_STAYOVER},
    )
    assert context.enrollment["points_per_skip"] == 250
    context.accrue()
    budgeted = context.accrue()
    assert budgeted["skips_accrued"] == 2
    assert budgeted["points_accrued"] == 500
    assert budgeted["status"] == ENROLLMENT_ACTIVE

    response = context.accrue_raw()

    validate_error(response, ApiErrorId.ENROLLMENT_SKIPS_EXHAUSTED, 422)
    enrollment = read_enrollment(api, context.enrollment_id)
    assert enrollment["skips_accrued"] == 2
    assert enrollment["points_accrued"] == 500
    assert enrollment["version"] == budgeted["version"], (
        "a refused accrual must not move the enrolment version"
    )
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 500
