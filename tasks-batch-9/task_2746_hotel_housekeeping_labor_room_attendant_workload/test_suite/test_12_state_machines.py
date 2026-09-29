"""State machines: initial states, guarded transitions, terminal lockdown, self-edges."""

from test_helpers import (
    ASSIGN_ASSIGNED,
    ASSIGN_DEFERRED,
    ASSIGN_IN_PROGRESS,
    ATTENDANT_ON_LEAVE,
    CLEAN_CLEAN,
    CLEAN_DIRTY,
    CLEAN_IN_SERVICE,
    COMPLIANCE_BREACH_BLOCKED,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_WAIVER_GRANTED,
    COMPLIANCE_USER_ID,
    DEFAULT_BUSINESS_DATE,
    DIRECTOR_HEADERS,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_COMPLETED,
    FORECAST_CLOSED,
    FORECAST_DRAFT,
    FORECAST_PUBLISHED,
    FRONT_DESK_HEADERS,
    OCCUPANCY_DUE_OUT,
    OCCUPANCY_STAYOVER,
    OCCUPANCY_VACANT,
    ORDINANCE_NONE,
    PROGRAM_OPT_OUT,
    PRODUCTIVITY_PENDING,
    ROSTER_CLOSED,
    ROSTER_PLANNED,
    SERVICE_CHECKOUT,
    SERVICE_DEEP_CLEAN,
    SERVICE_STAYOVER,
    WAIVER_DECISION_DENY,
    WAIVER_DECISION_GRANT,
    WAIVER_DENIED,
    WAIVER_GRANTED,
    WAIVER_NONE,
    WAIVER_REQUESTED,
    ApiErrorId,
    assert_business_date,
    assert_cents,
    assert_credits,
    assert_is_null,
    assert_roster_dimensions,
    assert_variance_pct,
    assert_whole_minutes,
    assignment_payload,
    build_enrollment,
    build_scenario,
    close_day,
    create_roster,
    decide_waiver,
    patch_attendant,
    publish_day,
    read_assignment,
    read_attendant,
    read_day,
    read_enrollment,
    read_property,
    read_room,
    read_roster,
    request_waiver,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ONE_ROOM_DAY = {
    "forecast_occupied_rooms": 1,
    "forecast_arrivals": 0,
    "forecast_departures": 1,
    "planned_deep_clean_rooms": 0,
}


# --------------------------------------------------------------------------
# The forecast day machine
# --------------------------------------------------------------------------


def _drafted_one_room_day(api, publish=False):
    """A single-KING-room property whose day forecasts one departure and one stayover."""
    return build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
        publish=publish,
        with_roster=False,
    )


def test_publishing_the_day_rewrites_the_projection_and_the_headcount(api):
    """One departure and one stayover on a single KING room imply 1.50 credits and one pair of hands.

    PRD 3.2: "The day then advances `DRAFT → PUBLISHED`, its `version` increments
    and its `updated_at` refreshes."

    Design: Corner/state_machines/sm_forecast_publish_recomputes_projection_and_headcount
    """
    scenario = _drafted_one_room_day(api)
    assert scenario.day["status"] == FORECAST_DRAFT

    day = publish_day(api, scenario.day_id)

    assert day["status"] == FORECAST_PUBLISHED
    assert_credits(
        day["projected_required_credits"], 1.50, "projected_required_credits"
    )
    assert day["required_attendants"] == 1, (
        "1.50 credits against a 14.5-credit shift ceiling needs one attendant, got "
        f"{day['required_attendants']}"
    )
    assert day["version"] == 2
    assert_is_null(day["actual_reconciled_credits"], "actual_reconciled_credits")
    assert_is_null(day["credit_variance_pct"], "credit_variance_pct")


def test_a_second_publish_of_the_same_day_is_refused(api):
    """The day has left DRAFT, so the projection is not quietly recomputed a second time.

    PRD 3.2: "The day must be in `DRAFT`, and the property must have at least one
    room type defined."

    Design: Corner/state_machines/sm_forecast_publish_on_a_published_day_is_rejected
    """
    scenario = _drafted_one_room_day(api, publish=True)

    response = api.publish_forecast_day(scenario.day_id, DIRECTOR_HEADERS)

    validate_error(response, ApiErrorId.FORECAST_NOT_DRAFT, 409)
    day = read_day(api, scenario.day_id)
    assert day["status"] == FORECAST_PUBLISHED
    assert day["version"] == 2, (
        f"the refused publish must not move the version, got {day['version']}"
    )
    assert_credits(
        day["projected_required_credits"], 1.50, "projected_required_credits"
    )


