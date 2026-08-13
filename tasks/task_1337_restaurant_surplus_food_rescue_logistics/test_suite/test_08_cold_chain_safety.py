"""Cold-chain safety: pickup kill screen, interpolated danger-zone verdicts,
the inclusive 240-minute boundary, and delivery overage (PRD §3.4-§3.5)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_donor, create_agency, create_driver, add_window, create_cooler,
    create_offer, set_clock, dispatch_run, respond_run, record_pickup,
    make_volunteer_driver_headers, assert_temperature_log,
    setup_confirmed_run, setup_picked_up_run,
)

ADMIN = TEST_USERS["admin_headers"]


class TestKillTemperatureAtPickup:
    def test_kill_screen_trips_inclusively_then_safety_discard_files_nothing(self, api):
        """PRD §3.5: "For `COLD_HELD` food, a pickup reading at or above 70.0°F
        trips the screen; for `HOT_HELD` food, a reading at or below 100.0°F
        trips it. A tripped screen rejects the pickup outright with
        `ERR_SAFETY_VIOLATION_AT_PICKUP`; a clean screen is what permits
        `safety_status` to become `PROVISIONAL_COMPLIANT`."
        PRD §3.6: "a `SAFETY_REJECTED` failure discards the food but blames no
        one, moving the offer from `SCHEDULED` to `DISCARDED` and filing no
        strike;"

        Design: Corner/errors/kill_temperature_at_pickup_rejected_then_safety_discard
        """
        ctx = setup_confirmed_run(
            driver_window=("2026-08-02T09:00:00Z", "2026-08-02T19:00:00Z"))
        set_clock("2026-08-02T10:15:00Z")
        # Exactly 70.0F: the kill threshold is inclusive ("at or above").
        resp = api.record_pickup(
            ctx["run"]["id"],
            {"pickup_time": "2026-08-02T10:15:00Z", "pickup_temp_f": 70.0,
             "attestation_confirmed": True},
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION_AT_PICKUP)
        resp = api.get_rescue_run(ctx["run"]["id"], ADMIN)
        assert validate_success(resp)["run_status"] == "CONFIRMED"
        # A rejected pickup is not a success: no PICKUP log is written.
        resp = api.list_temperature_logs(ctx["run"]["id"], ADMIN)
        assert validate_success(resp) == []
        # The follow-up SAFETY_REJECTED fail discards the food, blaming no one.
        resp = api.fail_rescue_run(
            ctx["run"]["id"], {"fault_party": "NONE", "reason": "SAFETY_REJECTED"},
            make_volunteer_driver_headers(ctx["driver"]["id"]))
        run = validate_success(resp)
        assert run["run_status"] == "FAILED_PICKUP"
        resp = api.get_donation_offer(ctx["offer"]["id"], ADMIN)
        assert validate_success(resp)["status"] == "DISCARDED"
        resp = api.list_run_strike_reports(ctx["run"]["id"], ADMIN)
        assert validate_success(resp) == [], "SAFETY_REJECTED files no strike"


class TestDangerZoneInterpolationMultibranch:
    def _setup_two_hot_runs(self, api):
        """Two CONFIRMED HOT_HELD runs, both picked up at 10:15Z at 140.0F."""
        donor = create_donor(legal_name="Hot Bistro", ein="555555555",
                             contact_email="h@bistro.example")
        agency = create_agency(accepts_categories=("HOT_HELD",),
                               capacity_hot_held_lbs=50)
        v1 = create_driver(full_name="V One", email="v1@example.com",
                           cold_chain_certified=True)
        add_window(v1["id"], "2026-08-02T09:00:00Z", "2026-08-02T18:00:00Z")
        v2 = create_driver(full_name="V Two", email="v2@example.com",
                           cold_chain_certified=True)
        add_window(v2["id"], "2026-08-02T09:00:00Z", "2026-08-02T18:00:00Z")
        c1 = create_cooler(label="C1")
        c2 = create_cooler(label="C2")
        oa = create_offer(donor["id"], food_category="HOT_HELD",
                          estimated_weight_lbs=20, publish=True)
        ob = create_offer(donor["id"], food_category="HOT_HELD",
                          estimated_weight_lbs=20, publish=True)
        set_clock("2026-08-02T09:30:00Z")
        ra = dispatch_run(oa["id"], driver_id=v1["id"], agency_id=agency["id"],
                          cooler_ids=[c1["id"]])
        respond_run(ra["id"], v1["id"], "ACCEPT")
        rb = dispatch_run(ob["id"], driver_id=v2["id"], agency_id=agency["id"],
                          cooler_ids=[c2["id"]])
        respond_run(rb["id"], v2["id"], "ACCEPT")
        record_pickup(ra["id"], v1["id"], pickup_temp_f=140.0)
        record_pickup(rb["id"], v2["id"], pickup_temp_f=140.0)
        return {"donor": donor, "agency": agency, "v1": v1, "v2": v2,
                "ra": ra, "rb": rb}

    def test_hot_held_eighty_danger_minutes_compliant(self, api):
        """PRD §3.5: "The cumulative danger minutes are computed by linear
        interpolation against the category's danger threshold K (41.0 for
        `COLD_HELD`, 135.0 for `HOT_HELD`): zero when neither reading is
        dangerous; the whole span when both are dangerous; when only the arrival
        reading is dangerous, the span multiplied by the difference between T₁
        and K and divided by the difference between T₁ and T₀; and when only the
        pickup reading is dangerous, the span multiplied by the difference
        between K and T₀ and divided by the difference between T₁ and T₀."

        Design: Difficulty/combinatorial_formula/danger_zone_interpolation_multibranch
        """
        s = self._setup_two_hot_runs(api)
        set_clock("2026-08-02T12:55:00Z")
        # Span 160 min; only T1=130.0 is dangerous (< 135): the crossing sits
        # halfway, so danger = 160 * (130-135)/(130-140) = 80 <= 240.
        resp = api.record_delivery(
            s["ra"]["id"],
            {"arrival_time": "2026-08-02T12:55:00Z", "arrival_temp_f": 130.0,
             "actual_weight_lbs": 20},
            make_volunteer_driver_headers(s["v1"]["id"]))
        run = validate_success(resp)
        assert run["run_status"] == "DELIVERED"
        assert run["safety_status"] == "VERIFIED_COMPLIANT"

    def test_hot_held_three_hundred_danger_minutes_violation(self, api):
        """PRD §3.5: "The verdict is `COMPLIANT` when the danger minutes total
        no more than 240 — four hours — and the boundary is inclusive: exactly
        240 is compliant, 241 is a violation. A violation rejects the delivery
        with `ERR_SAFETY_VERDICT_VIOLATION` and persists `VERIFIED_VIOLATION` on
        the run."

        Design: Difficulty/combinatorial_formula/danger_zone_interpolation_multibranch
        """
        s = self._setup_two_hot_runs(api)
        set_clock("2026-08-02T16:55:00Z")
        # Same pickup 140.0F but a 400-minute span to 120.0F: the crossing sits
        # a quarter of the way in, so danger = 400 * (120-135)/(120-140) = 300.
        resp = api.record_delivery(
            s["rb"]["id"],
            {"arrival_time": "2026-08-02T16:55:00Z", "arrival_temp_f": 120.0,
             "actual_weight_lbs": 20},
            make_volunteer_driver_headers(s["v2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VERDICT_VIOLATION)
        resp = api.get_rescue_run(s["rb"]["id"], ADMIN)
        run = validate_success(resp)
        assert run["run_status"] == "PICKED_UP"
        assert run["safety_status"] == "VERIFIED_VIOLATION"


class TestDangerMinutesInclusiveBoundary:
    def _setup_two_cold_runs(self, api):
        """Two CONFIRMED COLD_HELD runs on one driver: RA picked up 10:15Z,
        RB picked up 13:45Z, both at 35.0F."""
        donor = create_donor(legal_name="Bound Bistro", ein="565656565",
                             contact_email="b@bistro.example")
        agency = create_agency()
        v1 = create_driver(cold_chain_certified=True)
        add_window(v1["id"], "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z")
        add_window(v1["id"], "2026-08-02T13:00:00Z", "2026-08-02T22:00:00Z")
        c1 = create_cooler(label="C1")
        c2 = create_cooler(label="C2")
        oa = create_offer(donor["id"], estimated_weight_lbs=50, publish=True)
        ob = create_offer(donor["id"], estimated_weight_lbs=50,
                          pickup_window_start="2026-08-02T13:30:00Z",
                          pickup_window_end="2026-08-02T14:30:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        ra = dispatch_run(oa["id"], driver_id=v1["id"], agency_id=agency["id"],
                          cooler_ids=[c1["id"]])
        respond_run(ra["id"], v1["id"], "ACCEPT")
        rb = dispatch_run(ob["id"], driver_id=v1["id"], agency_id=agency["id"],
                          cooler_ids=[c2["id"]])
        respond_run(rb["id"], v1["id"], "ACCEPT")
        record_pickup(ra["id"], v1["id"], pickup_temp_f=35.0)
        record_pickup(rb["id"], v1["id"], pickup_time="2026-08-02T13:45:00Z",
                      pickup_temp_f=35.0)
        return {"donor": donor, "agency": agency, "v1": v1, "ra": ra, "rb": rb}

    def test_exactly_240_danger_minutes_is_compliant(self, api):
        """PRD §3.5: "The verdict is `COMPLIANT` when the danger minutes total
        no more than 240 — four hours — and the boundary is inclusive: exactly
        240 is compliant, 241 is a violation."

        Design: Difficulty/boundary_precision_check/danger_minutes_240_inclusive_boundary
        """
        s = self._setup_two_cold_runs(api)
        set_clock("2026-08-02T18:15:00Z")
        # 480-minute span with a midpoint crossing: danger = 480 * 6/12 = 240.
        resp = api.record_delivery(
            s["ra"]["id"],
            {"arrival_time": "2026-08-02T18:15:00Z", "arrival_temp_f": 47.0,
             "actual_weight_lbs": 50},
            make_volunteer_driver_headers(s["v1"]["id"]))
        run = validate_success(resp)
        assert run["run_status"] == "DELIVERED"
        assert run["safety_status"] == "VERIFIED_COMPLIANT", (
            "exactly 240 danger minutes is compliant (inclusive boundary)"
        )

    def test_241_danger_minutes_is_violation(self, api):
        """PRD §3.5: "The verdict is `COMPLIANT` when the danger minutes total
        no more than 240 — four hours — and the boundary is inclusive: exactly
        240 is compliant, 241 is a violation. A violation rejects the delivery
        with `ERR_SAFETY_VERDICT_VIOLATION` and persists `VERIFIED_VIOLATION` on
        the run."

        Design: Difficulty/boundary_precision_check/danger_minutes_240_inclusive_boundary
        """
        s = self._setup_two_cold_runs(api)
        set_clock("2026-08-02T21:47:00Z")
        # Identical readings over a 482-minute span: danger = 482 * 6/12 = 241.
        resp = api.record_delivery(
            s["rb"]["id"],
            {"arrival_time": "2026-08-02T21:47:00Z", "arrival_temp_f": 47.0,
             "actual_weight_lbs": 50},
            make_volunteer_driver_headers(s["v1"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAFETY_VERDICT_VIOLATION)
        resp = api.get_rescue_run(s["rb"]["id"], ADMIN)
        run = validate_success(resp)
        assert run["run_status"] == "PICKED_UP"
        assert run["safety_status"] == "VERIFIED_VIOLATION"


class TestDeliveryOverageBoundary:
    def test_actual_weight_at_125_percent_ceiling_accepted_one_over_rejected(self, api):
        """PRD §3.4: "The weight must be at least one pound and no more than the
        `estimated_weight_snapshot` scaled by five-quarters and rounded up to a
        whole pound — exactly hitting that ceiling is allowed, and exceeding it
        is rejected with `ERR_DELIVERY_OVERAGE_EXCEEDED`."

        Design: Corner/calculations/delivery_overage_boundary_exact_125_percent
        """
        donor = create_donor(legal_name="OV Bistro", ein="100000012",
                             contact_email="ov@bistro.example")
        agency = create_agency(accepts_categories=("SHELF_STABLE",),
                               capacity_shelf_stable_lbs=300)
        driver = create_driver(cooler_slot_count=0)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z")
        add_window(driver["id"], "2026-08-02T13:00:00Z", "2026-08-02T18:00:00Z")
        o1 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=80, publish=True)
        o2 = create_offer(donor["id"], food_category="SHELF_STABLE",
                          estimated_weight_lbs=80,
                          pickup_window_start="2026-08-02T13:30:00Z",
                          pickup_window_end="2026-08-02T15:00:00Z", publish=True)
        set_clock("2026-08-02T09:30:00Z")
        r1 = dispatch_run(o1["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r1["id"], driver["id"], "ACCEPT")
        r2 = dispatch_run(o2["id"], driver_id=driver["id"],
                          agency_id=agency["id"])
        respond_run(r2["id"], driver["id"], "ACCEPT")
        record_pickup(r1["id"], driver["id"],
                      pickup_time="2026-08-02T10:15:00Z")
        record_pickup(r2["id"], driver["id"],
                      pickup_time="2026-08-02T13:45:00Z")
        # ceil(80 * 5/4) == 100: exactly at the ceiling is allowed.
        set_clock("2026-08-02T12:00:00Z")
        resp = api.record_delivery(
            r1["id"],
            {"arrival_time": "2026-08-02T11:30:00Z", "actual_weight_lbs": 100},
            make_volunteer_driver_headers(driver["id"]))
        assert validate_success(resp)["run_status"] == "DELIVERED"
        # 101 > 100: one pound over is rejected and the run does not advance.
        set_clock("2026-08-02T15:30:00Z")
        resp = api.record_delivery(
            r2["id"],
            {"arrival_time": "2026-08-02T15:00:00Z", "actual_weight_lbs": 101},
            make_volunteer_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERY_OVERAGE_EXCEEDED)
        resp = api.get_rescue_run(r2["id"], ADMIN)
        assert validate_success(resp)["run_status"] == "PICKED_UP"


class TestTemperatureLogImmutability:
    def test_pickup_log_fields_and_no_version_fields(self, api):
        """PRD §2.5: "Temperature logs are the one exception to this contract: a
        temperature log carries only `id` and `created_at`. Both `updated_at`
        and `version` are absent from temperature logs, because a recorded
        reading is an immutable artifact and is never edited after creation."
        PRD §3.5: "Every temperature log records the `rescue_run_id` it belongs
        to, its `point` (`PICKUP` from record-pickup, `ARRIVAL` from a
        record-delivery attempt), the `temp_f` reading, a `recorded_at` equal to
        `pickup_time` for pickup logs and to `arrival_time` for arrival logs,
        and the `recorded_by_user_id` of the caller."

        Design: Corner/entities/temperature_log_is_immutable_event
        """
        ctx = setup_picked_up_run(pickup_time="2026-08-02T10:15:00Z",
                                  pickup_temp_f=35.0)
        resp = api.list_temperature_logs(ctx["run"]["id"], ADMIN)
        logs = validate_success(resp)
        assert len(logs) == 1
        log = logs[0]
        assert_temperature_log(log)
        assert log["point"] == "PICKUP"
        assert log["temp_f"] == 35.0
        assert log["recorded_at"].startswith("2026-08-02T10:15"), (
            "recorded_at mirrors pickup_time for PICKUP logs"
        )
        assert log["recorded_by_user_id"] == ctx["driver"]["id"]
