"""Weather sweeps, wind-resume hysteresis, and incident cascades
(PRD section 3.7).

Covers design instances:
  Difficulty/non_linear_state_machine/ride_daily_status_cycles_through_weather_holds
  Difficulty/boundary_precision_check/wind_resume_hysteresis_exact_boundary
  Difficulty/transitive_cascade/order_shutdown_revokes_license_closes_ride_voids_queue
  Corner/errors/minor_incident_threshold_and_conditional_clear_behavior
"""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_inspector_headers,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestRideDailyStatusCycles:
    def test_per_ride_hold_at_limit_and_license_untouched(self, api):
        """PRD section 3.7: "The ride hold rule: every ride whose
        `daily_status` is `OPEN` and whose own `wind_limit_mph` is met or
        exceeded by the reading moves to `WEATHER_HOLD` — the boundary is
        inclusive, so a reading exactly equal to a ride's limit holds that
        ride."

        The license axis is independent: it stays LICENSED through a hold.

        Design: Difficulty/non_linear_state_machine/ride_daily_status_cycles_through_weather_holds
        """
        ctx = fx.setup_open_day("F")
        sup = ctx["sup"]
        fx.record_wind(sup, ctx["day"]["id"], 30)
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["daily_status"] == "WEATHER_HOLD", (
            f"wind 30 >= limit 30 must hold the ride; got {ride['daily_status']}")
        assert ride["license_status"] == "LICENSED"

    def test_fair_closure_sweep_and_staged_resume(self, api):
        """PRD section 3.7: "when the reading reaches 45 mph and the day's
        posture is `OPEN`, the day itself moves to `WEATHER_HOLD` and every
        `OPEN` ride moves to `WEATHER_HOLD` regardless of per-ride limits" and
        "Resuming the whole day... requires the latest observation to read at
        or below 39 mph (`ERR_WIND_ABOVE_LIMIT`); day resumption deliberately
        leaves every ride in `WEATHER_HOLD`, and each ride then reopens
        individually through the per-ride resume."

        Design: Difficulty/non_linear_state_machine/ride_daily_status_cycles_through_weather_holds
        """
        ctx = fx.setup_open_day("Fb")
        sup = ctx["sup"]
        day_id, ride_id = ctx["day"]["id"], ctx["ride"]["id"]
        fx.record_wind(sup, day_id, 30)
        fx.record_wind(sup, day_id, 27)
        resumed = validate_success(api.resume_ride(ride_id, {}, make_manager_headers(sup["id"])))
        assert resumed["daily_status"] == "OPEN"
        fx.record_wind(sup, day_id, 45)
        day = fx.get_day(sup, day_id)
        assert day["posture"] == "WEATHER_HOLD"
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "WEATHER_HOLD"
        resp = api.resume_day(day_id, {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_WIND_ABOVE_LIMIT, 422)
        fx.record_wind(sup, day_id, 39)
        day = validate_success(api.resume_day(day_id, {}, make_manager_headers(sup["id"])))
        assert day["posture"] == "OPEN", "39 <= 39 must satisfy the day resume guard"
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "WEATHER_HOLD", (
            "day resumption must leave rides in WEATHER_HOLD")
        fx.record_wind(sup, day_id, 20)
        resumed = validate_success(api.resume_ride(ride_id, {}, make_manager_headers(sup["id"])))
        assert resumed["daily_status"] == "OPEN"


class TestWindResumeHysteresis:
    def _setup_held_ride(self, api, name):
        ctx = fx.setup_open_day(name)
        sup = ctx["sup"]
        fx.record_wind(sup, ctx["day"]["id"], 30)
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["daily_status"] == "WEATHER_HOLD"
        return ctx

    def test_resume_at_limit_and_limit_minus_two_rejected(self, api):
        """PRD section 3.7: "the latest observation of the day — the one with
        the greatest `created_at` — to read at least 3 mph under the ride's
        `wind_limit_mph`, that is, wind at or below the limit minus three for
        these integer readings (`ERR_WIND_ABOVE_LIMIT`)".

        With limit 30: latest wind 30 and 28 both fail (28 > 30 - 3 = 27).

        Design: Difficulty/boundary_precision_check/wind_resume_hysteresis_exact_boundary
        """
        ctx = self._setup_held_ride(api, "L")
        sup = ctx["sup"]
        day_id, ride_id = ctx["day"]["id"], ctx["ride"]["id"]
        resp = api.resume_ride(ride_id, {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_WIND_ABOVE_LIMIT, 422)
        fx.record_wind(sup, day_id, 28)
        resp = api.resume_ride(ride_id, {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_WIND_ABOVE_LIMIT, 422)
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "WEATHER_HOLD"

    def test_resume_at_limit_minus_three_succeeds(self, api):
        """PRD section 3.7: "a successful resume moves the ride back to `OPEN`
        and advances its `version`."

        At exactly wind 27 == 30 - 3 the resume succeeds — the resume guard is
        a strict inequality against limit - 2, i.e. wind <= limit - 3.

        Design: Difficulty/boundary_precision_check/wind_resume_hysteresis_exact_boundary
        """
        ctx = self._setup_held_ride(api, "Lb")
        sup = ctx["sup"]
        day_id, ride_id = ctx["day"]["id"], ctx["ride"]["id"]
        fx.record_wind(sup, day_id, 27)
        resumed = validate_success(api.resume_ride(ride_id, {}, make_manager_headers(sup["id"])))
        assert resumed["daily_status"] == "OPEN"


class TestOrderShutdownCascade:
    def _setup_serious_incident(self, api, name):
        ctx = fx.setup_open_day(name)
        sup, clerk, op = ctx["sup"], ctx["clerk"], ctx["op"]
        prod = fx.create_product(sup, name="Credits")
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=3)
        q1 = fx.queue_redemption(op, sale["id"], ctx["ride"]["id"])
        inc = fx.file_incident(op, "operator", ctx["ride"]["id"], ctx["day"]["id"],
                               severity="SERIOUS", injury_count=1,
                               description="lap bar released mid-cycle")
        ctx.update({"sale": sale, "q1": q1, "inc": inc})
        return ctx

    def test_serious_preserves_queue_then_order_voids_it(self, api):
        """PRD section 3.7: "A `SERIOUS` report moves the ride's
        `license_status` from `LICENSED` to `SUSPENDED` and moves the
        `daily_status` of an `OPEN` or `WEATHER_HOLD` ride to `INCIDENT_HOLD`,
        preserving its queued redemptions."

        Design: Difficulty/transitive_cascade/order_shutdown_revokes_license_closes_ride_voids_queue
        """
        ctx = self._setup_serious_incident(api, "I")
        sup = ctx["sup"]
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["daily_status"] == "INCIDENT_HOLD"
        assert ride["license_status"] == "SUSPENDED"
        q1 = fx.get_redemption(sup, ctx["q1"]["id"])
        assert q1["status"] == "QUEUED", "SERIOUS must preserve the queue"

    def test_order_shutdown_depth_three_cascade(self, api):
        """PRD section 3.7: "Ordering a shutdown instead moves the report to
        `SHUTDOWN_ORDERED` and fires the heaviest cascade: the ride's
        `license_status` moves from `LICENSED` or `SUSPENDED` to `REVOKED`, its
        `daily_status` moves to `CLOSED` from `OPEN`, `WEATHER_HOLD`, or
        `INCIDENT_HOLD`, and every `QUEUED` redemption of the ride for the day
        is voided."

        Design: Difficulty/transitive_cascade/order_shutdown_revokes_license_closes_ride_voids_queue
        """
        ctx = self._setup_serious_incident(api, "Ib")
        sup = ctx["sup"]
        insp1 = ctx["inspectors"][0]
        ordered = validate_success(api.order_shutdown(
            ctx["inc"]["id"], {}, make_inspector_headers(insp1["id"])))
        assert ordered["status"] == "SHUTDOWN_ORDERED"
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["license_status"] == "REVOKED"
        assert ride["daily_status"] == "CLOSED"
        q1 = fx.get_redemption(sup, ctx["q1"]["id"])
        assert q1["status"] == "VOIDED"
        assert q1["ride_cycle_id"] is None
        sale = fx.get_sale(sup, ctx["sale"]["id"])
        assert sale["credits_redeemed"] == 0
        assert sale["credits_remaining"] == 3, (
            "QUEUED redemptions were never debited; voiding them moves no credit")


class TestMinorIncidentEscalation:
    def _setup_open(self, api, name):
        return fx.setup_open_day(name)

    def test_two_minors_leave_ride_open_third_holds(self, api):
        """PRD section 3.7: "A `MINOR` report increments the ride's
        `minor_incidents_today`, and when that counter reaches three for the
        current operating date — the threshold is inclusive, so the third minor
        incident of the day triggers while the second does nothing — a ride
        whose `daily_status` is `OPEN` or `WEATHER_HOLD` moves to
        `INCIDENT_HOLD`, with its license untouched".

        Design: Corner/errors/minor_incident_threshold_and_conditional_clear_behavior
        """
        ctx = self._setup_open(api, "ER8")
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                         injury_count=0, description="scrape reported")
        fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                         injury_count=0, description="bruise reported")
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "OPEN", (
            f"two MINORs must not hold the ride; got {ride['daily_status']}")
        assert ride["minor_incidents_today"] == 2
        fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                         injury_count=0, description="pinch reported")
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "INCIDENT_HOLD"
        assert ride["license_status"] == "LICENSED", "minor holds never touch the license"

    def test_resume_blocked_until_last_clear_and_reclear_rejected(self, api):
        """PRD section 3.7: "the incident-hold resume — again a `FairManager`
        action — requires the day's posture `OPEN` (`ERR_INVALID_DAY_POSTURE`),
        the ride `LICENSED` (`ERR_RIDE_NOT_LICENSED`), and no report for that
        ride and day remaining in `FILED` or `SHUTDOWN_ORDERED`
        (`ERR_INCIDENTS_OPEN`)" and "Clearing a report... moves the report to
        `CLEARED`, and then relaxes the ride: if no other report for the same
        ride and day remains in `FILED` or `SHUTDOWN_ORDERED`, the ride's
        `daily_status` moves from `INCIDENT_HOLD` to `CLOSED`." Also "acting
        only on `FILED` reports (`ERR_INCIDENT_INVALID_STATE`)".

        Design: Corner/errors/minor_incident_threshold_and_conditional_clear_behavior
        """
        ctx = self._setup_open(api, "ER8b")
        sup, op = ctx["sup"], ctx["op"]
        insp1 = ctx["inspectors"][0]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        i1 = fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                              injury_count=0, description="scrape reported")
        i2 = fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                              injury_count=0, description="bruise reported")
        i3 = fx.file_incident(op, "operator", ride_id, day_id, severity="MINOR",
                              injury_count=0, description="pinch reported")
        resp = api.resume_ride(ride_id, {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INCIDENTS_OPEN, 422)
        validate_success(api.clear_incident(i1["id"], {}, make_inspector_headers(insp1["id"])))
        validate_success(api.clear_incident(i2["id"], {}, make_inspector_headers(insp1["id"])))
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "INCIDENT_HOLD", (
            "ride must stay held while one report remains FILED")
        validate_success(api.clear_incident(i3["id"], {}, make_inspector_headers(insp1["id"])))
        ride = fx.get_ride(sup, ride_id)
        assert ride["daily_status"] == "CLOSED", (
            "clearing the last open incident must drop INCIDENT_HOLD to CLOSED")
        resp = api.clear_incident(i3["id"], {}, make_inspector_headers(insp1["id"]))
        validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE, 409)