def test_a_closed_day_refuses_both_of_its_transitions_with_distinct_codes(api):
    """Publish and close aimed at the same closed day are both refused, changing nothing.

    PRD 3.2: "Any subsequent mutation aimed at a `CLOSED` day is refused with
    `ERR_FORECAST_ALREADY_CLOSED`, and a publish attempt on a day that is not
    `DRAFT` is `ERR_FORECAST_NOT_DRAFT`."

    A publish aimed at a `CLOSED` day satisfies both halves of that sentence at
    once — it is a mutation aimed at a `CLOSED` day *and* a publish attempt on a
    day that is not `DRAFT` — and neither PRD 3.2 nor the tenth rung of PRD 2.10
    states which of the two codes pre-empts the other, so both are accepted here.
    The close leg is unambiguous and stays exact.

    Design: Corner/state_machines/sm_closed_forecast_day_rejects_every_further_transition
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
    )
    scenario.close_roster(200, 20)
    closed = close_day(api, scenario.day_id)
    assert closed["status"] == FORECAST_CLOSED
    assert_credits(
        closed["actual_reconciled_credits"], 0.00, "actual_reconciled_credits"
    )
    assert_variance_pct(closed["credit_variance_pct"], -100.00)
    version_at_close = closed["version"]

    publish_again = api.publish_forecast_day(scenario.day_id, DIRECTOR_HEADERS)
    close_again = api.close_forecast_day(scenario.day_id, DIRECTOR_HEADERS)

    assert publish_again.status_code == 409, publish_again.text
    validate_error_is_one_of(
        publish_again,
        [ApiErrorId.FORECAST_NOT_DRAFT, ApiErrorId.FORECAST_ALREADY_CLOSED],
    )
    validate_error(close_again, ApiErrorId.FORECAST_ALREADY_CLOSED, 409)
    day = read_day(api, scenario.day_id)
    assert day["status"] == FORECAST_CLOSED
    assert day["version"] == version_at_close, (
        "neither refusal may move the version of a closed day"
    )
    assert_credits(
        day["actual_reconciled_credits"], 0.00, "actual_reconciled_credits"
    )


# --------------------------------------------------------------------------
# The roster machine
# --------------------------------------------------------------------------


def test_clock_in_reads_the_attendants_current_employment_status(api):
    """The roster was planned while the attendant was active; the leave came afterwards.

    PRD 3.3: "Four conditions must hold: the roster must still be `PLANNED`; the
    parent forecast day must still be `PUBLISHED`, or the attempt is refused with
    `ERR_FORECAST_NOT_PUBLISHED`; the attendant's employment `status` must still be
    `ACTIVE`, or `ERR_ATTENDANT_NOT_ACTIVE`; and the roster's `compliance_state`
    must not be `BREACH_BLOCKED`, or `ERR_ROSTER_WORKLOAD_BREACH`."

    Design: Corner/state_machines/sm_clock_in_on_an_on_leave_attendant_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
        clocked_in=False,
    )
    version_before = read_roster(api, scenario.roster_id)["version"]
    patch_attendant(api, scenario.worker_id, status=ATTENDANT_ON_LEAVE)

    response = api.clock_in(scenario.roster_id, scenario.attendant_headers())

    validate_error(response, ApiErrorId.ATTENDANT_NOT_ACTIVE, 409)
    roster = read_roster(api, scenario.roster_id)
    assert roster["status"] == ROSTER_PLANNED
    assert roster["version"] == version_before, (
        f"the refused clock-in must not move the version, got {roster['version']}"
    )
    assert read_attendant(api, scenario.worker_id)["status"] == ATTENDANT_ON_LEAVE


