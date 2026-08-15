"""Scale-house operations: the truck queue, weigh-in/weigh-out gates,
ticket voids, and scale certification windows."""
import pytest

from test_helpers import (
    ADMIN,
    FINANCE,
    MANAGER,
    NON_EXISTENT_UUID,
    SCALE_OP,
    ApiErrorId,
    assert_stockpile_invariants,
    call_next_truck,
    complete_ticket,
    create_confirmed_order,
    create_scale,
    create_scale_calibration_payload,
    create_site,
    generate_statement,
    get_order,
    get_queue_entry,
    get_stockpile,
    get_ticket,
    issue_citation,
    move_to_scale_out,
    open_inspection,
    queue_truck,
    set_clock,
    setup_ticketing_site,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_in_truck,
    weigh_out_ticket,
)


class TestQueueDispatch:
    def test_queue_dispatch_priority_then_queued_at_tiebreak(self, api):
        """PRD 3.7: "calling the next truck for a site considers only its
        `QUEUED` entries, ranks `CONTRACT` ahead of `SPOT` ahead of
        `INTERNAL`, breaks ties by the earlier `queued_at` and then by
        `truck_id` in ascending string order, and moves the winner `QUEUED`
        → `AT_SCALE_IN`; an empty pool is rejected with `ERR_QUEUE_EMPTY`."

        Design: Corner/calculations/queue_dispatch_priority_then_queued_at_tiebreak
        """
        site = create_site()
        set_clock("2026-08-01T09:00:00Z")
        e1 = queue_truck(site["id"], truck_id="TRK-1", priority_class="SPOT")
        set_clock("2026-08-01T09:01:00Z")
        e2 = queue_truck(site["id"], truck_id="TRK-9",
                         priority_class="CONTRACT")
        set_clock("2026-08-01T09:02:00Z")
        e3 = queue_truck(site["id"], truck_id="TRK-2",
                         priority_class="CONTRACT")
        # CONTRACT beats SPOT regardless of arrival; between the two
        # CONTRACT entries the earlier queued_at wins (not the smaller id).
        assert call_next_truck(site["id"])["id"] == e2["id"]
        assert call_next_truck(site["id"])["id"] == e3["id"]
        assert call_next_truck(site["id"])["id"] == e1["id"]
        resp = api.call_next_queue_entry({"site_id": site["id"]}, SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_QUEUE_EMPTY)

    def test_truck_single_active_queue_occupancy_rejected(self, api):
        """PRD 3.7: "A truck may hold at most one active entry per site —
        active meaning `QUEUED`, `AT_SCALE_IN`, `LOADING`, or
        `AT_SCALE_OUT` — and a duplicate is rejected with
        `ERR_TRUCK_ALREADY_QUEUED`."

        Design: Difficulty/resource_temporal_overlap/truck_single_active_queue_occupancy
        """
        site = create_site()
        queue_truck(site["id"], truck_id="TRK-1")
        resp = api.create_queue_entry(
            {"site_id": site["id"], "truck_id": "TRK-1",
             "priority_class": "SPOT", "certified_tare_lbs": 28000,
             "max_payload_lbs": 70000}, SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_TRUCK_ALREADY_QUEUED)

    def test_truck_terminal_entry_frees_occupancy(self, api):
        """PRD 3.7: "A truck may hold at most one active entry per site —
        active meaning `QUEUED`, `AT_SCALE_IN`, `LOADING`, or
        `AT_SCALE_OUT`"; a `NO_SHOW` entry is terminal, so the truck may
        queue again.

        Design: Difficulty/resource_temporal_overlap/truck_single_active_queue_occupancy
        """
        site = create_site()
        e1 = queue_truck(site["id"], truck_id="TRK-1")
        validate_success(api.mark_no_show(e1["id"], SCALE_OP))
        e2 = queue_truck(site["id"], truck_id="TRK-1", priority_class="SPOT")
        assert e2["status"] == "QUEUED"


