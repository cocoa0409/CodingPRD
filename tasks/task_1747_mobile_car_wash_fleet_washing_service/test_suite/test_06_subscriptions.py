"""Subscriptions: pause/resume cycles, pause counters, calendar conservation,
duplicate guard (PRD §3.2)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, cancel_subscription, create_subscription,
    get_subscription, make_customer_headers, pause_subscription,
    resume_subscription, set_clock, setup_customer_site_vehicles, validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _subscription(next_service_date="2026-08-20"):
    """RETAIL customer + site + vehicle + ACTIVE subscription."""
    ctx = setup_customer_site_vehicles(num_vehicles=1, vehicle_class="SEDAN")
    sub = create_subscription(
        ctx["customer"]["id"], ctx["vehicle_ids"][0],
        cadence="MONTHLY", next_service_date=next_service_date,
    )
    ctx["subscription"] = sub
    return ctx


class TestSubscriptionPauseCycleCounters:
    def test_first_pause_resume_cycle_counters(self, api):
        """PRD §3.2: "Two computed counters summarize the window: `pause_count_365d`
        is the number of pause records whose `started_at` falls inside it (a
        prospective pause being requested is not yet counted), and `paused_days_365d`
        sums the days of those records, an open record contributing the days elapsed
        from its `started_at` through the clock date."
        PRD §3.2: "Resuming closes the open record: `ended_at` becomes the clock date,
        the record's `days` becomes the elapsed day count, and `next_service_date`
        shifts forward by exactly that closed record's days"

        Design: Difficulty/non_linear_state_machine/subscription_pause_cycle_counters
        """
        ctx = _subscription()
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        paused = pause_subscription(sub_id, 21, cust_id)
        assert paused["status"] == "PAUSED"
        assert paused["pause_count_365d"] == 1
        set_clock("2026-08-22T00:00:00Z")
        resumed = resume_subscription(sub_id, cust_id)
        assert resumed["status"] == "ACTIVE"
        # 2026-08-20 + 21 closed pause days
        assert resumed["next_service_date"] == "2026-09-10"
        assert resumed["paused_days_365d"] == 21

    def test_second_pause_admitted_with_counters(self, api):
        """PRD §3.2: "Two guards apply, evaluated in this order: first, the trailing
        pause count must be below two and the requested pause must be at least seven
        days long — otherwise the request fails with `ERR_PAUSE_LIMIT_EXCEEDED`;
        second, the trailing paused days plus the requested days must not exceed
        ninety — ninety exactly is allowed — otherwise the request fails with
        `ERR_PAUSE_DURATION_EXCEEDED`."

        Design: Difficulty/non_linear_state_machine/subscription_pause_cycle_counters
        """
        ctx = _subscription()
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        pause_subscription(sub_id, 21, cust_id)
        set_clock("2026-08-22T00:00:00Z")
        resume_subscription(sub_id, cust_id)
        # count was 1 < 2 and 21 + 30 <= 90: second pause admitted
        paused2 = pause_subscription(sub_id, 30, cust_id)
        assert paused2["status"] == "PAUSED"
        assert paused2["pause_count_365d"] == 2
        # open pause contributes clock - started_at = 0 at pause time
        assert paused2["paused_days_365d"] == 21


class TestSubscriptionCalendarConservedAcrossPauseResume:
    def test_first_pair_shifts_next_service_date_by_closed_days(self, api):
        """PRD §3.2: "Resuming closes the open record: `ended_at` becomes the clock
        date, the record's `days` becomes the elapsed day count, and
        `next_service_date` shifts forward by exactly that closed record's days, so
        the subscription calendar is conserved — the service date after a
        pause-resume pair minus the date before it equals the paused days."

        Design: Difficulty/compensating_invariant/subscription_calendar_conserved_across_pause_resume
        """
        ctx = _subscription()
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        pause_subscription(sub_id, 21, cust_id)
        set_clock("2026-08-22T00:00:00Z")
        resumed = resume_subscription(sub_id, cust_id)
        assert resumed["next_service_date"] == "2026-09-10"  # 2026-08-20 + 21 days
        assert resumed["pauses"][0]["days"] == 21
        assert resumed["pauses"][0]["ended_at"] is not None

    def test_two_pairs_cumulative_shift_equals_cumulative_days(self, api):
        """PRD §3.2: "Resuming closes the open record: `ended_at` becomes the clock
        date, the record's `days` becomes the elapsed day count, and
        `next_service_date` shifts forward by exactly that closed record's days, so
        the subscription calendar is conserved — the service date after a
        pause-resume pair minus the date before it equals the paused days."

        Design: Difficulty/compensating_invariant/subscription_calendar_conserved_across_pause_resume
        """
        ctx = _subscription()
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        pause_subscription(sub_id, 21, cust_id)
        set_clock("2026-08-22T00:00:00Z")
        resume_subscription(sub_id, cust_id)
        pause_subscription(sub_id, 7, cust_id)
        set_clock("2026-08-29T00:00:00Z")
        resumed2 = resume_subscription(sub_id, cust_id)
        # 2026-09-10 + 7 days; cumulative shift 28 == 21 + 7 closed days
        assert resumed2["next_service_date"] == "2026-09-17"
        assert resumed2["paused_days_365d"] == 28
        assert resumed2["pause_count_365d"] == 2


class TestPauseNinetyDaysExactlyAllowed:
    def test_budget_at_exactly_90_admitted(self, api):
        """PRD §3.2: "second, the trailing paused days plus the requested days must
        not exceed ninety — ninety exactly is allowed — otherwise the request fails
        with `ERR_PAUSE_DURATION_EXCEEDED`."

        Design: Corner/calculations/pause_ninety_days_exactly_allowed
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = _subscription(next_service_date="2026-02-15")
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        set_clock("2026-03-01T00:00:00Z")
        pause_subscription(sub_id, 75, cust_id)
        set_clock("2026-05-15T00:00:00Z")
        resumed = resume_subscription(sub_id, cust_id)
        assert resumed["paused_days_365d"] == 75
        assert resumed["pause_count_365d"] == 1
        paused = pause_subscription(sub_id, 15, cust_id)  # 75 + 15 == 90 exactly
        assert paused["status"] == "PAUSED"


