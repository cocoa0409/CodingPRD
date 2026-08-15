"""Turnout order placement: quantity computation, balance boundary,
turnaround gap, commitment conservation, filtered listing, and OCC."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    assert_turnout_order,
    create_account,
    create_allocation,
    create_turnout_order_payload,
    get_account,
    get_allocation,
    get_order,
    get_work_order,
    make_water_user_headers,
    place_order,
    schedule_order,
    setup_open_season_with_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderQuantity:
    def test_order_quantity_half_up_rounding(self, api):
        """PRD §3.3: "At creation the order's `requested_quantity_af` is
        computed: the window's length in hours — the difference between
        `requested_end_at` and `requested_start_at` measured in seconds and
        divided by 3600 — is multiplied by `requested_cfs` and by the 0.0826
        conversion factor, and the product is rounded half-up to 2 decimal
        places."
        (3.0 cfs x 7 h x 0.0826 = 1.7346, rounding half-up to 1.73.)

        Design: Corner/calculations/order_quantity_half_up_rounding
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Round R", parcel_number="APN-116",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=3.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T15:00:00Z",
        )
        assert_turnout_order(order)
        assert_amount(order["requested_quantity_af"], 1.73,
                      "requested_quantity_af (round-half-up of 1.7346)")


class TestAvailableBalanceBoundary:
    def _setup_edge_account(self):
        # 2.065 acres x 2.0 af/acre = exactly 4.13 af of base entitlement.
        return setup_open_season_with_allocation(
            irrigated_acres=2.065, holder_name="Edge E", parcel_number="APN-012",
        )

    def test_order_exactly_equal_to_available_is_accepted(self, api):
        """PRD §3.3: "Creation is refused when ... `requested_quantity_af`
        exceeds the allocation's `available_af` on the net-of-committed
        reading (`ERR_INSUFFICIENT_ALLOCATION`)."
        A request exactly equal to available does not exceed it, so it is
        accepted: 5 cfs x 10 h x 0.0826 = 4.13 af against 4.13 available.

        Design: Difficulty/boundary_precision_check/order_quantity_exactly_equals_available
        """
        scenario = self._setup_edge_account()
        resp = api.create_turnout_order(
            create_turnout_order_payload(
                scenario["account"]["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=scenario["account"]["version"],
                requested_cfs=5.0,
                requested_start_at="2026-06-01T08:00:00Z",
                requested_end_at="2026-06-01T18:00:00Z",
            ),
            make_water_user_headers(scenario["account"]["id"]),
        )
        order = validate_success(resp, expected_status=201)
        assert_amount(order["requested_quantity_af"], 4.13,
                      "requested_quantity_af (5 cfs x 10 h)")
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 4.13, "committed_af")
        assert_amount(allocation["available_af"], 0.00,
                      "available_af after the boundary-equal order")

    def test_order_beyond_exhausted_balance_rejected(self, api):
        """PRD §3.3: "Creation is refused when ... `requested_quantity_af`
        exceeds the allocation's `available_af` on the net-of-committed
        reading (`ERR_INSUFFICIENT_ALLOCATION`)."
        After the 4.13 af boundary order drains the balance to 0.00, a
        follow-up 0.08 af order (1 cfs x 1 h) exceeds it.

        Design: Difficulty/boundary_precision_check/order_quantity_exactly_equals_available
        """
        scenario = self._setup_edge_account()
        place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        account = get_account(scenario["account"]["id"])
        resp = api.create_turnout_order(
            create_turnout_order_payload(
                account["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=account["version"],
                requested_cfs=1.0,
                requested_start_at="2026-06-02T08:00:00Z",
                requested_end_at="2026-06-02T09:00:00Z",
            ),
            make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION)


class TestTurnaroundGap:
    def _setup_turnaround_account(self):
        scenario = setup_open_season_with_allocation(
            irrigated_acres=10.0, holder_name="Turn T", parcel_number="APN-017",
        )
        # Order 1: [06:00, 10:00) — 5 cfs x 4 h = 1.65 af.
        order1 = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-08-12T06:00:00Z", end="2026-08-12T10:00:00Z",
        )
        scenario["order1"] = order1
        return scenario

    def test_five_hour_gap_rejected(self, api):
        """PRD §2.8: "Turnout orders placed by the same account must respect a
        turnaround gap: between any two non-terminal orders of the same
        account, the gap between their delivery windows must be at least 6
        hours; a gap of exactly 6 hours is permitted."
        PRD §3.3: creation is refused "when the window fails the
        turnaround-gap rule against the account's other non-terminal orders
        (`ERR_ORDER_TURNAROUND_CONFLICT`)".
        A second order starting 5 hours after the first ends violates the gap.

        Design: Difficulty/resource_temporal_overlap/account_order_turnaround_buffer
        """
        scenario = self._setup_turnaround_account()
        account = get_account(scenario["account"]["id"])
        resp = api.create_turnout_order(
            create_turnout_order_payload(
                account["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=account["version"],
                requested_cfs=5.0,
                requested_start_at="2026-08-12T15:00:00Z",
                requested_end_at="2026-08-12T18:00:00Z",
            ),
            make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_TURNAROUND_CONFLICT)

    def test_exactly_six_hour_gap_allowed(self, api):
        """PRD §2.8: "Turnout orders placed by the same account must respect a
        turnaround gap: between any two non-terminal orders of the same
        account, the gap between their delivery windows must be at least 6
        hours; a gap of exactly 6 hours is permitted."
        The order starting exactly 6 hours after order 1 ends is created, and
        committed_af becomes 1.65 + 1.24 = 2.89 af.

        Design: Difficulty/resource_temporal_overlap/account_order_turnaround_buffer
        """
        scenario = self._setup_turnaround_account()
        order3 = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-08-12T16:00:00Z", end="2026-08-12T19:00:00Z",
        )
        assert_amount(order3["requested_quantity_af"], 1.24,
                      "requested_quantity_af (5 cfs x 3 h)")
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 2.89,
                      "committed_af (1.65 + 1.24; nothing else committed)")


