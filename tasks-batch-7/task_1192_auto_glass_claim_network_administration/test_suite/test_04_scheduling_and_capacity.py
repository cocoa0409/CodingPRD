"""Scheduling rules, bay/mobile capacity, calibration rig, no-show cycle, OCC."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error,
    ApiErrorId,
    assert_capacity_conservation,
    schedule_payload, create_calibration_event_payload,
    make_policyholder_headers, make_shop_operator_headers, make_shop, make_claim,
    add_disclosure, verify_claim, route_claim, accept_work_order,
    schedule_work_order, get_work_order, get_claim, get_policyholder,
    get_capacity,
    setup_network, setup_claim_verified,
    setup_work_order_accepted, setup_work_order_scheduled,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestSchedulePayloadSanity:
    def test_schedule_inverted_interval_invalid_request(self, api):
        """PRD §3.4: "`scheduled_end` must be strictly later than
        `scheduled_start` (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/schedule_inverted_interval_invalid_request
        """
        ctx = setup_work_order_accepted()
        wo = ctx["work_order"]
        resp = api.schedule_work_order(
            wo["id"],
            schedule_payload(wo["version"],
                             scheduled_start="2026-05-02T11:00:00Z",
                             scheduled_end="2026-05-02T10:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert get_work_order(wo["id"])["status"] == "ACCEPTED"


class TestScheduleOcc:
    def test_occ_stale_work_order_version_on_schedule(self, api):
        """PRD §2.7: "Scheduling or rescheduling a work order must carry
        `expected_work_order_version`, holding the work order `version` the
        client last observed. ... instead the stale request is rejected with
        `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_work_order_version_on_schedule
        """
        ctx = setup_work_order_accepted()
        wo = ctx["work_order"]
        v2 = wo["version"]
        scheduled = schedule_work_order(
            wo["id"], ctx["shop"]["id"],
            start="2026-05-03T10:00:00Z", end="2026-05-03T11:00:00Z",
            expected_work_order_version=v2)
        assert scheduled["status"] == "SCHEDULED"
        stale = api.schedule_work_order(
            wo["id"],
            schedule_payload(v2, scheduled_start="2026-05-03T13:00:00Z",
                             scheduled_end="2026-05-03T14:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION)
        assert get_work_order(wo["id"])["scheduled_start"] == "2026-05-03T10:00:00Z"
        current = api.schedule_work_order(
            wo["id"],
            schedule_payload(scheduled["version"],
                             scheduled_start="2026-05-03T13:00:00Z",
                             scheduled_end="2026-05-03T14:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        data = validate_success(current, 200)
        assert data["scheduled_start"] == "2026-05-03T13:00:00Z"
        assert data["version"] == scheduled["version"] + 1


class TestCapacityRead:
    def test_capacity_computed_read(self, api):
        """PRD §3.4: "Anyone can read a shop's computed capacity for a supplied
        calendar `date`, which answers `bay_minutes_total` (bay count times
        operating minutes per day), `bay_minutes_booked` (the summed durations of
        the shop's `SCHEDULED` in-shop work orders starting on that date),
        `bay_minutes_available` (the total minus the booked minutes), and
        `mobile_units_total`."

        Design: Corner/endpoints/capacity_computed_read
        """
        shop = make_shop(shop_name="Cap Read", mobile_capable=True, bay_count=2,
                         mobile_unit_count=3, operating_minutes_per_day=300)
        cap = validate_success(api.get_shop_capacity(shop["id"], "2026-05-10", ADMIN), 200)
        assert cap["bay_minutes_total"] == 600
        assert cap["bay_minutes_booked"] == 0
        assert cap["bay_minutes_available"] == 600
        assert cap["mobile_units_total"] == 3


class TestCompletionTiming:
    def test_completion_before_scheduled_start_rejected(self, api):
        """PRD §3.4: "the logical clock must have reached `scheduled_start`
        (completing earlier is rejected with
        `ERR_COMPLETION_BEFORE_SCHEDULED_START`, HTTP 422)."

        Design: Corner/validations/completion_before_scheduled_start_rejected
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
            claim_overrides={"part_category": "SIDE_GLASS"})
        # Clock is still the startup default 2026-05-01T00:00:00Z.
        resp = api.complete_work_order(
            ctx["work_order"]["id"],
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLETION_BEFORE_SCHEDULED_START)
        assert get_work_order(ctx["work_order"]["id"])["status"] == "SCHEDULED"


class TestClaimCancelCascade:
    def test_claim_cancel_from_work_authorized_cascades(self, api):
        """PRD §3.2: "Cancelling from `WORK_AUTHORIZED` cascades: every linked
        work order in `OFFERED`, `ACCEPTED`, or `SCHEDULED` moves to `CANCELLED`,
        and any that were scheduled release their reserved capacity."

        Design: Corner/state_machines/claim_cancel_from_work_authorized_cascades
        """
        ctx = setup_work_order_scheduled(
            start="2026-05-04T10:00:00Z", end="2026-05-04T12:00:00Z")
        resp = api.cancel_claim(
            ctx["claim"]["id"], {},
            make_policyholder_headers(ctx["policyholder"]["id"]))
        assert validate_success(resp, 200)["status"] == "CANCELLED"
        assert get_work_order(ctx["work_order"]["id"])["status"] == "CANCELLED"
        cap = get_capacity(ctx["shop"]["id"], "2026-05-04")
        assert cap["bay_minutes_booked"] == 0
        assert cap["bay_minutes_available"] == 480


# ---------------------------------------------------------------------------
# Difficulty: capability (P7) masks temporal (P8) on schedule
# ---------------------------------------------------------------------------

class TestConstraintMasksTemporalOnSchedule:
    def _setup(self):
        return setup_work_order_accepted()  # default shop: mobile_capable False

    def test_mobile_on_non_capable_shop_rejected(self, api):
        """PRD §3.4: "a `service_mode` of `MOBILE` requires the shop to be
        `mobile_capable` (else `ERR_SERVICE_MODE_CAPABILITY_MISMATCH`,
        HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_schedule
        """
        ctx = self._setup()
        resp = api.schedule_work_order(
            ctx["work_order"]["id"],
            schedule_payload(ctx["work_order"]["version"], service_mode="MOBILE",
                             scheduled_start="2026-05-02T10:00:00Z",
                             scheduled_end="2026-05-02T12:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SERVICE_MODE_CAPABILITY_MISMATCH)

    def test_rejected_schedule_leaves_work_order_accepted(self, api):
        """PRD §2.8: "Every request is then evaluated against the following
        ordered cascade, and a failure in an earlier category masks the
        evaluation of later categories: ... 7. **Capability and uniqueness
        constraints** ... 8. **Temporal conflicts** ..."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_schedule
        """
        ctx = self._setup()
        api.schedule_work_order(
            ctx["work_order"]["id"],
            schedule_payload(ctx["work_order"]["version"], service_mode="MOBILE",
                             scheduled_start="2026-05-02T10:00:00Z",
                             scheduled_end="2026-05-02T12:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Difficulty: mobile buffered-interval overlap
# ---------------------------------------------------------------------------

class TestMobileBufferedIntervalOverlap:
    def _setup_two_accepted(self):
        """One mobile-capable shop with a single van; two accepted work orders."""
        net = setup_network(
            shop_overrides={"mobile_capable": True, "mobile_unit_count": 1},
            with_part=False)
        ph, pol, shop = net["policyholder"], net["policy"], net["shop"]
        ctx_a = setup_claim_verified(net)
        wo_a = accept_work_order(
            route_claim(ctx_a["claim"]["id"], requested_shop_id=shop["id"])["id"],
            shop["id"])
        claim_b = make_claim(ph, pol, loss_date="2026-04-11", description="mobB")
        add_disclosure(claim_b["id"], ph["id"])
        verify_claim(claim_b["id"])
        wo_b = accept_work_order(
            route_claim(claim_b["id"], requested_shop_id=shop["id"])["id"],
            shop["id"])
        return shop, wo_a, wo_b

    def test_buffered_overlap_rejected(self, api):
        """PRD §3.4: "For mobile service, each booking occupies a buffered
        interval running from its `scheduled_start` to forty-five minutes after
        its `scheduled_end`; the new buffered interval must overlap fewer of the
        shop's other non-terminal `SCHEDULED` mobile work orders' buffered
        intervals than the shop has `mobile_unit_count` — that is, a shop with
        two vans may run at most two overlapping buffered mobile windows — and a
        violation is rejected with `ERR_MOBILE_BUFFER_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/mobile_buffered_interval_overlap
        """
        shop, wo_a, wo_b = self._setup_two_accepted()
        schedule_work_order(wo_a["id"], shop["id"], service_mode="MOBILE",
                            start="2026-05-05T10:00:00Z", end="2026-05-05T11:00:00Z")
        # Buffered interval of A: [10:00, 11:45); 11:30 start collides.
        resp = api.schedule_work_order(
            wo_b["id"],
            schedule_payload(wo_b["version"], service_mode="MOBILE",
                             scheduled_start="2026-05-05T11:30:00Z",
                             scheduled_end="2026-05-05T12:30:00Z"),
            make_shop_operator_headers(shop["id"]))
        validate_error(resp, ApiErrorId.ERR_MOBILE_BUFFER_VIOLATION)

    def test_touching_buffered_boundary_succeeds(self, api):
        """PRD §3.4: "the new buffered interval must overlap fewer of the shop's
        other non-terminal `SCHEDULED` mobile work orders' buffered intervals
        than the shop has `mobile_unit_count`". (11:45 is exactly the buffered
        end of a 10:00-11:00 job, so the intervals share no interior point.)

        Design: Difficulty/resource_temporal_overlap/mobile_buffered_interval_overlap
        """
        shop, wo_a, wo_b = self._setup_two_accepted()
        schedule_work_order(wo_a["id"], shop["id"], service_mode="MOBILE",
                            start="2026-05-05T10:00:00Z", end="2026-05-05T11:00:00Z")
        resp = api.schedule_work_order(
            wo_b["id"],
            schedule_payload(wo_b["version"], service_mode="MOBILE",
                             scheduled_start="2026-05-05T11:45:00Z",
                             scheduled_end="2026-05-05T12:45:00Z"),
            make_shop_operator_headers(shop["id"]))
        assert validate_success(resp, 200)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: calibration rig strict half-open overlap
# ---------------------------------------------------------------------------

class TestCalibrationRigOverlap:
    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.4: "a new event whose half-open window overlaps the half-open
        window of any other `SCHEDULED` calibration event of the same shop —
        intervals touching at an endpoint do not overlap — is rejected with
        `ERR_CALIBRATION_SLOT_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/calibration_rig_strict_half_open_overlap
        """
        from test_helpers import setup_calibration_event
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        setup_calibration_event(ctx, "2026-05-02T12:30:00Z", "2026-05-02T13:00:00Z")
        resp = api.create_calibration_event(
            ctx["work_order"]["id"],
            create_calibration_event_payload(
                calibration_type="DYNAMIC",
                scheduled_start="2026-05-02T12:59:00Z",
                scheduled_end="2026-05-02T13:30:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CALIBRATION_SLOT_CONFLICT)

    def test_adjacent_endpoint_allowed(self, api):
        """PRD §3.4: "intervals touching at an endpoint do not overlap".

        Design: Difficulty/resource_temporal_overlap/calibration_rig_strict_half_open_overlap
        """
        from test_helpers import setup_calibration_event
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T12:00:00Z",
            claim_overrides={"requires_adas_calibration": True,
                             "estimated_repair_cost_cents": 150000},
            shop_overrides={"adas_certified": True})
        setup_calibration_event(ctx, "2026-05-02T12:30:00Z", "2026-05-02T13:00:00Z")
        resp = api.create_calibration_event(
            ctx["work_order"]["id"],
            create_calibration_event_payload(
                calibration_type="DYNAMIC",
                scheduled_start="2026-05-02T13:00:00Z",
                scheduled_end="2026-05-02T13:30:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        assert validate_success(resp, 201)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: in-shop daily-minutes aggregate semantics
# ---------------------------------------------------------------------------

class TestInShopDailyMinutesAggregate:
    def _setup_two_accepted(self):
        net = setup_network(with_part=False)  # 1 bay, 480 min/day
        ph, pol, shop = net["policyholder"], net["policy"], net["shop"]
        ctx_a = setup_claim_verified(net)
        wo_a = accept_work_order(route_claim(ctx_a["claim"]["id"])["id"], shop["id"])
        claim_b = make_claim(ph, pol, loss_date="2026-04-11",
                             part_category="SIDE_GLASS", description="aggB")
        add_disclosure(claim_b["id"], ph["id"])
        verify_claim(claim_b["id"])
        wo_b = accept_work_order(route_claim(claim_b["id"])["id"], shop["id"])
        return shop, wo_a, wo_b

    def test_disjoint_intervals_still_conflict_in_aggregate(self, api):
        """PRD §3.4: "the total duration in minutes of the shop's non-terminal
        `SCHEDULED` in-shop work orders whose scheduled start falls on the
        calendar date of the new `scheduled_start`, plus the duration of the new
        booking, must not exceed the shop's `bay_count` multiplied by its
        `operating_minutes_per_day`; overflow is rejected with
        `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/in_shop_daily_minutes_aggregate_semantics
        """
        shop, wo_a, wo_b = self._setup_two_accepted()
        schedule_work_order(wo_a["id"], shop["id"],
                            start="2026-05-05T08:00:00Z", end="2026-05-05T13:00:00Z")
        # Disjoint clock interval but 300 + 300 = 600 > 480 in aggregate.
        resp = api.schedule_work_order(
            wo_b["id"],
            schedule_payload(wo_b["version"],
                             scheduled_start="2026-05-05T14:00:00Z",
                             scheduled_end="2026-05-05T19:00:00Z"),
            make_shop_operator_headers(shop["id"]))
        validate_error(resp, ApiErrorId.ERR_BAY_CAPACITY_EXCEEDED)

    def test_shortened_booking_fits_aggregate(self, api):
        """PRD §3.4: "must not exceed the shop's `bay_count` multiplied by its
        `operating_minutes_per_day`" (300 + 180 == 480 fits the 480 budget).

        Design: Difficulty/resource_temporal_overlap/in_shop_daily_minutes_aggregate_semantics
        """
        shop, wo_a, wo_b = self._setup_two_accepted()
        schedule_work_order(wo_a["id"], shop["id"],
                            start="2026-05-05T08:00:00Z", end="2026-05-05T13:00:00Z")
        resp = api.schedule_work_order(
            wo_b["id"],
            schedule_payload(wo_b["version"],
                             scheduled_start="2026-05-05T14:00:00Z",
                             scheduled_end="2026-05-05T17:00:00Z"),
            make_shop_operator_headers(shop["id"]))
        assert validate_success(resp, 200)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: bay capacity exact-fit boundary
# ---------------------------------------------------------------------------

class TestBayCapacityBoundary:
    def _setup_two_accepted(self):
        net = setup_network(with_part=False)  # bay_count 1, 480 min/day
        ph, pol, shop = net["policyholder"], net["policy"], net["shop"]
        ctx_a = setup_claim_verified(net)
        wo_a = accept_work_order(route_claim(ctx_a["claim"]["id"])["id"], shop["id"])
        claim_b = make_claim(ph, pol, loss_date="2026-04-11",
                             part_category="SIDE_GLASS", description="bayB",
                             estimated_repair_cost_cents=40000)
        add_disclosure(claim_b["id"], ph["id"])
        verify_claim(claim_b["id"])
        wo_b = accept_work_order(route_claim(claim_b["id"])["id"], shop["id"])
        return shop, wo_a, wo_b

    def test_exact_fit_succeeds_and_full_capacity_reported(self, api):
        """PRD §3.4: "the total duration in minutes ... must not exceed the
        shop's `bay_count` multiplied by its `operating_minutes_per_day`;
        overflow is rejected with `ERR_BAY_CAPACITY_EXCEEDED` (HTTP 409)."
        (480 == 1 x 480 is within the budget.)

        Design: Difficulty/boundary_precision_check/bay_capacity_exact_fit_vs_overflow
        """
        shop, wo_a, _wo_b = self._setup_two_accepted()
        resp = api.schedule_work_order(
            wo_a["id"],
            schedule_payload(wo_a["version"],
                             scheduled_start="2026-05-05T08:00:00Z",
                             scheduled_end="2026-05-05T16:00:00Z"),
            make_shop_operator_headers(shop["id"]))
        assert validate_success(resp, 200)["status"] == "SCHEDULED"
        cap = get_capacity(shop["id"], "2026-05-05")
        assert cap["bay_minutes_total"] == 480
        assert cap["bay_minutes_booked"] == 480
        assert cap["bay_minutes_available"] == 0

    def test_one_minute_overflow_rejected(self, api):
        """PRD §3.4: "overflow is rejected with `ERR_BAY_CAPACITY_EXCEEDED`
        (HTTP 409)." (480 + 1 > 480.)

        Design: Difficulty/boundary_precision_check/bay_capacity_exact_fit_vs_overflow
        """
        shop, wo_a, wo_b = self._setup_two_accepted()
        schedule_work_order(wo_a["id"], shop["id"],
                            start="2026-05-05T08:00:00Z", end="2026-05-05T16:00:00Z")
        resp = api.schedule_work_order(
            wo_b["id"],
            schedule_payload(wo_b["version"],
                             scheduled_start="2026-05-05T16:00:00Z",
                             scheduled_end="2026-05-05T16:01:00Z"),
            make_shop_operator_headers(shop["id"]))
        validate_error(resp, ApiErrorId.ERR_BAY_CAPACITY_EXCEEDED)


# ---------------------------------------------------------------------------
# Difficulty: bay-minutes conservation under schedule/cancel
# ---------------------------------------------------------------------------

class TestBayMinutesConservation:
    def _setup(self):
        return setup_work_order_accepted()

    def test_schedule_then_cancel_restores_availability(self, api):
        """PRD §2.9: "Shop bay minutes are conserved per shop per calendar date:
        the minutes available always equal the minutes configured minus the
        minutes booked, and schedule-then-cancel returns availability to its
        prior value with zero drift."

        Design: Difficulty/compensating_invariant/bay_minutes_conservation_schedule_cancel
        """
        ctx = self._setup()
        shop, wo = ctx["shop"], ctx["work_order"]
        before = get_capacity(shop["id"], "2026-05-06")
        assert before["bay_minutes_available"] == 480
        schedule_work_order(wo["id"], shop["id"],
                            start="2026-05-06T10:00:00Z", end="2026-05-06T12:00:00Z")
        during = get_capacity(shop["id"], "2026-05-06")
        assert during["bay_minutes_booked"] == 120
        assert during["bay_minutes_available"] == 360
        resp = api.cancel_work_order(wo["id"], {"cancel_reason": "changed"}, ADJUSTER)
        validate_success(resp, 200)
        after = get_capacity(shop["id"], "2026-05-06")
        assert after["bay_minutes_booked"] == 0
        assert after["bay_minutes_available"] == 480
        assert_capacity_conservation(after)

    def test_cancel_bubbles_claim_back_to_coverage_verified(self, api):
        """PRD §3.4: "a scheduled cancellation releases its capacity, and when
        no non-terminal work order remains the claim reverts to
        `COVERAGE_VERIFIED`."

        Design: Difficulty/compensating_invariant/bay_minutes_conservation_schedule_cancel
        """
        ctx = self._setup()
        shop, wo = ctx["shop"], ctx["work_order"]
        schedule_work_order(wo["id"], shop["id"],
                            start="2026-05-06T10:00:00Z", end="2026-05-06T12:00:00Z")
        api.cancel_work_order(wo["id"], {"cancel_reason": "changed"}, ADJUSTER)
        assert get_claim(ctx["claim"]["id"])["status"] == "COVERAGE_VERIFIED"


# ---------------------------------------------------------------------------
# Difficulty: no-show recovery cycle
# ---------------------------------------------------------------------------

class TestNoShowRescheduleCycle:
    def _setup_no_show(self):
        from test_helpers import api_client
        ctx = setup_work_order_scheduled(
            start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z")
        resp = api_client.mark_no_show(ctx["work_order"]["id"],
                                       make_shop_operator_headers(ctx["shop"]["id"]))
        ctx["work_order"] = validate_success(resp, 200)
        return ctx

    def test_no_show_releases_capacity_and_counts(self, api):
        """PRD §3.4: "Marking a customer no-show requires the work order to be
        `SCHEDULED` (else `ERR_WORK_ORDER_NOT_SCHEDULED`) and moves it to
        `NO_SHOW`: the policyholder's `no_show_count` increments by one and the
        reserved capacity is released."

        Design: Difficulty/non_linear_state_machine/work_order_no_show_reschedule_cycle
        """
        ctx = self._setup_no_show()
        assert ctx["work_order"]["status"] == "NO_SHOW"
        assert get_policyholder(ctx["policyholder"]["id"])["no_show_count"] == 1
        cap = get_capacity(ctx["shop"]["id"], "2026-05-02")
        assert cap["bay_minutes_booked"] == 0
        assert cap["bay_minutes_available"] == 480

    def test_reschedule_from_no_show_consumes_new_capacity(self, api):
        """PRD §3.4: "The no-show recovery cycle then allows the shop to
        schedule again from `NO_SHOW`."

        Design: Difficulty/non_linear_state_machine/work_order_no_show_reschedule_cycle
        """
        ctx = self._setup_no_show()
        wo = ctx["work_order"]
        resp = api.schedule_work_order(
            wo["id"],
            schedule_payload(wo["version"],
                             scheduled_start="2026-05-03T10:00:00Z",
                             scheduled_end="2026-05-03T11:00:00Z"),
            make_shop_operator_headers(ctx["shop"]["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_start"] == "2026-05-03T10:00:00Z"
        cap = get_capacity(ctx["shop"]["id"], "2026-05-03")
        assert cap["bay_minutes_booked"] == 60