def test_every_new_row_lands_on_its_declared_initial_state(api):
    """A day, a roster, a room and an assignment each start where their machine begins.

    PRD 3.3: "`status` starts at `PLANNED`, `waiver_state` at `NONE`,
    `productivity_flag` at `PENDING`, `assigned_credits` at 0.00 and
    `assigned_square_feet` at 0."

    Design: Corner/state_machines/sm_new_rows_start_in_their_declared_initial_states
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
        publish=False,
        with_roster=False,
    )
    assert scenario.day["status"] == FORECAST_DRAFT
    assert scenario.rooms["101"]["cleanliness_status"] == CLEAN_DIRTY, (
        "a room starts DIRTY even when its occupancy posture was supplied as DUE_OUT"
    )
    publish_day(api, scenario.day_id)

    roster = create_roster(api, scenario.day_id, scenario.worker_id)
    assignment = validate_success(
        api.create_room_assignment(
            assignment_payload(
                roster["id"],
                scenario.room_id("101"),
                roster["version"],
                SERVICE_CHECKOUT,
            ),
            scenario.supervisor_headers(),
        ),
        201,
    )

    assert_roster_dimensions(
        roster, ROSTER_PLANNED, COMPLIANCE_COMPLIANT, WAIVER_NONE
    )
    assert roster["productivity_flag"] == PRODUCTIVITY_PENDING
    assert_credits(roster["assigned_credits"], 0.00, "assigned_credits")
    assert roster["assigned_square_feet"] == 0
    assert assignment["status"] == ASSIGN_ASSIGNED
    assert assignment["reclean_generation"] == 0
    after = read_roster(api, roster["id"])
    assert_credits(after["assigned_credits"], 1.00, "assigned_credits")
    assert after["compliance_state"] == COMPLIANCE_COMPLIANT


def test_closing_the_shift_defers_the_untouched_room_and_settles_the_pay(api):
    """A room nobody started is pushed off the day, and 200 worked minutes are paid as 240.

    PRD 3.7: "**Hop one**: every assignment on the roster still sitting in
    `ASSIGNED` advances `ASSIGNED → DEFERRED`, processed in ascending `created_at`
    order."

    Design: Corner/state_machines/sm_roster_close_sweeps_assigned_rows_and_settles_pay
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
    )
    assignment = scenario.assign("101", SERVICE_CHECKOUT)

    closed = scenario.close_roster(200, 20)

    assert closed["status"] == ROSTER_CLOSED
    assert read_assignment(api, assignment["id"])["status"] == ASSIGN_DEFERRED
    assert_credits(closed["assigned_credits"], 0.00, "assigned_credits")
    assert closed["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_credits(
        read_day(api, scenario.day_id)["allocated_credits_total"],
        0.00,
        "allocated_credits_total",
    )
    assert_whole_minutes(closed["paid_minutes"], 240, "paid_minutes")
    assert_whole_minutes(closed["overtime_minutes"], 0, "overtime_minutes")
    assert_cents(closed["base_wage_cents"], 12000, "base_wage_cents")
    assert_cents(closed["ordinance_premium_cents"], 0, "ordinance_premium_cents")
    assert_cents(closed["total_labor_cost_cents"], 12000, "total_labor_cost_cents")
    assert closed["rooms_completed_gross"] == 0
    assert closed["rooms_credited_net"] == 0
    assert_is_null(closed["minutes_per_room_gross"], "minutes_per_room_gross")
    assert_is_null(closed["minutes_per_room_net"], "minutes_per_room_net")
    assert_is_null(closed["target_minutes_per_room"], "target_minutes_per_room")
    assert closed["productivity_flag"] == PRODUCTIVITY_PENDING


# --------------------------------------------------------------------------
# The assignment machine
# --------------------------------------------------------------------------


