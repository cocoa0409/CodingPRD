"""Cash shipments: linked-order gating, exception branch, turnaround buffer,
dock capacity, liability cap, cancel compensation, carrier ownership."""
from test_helpers import (
    ApiErrorId,
    create_acknowledged_order,
    create_carrier,
    create_inter_site_shipment,
    create_order_shipment,
    create_staffed_site,
    create_submitted_order,
    get_success_data,
    get_site,
    make_carrier_dispatcher_headers,
    validate_error,
    validate_paginated,
)


class TestLoadBlockedUntilAcknowledged:
    def test_load_rejected_while_order_submitted_then_succeeds_after_ack(self, api):
        """PRD §3.4: "Loading the truck moves `SCHEDULED → LOADED` and requires the
        shipment to currently be `SCHEDULED`, failing with
        `ERR_SHIPMENT_INVALID_STATE` (HTTP 409) from any other state. The carrier
        must still be `ACTIVE`, a linked order must be `ACKNOWLEDGED` by this point
        (`ERR_LINKED_ORDER_NOT_ACKNOWLEDGED`), and an outbound load requires the
        origin site not be `FROZEN`."
        PRD §3.4: "Inbound loading instead adds the declared value to the
        destination's `in_transit_inbound_cents`."

        Design: Difficulty/cross_entity_state_dependency/shipment_load_blocked_until_order_acknowledged
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 30000000, "site_type": "CENTRAL"},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]
        carrier = create_carrier()

        order = create_submitted_order(
            site_id, coord, direction="ORDER", business_date="2026-08-04"
        )
        # Scheduling is allowed while the order is merely SUBMITTED.
        shipment = create_order_shipment(order["id"], carrier["id"], coord)

        resp = api.load_cash_shipment(shipment["id"], coord)
        validate_error(resp, ApiErrorId.ERR_LINKED_ORDER_NOT_ACKNOWLEDGED)

        get_success_data(api.acknowledge_fed_order(order["id"], coord))
        loaded = get_success_data(api.load_cash_shipment(shipment["id"], coord))
        assert loaded["status"] == "LOADED"
        site = get_site(site_id)
        assert site["in_transit_inbound_cents"] == 2000000

    def test_load_success_books_inbound_in_transit_value(self, api):
        """PRD §3.4: "A Fed-linked shipment carries a `fed_order_id`; its origin
        and destination sites are then derived from the linked order (an inbound
        `ORDER` has no origin site because cash originates at the Fed; an outbound
        `DEPOSIT` has no destination site), its `declared_value_cents` is taken
        from the order's `face_total_cents`, and the linked order must be
        `SUBMITTED` or `ACKNOWLEDGED` at scheduling time — otherwise
        `ERR_LINKED_ORDER_NOT_ACKNOWLEDGED` (HTTP 409)."
        PRD §3.4: "Inbound loading instead adds the declared value to the
        destination's `in_transit_inbound_cents`."

        Design: Difficulty/cross_entity_state_dependency/shipment_load_blocked_until_order_acknowledged
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 30000000, "site_type": "CENTRAL"},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]
        carrier = create_carrier()

        order = create_acknowledged_order(
            site_id, coord, direction="ORDER", business_date="2026-08-04"
        )
        shipment = create_order_shipment(order["id"], carrier["id"], coord)
        assert shipment["declared_value_cents"] == 2000000, (
            "linked shipment declared value must be taken from the order face total"
        )
        loaded = get_success_data(api.load_cash_shipment(shipment["id"], coord))
        assert loaded["status"] == "LOADED"
        site = get_site(site_id)
        assert site["in_transit_inbound_cents"] == 2000000
        # Inbound load moves no on-hand cash yet.
        assert site["on_hand_fit_cents"] == 30000000


