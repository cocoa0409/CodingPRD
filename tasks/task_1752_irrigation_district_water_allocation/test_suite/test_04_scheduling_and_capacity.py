"""Scheduling gates: work-order creation, reach capacity, maintenance-window
conflict priority, and the suspended-account gate."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_rider_work_order,
    create_account,
    create_allocation,
    create_turnout_order_payload,
    create_window,
    get_account,
    get_allocation,
    get_order,
    make_water_user_headers,
    pay_invoice,
    place_order,
    schedule_order,
    setup_open_season_with_allocation,
    suspend_account_via_lien,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestScheduleSuccess:
    def test_schedule_response_immediately_consistent(self, api):
        """PRD §3.3: "When all gates pass, the order moves `REQUESTED →
        SCHEDULED` and a `RiderWorkOrder` is created in one stroke — its
        `turnout_order_id` pointing at this order, its `rider_user_id` taken
        from the scheduling input, its status `ASSIGNED`."

        Design: Corner/endpoints/schedule_response_immediately_consistent
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Imm I", parcel_number="APN-133",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
        )

        resp = api.schedule_turnout_order(order["id"], {"rider_user_id": "rider-7"}, ADMIN)
        scheduled = validate_success(resp, expected_status=200)
        assert scheduled["status"] == "SCHEDULED", (
            "The schedule response itself carries the new status"
        )

        data, meta = validate_paginated(
            api.list_rider_work_orders(ADMIN, params={"turnout_order_id": order["id"]})
        )
        assert meta["total_count"] == 1, "Exactly one work order is created"
        assert_rider_work_order(data[0])
        assert data[0]["status"] == "ASSIGNED"
        assert data[0]["rider_user_id"] == "rider-7"
        assert data[0]["turnout_order_id"] == order["id"]


class TestReachCapacity:
    def test_reach_capacity_aggregate_overlap(self, api):
        """PRD §3.3: "Capacity is then enforced instant-by-instant: at every
        instant of the requested window, the sum of `requested_cfs` over the
        reach's other `SCHEDULED` or `FLOWING` orders overlapping that
        instant, plus this order's own `requested_cfs`, must not exceed the
        reach's `max_capacity_cfs`, else `ERR_REACH_CAPACITY_EXCEEDED`."
        Two overlapping 3 cfs orders fit under the 10 cfs cap; a third
        overlapping 5 cfs order would push the instantaneous sum to 11.

        Design: Corner/calculations/reach_capacity_aggregate_overlap
        """
        season = setup_open_season_with_allocation(
            irrigated_acres=100.0, holder_name="Agg A", parcel_number="APN-122",
            reach_capacity_cfs=10.0,
        )
        reach_id = season["reach"]["id"]
        season_id = season["season"]["id"]

        account_b = create_account(
            holder_name="Agg B", parcel_number="APN-123", irrigated_acres=100.0,
        )
        alloc_b = create_allocation(account_b["id"], season_id)
        account_c = create_account(
            holder_name="Agg C", parcel_number="APN-124", irrigated_acres=100.0,
        )
        alloc_c = create_allocation(account_c["id"], season_id)

        order_a = place_order(
            season["account"]["id"], season["allocation"]["id"], reach_id,
            requested_cfs=3.0,
            start="2026-07-01T08:00:00Z", end="2026-07-01T18:00:00Z",
        )
        schedule_order(order_a["id"], "rider-1")
        order_b = place_order(
            account_b["id"], alloc_b["id"], reach_id,
            requested_cfs=3.0,
            start="2026-07-01T08:00:00Z", end="2026-07-01T18:00:00Z",
        )
        schedule_order(order_b["id"], "rider-2")
        # Instantaneous sum of the two overlapping SCHEDULED orders is 6 <= 10.
        order_c = place_order(
            account_c["id"], alloc_c["id"], reach_id,
            requested_cfs=5.0,
            start="2026-07-01T10:00:00Z", end="2026-07-01T20:00:00Z",
        )

        resp = api.schedule_turnout_order(order_c["id"], {"rider_user_id": "rider-3"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REACH_CAPACITY_EXCEEDED)
        assert get_order(order_c["id"])["status"] == "REQUESTED", (
            "The rejected order remains REQUESTED"
        )


class TestSchedulePriorityAndStateGates:
    def _setup_window_and_capacity_conflict(self):
        """One order whose schedule violates both the maintenance-window
        overlap rule and the reach capacity rule."""
        scenario = setup_open_season_with_allocation(
            irrigated_acres=100.0, holder_name="Cap K", parcel_number="APN-011",
            reach_capacity_cfs=5.0,
        )
        # Created while no maintenance window exists yet.
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=6.0,
            start="2026-07-10T08:00:00Z", end="2026-07-10T18:00:00Z",
        )
        create_window(
            scenario["reach"]["id"],
            start_at="2026-07-10T12:00:00Z", end_at="2026-07-10T20:00:00Z",
            reason="gate replacement",
        )
        scenario["order"] = order
        return scenario

    def test_schedule_temporal_beats_capacity(self, api):
        """PRD §2.7: "When several checks could fail on the same request, the
        server reports the first failure in this fixed evaluation order:" with
        "8. **Temporal conflicts** — window-vs-order conflicts, turnaround
        gaps, and clock-window checks, else the appropriate 422 code." ahead
        of "9. **Uniqueness and capacity** — duplicate season years, duplicate
        allocations or invoices per (account, season), and reach instantaneous
        capacity, else the appropriate 409 or 422 code."
        PRD §3.3: "no `PLANNED` or `ACTIVE` maintenance window on that reach
        may overlap the order's half-open window, else
        `ERR_WINDOW_TIME_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_capacity
        """
        scenario = self._setup_window_and_capacity_conflict()
        resp = api.schedule_turnout_order(
            scenario["order"]["id"], {"rider_user_id": "rider-1"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_TIME_CONFLICT)

    def test_schedule_conflict_leaves_order_requested(self, api):
        """PRD §3.3: "Capacity is then enforced instant-by-instant ... else
        `ERR_REACH_CAPACITY_EXCEEDED`" and "no `PLANNED` or `ACTIVE`
        maintenance window on that reach may overlap the order's half-open
        window, else `ERR_WINDOW_TIME_CONFLICT`."
        A schedule rejected by the temporal-first evaluation changes nothing:
        the order stays REQUESTED and no work order is created.

        Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_capacity
        """
        scenario = self._setup_window_and_capacity_conflict()
        resp = api.schedule_turnout_order(
            scenario["order"]["id"], {"rider_user_id": "rider-1"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_TIME_CONFLICT)

        assert get_order(scenario["order"]["id"])["status"] == "REQUESTED"
        _data, meta = validate_paginated(
            api.list_rider_work_orders(
                ADMIN, params={"turnout_order_id": scenario["order"]["id"]},
            )
        )
        assert meta["total_count"] == 0, "No work order may be created by the rejection"


class TestSuspendedAccountGates:
    def _setup_suspended_with_order(self, irrigated_acres=5.0):
        scenario = setup_open_season_with_allocation(
            irrigated_acres=irrigated_acres,
            holder_name="Gate G", parcel_number="APN-014",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        invoice = suspend_account_via_lien(
            scenario["account"]["id"], scenario["season"]["id"],
        )
        scenario.update({"order": order, "invoice": invoice})
        return scenario

    def test_order_schedule_blocked_by_suspended_account(self, api):
        """PRD §3.8: "A `SUSPENDED` account is barred from new turnout orders
        and new transfer requests — order creation and scheduling, and
        transfer creation, approval, and posting, all fail with
        `ERR_ACCOUNT_NOT_ACTIVE` while the hold stands."

        Design: Difficulty/cross_entity_state_dependency/order_schedule_blocked_by_suspended_account
        """
        scenario = self._setup_suspended_with_order()
        assert get_account(scenario["account"]["id"])["status"] == "SUSPENDED"

        resp = api.schedule_turnout_order(
            scenario["order"]["id"], {"rider_user_id": "rider-1"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)
        assert get_order(scenario["order"]["id"])["status"] == "REQUESTED", (
            "Scheduling is gated by the account's state, not the order's"
        )

    def test_schedule_allowed_again_after_lien_released(self, api):
        """PRD §3.8: "Paying a `LIEN_FILED` invoice additionally releases the
        lien hold: if no other `LIEN_FILED` invoice remains for the account,
        the account's status returns to `ACTIVE` and its `version` increments
        by 1."
        PRD §3.3: "Scheduling re-checks that the account is `ACTIVE` and the
        season `OPEN`..." — with the hold lifted, the same order schedules.

        Design: Difficulty/cross_entity_state_dependency/order_schedule_blocked_by_suspended_account
        """
        scenario = self._setup_suspended_with_order()
        account_id = scenario["account"]["id"]
        assert get_account(account_id)["status"] == "SUSPENDED"

        paid = pay_invoice(scenario["invoice"]["id"], account_id)
        assert paid["status"] == "PAID"
        assert get_account(account_id)["status"] == "ACTIVE", (
            "Paying the only liened invoice releases the hold"
        )

        order, work_order = schedule_order(scenario["order"]["id"], "rider-1")
        assert order["status"] == "SCHEDULED"
        assert work_order["status"] == "ASSIGNED"

    def _setup_suspended_small_account(self):
        scenario = setup_open_season_with_allocation(
            irrigated_acres=1.0, holder_name="Dual D", parcel_number="APN-010",
        )
        suspend_account_via_lien(
            scenario["account"]["id"], scenario["season"]["id"],
        )
        return scenario

    def test_order_create_state_beats_fiscal(self, api):
        """PRD §2.7: "When several checks could fail on the same request, the
        server reports the first failure in this fixed evaluation order:" with
        "6. **Lifecycle state** — the target entity is in a valid from-state
        for the transition and cross-entity state gates hold (account
        `ACTIVE`, season `OPEN`, reach `IN_SERVICE`), else the appropriate
        `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_SEASON_NOT_OPEN`, or
        `ERR_INVALID_*_STATE` code." ahead of "10. **Sufficient water** — the
        quantity requested fits within the available balance, else
        `ERR_INSUFFICIENT_ALLOCATION`."
        The suspended account's 4.13 af request also exceeds its 2.00 af
        balance, yet the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_fiscal
        """
        scenario = self._setup_suspended_small_account()
        account = get_account(scenario["account"]["id"])
        assert account["status"] == "SUSPENDED"

        resp = api.create_turnout_order(
            create_turnout_order_payload(
                account["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=account["version"],
                requested_cfs=5.0,
                requested_start_at="2026-08-20T08:00:00Z",
                requested_end_at="2026-08-20T18:00:00Z",
            ),
            make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)

    def test_rejected_dual_violation_commits_nothing(self, api):
        """PRD §3.3: "Creation is refused when the account is not `ACTIVE`
        (`ERR_ACCOUNT_NOT_ACTIVE`) ... or when `requested_quantity_af` exceeds
        the allocation's `available_af` on the net-of-committed reading
        (`ERR_INSUFFICIENT_ALLOCATION`)."
        The refused create commits no water: committed_af stays 0.00.

        Design: Difficulty/priority_pair_validation_conflict/order_create_state_beats_fiscal
        """
        scenario = self._setup_suspended_small_account()
        account = get_account(scenario["account"]["id"])
        resp = api.create_turnout_order(
            create_turnout_order_payload(
                account["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=account["version"],
                requested_cfs=5.0,
                requested_start_at="2026-08-20T08:00:00Z",
                requested_end_at="2026-08-20T18:00:00Z",
            ),
            make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE)

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 0.00,
                      "No water is committed by the rejected request")
