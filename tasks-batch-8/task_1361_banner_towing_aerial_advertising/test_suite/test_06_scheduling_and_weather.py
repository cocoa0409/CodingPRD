"""Flight-day operations: scheduling cutoff, go/no-go verdict thresholds,
the WEATHER_HOLD two-strike rule, and make-good credit creation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    book_slot_in,
    get_slot,
    post_weather,
    schedule_slot,
    set_clock,
    setup_operation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, DISPATCHER


class TestSchedulingCutoff:

    def test_schedule_within_two_hours_rejected(self, api):
        """PRD §3.6: "Moving a slot from `BOOKED` to `SCHEDULED` requires the
        request to arrive at least two hours before `planned_start_utc` —
        anything closer is rejected with `ERR_TOO_LATE_TO_SCHEDULE`
        (HTTP 409)."

        The slot is booked while the clock reads 2026-08-09 (well over
        twenty-four hours before takeoff, satisfying §3.5), then the clock
        advances to 90 minutes before `planned_start_utc`.

        Design: Corner/validations/schedule_within_2h_rejected
        """
        sc = setup_operation(base_code="K2L8", clock="2026-08-09T13:30:00Z",
                             date_local="2026-08-10",
                             window_start="2026-08-10T14:00:00Z",
                             window_end="2026-08-10T18:00:00Z")
        slot = book_slot_in(sc, planned_start="2026-08-10T15:00:00Z",
                            planned_duration_hours=1)
        set_clock("2026-08-10T13:30:00Z")
        resp = api.schedule_flight_slot(slot["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_TOO_LATE_TO_SCHEDULE,
                       expected_status=409)


class TestGoNoGoThresholds:

    def test_marginal_band_verdict_leaves_slot_scheduled(self, api):
        """PRD §3.6: "failing that, visibility below 5.0 statute miles, or a
        ceiling below 1,500 feet, or wind above 18 knots yields `MARGINAL`"
        and "A `GO` or `MARGINAL` verdict leaves the slot's state untouched —
        marginal weather is logged for the record but never moves the slot."

        Visibility 4.0 SM / ceiling 1,200 ft / wind 10 kts sits in the
        marginal band.

        Design: Corner/calculations/go_no_go_marginal_band
        """
        sc = setup_operation(base_code="KMGN")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        assessment = post_weather(slot["id"], ceiling_ft=1200,
                                  visibility_sm=4.0, wind_kts=10)
        assert assessment["verdict"] == "MARGINAL", (
            f"4.0 SM visibility is below the 5.0 marginal floor, verdict "
            f"must be MARGINAL, got {assessment['verdict']}"
        )
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "SCHEDULED", (
            f"MARGINAL must not move the slot, got {slot_after['status']}"
        )
        assert slot_after["weather_hold_count"] == 0

    def test_visibility_exactly_3_sm_is_not_no_go(self, api):
        """PRD §3.6: "visibility below 3.0 statute miles, or a ceiling below
        1,000 feet, or surface wind above 25 knots yields `NO_GO`; failing
        that, visibility below 5.0 statute miles, or a ceiling below 1,500
        feet, or wind above 18 knots yields `MARGINAL`; anything better
        yields `GO`."

        At exactly 3.0 statute miles the visibility is not "below 3.0", so
        the NO_GO band does not fire; 3.0 is below the 5.0 marginal floor,
        so the verdict is MARGINAL and the slot stays SCHEDULED.

        Design: Difficulty/boundary_precision_check/visibility_exactly_3_sm_is_go
        """
        sc = setup_operation(base_code="KV30")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        assessment = post_weather(slot["id"], ceiling_ft=5000,
                                  visibility_sm=3.0, wind_kts=10)
        assert assessment["verdict"] == "MARGINAL", (
            f"visibility of exactly 3.0 SM is not below the 3.0 NO_GO "
            f"threshold but is below the 5.0 marginal floor, verdict must "
            f"be MARGINAL, got {assessment['verdict']}"
        )
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "SCHEDULED", (
            f"a non-NO_GO verdict must not move the slot, got "
            f"{slot_after['status']}"
        )

    def test_visibility_just_below_3_sm_drives_weather_hold(self, api):
        """PRD §3.6: "visibility below 3.0 statute miles, or a ceiling below
        1,000 feet, or surface wind above 25 knots yields `NO_GO`" and "A
        `NO_GO` verdict drives the state machine: the slot moves from
        `SCHEDULED` to `WEATHER_HOLD` and its `weather_hold_count` increments
        by one, except when the increment would bring the count to two or
        more, in which case the slot is cancelled outright to
        `CANCELLED_WEATHER`."

        At 2.9 statute miles the NO_GO band fires on the first strike.

        Design: Difficulty/boundary_precision_check/visibility_exactly_3_sm_is_go
        """
        sc = setup_operation(base_code="KV29")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        assessment = post_weather(slot["id"], ceiling_ft=5000,
                                  visibility_sm=2.9, wind_kts=10)
        assert assessment["verdict"] == "NO_GO"
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "WEATHER_HOLD", (
            f"first NO_GO must move the slot to WEATHER_HOLD, got "
            f"{slot_after['status']}"
        )
        assert slot_after["weather_hold_count"] == 1


class TestWeatherHoldTwoStrikeRule:

    def test_second_no_go_cancels_slot(self, api):
        """PRD §3.6: "A `NO_GO` verdict drives the state machine: the slot
        moves from `SCHEDULED` to `WEATHER_HOLD` and its `weather_hold_count`
        increments by one, except when the increment would bring the count to
        two or more, in which case the slot is cancelled outright to
        `CANCELLED_WEATHER`."
        PRD §3.6: "The dispatcher can reschedule from `WEATHER_HOLD` back to
        `SCHEDULED` by supplying a new `planned_start_utc`, provided the new
        start still falls inside the approval window and the slot's
        `weather_hold_count` is below two".

        Design: Difficulty/non_linear_state_machine/flight_slot_weather_hold_cycle
        """
        sc = setup_operation(base_code="KWH2")
        slot = book_slot_in(sc, planned_start="2026-08-13T15:00:00Z",
                            planned_duration_hours=1)
        schedule_slot(slot["id"])
        post_weather(slot["id"], ceiling_ft=500, visibility_sm=2.0,
                     wind_kts=5)
        held = get_slot(slot["id"])
        assert held["status"] == "WEATHER_HOLD"
        assert held["weather_hold_count"] == 1
        resp = api_client.reschedule_after_hold(
            slot["id"], {"planned_start_utc": "2026-08-13T16:00:00Z"},
            DISPATCHER)
        validate_success(resp, expected_status=200)
        post_weather(slot["id"], ceiling_ft=500, visibility_sm=2.0,
                     wind_kts=5)
        after = get_slot(slot["id"])
        assert after["status"] == "CANCELLED_WEATHER", (
            f"second NO_GO must cancel the slot outright, got "
            f"{after['status']}"
        )
        assert after["weather_hold_count"] == 2
        capacity = validate_success(
            api.get_seasonal_capacity(sc["capacity"]["id"], ADMIN),
            expected_status=200)
        assert capacity["hours_committed"] == 0, (
            "weather cancellation releases the slot's planned hours "
            "(PRD §3.6)"
        )

    def test_weather_cancellation_creates_make_good_credit(self, api):
        """PRD §3.6: "Cancellation by weather is never billed; instead the
        system creates a **MakeGoodCredit** whose `original_cents` equals the
        source slot's `planned_duration_hours` multiplied by the assigned
        aircraft's `hourly_rate_cents`, whose `expires_on_local` falls
        exactly thirty days after the source slot's `date_local`, and whose
        `remaining_cents` starts equal to that original value with the credit
        in `OPEN` status."

        A 2-hour slot at 30,000 cents/hour weather-cancelled on 2026-08-13
        yields a 60,000-cent credit expiring 2026-09-12.

        Design: Difficulty/non_linear_state_machine/flight_slot_weather_hold_cycle
        """
        sc = setup_operation(base_code="KMGC")
        slot = book_slot_in(sc, planned_start="2026-08-13T14:00:00Z",
                            planned_duration_hours=2)
        schedule_slot(slot["id"])
        post_weather(slot["id"], ceiling_ft=500, visibility_sm=2.0,
                     wind_kts=5)
        validate_success(api_client.reschedule_after_hold(
            slot["id"], {"planned_start_utc": "2026-08-13T16:00:00Z"},
            DISPATCHER), expected_status=200)
        post_weather(slot["id"], ceiling_ft=500, visibility_sm=2.0,
                     wind_kts=5)
        assert get_slot(slot["id"])["status"] == "CANCELLED_WEATHER"
        credits = validate_success(
            api.list_make_good_credits(sc["campaign"]["id"], ADMIN),
            expected_status=200)
        assert len(credits) == 1, f"exactly one credit expected, got {len(credits)}"
        credit = credits[0]
        assert credit["source_slot_id"] == slot["id"]
        assert credit["original_cents"] == 2 * 30000
        assert credit["remaining_cents"] == 60000
        assert credit["status"] == "OPEN"
        assert credit["expires_on_local"] == "2026-09-12", (
            f"expiry must be date_local + 30 days, got "
            f"{credit['expires_on_local']}"
        )


class TestWeatherAssessmentImmutability:

    def test_assessments_of_nonexistent_slot_return_not_found(self, api):
        """PRD §2.6: "The existence of each path identifier is confirmed in
        sequence, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the first identifier that does not correspond to an existing
        resource". PRD §2.4: "Two resources are immutable evidentiary records
        and break this pattern deliberately: a `WeatherAssessment` and a
        `ProofOfFlight` each carry `id` and `created_at` only. Neither has
        `updated_at` and neither has `version`; once created, they are never
        modified."

        Design: Corner/entities/weather_assessment_immutable_no_update_endpoint
        """
        resp = api.list_weather_assessments(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