class TestExceptionBranchEffects:
    def test_exception_then_accept_books_counted_value(self, api):
        """PRD §3.4: "Departure moves `LOADED → IN_TRANSIT` and, if a Fed order is
        linked, moves the order `ACKNOWLEDGED → IN_TRANSIT` alongside it; departing
        from any state other than `LOADED` is rejected with
        `ERR_SHIPMENT_INVALID_STATE`."
        PRD §3.4: "A mismatched count instead moves `IN_TRANSIT → EXCEPTION`,
        recording the counted value but moving no cash. From `EXCEPTION`, a second
        verification with `accept_variance` set to `true` accepts the variance and
        moves to `VERIFIED`: an inbound shipment credits the destination with the
        counted value (releasing the full declared amount from
        `in_transit_inbound_cents`) and posts the corresponding `SHIPMENT_IN` or
        `FED_RECEIPT` entry, while an outbound shipment posts an `ADJUSTMENT`
        entry of the declared-minus-counted difference in the `FIT` bucket,
        returning undelivered value to the origin's fit balance; a linked order
        moves to `RECEIVED` with `settled_basis_cents` set to the counted value,
        and the full site cascade follows."

        Design: Corner/state_machines/shipment_lifecycle_exception_branch_effects
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 30000000, "site_type": "CENTRAL"},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]
        carrier = create_carrier()
        dispatcher = make_carrier_dispatcher_headers(carrier["id"])

        order = create_acknowledged_order(
            site_id, coord, direction="ORDER", business_date="2026-08-04"
        )
        shipment = create_order_shipment(order["id"], carrier["id"], coord)
        get_success_data(api.load_cash_shipment(shipment["id"], coord))
        get_success_data(api.depart_cash_shipment(shipment["id"], dispatcher))

        order_mid = get_success_data(api.get_fed_order(order["id"], coord))
        assert order_mid["status"] == "IN_TRANSIT", (
            "departure must move the linked order ACKNOWLEDGED → IN_TRANSIT"
        )

        exception = get_success_data(
            api.verify_cash_shipment(
                shipment["id"], {"counted_value_cents": 1900000}, dispatcher
            )
        )
        assert exception["status"] == "EXCEPTION"
        site_mid = get_site(site_id)
        assert site_mid["on_hand_fit_cents"] == 30000000, (
            "a mismatched count moves no cash while in EXCEPTION"
        )

        verified = get_success_data(
            api.verify_cash_shipment(
                shipment["id"],
                {"counted_value_cents": 1900000, "accept_variance": True},
                dispatcher,
            )
        )
        assert verified["status"] == "VERIFIED"
        site_end = get_site(site_id)
        assert site_end["on_hand_fit_cents"] == 31900000, (
            f"the counted 1,900,000 (not the declared 2,000,000) must be credited, "
            f"got {site_end['on_hand_fit_cents']}"
        )
        assert site_end["in_transit_inbound_cents"] == 0
        assert site_end["pending_inbound_order_cents"] == 0
        order_end = get_success_data(api.get_fed_order(order["id"], coord))
        assert order_end["status"] == "RECEIVED"
        assert order_end["settled_basis_cents"] == 1900000


class TestCarrierTurnaround:
    def test_buffer_inside_45_minutes_rejected_exactly_45_allowed(self, api):
        """PRD §3.4: "Second, carrier turnaround: the new shipment's
        departure-to-arrival window, expanded by 45 minutes on both ends, must not
        overlap any non-cancelled shipment of the same carrier; the windows are
        half-open, so a gap of exactly 45 minutes is permitted, while anything
        closer is rejected with `ERR_CARRIER_TURNAROUND_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/carrier_turnaround_buffer_boundary
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "opening_fit_cents": 10000000,
                "site_type": "CENTRAL",
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        from test_helpers import create_site

        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=5, opening_fit_cents=0
        )
        carrier = create_carrier()

        s1 = create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            carrier["id"],
            coord,
            declared_value_cents=100000,
            departure="2026-08-10T10:00:00Z",
            arrival="2026-08-10T12:00:00Z",
        )
        assert s1["status"] == "SCHEDULED"

        # 12:30 departure is inside the 45-minute turnaround of the 12:00 arrival.
        too_close = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 100000,
                "scheduled_departure_at": "2026-08-10T12:30:00Z",
                "scheduled_arrival_at": "2026-08-10T14:00:00Z",
            },
            coord,
        )
        validate_error(too_close, ApiErrorId.ERR_CARRIER_TURNAROUND_CONFLICT)

        # Exactly 45 minutes after the arrival is permitted (half-open windows).
        s2 = get_success_data(
            api.create_cash_shipment(
                {
                    "carrier_id": carrier["id"],
                    "origin_site_id": site_a["id"],
                    "destination_site_id": site_b["id"],
                    "declared_value_cents": 100000,
                    "scheduled_departure_at": "2026-08-10T12:45:00Z",
                    "scheduled_arrival_at": "2026-08-10T14:00:00Z",
                },
                coord,
            )
        )
        assert s2["status"] == "SCHEDULED"
        site_a_now = get_site(site_a["id"])
        assert site_a_now["reserved_out_cents"] == 200000, (
            f"S1 + S2 reservations must total 200,000, got {site_a_now['reserved_out_cents']}"
        )

    def test_gap_below_buffer_on_departure_side_rejected(self, api):
        """PRD §3.4: "Second, carrier turnaround: the new shipment's
        departure-to-arrival window, expanded by 45 minutes on both ends, must not
        overlap any non-cancelled shipment of the same carrier; the windows are
        half-open, so a gap of exactly 45 minutes is permitted, while anything
        closer is rejected with `ERR_CARRIER_TURNAROUND_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/carrier_turnaround_buffer_boundary
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "opening_fit_cents": 10000000,
                "site_type": "CENTRAL",
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        from test_helpers import create_site

        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=5, opening_fit_cents=0
        )
        carrier = create_carrier()

        create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            carrier["id"],
            coord,
            declared_value_cents=100000,
            departure="2026-08-10T10:00:00Z",
            arrival="2026-08-10T12:00:00Z",
        )
        # 12:44 is one minute short of the exact 45-minute gap → still rejected.
        resp = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 100000,
                "scheduled_departure_at": "2026-08-10T12:44:00Z",
                "scheduled_arrival_at": "2026-08-10T14:00:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_CARRIER_TURNAROUND_CONFLICT)
        # A different carrier is untouched by this carrier's turnaround window.
        other_carrier = create_carrier(name="Carrier Other")
        other = get_success_data(
            api.create_cash_shipment(
                {
                    "carrier_id": other_carrier["id"],
                    "origin_site_id": site_a["id"],
                    "destination_site_id": site_b["id"],
                    "declared_value_cents": 100000,
                    "scheduled_departure_at": "2026-08-10T12:44:00Z",
                    "scheduled_arrival_at": "2026-08-10T14:00:00Z",
                },
                coord,
            )
        )
        assert other["status"] == "SCHEDULED"