class TestPauseNinetyOneDaysRejected:
    def test_budget_at_91_rejected(self, api):
        """PRD §3.2: "second, the trailing paused days plus the requested days must
        not exceed ninety — ninety exactly is allowed — otherwise the request fails
        with `ERR_PAUSE_DURATION_EXCEEDED`."

        Design: Corner/calculations/pause_ninety_one_days_rejected
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = _subscription(next_service_date="2026-02-15")
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        set_clock("2026-03-01T00:00:00Z")
        pause_subscription(sub_id, 75, cust_id)
        set_clock("2026-05-15T00:00:00Z")
        resume_subscription(sub_id, cust_id)
        resp = _raw_pause(api, sub_id, 16, cust_id)  # 75 + 16 == 91 > 90
        validate_error(resp, ApiErrorId.ERR_PAUSE_DURATION_EXCEEDED)
        assert get_subscription(sub_id)["status"] == "ACTIVE"


class TestThirdPauseInYearRejected:
    def test_third_pause_fails_on_count_even_when_days_fit(self, api):
        """PRD §3.2: "Two guards apply, evaluated in this order: first, the trailing
        pause count must be below two and the requested pause must be at least seven
        days long — otherwise the request fails with `ERR_PAUSE_LIMIT_EXCEEDED`"

        Design: Corner/validations/third_pause_in_year_rejected
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = _subscription(next_service_date="2026-02-15")
        sub_id, cust_id = ctx["subscription"]["id"], ctx["customer"]["id"]
        set_clock("2026-03-01T00:00:00Z")
        pause_subscription(sub_id, 31, cust_id)
        set_clock("2026-04-01T00:00:00Z")
        resume_subscription(sub_id, cust_id)
        set_clock("2026-06-01T00:00:00Z")
        pause_subscription(sub_id, 44, cust_id)
        set_clock("2026-07-15T00:00:00Z")
        resumed = resume_subscription(sub_id, cust_id)
        assert resumed["pause_count_365d"] == 2
        assert resumed["paused_days_365d"] == 75
        # 75 + 7 == 82 <= 90 would pass the day budget; the count check fires first
        resp = _raw_pause(api, sub_id, 7, cust_id)
        validate_error(resp, ApiErrorId.ERR_PAUSE_LIMIT_EXCEEDED)


class TestDuplicateSubscriptionSameVehicle:
    def test_second_active_subscription_rejected_then_allowed_after_cancel(self, api):
        """PRD §3.2: "A vehicle may carry at most one subscription in `ACTIVE` or
        `PAUSED`; a second attempt is rejected with `ERR_DUPLICATE_SUBSCRIPTION`, and
        a suspended customer cannot create one at all (`ERR_CUSTOMER_SUSPENDED`)."

        Design: Corner/validations/duplicate_subscription_same_vehicle
        """
        ctx = _subscription(next_service_date="2026-08-10")
        cust_id, veh_id = ctx["customer"]["id"], ctx["vehicle_ids"][0]
        resp = api_client_create_subscription(api, cust_id, veh_id)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUBSCRIPTION)
        cancel_subscription(ctx["subscription"]["id"], cust_id)
        replacement = create_subscription(
            cust_id, veh_id, cadence="MONTHLY", next_service_date="2026-09-01",
        )
        assert replacement["status"] == "ACTIVE"


def _raw_pause(api, subscription_id, pause_days, customer_id):
    return api.subscription_event(
        subscription_id, {"event_type": "PAUSE", "pause_days": pause_days},
        make_customer_headers(customer_id),
    )


def api_client_create_subscription(api, customer_id, vehicle_id):
    return api.create_subscription(
        {"customer_id": customer_id, "vehicle_id": vehicle_id,
         "cadence": "MONTHLY", "next_service_date": "2026-09-01"},
        ADMIN,
    )
