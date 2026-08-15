"""Field delivery: rider start gates, measurement submission, district
verification, and the rework loop."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    get_allocation,
    get_order,
    get_work_order,
    make_ditch_rider_headers,
    make_water_user_headers,
    set_clock,
    setup_delivered_order,
    setup_flowing_order,
    setup_scheduled_order,
    submit_measurement,
    validate_error,
    validate_success,
    verify_work_order,
)


class TestReworkCycle:
    def _setup_submitted(self):
        # 2.0 acres x 2.0 af/acre = 4.00 af; order 3 cfs x 10 h = 2.48 af.
        scenario = setup_flowing_order(
            irrigated_acres=2.0, holder_name="Rex R", parcel_number="APN-005",
            requested_cfs=3.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
            rider_user_id="rider-9",
            clock_at="2026-06-01T09:00:00Z",
        )
        work_order = submit_measurement(
            scenario["work_order"]["id"], "rider-9",
            measured_cfs=3.0, measured_hours=10.0,
        )
        scenario["work_order"] = work_order
        assert work_order["status"] == "MEASUREMENT_SUBMITTED"
        return scenario

    def test_return_clears_measurement_and_keeps_order_flowing(self, api):
        """PRD §3.4: "Alternatively, the administrator may return the
        measurement for rework, moving the work order `MEASUREMENT_SUBMITTED →
        IN_PROGRESS`: the submitted `measured_cfs`, `measured_hours`, and
        `measured_af` are cleared to null, the supplied `return_reason` is
        recorded, and — notably — the linked turnout order remains `FLOWING`
        while the rider re-measures."

        Design: Difficulty/non_linear_state_machine/rider_measurement_rework_cycle
        """
        scenario = self._setup_submitted()
        work_order = scenario["work_order"]

        resp = api.return_work_order(
            work_order["id"], {"return_reason": "flume reading suspect"}, ADMIN,
        )
        returned = validate_success(resp, expected_status=200)
        assert returned["status"] == "IN_PROGRESS"
        assert returned["measured_af"] is None, "measured_af is cleared to null"
        assert returned["measured_cfs"] is None, "measured_cfs is cleared to null"
        assert returned["measured_hours"] is None, "measured_hours is cleared to null"
        assert returned["return_reason"] == "flume reading suspect"

        order = get_order(scenario["order"]["id"])
        assert order["status"] == "FLOWING", (
            "The linked order remains FLOWING during rework"
        )

    def test_resubmit_and_verify_posts_only_second_measurement(self, api):
        """PRD §3.4: "Verifying the measurement moves the work order
        `MEASUREMENT_SUBMITTED → VERIFIED` and, in the same stroke, delivers
        the turnout order: the order moves `FLOWING → DELIVERED`, its
        `actual_delivered_af` (null until this moment) is set to the verified
        `measured_af`, and its `over_delivered` flag is set true exactly when
        the measured volume exceeds the order's `requested_quantity_af`. The
        allocation ledger posts the delivery: `measured_af` is added to
        `delivered_af` while the order's `requested_quantity_af` is released
        from `committed_af`."
        The returned first measurement (2.48 af) is discarded; only the
        resubmitted 3.30 af (4.0 cfs x 10 h) posts.

        Design: Difficulty/non_linear_state_machine/rider_measurement_rework_cycle
        """
        scenario = self._setup_submitted()
        work_order = scenario["work_order"]
        validate_success(
            api.return_work_order(
                work_order["id"], {"return_reason": "flume reading suspect"}, ADMIN,
            )
        )

        resubmitted = submit_measurement(
            work_order["id"], "rider-9", measured_cfs=4.0, measured_hours=10.0,
        )
        assert_amount(resubmitted["measured_af"], 3.30,
                      "measured_af (4.0 cfs x 10 h x 0.0826)")
        verified = verify_work_order(work_order["id"])
        assert verified["status"] == "VERIFIED"

        order = get_order(scenario["order"]["id"])
        assert order["status"] == "DELIVERED"
        assert_amount(order["actual_delivered_af"], 3.30, "actual_delivered_af")
        assert order["over_delivered"] is True, "3.30 measured > 2.48 requested"

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["delivered_af"], 3.30,
                      "delivered_af posts exactly once (no double-post of 2.48)")
        assert_amount(allocation["committed_af"], 0.00,
                      "committed_af released at delivery")


class TestStartGates:
    def test_start_order_outside_window_rejected(self, api):
        """PRD §3.4: "Two further gates apply: the reach must be `IN_SERVICE`
        (a start attempted while the reach is `SHUTDOWN` is refused with
        `ERR_INVALID_ORDER_STATE`), and the logical clock must fall within the
        order's half-open window — at or after `requested_start_at` and
        strictly before `requested_end_at` — else
        `ERR_OUTSIDE_DELIVERY_WINDOW`."

        Design: Corner/state_machines/start_order_outside_window_rejected
        """
        scenario = setup_scheduled_order(
            holder_name="Early E", parcel_number="APN-111",
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
            rider_user_id="rider-1",
        )
        set_clock("2026-05-30T00:00:00Z")

        resp = api.start_turnout_order(
            scenario["order"]["id"], make_ditch_rider_headers("rider-1"),
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW)
        assert get_order(scenario["order"]["id"])["status"] == "SCHEDULED"

    def test_start_order_by_unassigned_rider_forbidden(self, api):
        """PRD §3.4: "Starting the order is permitted only to the rider whose
        `X-User-ID` equals the linked work order's `rider_user_id` — any other
        caller receives `ERR_FORBIDDEN`."

        Design: Corner/state_machines/start_order_by_unassigned_rider_forbidden
        """
        scenario = setup_scheduled_order(
            holder_name="Owner O", parcel_number="APN-112",
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
            rider_user_id="rider-1",
        )
        set_clock("2026-06-01T09:00:00Z")

        resp = api.start_turnout_order(
            scenario["order"]["id"], make_ditch_rider_headers("rider-2"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_order(scenario["order"]["id"])["status"] == "SCHEDULED"


class TestTerminalDelivery:
    def test_verify_work_order_twice_rejected(self, api):
        """PRD §3.4: "Verifying twice, or verifying a work order that has not
        reached `MEASUREMENT_SUBMITTED`, is refused with
        `ERR_INVALID_WORK_ORDER_STATE`."
        The delivered 2.48 af (3 cfs x 10 h) must not be posted twice.

        Design: Corner/state_machines/verify_work_order_twice_rejected
        """
        scenario = setup_delivered_order(
            holder_name="Idem I", parcel_number="APN-108",
            requested_cfs=3.0, measured_cfs=3.0, measured_hours=10.0,
            clock_at="2026-06-01T09:00:00Z",
        )
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["delivered_af"], 2.48, "delivered_af after verify")

        resp = api.verify_work_order(scenario["work_order"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WORK_ORDER_STATE)

        allocation_after = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation_after["delivered_af"], 2.48,
                      "delivered_af is not double-posted")

    def test_cancel_delivered_order_rejected(self, api):
        """PRD §3.3: "Terminal orders (`DELIVERED`, `CANCELLED`, `REJECTED`)
        accept no further transitions; attempts to schedule a non-`REQUESTED`
        order or cancel a terminal one are refused with
        `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/cancel_delivered_order_rejected
        """
        scenario = setup_delivered_order(
            holder_name="Term T", parcel_number="APN-106",
            requested_cfs=3.0, measured_cfs=3.0, measured_hours=10.0,
            clock_at="2026-06-01T09:00:00Z",
        )
        assert scenario["order"]["status"] == "DELIVERED"

        resp = api.cancel_turnout_order(
            scenario["order"]["id"],
            make_water_user_headers(scenario["account"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)

        assert get_order(scenario["order"]["id"])["status"] == "DELIVERED"
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["delivered_af"], 2.48,
                      "The delivered ledger stays posted")


class TestSegregationOfDuties:
    def test_ditchrider_cannot_verify_own_measurement(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint,
        or whose ownership check fails, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /district/rider-work-orders/{id}/verify is authorized for
        DistrictAdmin only.

        Design: Corner/rbac/ditchrider_cannot_verify_own_measurement
        """
        scenario = setup_flowing_order(
            holder_name="SoD S", parcel_number="APN-139",
            rider_user_id="rider-1", clock_at="2026-06-01T09:00:00Z",
        )
        work_order = submit_measurement(
            scenario["work_order"]["id"], "rider-1",
            measured_cfs=5.0, measured_hours=10.0,
        )
        assert work_order["status"] == "MEASUREMENT_SUBMITTED"

        resp = api.verify_work_order(
            work_order["id"], make_ditch_rider_headers("rider-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_work_order(work_order["id"])["status"] == "MEASUREMENT_SUBMITTED"