def test_cancel_is_refused_once_the_room_is_being_cleaned(api):
    """Cancel is wired from ASSIGNED alone, so a room already under way cannot be withdrawn.

    PRD 3.4: "Cancelling an assignment is the compensating move, available to a
    `HousekeepingDirector` or a `Supervisor` while the assignment is still
    `ASSIGNED`."

    Design: Corner/state_machines/sm_cancel_of_an_in_progress_assignment_is_rejected
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
        linen={"total_owned_sets": 20},
    )
    assignment = scenario.assign("101", SERVICE_CHECKOUT)
    started = scenario.start(assignment["id"], "2026-08-03T09:00:00.000Z")

    response = api.cancel_assignment(
        assignment["id"], None, scenario.supervisor_headers()
    )

    validate_error(response, ApiErrorId.ASSIGNMENT_TERMINAL, 409)
    refused = read_assignment(api, assignment["id"])
    assert refused["status"] == ASSIGN_IN_PROGRESS
    assert refused["version"] == started["version"], (
        f"the refused cancel must not move the version, got {refused['version']}"
    )
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_IN_SERVICE
    )
    assert_credits(
        read_roster(api, scenario.roster_id)["assigned_credits"],
        1.00,
        "assigned_credits",
    )


# --------------------------------------------------------------------------
# The room-condition machine is cyclic
# --------------------------------------------------------------------------


def test_a_cleaned_room_returns_to_dirty_when_it_is_due_out_again(api):
    """The next departure sends the same room back to the head of the cleaning loop.

    PRD 3.1: "Setting `occupancy_state` to `DUE_OUT` returns a serviced room to the
    head of the cleaning loop: a room whose condition was `CLEAN` moves `CLEAN →
    DIRTY`, and a room whose condition was `INSPECTED_PASS` moves `INSPECTED_PASS →
    DIRTY`, ready for the next business date."

    Design: Corner/state_machines/sm_room_returns_to_dirty_when_patched_back_to_due_out
    """
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT}],
        forecast=ONE_ROOM_DAY,
    )
    cleaned = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T09:00:00.000Z",
        "2026-08-03T09:30:00.000Z",
    )
    serviced = read_room(api, scenario.room_id("101"))
    assert serviced["cleanliness_status"] == CLEAN_CLEAN
    assert_business_date(
        serviced["last_serviced_business_date"],
        DEFAULT_BUSINESS_DATE,
        "last_serviced_business_date",
    )
    assert_whole_minutes(cleaned["actual_minutes"], 30, "actual_minutes")
    assert cleaned["linen_sets_debited"] == 0, (
        "the property holds no SHEET_SET line, so the debit is skipped entirely"
    )

    patched = validate_success(
        api.patch_room(
            scenario.room_id("101"),
            {"occupancy_state": OCCUPANCY_DUE_OUT},
            FRONT_DESK_HEADERS,
        ),
        200,
    )

    assert patched["cleanliness_status"] == CLEAN_DIRTY, (
        f"the room should be dirty again, got {patched['cleanliness_status']}"
    )
    assert patched["occupancy_state"] == OCCUPANCY_DUE_OUT
    assert_business_date(
        patched["last_serviced_business_date"],
        DEFAULT_BUSINESS_DATE,
        "last_serviced_business_date",
    )


# --------------------------------------------------------------------------
# The waiver dimension
# --------------------------------------------------------------------------


def _breached_roster_awaiting_a_decision(api):
    """Three rooms worth 3.50 credits on an attendant whose ceiling has just fallen to 3.00."""
    scenario = build_scenario(
        api,
        property_overrides={
            "ordinance_profile": ORDINANCE_NONE,
            "max_daily_credits": 4.00,
        },
        rooms=[
            {"number": "101", "occupancy_state": OCCUPANCY_DUE_OUT},
            {"number": "102", "occupancy_state": OCCUPANCY_STAYOVER},
            {"number": "103", "occupancy_state": OCCUPANCY_VACANT},
        ],
        linen={"total_owned_sets": 20},
        forecast={
            "forecast_occupied_rooms": 2,
            "forecast_arrivals": 0,
            "forecast_departures": 1,
            "planned_deep_clean_rooms": 1,
        },
        clocked_in=False,
    )
    scenario.assign("101", SERVICE_CHECKOUT)
    scenario.assign("102", SERVICE_STAYOVER)
    scenario.assign("103", SERVICE_DEEP_CLEAN)
    patch_attendant(api, scenario.worker_id, restricted_duty=True)
    breached = read_roster(api, scenario.roster_id)
    assert_credits(breached["assigned_credits"], 3.50, "assigned_credits")
    assert_credits(breached["effective_credit_cap"], 3.00, "effective_credit_cap")
    assert breached["compliance_state"] == COMPLIANCE_BREACH_BLOCKED
    requested = request_waiver(api, scenario.roster_id, 3.50, scenario.inspector_id)
    assert requested["waiver_state"] == WAIVER_REQUESTED
    return scenario


def test_a_granted_waiver_reopens_the_blocked_roster(api):
    """The grant covers the 3.50 credits already allocated, so the freeze lifts.

    PRD 3.3: "A `GRANT` advances `waiver_state` from `REQUESTED` to `GRANTED` and
    re-runs the compliance derivation, which yields `WAIVER_GRANTED` when
    `assigned_credits` is at or below `waiver_requested_credits` — so a roster
    sitting in `BREACH_BLOCKED` moves `BREACH_BLOCKED → WAIVER_GRANTED` and both
    clock-in and assignment starts re-open."

    Design: Corner/state_machines/sm_waiver_grant_reopens_a_breached_roster
    """
    scenario = _breached_roster_awaiting_a_decision(api)

    decided = decide_waiver(api, scenario.roster_id, WAIVER_DECISION_GRANT)

    assert decided["waiver_state"] == WAIVER_GRANTED
    assert decided["compliance_state"] == COMPLIANCE_WAIVER_GRANTED, (
        f"the compliance dimension should read WAIVER_GRANTED, got "
        f"{decided['compliance_state']}"
    )
    assert decided["status"] == ROSTER_PLANNED, (
        "deciding a waiver must not move the lifecycle dimension"
    )
    assert decided["waiver_decided_by_user_id"] == COMPLIANCE_USER_ID
    assert_is_null(read_roster(api, scenario.roster_id)["effective_sqft_cap"], (
        "effective_sqft_cap"
    ))


def test_a_denied_waiver_leaves_the_roster_frozen(api):
    """The denial re-derives compliance with the waiver ignored, so the clock-in still fails.

    PRD 3.3: "A `DENY` advances `waiver_state` from `REQUESTED` to `DENIED` and
    re-runs the same derivation while **ignoring** the waiver entirely, so a roster
    over its ceiling stays in `BREACH_BLOCKED` and remains frozen."

    Design: Corner/state_machines/sm_waiver_denial_keeps_the_roster_blocked
    """
    scenario = _breached_roster_awaiting_a_decision(api)

    decided = decide_waiver(api, scenario.roster_id, WAIVER_DECISION_DENY)
    response = api.clock_in(scenario.roster_id, scenario.attendant_headers())

    assert decided["waiver_state"] == WAIVER_DENIED
    assert decided["compliance_state"] == COMPLIANCE_BREACH_BLOCKED
    validate_error(response, ApiErrorId.ROSTER_WORKLOAD_BREACH, 409)
    assert read_roster(api, scenario.roster_id)["status"] == ROSTER_PLANNED


# --------------------------------------------------------------------------
# The enrolment machine and the property ledger
# --------------------------------------------------------------------------


def test_each_accrual_pushes_its_points_into_the_property_ledger(api):
    """Two skips on a two-night opt-out stay close the enrolment at 1000 points.

    PRD 3.9: "A permitted accrual increments `skips_accrued` by one and recomputes
    `points_accrued` as `skips_accrued` multiplied by `points_per_skip`; the
    property's `outstanding_incentive_points` is then recomputed across its
    `ACTIVE` enrolments, and the enrolment's `version` increments."

    Design: Corner/state_machines/sm_enrollment_accrual_syncs_points_into_the_property_ledger
    """
    context = build_enrollment(api, program=PROGRAM_OPT_OUT, nights=2)
    assert context.enrollment["points_per_skip"] == 500
    assert read_room(api, context.room["id"])["service_program"] == PROGRAM_OPT_OUT
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 0

    first = context.accrue()
    assert first["skips_accrued"] == 1
    assert first["points_accrued"] == 500
    assert first["status"] == ENROLLMENT_ACTIVE
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 500

    second = context.accrue()

    assert second["skips_accrued"] == 2
    assert second["points_accrued"] == 1000
    assert second["status"] == ENROLLMENT_COMPLETED, (
        f"the accrual that reaches the night count closes the enrolment, got "
        f"{second['status']}"
    )
    # PRD 3.1: "`outstanding_incentive_points` is the sum of `points_accrued`
    # across every service enrolment whose room belongs to the property and whose
    # `status` is still `ACTIVE`".  The second accrual took this enrolment
    # `ACTIVE -> COMPLETED`, so it has dropped out of that sum and the ledger
    # falls back to 0 even though the enrolment itself still shows 1000 points.
    assert read_property(api, context.prop["id"])["outstanding_incentive_points"] == 0
    assert read_enrollment(api, context.enrollment_id)["version"] == 3