class TestWeighOutGuards:
    def test_ticket_weighout_requires_entry_at_scale_out(self, api):
        """PRD 3.7: "The queue entry must stand `AT_SCALE_OUT`
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/ticket_weighout_requires_entry_at_scale_out
        """
        ctx = setup_ticketing_site()
        entry, ticket = weigh_in_truck(ctx, truck_id="TRK-1",
                                       gross_lbs=80000)
        assert get_queue_entry(entry["id"])["status"] == "LOADING"
        resp = api.weigh_out_ticket(ticket["id"], {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_ticket(ticket["id"])["status"] == "OPEN"

    def test_not_found_beats_state_on_weighout(self, api):
        """PRD 2.7 tier 4: "Existence — path identifiers must resolve, then
        body foreign-key identifiers must resolve, checked left-to-right in
        input order; the first unresolvable identifier determines the
        rejection, `ERR_NOT_FOUND` (404)."
        PRD 2.7: "when several rules fail at once, the rejection returned
        is the one belonging to the earliest tier" — existence precedes own
        state.

        Design: Corner/validations/not_found_beats_state_on_weighout
        """
        resp = api.weigh_out_ticket(NON_EXISTENT_UUID, {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_tare_variance_rejected_then_overridden(self, api):
        """PRD 3.7: "`tare_variance_pct` is the absolute difference between
        `tare_lbs` and the entry's `certified_tare_lbs`, expressed as a
        percentage of `certified_tare_lbs` and rounded half-up to two
        decimals — a variance of at most 2.00 passes, while a greater
        variance is rejected with `ERR_TARE_VARIANCE` (422) unless the
        payload sets `allow_tare_variance` to true."
        PRD 3.7: "The `net_tons` are `gross_lbs` minus `tare_lbs`, divided
        by 2,000 pounds per ton, rounded half-up to three decimals. The
        provisional royalty `royalty_provisional_usd` accrues at the flat
        base rate — `net_tons` times the covering agreement's
        `base_rate_per_ton`, rounded half-up to two decimals".

        Design: Corner/validations/tare_variance_rejected_then_overridden
        """
        ctx = setup_ticketing_site()
        entry, ticket = weigh_in_truck(ctx, gross_lbs=80000)
        move_to_scale_out(entry["id"])
        resp = api.weigh_out_ticket(ticket["id"], {"tare_lbs": 29000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_TARE_VARIANCE)
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        ticket = weigh_out_ticket(ticket["id"], tare_lbs=29000,
                                  allow_tare_variance=True)
        assert ticket["status"] == "COMPLETED"
        assert ticket["net_tons"] == pytest.approx(25.500, abs=1e-6)
        assert ticket["tare_variance_pct"] == pytest.approx(3.57, abs=1e-6)
        # round_half_up(25.500 x 0.25, 2) from 6.375 -> 6.38
        assert ticket["royalty_provisional_usd"] == pytest.approx(6.38,
                                                                  abs=1e-6)

    def test_truck_overweight_rejected(self, api):
        """PRD 3.7: "The legal-weight check requires `gross_lbs` minus
        `tare_lbs` not to exceed the entry's `max_payload_lbs`
        (`ERR_TRUCK_OVERWEIGHT`, 422)."

        Design: Corner/validations/truck_overweight_rejected
        """
        ctx = setup_ticketing_site()
        entry, ticket = weigh_in_truck(ctx, gross_lbs=80000,
                                       max_payload_lbs=40000)
        move_to_scale_out(entry["id"])
        resp = api.weigh_out_ticket(ticket["id"], {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_TRUCK_OVERWEIGHT)
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        assert get_queue_entry(entry["id"])["status"] == "AT_SCALE_OUT"

    def test_royalty_agreement_required_at_weighout(self, api):
        """PRD 3.7: "Royalty coverage must exist: an `ACTIVE` royalty
        agreement of the site whose `effective_from` is on or before the
        current date and whose `effective_to` is either unset or after the
        current date (`ERR_ROYALTY_AGREEMENT_REQUIRED`)."

        Design: Corner/validations/royalty_agreement_required_at_weighout
        """
        ctx = setup_ticketing_site(with_agreement=False)
        entry, ticket = weigh_in_truck(ctx, gross_lbs=80000)
        move_to_scale_out(entry["id"])
        resp = api.weigh_out_ticket(ticket["id"], {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_ROYALTY_AGREEMENT_REQUIRED)
        assert get_ticket(ticket["id"])["status"] == "OPEN"

    def test_posture_suspended_blocks_weighin(self, api):
        """PRD 3.7: "The order must stand `CONFIRMED` or `IN_FULFILLMENT`;
        the scale must be certified and in-date; the order's stockpile must
        stand `OPEN` (`ERR_STOCKPILE_QUARANTINED`); and the site posture
        must not be `SUSPENDED`."
        PRD 2.7 tier 6: "ticket weigh-in and weigh-out require any posture
        other than `SUSPENDED`; otherwise `ERR_SITE_POSTURE_BLOCKED`
        (409)."

        Design: Corner/validations/posture_suspended_blocks_weighin
        """
        ctx = setup_ticketing_site()
        entry = queue_truck(ctx["site"]["id"], truck_id="TRK-1")
        call_next_truck(ctx["site"]["id"])
        insp = open_inspection(ctx["site"]["id"], inspection_type="SPOT")
        issue_citation(insp["id"], s_and_s=True, abatement_due_on="2026-07-15")
        resp = api.create_scale_ticket(
            {"queue_entry_id": entry["id"],
             "sales_order_id": ctx["order"]["id"],
             "scale_id": ctx["scale"]["id"], "gross_lbs": 80000}, SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKED)
        data, _meta = validate_paginated(api.list_scale_tickets(
            MANAGER, params={"queue_entry_id": entry["id"]}))
        assert data == []
        assert get_queue_entry(entry["id"])["status"] == "AT_SCALE_IN"


class TestScaleCertificationWindows:
    def test_calibration_tolerance_pass_boundary(self, api):
        """PRD 3.7: "the calibration's `result` is `PASS` when the absolute
        as-left error is at most 0.25 percent — exactly 0.25 passes — and
        `FAIL` otherwise. ... A recorded `PASS` moves the scale to
        `CERTIFIED` and sets `certified_through` to `calibrated_on` plus
        180 days, that date being the inclusive last valid day of
        certification".

        Design: Difficulty/boundary_precision_check/calibration_tolerance_inclusive_boundary
        """
        site = create_site()
        scale = create_scale(site["id"], scale_code="TRUCK-01")
        payload = create_scale_calibration_payload(
            scale["id"], calibrated_on="2026-02-02", as_found_error_pct=0.40,
            as_left_error_pct=0.25)
        cal = validate_success(
            api.create_scale_calibration(payload, ADMIN), 201)
        assert cal["result"] == "PASS"
        scale = validate_success(api.get_scale(scale["id"], ADMIN))
        assert scale["status"] == "CERTIFIED"
        # 2026-02-02 + 180 days == 2026-08-01.
        assert scale["certified_through"] == "2026-08-01"

    def test_calibration_tolerance_fail_just_past_boundary(self, api):
        """PRD 3.7: "the calibration's `result` is `PASS` when the absolute
        as-left error is at most 0.25 percent — exactly 0.25 passes — and
        `FAIL` otherwise"; a FAIL leaves the scale `OUT_OF_SERVICE`.

        Design: Difficulty/boundary_precision_check/calibration_tolerance_inclusive_boundary
        """
        site = create_site()
        scale = create_scale(site["id"], scale_code="TRUCK-02")
        payload = create_scale_calibration_payload(
            scale["id"], calibrated_on="2026-02-02", as_found_error_pct=0.40,
            as_left_error_pct=0.251)
        cal = validate_success(
            api.create_scale_calibration(payload, ADMIN), 201)
        assert cal["result"] == "FAIL"
        scale = validate_success(api.get_scale(scale["id"], ADMIN))
        assert scale["status"] == "OUT_OF_SERVICE"
        assert scale.get("certified_through") is None

    def test_scale_certified_through_inclusive_boundary(self, api):
        """PRD 3.7: "Wherever this document requires a usable scale —
        ticket weigh-in, ticket weigh-out, run start — usable means
        `CERTIFIED` with `certified_through` on or after the current
        logical date, and failure is `ERR_SCALE_NOT_CERTIFIED`."

        Design: Corner/calculations/scale_certified_through_inclusive_boundary
        """
        # Calibration 2026-02-02 -> certified_through 2026-08-01.
        ctx = setup_ticketing_site(calibrated_on="2026-02-02")
        # Weigh-in on the inclusive last valid day succeeds.
        _entry1, ticket1 = weigh_in_truck(ctx, truck_id="TRK-1",
                                          gross_lbs=80000)
        assert ticket1["status"] == "OPEN"
        # One day later the same scale is no longer usable.
        entry2 = queue_truck(ctx["site"]["id"], truck_id="TRK-2")
        call_next_truck(ctx["site"]["id"])
        set_clock("2026-08-02T09:00:00Z")
        resp = api.create_scale_ticket(
            {"queue_entry_id": entry2["id"],
             "sales_order_id": ctx["order"]["id"],
             "scale_id": ctx["scale"]["id"], "gross_lbs": 80000}, SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_SCALE_NOT_CERTIFIED)
        assert get_queue_entry(entry2["id"])["status"] == "AT_SCALE_IN"

    def _setup_cert_window_expiring(self):
        # Calibration 2026-01-01 -> certified_through 2026-06-30.
        return setup_ticketing_site(calibrated_on="2026-01-01")

    def test_weighout_requires_scale_certified_in_date_error(self, api):
        """PRD 3.7: "the scale is re-checked as certified and in-date" at
        weigh-out, and "usable means `CERTIFIED` with `certified_through`
        on or after the current logical date, and failure is
        `ERR_SCALE_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/weighout_requires_scale_certified_in_date
        """
        ctx = self._setup_cert_window_expiring()
        set_clock("2026-06-15T09:00:00Z")
        entry, ticket = weigh_in_truck(ctx, gross_lbs=80000)
        move_to_scale_out(entry["id"])
        set_clock("2026-07-01T09:00:00Z")
        resp = api.weigh_out_ticket(ticket["id"], {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_SCALE_NOT_CERTIFIED)

    def test_weighout_scale_lapsed_no_side_effects(self, api):
        """PRD 3.7: a completed weigh-out "moves the entry `AT_SCALE_OUT` →
        `EXITED`, and the ticket stands `COMPLETED`" — a rejected weigh-out
        leaves the ticket `OPEN` and the entry at `AT_SCALE_OUT`.

        Design: Difficulty/cross_entity_state_dependency/weighout_requires_scale_certified_in_date
        """
        ctx = self._setup_cert_window_expiring()
        set_clock("2026-06-15T09:00:00Z")
        entry, ticket = weigh_in_truck(ctx, gross_lbs=80000)
        move_to_scale_out(entry["id"])
        set_clock("2026-07-01T09:00:00Z")
        validate_error(api.weigh_out_ticket(ticket["id"],
                                            {"tare_lbs": 28000}, SCALE_OP),
                       ApiErrorId.ERR_SCALE_NOT_CERTIFIED)
        assert get_ticket(ticket["id"])["status"] == "OPEN"
        assert get_queue_entry(entry["id"])["status"] == "AT_SCALE_OUT"


class TestOrderCompletionBoundary:
    def test_first_draw_moves_order_to_in_fulfillment(self, api):
        """PRD 3.7: "The order's `fulfilled_tons` grows by `net_tons`,
        moving `CONFIRMED` → `IN_FULFILLMENT` on the first draw and on to
        `COMPLETED` when fulfillment reaches the ordered quantity".
        PRD 3.6: "When a draw brings `fulfilled_tons` to at least
        `quantity_tons` — reaching it exactly completes the order".

        Design: Difficulty/boundary_precision_check/order_completion_exact_quantity_boundary
        """
        ctx = setup_ticketing_site(quantity_tons=52)
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        order = get_order(ctx["order"]["id"])
        assert order["status"] == "IN_FULFILLMENT"
        assert order["fulfilled_tons"] == pytest.approx(26.000, abs=1e-6)
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=80000)
        order = get_order(ctx["order"]["id"])
        # 26.000 + 26.000 == 52.000 == quantity_tons: equality completes.
        assert order["fulfilled_tons"] == pytest.approx(52.000, abs=1e-6)
        assert order["status"] == "COMPLETED"

    def test_completed_order_releases_reservation(self, api):
        """PRD 3.6: "When a draw brings `fulfilled_tons` to at least
        `quantity_tons` — reaching it exactly completes the order — the
        order auto-transitions to the terminal state `COMPLETED` and its
        reservation drops to zero."

        Design: Difficulty/boundary_precision_check/order_completion_exact_quantity_boundary
        """
        ctx = setup_ticketing_site(quantity_tons=52)
        complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        complete_ticket(ctx, truck_id="TRK-2", gross_lbs=80000)
        pile = get_stockpile(ctx["pile"]["id"])
        assert pile["reserved_tons"] == pytest.approx(0.0, abs=1e-9)
        assert pile["on_hand_tons"] == pytest.approx(148.0, abs=1e-6)
        assert_stockpile_invariants(pile)


class TestOverShipmentBoundary:
    def test_over_shipment_tolerance_inclusive_boundary(self, api):
        """PRD 3.7: "Finally the over-shipment guard requires that the
        order's `fulfilled_tons` plus this draw's `net_tons` not exceed one
        hundred ten percent of `quantity_tons`, computed as `quantity_tons`
        times 1.10 and rounded half-up to three decimals, with exactly that
        bound allowed (`ERR_OVER_SHIPMENT`)."

        Design: Corner/validations/over_shipment_tolerance_inclusive_boundary
        """
        ctx = setup_ticketing_site(quantity_tons=20)
        order2 = create_confirmed_order(ctx["site"]["id"], ctx["spec"]["id"],
                                        ctx["zone"]["id"],
                                        customer_name="BETA",
                                        quantity_tons=20)
        # net 22.000 == round(20 x 1.10, 3) exactly -> allowed.
        _e1, t1 = complete_ticket(ctx, truck_id="TRK-1", gross_lbs=72000)
        assert t1["net_tons"] == pytest.approx(22.000, abs=1e-6)
        assert get_order(ctx["order"]["id"])["status"] == "COMPLETED"
        # net 23.000 > 22.000 -> rejected.
        entry2, ticket2 = weigh_in_truck(ctx, truck_id="TRK-2",
                                         gross_lbs=74000,
                                         order_id=order2["id"])
        move_to_scale_out(entry2["id"])
        resp = api.weigh_out_ticket(ticket2["id"], {"tare_lbs": 28000},
                                    SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_OVER_SHIPMENT)
        assert get_ticket(ticket2["id"])["status"] == "OPEN"
        assert get_order(order2["id"])["status"] == "CONFIRMED"


class TestTicketVoid:
    def test_terminal_lockdown_voided_ticket_cannot_void_twice(self, api):
        """PRD 3.7: "The void moves the ticket to the terminal state
        `VOIDED`".
        PRD 2.7 tier 5: "terminal states accept no further transitions at
        all, otherwise `ERR_INVALID_STATE` (409)".

        Design: Corner/state_machines/terminal_lockdown_voided_ticket_cannot_void_twice
        """
        ctx = setup_ticketing_site()
        _entry, ticket = complete_ticket(ctx, gross_lbs=80000)
        validate_success(api.void_scale_ticket(
            ticket["id"], {"void_reason": "duplicate entry"}, MANAGER))
        resp = api.void_scale_ticket(ticket["id"],
                                     {"void_reason": "second attempt"},
                                     MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_ticket(ticket["id"])["status"] == "VOIDED"

    def test_scale_operator_cannot_void_ticket(self, api):
        """PRD 2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN` (403)."
        PRD 4: POST /scale-tickets/{id}/void is authorized for SiteManager.

        Design: Corner/rbac/scale_operator_cannot_void_ticket
        """
        ctx = setup_ticketing_site()
        _entry, ticket = complete_ticket(ctx, gross_lbs=80000)
        resp = api.void_scale_ticket(ticket["id"],
                                     {"void_reason": "operator attempt"},
                                     SCALE_OP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_ticket(ticket["id"])["status"] == "COMPLETED"

    def test_statement_locked_blocks_ticket_void(self, api):
        """PRD 3.7: "Only a `COMPLETED` ticket may be voided, and only
        while no royalty statement in `DRAFT`, `ISSUED`, or `PAID` has a
        period containing the ticket's `completed_at`
        (`ERR_STATEMENT_LOCKED`)."
        PRD 3.8: "A draft statement may instead be voided by a
        `FinanceClerk`, moving it `DRAFT` → `VOID`; the period then becomes
        available for regeneration".

        Design: Corner/validations/statement_locked_blocks_ticket_void
        """
        ctx = setup_ticketing_site(calibrated_on="2025-12-01")
        set_clock("2026-01-15T09:00:00Z")
        _entry, ticket = complete_ticket(ctx, gross_lbs=80000)
        stmt = generate_statement(ctx["site"]["id"], "2026-01-01",
                                  "2026-02-01")
        assert stmt["status"] == "DRAFT"
        resp = api.void_scale_ticket(ticket["id"],
                                     {"void_reason": "weighbridge fault"},
                                     MANAGER)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_LOCKED)
        validate_success(api.void_royalty_statement(stmt["id"], FINANCE))
        ticket = validate_success(api.void_scale_ticket(
            ticket["id"], {"void_reason": "weighbridge fault"}, MANAGER))
        assert ticket["status"] == "VOIDED"

    def test_ticket_void_roundtrip_holds_available_tons(self, api):
        """PRD 3.4: "One invariant governs the pile at all times:
        `available_tons` always equals `on_hand_tons` minus `reserved_tons`,
        and every mutation — production credits, ticket draws, manual
        adjustments, reservations and their release, voids — maintains it."

        Design: Difficulty/compensating_invariant/ticket_void_roundtrip_conserves_available_tons
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100)
        pile = get_stockpile(ctx["pile"]["id"])
        assert pile["available_tons"] == pytest.approx(100.0, abs=1e-6)
        _entry, ticket = complete_ticket(ctx, gross_lbs=80000)
        pile = get_stockpile(ctx["pile"]["id"])
        # Draw 26.000: on_hand 174.0, reserved 74.0, available unchanged.
        assert pile["on_hand_tons"] == pytest.approx(174.0, abs=1e-6)
        assert pile["reserved_tons"] == pytest.approx(74.0, abs=1e-6)
        assert pile["available_tons"] == pytest.approx(100.0, abs=1e-6)
        assert_stockpile_invariants(pile)

    def test_ticket_void_roundtrip_full_compensation(self, api):
        """PRD 3.7: "The void moves the ticket to the terminal state
        `VOIDED` and compensates in full: the stockpile regains `net_tons`
        in `on_hand_tons`; the order's `fulfilled_tons` loses `net_tons`,
        its reservation is recomputed as the unfulfilled balance floored at
        zero, and an order that had auto-completed reverts from `COMPLETED`
        back to `IN_FULFILLMENT`".

        Design: Difficulty/compensating_invariant/ticket_void_roundtrip_conserves_available_tons
        """
        ctx = setup_ticketing_site(on_hand=200.0, quantity_tons=100)
        _entry, ticket = complete_ticket(ctx, gross_lbs=80000)
        ticket = validate_success(api.void_scale_ticket(
            ticket["id"], {"void_reason": "duplicate entry"}, MANAGER))
        assert ticket["status"] == "VOIDED"
        pile = get_stockpile(ctx["pile"]["id"])
        assert pile["on_hand_tons"] == pytest.approx(200.0, abs=1e-6)
        assert pile["reserved_tons"] == pytest.approx(100.0, abs=1e-6)
        assert pile["available_tons"] == pytest.approx(100.0, abs=1e-6)
        order = get_order(ctx["order"]["id"])
        assert order["fulfilled_tons"] == pytest.approx(0.0, abs=1e-9)
        assert order["status"] == "IN_FULFILLMENT"


class TestTicketListing:
    def test_filtered_list_reverse_reachability(self, api):
        """PRD 2.3: "Many list endpoints additionally accept optional
        filters named after resource fields — for example `site_id`,
        `status`, `bench_id`, `shot_plan_id`, `stockpile_id`,
        `product_spec_id`, ... `sales_order_id` ...".

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        ctx = setup_ticketing_site(on_hand=500.0, quantity_tons=200)
        order2 = create_confirmed_order(ctx["site"]["id"], ctx["spec"]["id"],
                                        ctx["zone"]["id"],
                                        customer_name="BETA",
                                        quantity_tons=100)
        _e1, t1 = complete_ticket(ctx, truck_id="TRK-1", gross_lbs=80000)
        _e2, t2 = complete_ticket(ctx, truck_id="TRK-2", gross_lbs=80000)
        _e3, _t3 = complete_ticket(ctx, truck_id="TRK-3", gross_lbs=80000,
                                   order_id=order2["id"])
        data, meta = validate_paginated(api.list_scale_tickets(
            MANAGER, params={"sales_order_id": ctx["order"]["id"]}))
        assert sorted(t["id"] for t in data) == sorted([t1["id"], t2["id"]])
        for ticket in data:
            assert ticket["stockpile_id"] == ctx["pile"]["id"]
            assert ticket["status"] == "COMPLETED"
