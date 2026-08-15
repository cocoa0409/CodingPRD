"""Warehouse staging: per-day capacity, receipt, release, reservation states."""
from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
    AE,
    PM,
    WH,
)

class TestStagingCapacityBoundary:
    def test_staging_capacity_exact_fit_allowed(self, api):
        """PRD section 3.5: "rejects the reservation with
        `ERR_CAPACITY_EXCEEDED` if the result would exceed the dealership's
        `staging_capacity_units` on any day. A result exactly equal to the
        ceiling is allowed." — 7 units plus 3 units exactly fill capacity 10.

        Design: Difficulty/boundary_precision_check/staging_capacity_exact_fit
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 10},
        )
        fx.add_staging_reservation(
            ctx, {"units": 7, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        resp = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 3,
                "start_date": "2026-08-11",
                "end_date": "2026-08-13",
            },
            PM,
        )
        assert validate_success(resp, 201)["id"]

    def test_staging_capacity_one_over_rejected(self, api):
        """PRD section 3.5: "rejects the reservation with
        `ERR_CAPACITY_EXCEEDED` if the result would exceed the dealership's
        `staging_capacity_units` on any day." — 7 + 3 + 1 = 11 exceeds
        capacity 10 on 2026-08-12.

        Design: Difficulty/boundary_precision_check/staging_capacity_exact_fit
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 10},
        )
        fx.add_staging_reservation(
            ctx, {"units": 7, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        fx.add_staging_reservation(
            ctx, {"units": 3, "start_date": "2026-08-11", "end_date": "2026-08-13"}
        )
        resp = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 1,
                "start_date": "2026-08-12",
                "end_date": "2026-08-12",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestStagingInclusiveWindows:
    def test_staging_inclusive_window_disjoint_windows(self, api):
        """PRD section 3.5: "for every calendar date in the requested window,
        both bounds inclusive, the server sums `units` across all of the
        dealership's `RESERVED` and `OCCUPIED` reservations whose own windows
        cover that date" — windows [08-10..08-12] and [08-13..08-15] share no
        date, so six units each never interact even though twelve units exceed
        the capacity of ten in aggregate.

        Design: Difficulty/resource_temporal_overlap/staging_inclusive_window_aggregate_capacity
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 30},
        )
        r1 = fx.add_staging_reservation(
            ctx, {"units": 6, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        r2 = fx.add_staging_reservation(
            ctx, {"units": 6, "start_date": "2026-08-13", "end_date": "2026-08-15"}
        )
        assert r1["id"] and r2["id"]

    def test_staging_inclusive_window_shared_boundary_counts(self, api):
        """PRD section 3.5: "for every calendar date in the requested window,
        both bounds inclusive" — a window [08-12..08-13] shares its first date
        with [08-10..08-12] and its second with [08-13..08-15], so its units
        count against both days: four units fit exactly (6 + 4 == 10), one more
        tips both days to 11 and is rejected with `ERR_CAPACITY_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/staging_inclusive_window_aggregate_capacity
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 30},
        )
        fx.add_staging_reservation(
            ctx, {"units": 6, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        fx.add_staging_reservation(
            ctx, {"units": 6, "start_date": "2026-08-13", "end_date": "2026-08-15"}
        )
        r3 = fx.add_staging_reservation(
            ctx, {"units": 4, "start_date": "2026-08-12", "end_date": "2026-08-13"}
        )
        assert r3["id"]
        resp = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 1,
                "start_date": "2026-08-12",
                "end_date": "2026-08-13",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_capacity_counts_reserved_and_occupied(self, api):
        """PRD section 2.9: "Reservations in `RESERVED` or `OCCUPIED` status
        count toward occupancy; `CANCELLED` and `RELEASED` reservations do
        not." — five OCCUPIED units plus a five-unit reservation exactly fill
        capacity 10; one further unit fails.

        Design: Corner/calculations/capacity_counts_reserved_and_occupied
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 30},
        )
        r1 = fx.add_staging_reservation(
            ctx, {"units": 5, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        fx.receive_units(ctx, r1["id"], received_units=5)
        r2 = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 5,
                "start_date": "2026-08-11",
                "end_date": "2026-08-11",
            },
            PM,
        )
        assert validate_success(r2, 201)["id"]
        r3 = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 1,
                "start_date": "2026-08-11",
                "end_date": "2026-08-11",
            },
            PM,
        )
        validate_error(r3, ApiErrorId.ERR_CAPACITY_EXCEEDED)


class TestReservationLifecycle:
    def test_staging_reserve_receive_release_occupied_conserves(self, api):
        """PRD section 3.5: "On a successful receive the reservation
        transitions to `OCCUPIED`, its `received_units` increases by the
        received amount, and the line's `received_units` is recomputed as the
        sum across the line's non-`CANCELLED` reservations." RESERVED and
        OCCUPIED both count toward occupancy (PRD section 2.9), so receipt
        conserves the occupied pool: five OCCUPIED units still leave room for
        exactly five more against capacity ten.

        Design: Difficulty/compensating_invariant/staging_reserve_receive_release_roundtrip
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 10},
        )
        fx.add_staging_reservation(
            ctx, {"units": 5, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        occupied = fx.receive_units(ctx, received_units=5)
        assert occupied["status"] == "OCCUPIED"
        line = validate_success(api.get_order_line(ctx.line["id"], WH))
        assert line["received_units"] == 5
        probe = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 5,
                "start_date": "2026-08-11",
                "end_date": "2026-08-11",
            },
            PM,
        )
        assert validate_success(probe, 201)["id"]

    def test_staging_reserve_receive_release_frees_pool(self, api):
        """PRD section 3.5: "A `WarehouseLead` releases an `OCCUPIED`
        reservation, moving it to `RELEASED` and freeing its units from staging
        occupancy." — after reserve(5) -> receive(5) -> release, a probe of the
        full capacity of ten fits on the same date, proving occupancy returned
        to zero.

        Design: Difficulty/compensating_invariant/staging_reserve_receive_release_roundtrip
        """
        ctx = fx.setup_acknowledged_order(
            dealership_overrides={"staging_capacity_units": 10},
            line_overrides={"quantity": 10},
        )
        fx.add_staging_reservation(
            ctx, {"units": 5, "start_date": "2026-08-10", "end_date": "2026-08-12"}
        )
        fx.receive_units(ctx, received_units=5)
        released = validate_success(api.release_staging(ctx.reservation["id"], WH))
        assert released["status"] == "RELEASED"
        probe = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 10,
                "start_date": "2026-08-11",
                "end_date": "2026-08-11",
            },
            PM,
        )
        assert validate_success(probe, 201)["id"]

    def test_over_receipt_rejected(self, api):
        """PRD section 3.5: "The receive is rejected with `ERR_OVER_RECEIPT`
        when the input `received_units` is less than 1, or when the
        reservation's already-received units plus the new receipt would exceed
        the reservation's `units`, or when it would exceed the line's remaining
        unreceived quantity" — six against a five-unit reservation fails;
        exactly five succeeds (the comparison is inclusive).

        Design: Corner/validations/over_receipt_rejected
        """
        ctx = fx.setup_acknowledged_order(line_overrides={"quantity": 10})
        fx.add_staging_reservation(ctx, {"units": 5})
        resp = api.receive_staging(
            ctx.reservation["id"], {"received_units": 6, "condition": "GOOD"}, WH
        )
        validate_error(resp, ApiErrorId.ERR_OVER_RECEIPT)
        ok = validate_success(
            api.receive_staging(
                ctx.reservation["id"], {"received_units": 5, "condition": "GOOD"}, WH
            )
        )
        assert ok["status"] == "OCCUPIED"
        assert ok["received_units"] == 5

    def test_staging_cancel_from_occupied_rejected(self, api):
        """PRD section 3.5: "A `ProjectManager` may cancel a reservation that
        is still `RESERVED`, moving it to `CANCELLED`" — no cancellation
        transition exists from `OCCUPIED` (PRD section 2.8 rule 4), so the
        attempt is rejected with ERR_INVALID_STATE (HTTP 409 per the section 5
        catalogue).

        Design: Corner/state_machines/staging_cancel_from_occupied_rejected
        """
        ctx = fx.setup_acknowledged_order(line_overrides={"quantity": 10})
        fx.add_staging_reservation(ctx, {"units": 5})
        fx.receive_units(ctx, received_units=5)
        resp = api.cancel_staging(ctx.reservation["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_warehouse_damage_receive_creates_punch(self, api):
        """PRD section 3.5: "When the receipt's `condition` is `DAMAGED`, the
        system automatically opens a `PunchItem` attributed to the line's order
        and line, with `source` set to `WAREHOUSE`, `severity` `STANDARD`, and
        status `OPEN`."

        Design: Corner/state_machines/warehouse_damage_receive_creates_punch
        """
        ctx = fx.setup_acknowledged_order(line_overrides={"quantity": 10})
        fx.add_staging_reservation(ctx, {"units": 5})
        fx.receive_units(ctx, received_units=3, condition="DAMAGED")
        punches, meta = validate_paginated(
            api.list_punch_items(PM, params={"order_line_id": ctx.line["id"]})
        )
        assert meta["total_count"] == 1
        assert punches[0]["source"] == "WAREHOUSE"
        assert punches[0]["status"] == "OPEN"
        assert punches[0]["severity"] == "STANDARD"
        assert punches[0]["order_id"] == ctx.order["id"]
        assert punches[0]["order_line_id"] == ctx.line["id"]

    def test_staging_reservation_requires_acknowledged_line(self, api):
        """PRD section 3.5: "Reservation creation requires the referenced line
        to be `ACKNOWLEDGED` — with one exception: replacement lines (those
        with `is_replacement` true) may be staged while still `OPEN`. A
        reservation against a line in any other state is rejected with
        `ERR_ORDER_NOT_ACKNOWLEDGED`." On a merely-submitted order the line is
        `PLACED`, so the reservation is rejected.

        Design: Difficulty/cross_entity_state_dependency/install_event_requires_order_acknowledged
        """
        ctx = fx.setup_submitted_order()
        resp = api.create_staging_reservation(
            {
                "order_line_id": ctx.line["id"],
                "units": 1,
                "start_date": "2026-08-06",
                "end_date": "2026-08-08",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACKNOWLEDGED)


class TestFilteredLists:
    def test_fk_reverse_reachability_filtered_lists(self, api):
        """PRD section 2.3: "Paginated list responses include the following
        fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`." Listing the children created
        under a parent returns exactly those children in the total count.

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        ctx = fx.setup_draft_order(line_overrides={"quantity": 1})
        fx.add_line(ctx.order["id"], ctx.series["id"], {"quantity": 2})
        validate_success(api.submit_order(ctx.order["id"], AE))
        fx.add_punch(ctx, {"severity": "STANDARD", "description": "Scuff",
                           "affected_units": 1})
        _lines, meta_lines = validate_paginated(
            api.list_order_lines(AE, params={"order_id": ctx.order["id"]})
        )
        assert meta_lines["total_count"] == 2
        _typ, meta_typ = validate_paginated(
            api.list_typicals(fx.DESIGNER, params={"space_plan_id": ctx.plan["id"]})
        )
        assert meta_typ["total_count"] == 1
        _pu, meta_pu = validate_paginated(
            api.list_punch_items(PM, params={"order_id": ctx.order["id"]})
        )
        assert meta_pu["total_count"] == 1