class TestCommitmentLifecycle:
    def test_create_then_schedule_keeps_commitment(self, api):
        """PRD §3.2: "`committed_af` sums `requested_quantity_af` over the
        allocation's orders whose status is `REQUESTED`, `SCHEDULED`, or
        `FLOWING` — water reserved but not yet delivered."
        PRD §3.3: "That quantity is immediately committed: it is added to the
        allocation's `committed_af`, the account's `version` increments by 1,
        and the order is born `REQUESTED`."
        Create commits 4.13 af (available 10.00 -> 5.87); scheduling keeps the
        water committed.

        Design: Difficulty/compensating_invariant/committed_water_schedule_cancel_conservation
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Conserve C", parcel_number="APN-018",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 4.13, "committed_af after create")
        assert_amount(allocation["available_af"], 5.87, "available_af after create")

        order, work_order = schedule_order(order["id"], "rider-1")
        assert order["status"] == "SCHEDULED"
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 4.13,
                      "committed_af while SCHEDULED (still non-terminal)")

    def test_cancel_restores_commitment_exactly(self, api):
        """PRD §3.3: "Both paths release the order's `requested_quantity_af`
        from the allocation's `committed_af`, and cancelling a `SCHEDULED`
        order additionally cascades `CANCELLED` onto its linked work order
        when that work order is still `ASSIGNED` or `IN_PROGRESS`."
        After create (4.13) + schedule + cancel, committed_af is 0.00 and
        available_af is 10.00 — identical to before the create.

        Design: Difficulty/compensating_invariant/committed_water_schedule_cancel_conservation
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Conserve C", parcel_number="APN-018",
        )
        account_id = scenario["account"]["id"]
        order = place_order(
            account_id, scenario["allocation"]["id"], scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T18:00:00Z",
        )
        order, work_order = schedule_order(order["id"], "rider-1")

        resp = api.cancel_turnout_order(order["id"], make_water_user_headers(account_id))
        cancelled = validate_success(resp, expected_status=200)
        assert cancelled["status"] == "CANCELLED"

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 0.00,
                      "committed_af after cancellation (fully released)")
        assert_amount(allocation["available_af"], 10.00,
                      "available_af restored to the pre-create value")
        assert get_order(order["id"])["status"] == "CANCELLED"
        assert get_work_order(work_order["id"])["status"] == "CANCELLED", (
            "The linked work order is cascade-cancelled"
        )