class TestDockCapacity:
    def _build_sites_and_carriers(self, api):
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "opening_fit_cents": 30000000,
                "site_type": "CENTRAL",
                "dock_capacity": 5,
            },
        )
        from test_helpers import create_site

        site_a = ctx["site"]
        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=2, opening_fit_cents=0
        )
        c1 = create_carrier(name="C1")
        c2 = create_carrier(name="C2")
        c3 = create_carrier(name="C3")
        return site_a, site_b, ctx["staff"]["coordinator"]["headers"], c1, c2, c3

    def test_third_arrival_at_capacity_instant_rejected(self, api):
        """PRD §3.4: "Third, dock capacity for inbound shipments: the count of
        inbound shipments in `SCHEDULED`, `LOADED`, or `IN_TRANSIT` whose arrival
        window (30 minutes on either side) contains the new arrival instant must
        remain below the destination's `dock_capacity`, failing with
        `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dock_capacity_point_instant_aggregate
        """
        site_a, site_b, coord, c1, c2, c3 = self._build_sites_and_carriers(api)
        for carrier in (c1, c2):
            created = create_inter_site_shipment(
                site_a["id"],
                site_b["id"],
                carrier["id"],
                coord,
                declared_value_cents=100000,
                departure="2026-08-12T13:00:00Z",
                arrival="2026-08-12T14:00:00Z",
            )
            assert created["status"] == "SCHEDULED"

        # Third arrival at 14:00: the ±30-minute window 13:30–14:30 already holds
        # dock_capacity == 2 inbound shipments.
        resp = api.create_cash_shipment(
            {
                "carrier_id": c3["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 100000,
                "scheduled_departure_at": "2026-08-12T13:00:00Z",
                "scheduled_arrival_at": "2026-08-12T14:00:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)

        # Arrival at 14:31: the earlier pair's windows end at 14:30, so the count
        # at the new instant is below capacity.
        later = get_success_data(
            api.create_cash_shipment(
                {
                    "carrier_id": c3["id"],
                    "origin_site_id": site_a["id"],
                    "destination_site_id": site_b["id"],
                    "declared_value_cents": 100000,
                    "scheduled_departure_at": "2026-08-12T13:30:00Z",
                    "scheduled_arrival_at": "2026-08-12T14:31:00Z",
                },
                coord,
            )
        )
        assert later["status"] == "SCHEDULED"

    def test_arrival_inside_single_window_at_capacity_two_rejected(self, api):
        """PRD §3.4: "Third, dock capacity for inbound shipments: the count of
        inbound shipments in `SCHEDULED`, `LOADED`, or `IN_TRANSIT` whose arrival
        window (30 minutes on either side) contains the new arrival instant must
        remain below the destination's `dock_capacity`, failing with
        `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dock_capacity_point_instant_aggregate
        """
        site_a, site_b, coord, c1, c2, c3 = self._build_sites_and_carriers(api)
        create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            c1["id"],
            coord,
            declared_value_cents=100000,
            departure="2026-08-12T13:00:00Z",
            arrival="2026-08-12T14:00:00Z",
        )
        create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            c2["id"],
            coord,
            declared_value_cents=100000,
            departure="2026-08-12T13:00:00Z",
            arrival="2026-08-12T14:00:00Z",
        )
        # A new arrival at 14:10 is contained in both existing windows
        # (13:30–14:30), so the count at that instant is already 2 == capacity.
        resp = api.create_cash_shipment(
            {
                "carrier_id": c3["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 100000,
                "scheduled_departure_at": "2026-08-12T13:10:00Z",
                "scheduled_arrival_at": "2026-08-12T14:10:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_CAPACITY_EXCEEDED)


class TestInsuranceBeatsLiability:
    def test_double_violation_reports_insurance_headroom(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."
        PRD §3.3: "A candidate exceeding headroom is rejected with
        `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402)."
        PRD §3.4: "First, carrier liability: the declared value must not exceed
        the carrier's `liability_cap_per_truck_cents`, failing with
        `ERR_CARRIER_LIABILITY_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/insurance_safety_beats_liability_fiscal_on_shipment_create
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 10000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        # Site B: fit 900,000 against coverage 1,000,000 → headroom is 100,000.
        site_b = create_site(
            name="B",
            site_type="BRANCH",
            vault_limit_cents=10000000,
            insurance_coverage_cents=1000000,
            dock_capacity=2,
            opening_fit_cents=900000,
        )
        carrier = create_carrier(liability_cap_per_truck_cents=500000)

        # 600,000 busts BOTH headroom (100,000) and the liability cap (500,000);
        # insurance headroom comes first among business rules in §2.8's order.
        resp = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 600000,
                "scheduled_departure_at": "2026-08-10T10:00:00Z",
                "scheduled_arrival_at": "2026-08-10T12:00:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_HEADROOM_EXCEEDED)

        shipments, meta = validate_paginated(
            api.list_cash_shipments(coord, params={"origin_site_id": site_a["id"]})
        )
        assert meta["total_count"] == 0, (
            f"nothing must persist after the rejected create, got {meta['total_count']}"
        )

    def test_double_violation_reports_insurance_headroom_at_second_instant(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the first failure in a fixed evaluation order: authentication
        context first (missing or invalid headers, then role permission, then
        site-scope or carrier ownership), then existence of path identifiers
        validated left-to-right along the URL, then existence of body-referenced
        foreign keys (`site_id`, `atm_id`, `carrier_id`, `fed_order_id`,
        `fitness_batch_id`), then request shape and uniqueness
        (`ERR_INVALID_REQUEST` for missing or mistyped fields, invalid enum
        members, or an end date before its start date), then the target
        resource's own state machine, then cross-entity state guards, then
        segregation-of-duties checks, then business rules (insurance headroom,
        cutoff and scheduling windows, denomination mix, fiscal sufficiency)."
        PRD §3.3: "This guard applies at two points: submitting an
        `ORDER`-direction Fed order, and creating an inbound shipment. A
        candidate exceeding headroom is rejected with
        `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/insurance_safety_beats_liability_fiscal_on_shipment_create
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 10000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        site_b = create_site(
            name="B",
            site_type="BRANCH",
            vault_limit_cents=10000000,
            insurance_coverage_cents=1000000,
            dock_capacity=2,
            opening_fit_cents=900000,
        )
        carrier = create_carrier(liability_cap_per_truck_cents=500000)

        # Declared 600,000 busts headroom (100,000) and the liability cap
        # (500,000) simultaneously; insurance headroom is named first among the
        # business rules in §2.8's fixed order.
        resp = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 600000,
                "scheduled_departure_at": "2026-08-11T10:00:00Z",
                "scheduled_arrival_at": "2026-08-11T12:00:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_INSURANCE_HEADROOM_EXCEEDED)
        # Declared 150,000 is under the liability cap but still above headroom —
        # the same error surfaces when the fiscal check is not even engaged.
        resp2 = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 150000,
                "scheduled_departure_at": "2026-08-11T10:00:00Z",
                "scheduled_arrival_at": "2026-08-11T12:00:00Z",
            },
            coord,
        )
        validate_error(resp2, ApiErrorId.ERR_INSURANCE_HEADROOM_EXCEEDED)

    def test_liability_cap_isolated_when_headroom_ample(self, api):
        """PRD §3.4: "First, carrier liability: the declared value must not exceed
        the carrier's `liability_cap_per_truck_cents`, failing with
        `ERR_CARRIER_LIABILITY_EXCEEDED` (HTTP 402)."
        PRD §3.3: "A candidate exceeding headroom is rejected with
        `ERR_INSURANCE_HEADROOM_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/carrier_liability_exceeded_alone
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 10000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        site_b = create_site(
            name="B",
            site_type="BRANCH",
            vault_limit_cents=100000000,
            insurance_coverage_cents=100000000,
            dock_capacity=5,
            opening_fit_cents=0,
        )
        carrier = create_carrier(liability_cap_per_truck_cents=500000)

        resp = api.create_cash_shipment(
            {
                "carrier_id": carrier["id"],
                "origin_site_id": site_a["id"],
                "destination_site_id": site_b["id"],
                "declared_value_cents": 600000,
                "scheduled_departure_at": "2026-08-10T10:00:00Z",
                "scheduled_arrival_at": "2026-08-10T12:00:00Z",
            },
            coord,
        )
        validate_error(resp, ApiErrorId.ERR_CARRIER_LIABILITY_EXCEEDED)


class TestCancelCompensation:
    def test_create_then_cancel_restores_reserved_out(self, api):
        """PRD §3.4: "A successfully scheduled shipment lands in `SCHEDULED`; an
        outbound schedule immediately adds its declared value to the origin
        site's `reserved_out_cents` and re-derives the site."
        PRD §3.4: "Cancellation is available from `SCHEDULED` or `LOADED` and
        compensates whatever was reserved: the origin's `reserved_out_cents`
        always decreases by the declared value, and a cancellation from `LOADED`
        additionally returns the declared value to the origin's
        `on_hand_fit_cents` via a `SHIPMENT_IN` reversal ledger entry, with the
        reconciliation refresh cascade."

        Design: Difficulty/compensating_invariant/shipment_create_then_cancel_restores_reserved_out
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 5000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=5, opening_fit_cents=0
        )
        carrier = create_carrier()

        site0 = get_site(site_a["id"])
        fit0 = site0["on_hand_fit_cents"]
        res0 = site0["reserved_out_cents"]
        assert (fit0, res0) == (5000000, 0)

        shipment = create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            carrier["id"],
            coord,
            declared_value_cents=1000000,
        )
        site_mid = get_site(site_a["id"])
        assert site_mid["reserved_out_cents"] == 1000000, (
            f"create must reserve the declared value, got {site_mid['reserved_out_cents']}"
        )

        cancelled = get_success_data(api.cancel_cash_shipment(shipment["id"], coord))
        assert cancelled["status"] == "CANCELLED"
        site_end = get_site(site_a["id"])
        assert site_end["on_hand_fit_cents"] == fit0
        assert site_end["reserved_out_cents"] == res0
        committed_before = site0["on_hand_total_cents"] + site0["reserved_out_cents"]
        committed_after = (
            site_end["on_hand_total_cents"] + site_end["reserved_out_cents"]
        )
        assert committed_before == committed_after == 5000000, (
            "no drift in (on_hand_total + reserved_out) across create-then-cancel"
        )

    def test_cancel_from_loaded_returns_value_to_origin(self, api):
        """PRD §3.4: "Cancellation is available from `SCHEDULED` or `LOADED` and
        compensates whatever was reserved: the origin's `reserved_out_cents`
        always decreases by the declared value, and a cancellation from `LOADED`
        additionally returns the declared value to the origin's
        `on_hand_fit_cents` via a `SHIPMENT_IN` reversal ledger entry, with the
        reconciliation refresh cascade."
        PRD §3.4: "Outbound loading performs the physical debit: the origin site's
        `reserved_out_cents` decreases by the declared value, its
        `on_hand_fit_cents` decreases by the declared value — all outbound value
        is pinned to the `FIT` bucket — and a `SHIPMENT_OUT` ledger entry posts on
        the clock date (a `FED_DEPOSIT` entry instead when the shipment is linked
        to a `DEPOSIT`-direction order), followed by site re-derivation and the
        reconciliation refresh cascade."

        Design: Difficulty/compensating_invariant/shipment_create_then_cancel_restores_reserved_out
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 5000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=5, opening_fit_cents=0
        )
        carrier = create_carrier()

        shipment = create_inter_site_shipment(
            site_a["id"],
            site_b["id"],
            carrier["id"],
            coord,
            declared_value_cents=1000000,
        )
        get_success_data(api.load_cash_shipment(shipment["id"], coord))
        site_loaded = get_site(site_a["id"])
        assert site_loaded["on_hand_fit_cents"] == 4000000, (
            f"load must debit the declared value from fit, got {site_loaded['on_hand_fit_cents']}"
        )
        assert site_loaded["reserved_out_cents"] == 0

        get_success_data(api.cancel_cash_shipment(shipment["id"], coord))
        site_end = get_site(site_a["id"])
        assert site_end["on_hand_fit_cents"] == 5000000, (
            f"cancel from LOADED must return the value to fit, got {site_end['on_hand_fit_cents']}"
        )
        assert site_end["reserved_out_cents"] == 0


class TestCarrierOwnership:
    def test_depart_by_other_carrier_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `CarrierDispatcher`, `X-User-ID` is the
        `id` of the acting `Carrier`; a dispatcher may only depart or verify a
        shipment whose `carrier_id` equals `X-User-ID`, and a mismatch is rejected
        with `ERR_RESOURCE_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/validations/dispatcher_depart_other_carrier_rejected
        """
        from test_helpers import create_site

        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={
                "name": "A",
                "site_type": "CENTRAL",
                "opening_fit_cents": 30000000,
                "dock_capacity": 5,
            },
        )
        site_a = ctx["site"]
        coord = ctx["staff"]["coordinator"]["headers"]
        site_b = create_site(
            name="B", site_type="BRANCH", dock_capacity=5, opening_fit_cents=0
        )
        c1 = create_carrier(name="C1")
        c2 = create_carrier(name="C2")

        shipment = create_inter_site_shipment(
            site_a["id"], site_b["id"], c2["id"], coord, declared_value_cents=1000000
        )
        get_success_data(api.load_cash_shipment(shipment["id"], coord))

        resp = api.depart_cash_shipment(
            shipment["id"], make_carrier_dispatcher_headers(c1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP_VIOLATION)
        after = get_success_data(api.get_cash_shipment(shipment["id"], coord))
        assert after["status"] == "LOADED"
