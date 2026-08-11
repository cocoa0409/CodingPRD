"""Booking a service visit: provisional quote, initial states, window rules,
customer double-booking, battery safety ordering, allowance gating, listing."""
from test_helpers import (
    ApiErrorId,
    assert_service_request,
    get_subscription,
    make_bike,
    make_customer,
    make_subscription,
    setup_quoted_request,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestQuoteAndInitialState:
    def test_quoted_total_computed_by_server(self, api, dispatcher_headers):
        """PRD §3.4: "Every new request carries a provisional quote in
        `quoted_total_cents`, computed on the assumption of exactly the tier's
        `included_minutes` of labor and no parts."
        PRD §3.9: "a subtotal below 10000 cents pays no surcharge" and "The
        `tax_cents` is 8% of subtotal plus surcharge, rounded half up."

        Design: Corner/entities/quoted_total_computed_by_server
        """
        ctx = setup_quoted_request()
        req = ctx["request"]
        assert_service_request(req)
        # 2500 callout + 4900 base = 7400 subtotal; 7400 < 10000 so surcharge 0;
        # tax round_half_up(7400 * 0.08) = 592; total 7992.
        assert req["quoted_total_cents"] == 7992, (
            f"provisional quote must be 7992, got {req['quoted_total_cents']}")

    def test_request_created_in_initial_states(self, api, dispatcher_headers):
        """PRD §3.4: "A new request starts with `work_status` `QUOTED` and
        `billing_status` `ESTIMATED` — two independent dimensions that evolve
        separately from then on"

        Design: Corner/state_machines/request_created_in_initial_states
        """
        ctx = setup_quoted_request()
        req = ctx["request"]
        assert req["work_status"] == "QUOTED", f"work_status must start QUOTED, got {req['work_status']}"
        assert req["billing_status"] == "ESTIMATED", (
            f"billing_status must start ESTIMATED, got {req['billing_status']}")


class TestListing:
    def test_request_list_pagination_fields(self, api, dispatcher_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100." and "List
        responses carry `limit`, `offset`, `total_count`, and `has_more` in the
        `meta` object of the envelope."

        Design: Corner/entities/request_list_pagination_fields
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        validate_success(api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bike2["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T13:00:00Z", "window_end": "2026-05-02T14:00:00Z",
        }, dispatcher_headers), 201)

        data, meta = validate_paginated(api.list_service_requests(
            dispatcher_headers, params={"customer_id": ctx["customer"]["id"]}))
        assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["has_more"] is False
        assert len(data) == 2

        data1, meta1 = validate_paginated(api.list_service_requests(
            dispatcher_headers, params={"customer_id": ctx["customer"]["id"], "limit": 1}))
        assert len(data1) == 1, f"limit=1 must return 1 item, got {len(data1)}"
        assert meta1["has_more"] is True

    def test_list_filter_by_work_status(self, api, dispatcher_headers):
        """PRD §3.4: "Requests are listable with filters for `customer_id`,
        `bike_id`, `zone_id`, `tier_id`, `subscription_id`,
        `scheduled_mechanic_id`, `callback_of_id`, and `work_status`."

        Design: Corner/cross_cutting_layers/list_filter_by_work_status
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        req2 = validate_success(api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bike2["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T13:00:00Z", "window_end": "2026-05-02T14:00:00Z",
        }, dispatcher_headers), 201)
        validate_success(api.service_request_event(
            ctx["request"]["id"], {"event_type": "CANCEL"}, dispatcher_headers), 200)

        data, meta = validate_paginated(api.list_service_requests(
            dispatcher_headers,
            params={"customer_id": ctx["customer"]["id"], "work_status": "CANCELLED"}))
        assert meta["total_count"] == 1, f"filtered total_count must be 1, got {meta['total_count']}"
        assert data[0]["id"] == ctx["request"]["id"]
        assert data[0]["work_status"] == "CANCELLED"

        _, meta_all = validate_paginated(api.list_service_requests(
            dispatcher_headers, params={"customer_id": ctx["customer"]["id"]}))
        assert meta_all["total_count"] == 2, f"unfiltered total_count must be 2, got {meta_all['total_count']}"


class TestWindowValidation:
    def test_window_too_short_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "`window_end` minus `window_start` must be at least 30 minutes
        and at most 4 hours, and `window_start` must not precede the current
        logical clock; violations yield `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/validations/window_too_short_rejected
        """
        ctx = setup_quoted_request()
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": ctx["bike"]["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T10:20:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


class TestSubscriptionBookingRules:
    def test_subscription_window_outside_period_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "the `window_start` must fall within the inclusive
        [`period_start`, `period_end`] coverage period (`ERR_SUBSCRIPTION_PERIOD`,
        HTTP 422)"

        Design: Corner/validations/subscription_window_outside_period_rejected
        """
        ctx = setup_quoted_request(customer_kind="FLEET", subscription={})
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": ctx["bike"]["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "subscription_id": ctx["subscription"]["id"],
            "window_start": "2026-06-01T10:00:00Z", "window_end": "2026-06-01T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_PERIOD)

    def test_suspended_subscription_booking_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "the subscription must be `ACTIVE` or `PAST_DUE`
        (`ERR_SUBSCRIPTION_INACTIVE`, HTTP 409)"

        Design: Corner/validations/suspended_subscription_booking_rejected
        """
        cust = make_customer("FLEET")
        sub = make_subscription(cust["id"], included_tunes_per_period=4, discount_pct=0.10)
        validate_success(api.subscription_event(sub["id"], {"event_type": "SUSPEND"}, dispatcher_headers), 200)

        ctx = setup_quoted_request()
        bike = make_bike(cust["id"])
        resp = api.create_service_request({
            "customer_id": cust["id"], "bike_id": bike["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "subscription_id": sub["id"],
            "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T11:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_INACTIVE)


class TestOwnership:
    def test_request_with_unowned_bike_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "the bike's `customer_id` must equal the request's
        `customer_id` or the booking fails with `ERR_BIKE_NOT_OWNED` (HTTP 403)"

        Design: Corner/validations/request_with_unowned_bike_rejected
        """
        ctx = setup_quoted_request()
        bob = make_customer("INDIVIDUAL")
        bobs_bike = make_bike(bob["id"])
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bobs_bike["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T13:00:00Z", "window_end": "2026-05-02T14:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_BIKE_NOT_OWNED)


class TestRescheduleOcc:
    def test_occ_stale_reschedule_returns_412(self, api, dispatcher_headers):
        """PRD §2.7: "Moving a booked request's arrival window requires
        `expected_service_request_version` matching the service request's current
        `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.4: "The reschedule call carries the new `window_start` and
        `window_end` plus the OCC field `expected_service_request_version` (§2.7),
        re-validates window shape and customer double-booking under the same rules
        as creation, and increments the request's `version` by one."

        Design: Corner/cross_cutting_layers/occ_stale_reschedule_returns_412
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        req = ctx["request"]

        first = validate_success(api.reschedule_service_request(req["id"], {
            "window_start": "2026-05-03T10:00:00Z", "window_end": "2026-05-03T11:00:00Z",
            "expected_service_request_version": req["version"],
        }, dispatcher_headers), 200)
        assert first["version"] == req["version"] + 1, (
            f"reschedule must bump version to {req['version'] + 1}, got {first['version']}")

        stale = api.reschedule_service_request(req["id"], {
            "window_start": "2026-05-04T10:00:00Z", "window_end": "2026-05-04T11:00:00Z",
            "expected_service_request_version": req["version"],
        }, dispatcher_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_service_request(req["id"], dispatcher_headers), 200)
        assert after["window_start"] == "2026-05-03T10:00:00Z", (
            f"stale reschedule must not move the window, got {after['window_start']}")


class TestCustomerWindowOverlapSemantics:
    def test_touching_window_end_conflicts(self, api, dispatcher_headers):
        """PRD §3.4: "two requests of the same customer conflict when both are in
        a live state — `QUOTED`, `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or
        `ON_HOLD_PARTS` — and their windows overlap as closed intervals with no
        buffer, meaning the new `window_start` is at or before the existing
        `window_end` and the existing `window_start` is at or before the new
        `window_end`; touching endpoints conflict, so a window beginning exactly
        when another ends is refused with `ERR_CUSTOMER_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/customer_closed_interval_touch_conflicts
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bike2["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T11:00:00Z", "window_end": "2026-05-02T12:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_WINDOW_OVERLAP)

    def test_one_second_past_window_end_allowed(self, api, dispatcher_headers):
        """PRD §3.4: "the new `window_start` is at or before the existing
        `window_end` and the existing `window_start` is at or before the new
        `window_end`; touching endpoints conflict, so a window beginning exactly
        when another ends is refused with `ERR_CUSTOMER_WINDOW_OVERLAP` (HTTP 409)."
        A start one second after the existing end is not "at or before" it, so no
        conflict exists and booking succeeds.

        Design: Difficulty/resource_temporal_overlap/customer_closed_interval_touch_conflicts
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bike2["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T11:00:01Z", "window_end": "2026-05-02T12:00:01Z",
        }, dispatcher_headers)
        data = validate_success(resp, 201)
        assert data["work_status"] == "QUOTED"


class TestBatterySafetyPrecedence:
    def test_battery_safety_beats_customer_window_overlap(self, api, dispatcher_headers):
        """PRD §3.4: "Booking enforces its checks in this order. E-bike battery
        safety comes first: a request for an `EBIKE` bike requires
        `battery_certified` to be true and `battery_health_pct` to be at least 70,
        failing with `ERR_BATTERY_SAFETY` (HTTP 422) otherwise."

        Design: Difficulty/priority_pair_validation_conflict/battery_safety_beats_customer_window_overlap
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        weak_ebike = make_bike(ctx["customer"]["id"], bike_type="EBIKE", battery_wh=500,
                               battery_certified=True, battery_health_pct=50)
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": weak_ebike["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T10:30:00Z", "window_end": "2026-05-02T11:30:00Z",
        }, dispatcher_headers)
        # Both battery safety and customer overlap fail; safety is checked first.
        validate_error(resp, ApiErrorId.ERR_BATTERY_SAFETY)

    def test_overlap_fires_when_battery_healthy(self, api, dispatcher_headers):
        """PRD §3.4: "E-bike battery safety comes first: a request for an `EBIKE`
        bike requires `battery_certified` to be true and `battery_health_pct` to
        be at least 70, failing with `ERR_BATTERY_SAFETY` (HTTP 422) otherwise."
        PRD §3.4: "Then comes customer double-booking" — a healthy e-bike whose
        window overlaps an existing live request surfaces
        `ERR_CUSTOMER_WINDOW_OVERLAP` (HTTP 409).

        Design: Difficulty/priority_pair_validation_conflict/battery_safety_beats_customer_window_overlap
        """
        ctx = setup_quoted_request(window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        healthy_ebike = make_bike(ctx["customer"]["id"], bike_type="EBIKE", battery_wh=500,
                                  battery_certified=True, battery_health_pct=95)
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": healthy_ebike["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "window_start": "2026-05-02T10:30:00Z", "window_end": "2026-05-02T11:30:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_WINDOW_OVERLAP)


class TestAllowanceExhaustionBoundary:
    def test_last_allowance_unit_bookable(self, api, dispatcher_headers):
        """PRD §3.4: "at least one allowance unit must remain
        (`ERR_ALLOWANCE_EXHAUSTED`, HTTP 422, per §3.5). On success with coverage,
        the request's `covered_by_subscription` is set true and the subscription's
        reservation counter rises by one."

        Design: Difficulty/boundary_precision_check/allowance_exhaustion_boundary
        """
        ctx = setup_quoted_request(
            customer_kind="FLEET",
            subscription={"included_tunes_per_period": 1, "discount_pct": 0.10},
            window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        # allowance_remaining was exactly 1; >= 1 holds, so the booking succeeds.
        assert ctx["request"]["covered_by_subscription"] is True
        sub = get_subscription(ctx["subscription"]["id"])
        assert sub["allowance_reserved"] == 1
        assert sub["allowance_remaining"] == 0

    def test_zero_allowance_remaining_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "at least one allowance unit must remain
        (`ERR_ALLOWANCE_EXHAUSTED`, HTTP 422, per §3.5)"

        Design: Difficulty/boundary_precision_check/allowance_exhaustion_boundary
        """
        ctx = setup_quoted_request(
            customer_kind="FLEET",
            subscription={"included_tunes_per_period": 1, "discount_pct": 0.10},
            window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        bike2 = make_bike(ctx["customer"]["id"])
        resp = api.create_service_request({
            "customer_id": ctx["customer"]["id"], "bike_id": bike2["id"],
            "zone_id": ctx["zone"]["id"], "tier_id": ctx["tier"]["id"],
            "subscription_id": ctx["subscription"]["id"],
            "window_start": "2026-05-02T13:00:00Z", "window_end": "2026-05-02T14:00:00Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_ALLOWANCE_EXHAUSTED)