class TestOrderRejection:
    def test_reject_order_releases_committed(self, api):
        """PRD §3.3: "An administrator may reject a `REQUESTED` order, moving
        it `REQUESTED → REJECTED`; alternatively, the administrator or the
        owning irrigator may cancel a `REQUESTED` or `SCHEDULED` order, moving
        it to `CANCELLED`. Both paths release the order's
        `requested_quantity_af` from the allocation's `committed_af`..."
        The 0.83 af order (5 cfs x 2 h) is released in full.

        Design: Corner/state_machines/reject_order_releases_committed
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Rej R", parcel_number="APN-115",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
            requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T10:00:00Z",
        )
        assert_amount(order["requested_quantity_af"], 0.83,
                      "requested_quantity_af (5 cfs x 2 h)")

        resp = api.reject_turnout_order(order["id"], ADMIN)
        rejected = validate_success(resp, expected_status=200)
        assert rejected["status"] == "REJECTED"

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["committed_af"], 0.00,
                      "committed_af after rejection")
        assert_amount(allocation["available_af"], 10.00,
                      "available_af after the 0.83 af release")


class TestOrderListing:
    def test_filtered_orders_list_by_account(self, api):
        """PRD §4: "GET /district/turnout-orders — List turnout orders
        (filterable by `water_account_id`, `season_allocation_id`,
        `canal_reach_id`, `status`)".
        The filtered list returns only the queried account's orders.

        Design: Corner/endpoints/filtered_orders_list_by_account
        """
        scenario = setup_open_season_with_allocation(
            holder_name="List A", parcel_number="APN-134",
        )
        # Second account in the same season with its own allocation.
        account_c = create_account(
            holder_name="List B", parcel_number="APN-135",
            water_right_priority_date="1890-01-01T00:00:00Z",
        )
        alloc_c = create_allocation(account_c["id"], scenario["season"]["id"])

        order_a = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"],
        )
        order_b = place_order(
            account_c["id"], alloc_c["id"], scenario["reach"]["id"],
        )

        data, meta = validate_paginated(
            api.list_turnout_orders(
                ADMIN, params={"water_account_id": scenario["account"]["id"]},
            )
        )
        assert meta["total_count"] == 1, "Filtered list must contain exactly one order"
        ids = [row["id"] for row in data]
        assert order_a["id"] in ids
        assert order_b["id"] not in ids, (
            "The other account's order must be absent from the filtered result"
        )


class TestOrderCreateOCC:
    def test_occ_stale_version_on_order_create(self, api):
        """PRD §2.6: "Placing a turnout order must carry
        `expected_water_account_version` equal to the current `version` of the
        referenced `WaterAccount`. If the account's version has advanced since
        the client last read it — for example because another order was
        created against the account or a lien transition touched it — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)..."
        PRD §3.3: "...the account's `version` increments by 1, and the order
        is born `REQUESTED`."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_order_create
        """
        scenario = setup_open_season_with_allocation(
            irrigated_acres=10.0, holder_name="OCC O", parcel_number="APN-140",
        )
        account = scenario["account"]
        stale_version = account["version"]

        first = validate_success(
            api.create_turnout_order(
                create_turnout_order_payload(
                    account["id"], scenario["allocation"]["id"],
                    scenario["reach"]["id"],
                    expected_water_account_version=stale_version,
                    requested_cfs=5.0,
                    requested_start_at="2026-06-01T08:00:00Z",
                    requested_end_at="2026-06-01T10:00:00Z",
                ),
                make_water_user_headers(account["id"]),
            ),
            expected_status=201,
        )
        assert first["status"] == "REQUESTED"

        account_after = get_account(account["id"])
        assert account_after["version"] == stale_version + 1, (
            "Order creation increments the account version by 1"
        )

        resp = api.create_turnout_order(
            create_turnout_order_payload(
                account["id"], scenario["allocation"]["id"],
                scenario["reach"]["id"],
                expected_water_account_version=stale_version,
                requested_cfs=5.0,
                requested_start_at="2026-06-02T08:00:00Z",
                requested_end_at="2026-06-02T10:00:00Z",
            ),
            make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        _data, meta = validate_paginated(
            api.list_turnout_orders(ADMIN, params={"water_account_id": account["id"]})
        )
        assert meta["total_count"] == 1, (
            "Only the first order may exist after the stale create is rejected"
        )
