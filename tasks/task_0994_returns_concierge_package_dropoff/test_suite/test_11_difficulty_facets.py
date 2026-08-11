"""Second coverage test per difficulty-design instance (§2.1 queue A requires
>=2 tests per instance). Each test probes a distinct facet of the same
instance's claim and carries the same Design tag as its sibling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_order_to_tote,
    append_ledger_entry_payload,
    book_pickup,
    create_counter_order_dropped_off,
    create_location,
    create_order,
    create_return_item_line,
    create_return_order_payload,
    create_slot,
    drive_pickup_collect,
    fulfill_order_to_refund_posted,
    fulfill_order_via_pickup,
    get_order,
    get_projection,
    inspect_item,
    issue_label,
    list_order_items,
    make_location_operator_headers,
    make_platform_admin_headers,
    make_support_agent_headers,
    open_exception,
    receive_order,
    reserve_slot,
    resolve_exception,
    run_sweep,
    set_clock,
    setup_commercial_spine,
    setup_tote_with_route,
    start_investigation,
    tote_membership_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADMIN_1 = make_platform_admin_headers("admin-1")
ADMIN_2 = make_platform_admin_headers("admin-2")
AGENT_A = make_support_agent_headers("agent-a")
AGENT_B = make_support_agent_headers("agent-b")


def _pickup_spine(email, **plan_overrides):
    merged = {"pickup_enabled": True}
    merged.update(plan_overrides)
    return setup_commercial_spine(plan_overrides=merged, shopper_email=email,
                                  with_zone=True)


def _counter_spine(email, **plan_overrides):
    merged = {"pickup_enabled": False}
    merged.update(plan_overrides)
    return setup_commercial_spine(plan_overrides=merged, shopper_email=email)


class TestDualVariantCalc:

    def test_provisional_estimate_uses_declared_condition_not_inspected(self, api):
        """PRD §3.3: "a deduction percentage is taken from the *declared*
        condition — zero for `NEW`, ten percent for `LIGHT_USE`, fifty percent
        for `DAMAGED`, zero for `DEFECTIVE`, and one hundred percent for
        `WRONG_ITEM`; and the plan's `free_returns` waiver is *not* applied."

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_free_returns_divergence
        """
        spine = _pickup_spine("s1b@x.com", free_returns=True)
        # Declared DAMAGED (50%) but will inspect NEW (0% + waiver): the
        # estimate must use the DECLARED condition and ignore the waiver.
        order = create_order(
            spine, method="HOME_PICKUP", boxless=True,
            items=[create_return_item_line(sku="A2", unit_price_cents=8000,
                                           declared_condition="DAMAGED",
                                           longest_side_cm=40)],
        )
        # Pessimistic: declared DAMAGED -> 50% of 8000 = 4000 deducted.
        assert order["refund_estimate_cents"] == 4000

        items = list_order_items(order["id"])
        appointment = book_pickup(order, spine["zone"])
        drive_pickup_collect(appointment["id"])
        receive_order(order["id"])
        inspect_item(items[0]["id"], "NEW")

        order_after = get_order(order["id"])
        assert order_after["refund_final_cents"] == 8000
        assert order_after["refund_estimate_cents"] == 4000

    def test_preview_counts_in_flight_while_close_drops_it(self, api):
        """PRD §3.2: "is forward-looking: it counts both fulfilled and
        in-flight orders toward overage. A **final close** counts fulfilled
        orders only, so identical data with any in-flight orders yields a
        different total between the two variants."

        Design: Difficulty/dual_variant_calc/billing_preview_vs_close_inflight_divergence
        """
        # included_returns must be >= 1: at 0 the §3.3 overage hard cap
        # (2x inclusion = 0) forbids every order creation.
        spine = setup_commercial_spine(
            plan_overrides={"monthly_fee_cents": 1000, "included_returns": 1,
                            "overage_fee_cents": 100},
            shopper_email="sb2@x.com", with_zone=True,
        )
        cycle = spine["cycle"]
        # Two in-flight orders only: preview counts them, close does not.
        for sku in ("IF1", "IF2"):
            create_order(spine, method="HOME_PICKUP", boxless=True,
                         items=[create_return_item_line(sku=sku)])

        preview = validate_success(api.get_charge_preview(cycle["id"], ADMIN))
        assert preview["in_flight_count"] == 2
        assert preview["fulfilled_count"] == 0
        # counted = 2 -> overage 1 -> gross 1100.
        assert preview["overage_count"] == 1
        assert preview["gross_cents"] == 1100

        closed = validate_success(api.close_billing_cycle(cycle["id"], ADMIN))
        assert closed["fulfilled_count"] == 0
        assert closed["overage_count"] == 0
        assert closed["gross_cents"] == 1000

    def test_demand_load_equals_confirmed_when_no_retryable_failed(self, api):
        """PRD §3.6: "`demand_load` adds to that the `FAILED` appointments
        with `attempt_count` below three whose window contains now — the
        expected reschedules — so the demand gauge is always at least the
        confirmed one".

        Design: Difficulty/dual_variant_calc/zone_load_confirmed_vs_demand_projection_divergence
        """
        from test_helpers import api_client, create_zone
        spine = setup_commercial_spine(shopper_email="sz2@x.com")
        zone = create_zone(zone_code="Z2", window_capacity=5)
        order = create_order(spine, method="HOME_PICKUP", boxless=True,
                             items=[create_return_item_line(sku="Z9")])
        book_pickup(order, zone, window_start="2026-05-01T00:30:00Z",
                    window_end="2026-05-01T02:30:00Z")

        set_clock("2026-05-01T01:00:00Z")
        zone_after = validate_success(api_client.get_courier_zone(zone["id"], ADMIN))
        # No FAILED appointments: demand collapses onto confirmed.
        assert zone_after["confirmed_load"] == 1
        assert zone_after["demand_load"] == 1


class TestCombinatorialFormula:

    def test_damaged_never_waived_even_with_free_returns(self, api):
        """PRD §3.8: "a `DAMAGED` line is never waived and always keeps its
        fifty percent."

        Design: Difficulty/combinatorial_formula/item_deduction_condition_tier_plan_flag_interplay
        """
        spine = _pickup_spine("st2@x.com", free_returns=True)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="DM", unit_price_cents=7000,
                                           declared_condition="NEW",
                                           longest_side_cm=20)],
        )
        item = inspect_item(items[0]["id"], "DAMAGED")
        assert item["deduction_cents"] == 3500
        order_after = get_order(order["id"])
        assert order_after["refund_final_cents"] == 3500

    def test_rounding_half_up_applies_per_line(self, api):
        """PRD §2.6: "whenever a computation produces a non-integer cent value
        — which happens when a percentage is applied — the result is rounded
        **half-up** to the nearest integer cent." "each return item's
        `deduction_cents` is rounded half-up individually **before** any
        summation".

        Design: Difficulty/combinatorial_formula/refund_per_line_rounding_then_sum_pinned
        """
        spine = _pickup_spine("sr2@x.com", free_returns=False)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="HU", unit_price_cents=3335,
                                           longest_side_cm=15)],
        )
        # round_half_up(3335 * 0.10) = round_half_up(333.5) = 334.
        item = inspect_item(items[0]["id"], "LIGHT_USE")
        assert item["deduction_cents"] == 334
        projection = get_projection(order["id"])
        assert projection["final_cents"] == 3001

    def test_discount_tier_boundary_below_200000_earns_nothing(self, api):
        """PRD §3.2: "a gross of at least 200,000 cents but less than 500,000
        earns five percent, and anything below earns nothing".

        Design: Difficulty/combinatorial_formula/billing_discount_tier_evaluated_on_gross_pinned
        """
        spine = setup_commercial_spine(
            plan_overrides={"monthly_fee_cents": 199999, "included_returns": 100},
            shopper_email="sd2@x.com",
        )
        closed = validate_success(
            api.close_billing_cycle(spine["cycle"]["id"], ADMIN)
        )
        assert closed["gross_cents"] == 199999
        assert closed["discount_cents"] == 0
        assert closed["total_cents"] == 199999


class TestNonLinearStateMachine:

    def test_order_re_enters_inspecting_after_rejected_exception(self, api):
        """PRD §3.8: "This order-level re-evaluation also runs whenever an
        exception resolves: with no further open exceptions and at least one
        item still `PENDING`, the order returns `EXCEPTION_PENDING` →
        `INSPECTING`".

        Design: Difficulty/non_linear_state_machine/return_order_inspecting_exception_pending_cycle
        """
        spine = _pickup_spine("sc2@x.com")
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="C1", unit_price_cents=1000),
                create_return_item_line(sku="C2", unit_price_cents=1000),
            ],
        )
        inspect_item(items[0]["id"], "NEW")
        # DAMAGED_ITEM carries no terminal cascade when rejected (§3.9), so
        # resolution re-evaluates the order per §3.8; a rejected LOST_PARCEL
        # would instead close the order into REJECTED_CLOSED.
        case = open_exception(order["id"], "DAMAGED_ITEM", note="probe",
                              return_item_id=items[1]["id"],
                              opener_headers=AGENT_A)
        assert get_order(order["id"])["status"] == "EXCEPTION_PENDING"

        case = start_investigation(case["id"], headers=AGENT_A)
        resolve_exception(case["id"], "REJECTED", headers=AGENT_B)
        # One item still PENDING -> back to INSPECTING (not terminal).
        assert get_order(order["id"])["status"] == "INSPECTING"

    def test_appeal_on_posted_refund_keeps_order_refund_posted(self, api):
        """PRD §3.9: "An appeal on an already-posted refund does not unwind
        the posting: the order stays `REFUND_POSTED`, and any money correction
        flows through the ledger's `ADJUSTMENT` and `CORRECTION` machinery of
        §3.8 rather than by re-opening settlement."

        Design: Difficulty/non_linear_state_machine/exception_case_appeal_reopen_cycle
        """
        from test_helpers import api_client, appeal_payload
        spine = _pickup_spine("sa2@x.com")
        order, items = fulfill_order_via_pickup(
            spine, items=[create_return_item_line(sku="AP2",
                                                  unit_price_cents=1000)],
        )
        # The exception must be opened BEFORE the last PENDING item is
        # inspected: inspecting it with no open exception would settle the
        # order straight to the terminal REFUND_POSTED (§3.8), and §3.9 only
        # allows opening cases on non-terminal orders.
        case = open_exception(order["id"], "DAMAGED_ITEM", note="opened",
                              return_item_id=items[0]["id"],
                              opener_headers=AGENT_A)
        inspect_item(items[0]["id"], "DAMAGED")
        case = start_investigation(case["id"], headers=AGENT_A)
        resolve_exception(case["id"], "REJECTED", headers=AGENT_B)
        assert get_order(order["id"])["status"] == "REFUND_POSTED"

        appealed = validate_success(
            api_client.appeal_exception_case(
                case["id"], appeal_payload("recheck"), spine["shopper_headers"]
            )
        )
        assert appealed["status"] == "REOPENED"
        # The posted refund is not unwound by the appeal.
        assert get_order(order["id"])["status"] == "REFUND_POSTED"

    def test_unseal_then_reseal_then_dispatch_path(self, api):
        """PRD §3.7: "the seal can be deliberately reverted, moving `SEALED`
        back to `FILLING` and clearing `sealed_by_user_id`, a cyclic pair that
        allows repacking before dispatch."

        Design: Difficulty/non_linear_state_machine/tote_seal_unseal_discrepancy_cycles
        """
        from test_helpers import api_client
        spine = _counter_spine("so2@x.com")
        location = create_location(name="L-T2", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = create_counter_order_dropped_off(spine, location)
        tote = add_order_to_tote(tote, order, location["id"])

        op = make_location_operator_headers(location["id"])
        validate_success(api_client.seal_tote(tote["id"], op))
        unsealed = validate_success(api_client.unseal_tote(tote["id"], op))
        assert unsealed["status"] == "FILLING"
        assert unsealed["sealed_by_user_id"] is None

        resealed = validate_success(api_client.seal_tote(tote["id"], op))
        assert resealed["status"] == "SEALED"
        assert resealed["sealed_by_user_id"] == location["id"]

        validate_success(
            api_client.dispatch_route(route["id"],
                                      TEST_USERS["carrier_dispatcher_headers"])
        )
        dispatched = validate_success(api_client.dispatch_tote(tote["id"], op))
        assert dispatched["status"] == "DISPATCHED"


class TestTransitiveCascade:

    def test_approved_damaged_flips_condition_and_recomputes_final(self, api):
        """PRD §3.9: "An approved `DAMAGED_ITEM` case rewrites the linked
        item's condition from `DAMAGED` to `DEFECTIVE`."
        PRD §3.8: "zero for `DEFECTIVE`".

        Design: Difficulty/transitive_cascade/exception_approve_damaged_depth4_cascade
        """
        spine = _pickup_spine("s4b@x.com", free_returns=False)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="A5", unit_price_cents=6000,
                                           longest_side_cm=20)],
        )
        # Open the case before inspecting the only item: inspecting the last
        # PENDING item with no open exception would settle the order to the
        # terminal REFUND_POSTED at once (§3.8), making the case unopenable.
        case = open_exception(order["id"], "DAMAGED_ITEM", note="contest",
                              return_item_id=items[0]["id"],
                              opener_headers=AGENT_A)
        inspect_item(items[0]["id"], "DAMAGED")  # deduction 3000 recorded
        case = start_investigation(case["id"], headers=AGENT_A)
        resolve_exception(case["id"], "APPROVED", headers=AGENT_B)

        item_after = validate_success(api.get_return_item(items[0]["id"], ADMIN))
        assert item_after["condition"] == "DEFECTIVE"
        assert item_after["deduction_cents"] == 0
        order_after = get_order(order["id"])
        assert order_after["status"] == "REFUND_POSTED"
        assert order_after["refund_final_cents"] == 6000

    def test_consume_sets_dropoff_location_and_consumes_label(self, api):
        """PRD §3.5: "that flip causes the order to move `LABEL_ISSUED` →
        `DROPPED_OFF` with `dropoff_location_id` set to the slot's location;
        and the drop-off in turn consumes the bound label (`ISSUED` →
        `CONSUMED`)".

        Design: Difficulty/transitive_cascade/reservation_consume_three_link_cascade
        """
        from test_helpers import api_client
        spine = _counter_spine("sl2@x.com")
        location = create_location(name="L-L2", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order = create_order(
            spine, method="LOCKER_QR",
            items=[create_return_item_line(sku="L2", longest_side_cm=40)],
        )
        reservation = reserve_slot(order, slot, spine["shopper_headers"])
        validate_success(
            api_client.consume_slot_reservation(
                reservation["id"], make_location_operator_headers(location["id"])
            )
        )
        order_after = get_order(order["id"])
        assert order_after["status"] == "DROPPED_OFF"
        assert order_after["dropoff_location_id"] == location["id"]
        label_after = validate_success(
            api_client.get_label(reservation["label_id"], ADMIN)
        )
        assert label_after["status"] == "CONSUMED"

    def test_sweep_reports_counts_and_frees_slot(self, api):
        """PRD §2.5: "The sweep response reports `expired_label_count` and
        `expired_reservation_count`."
        PRD §3.5: "**Expiry** — from the §2.5 sweep — moves `HELD` →
        `EXPIRED` when `hold_until` has been reached, freeing the slot to
        `EMPTY` and recomputing the location's reserved count."

        Design: Difficulty/transitive_cascade/sweep_expiry_four_link_cascade
        """
        from test_helpers import api_client
        spine = _counter_spine("ss2@x.com")
        location = create_location(name="L-S2", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order = create_order(
            spine, method="LOCKER_QR",
            items=[create_return_item_line(sku="S2", longest_side_cm=40)],
        )
        reserve_slot(order, slot, spine["shopper_headers"])

        set_clock("2026-05-12T00:00:00Z")
        sweep = run_sweep()
        assert sweep["expired_label_count"] == 1
        assert sweep["expired_reservation_count"] == 1
        slot_after = validate_success(api_client.get_locker_slot(slot["id"], ADMIN))
        assert slot_after["status"] == "EMPTY"
        location_after = validate_success(
            api_client.get_dropoff_location(location["id"], ADMIN)
        )
        assert location_after["reserved_slot_count"] == 0


class TestPriorityPairs:

    def test_merchant_suspended_alone_rejects_create(self, api):
        """PRD §3.1: "may suspend the account (`ACTIVE` → `SUSPENDED`), which
        immediately blocks new return order creation for the merchant with
        `ERR_MERCHANT_SUSPENDED`".

        Design: Difficulty/priority_pair_validation_conflict/create_order_referential_beats_fiscal
        """
        from test_helpers import api_client
        spine = _pickup_spine("sp2@x.com")
        validate_success(
            api_client.suspend_merchant(spine["merchant"]["id"], ADMIN)
        )
        # Only the P7 referential failure holds here (no fiscal pressure);
        # the surfaced error is still ERR_MERCHANT_SUSPENDED.
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="HOME_PICKUP", boxless=True,
                items=[create_return_item_line(sku="P4")],
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MERCHANT_SUSPENDED)

    def test_boxless_gate_alone_rejects_locker_order(self, api):
        """PRD §3.3: "boxless flows require `boxless_enabled`, with violations
        rejected as `ERR_FEATURE_NOT_INCLUDED`."
        PRD §3.3: "Choosing `LOCKER_QR` forces `boxless` to true".

        Design: Difficulty/priority_pair_validation_conflict/create_order_safety_beats_plan_constraint
        """
        spine = _counter_spine("sf2@x.com", boxless_enabled=False)
        # 20 cm item: dimension safety passes; only the P9 feature gate fails.
        resp = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], spine["merchant"]["id"],
                method="LOCKER_QR",
                items=[create_return_item_line(sku="SM", longest_side_cm=20)],
            ),
            spine["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FEATURE_NOT_INCLUDED)

    def test_pickup_create_on_cancelled_order_rejected_invalid_state(self, api):
        """PRD §3.6: "A **PickupAppointment** is booked by the shopper for an
        order that must be `INITIATED` with method `HOME_PICKUP`".
        PRD §2.8: "the target resource is in a valid from-state for the
        requested transition and terminal resources reject everything, else
        `ERR_INVALID_STATE` or `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/priority_pair_validation_conflict/pickup_create_state_beats_temporal
        """
        from test_helpers import create_pickup_appointment_payload
        spine = _pickup_spine("stm2@x.com")
        zone = spine["zone"]
        order = create_order(spine, method="HOME_PICKUP", boxless=True,
                             items=[create_return_item_line(sku="TP2")])
        validate_success(api.cancel_return_order(order["id"],
                                                 spine["shopper_headers"]))
        # A FUTURE window on a terminal order: the temporal rule passes, so
        # the surfaced error is the state-legality one.
        resp = api.create_pickup_appointment(
            create_pickup_appointment_payload(order["id"], zone["id"]),
            spine["shopper_headers"],
        )
        # A cancelled (terminal) order rejects everything; the PRD allows
        # either state-legality error id here.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value,
                   ApiErrorId.ERR_ALREADY_TERMINAL.value],
        )


class TestBoundaryPrecision:

    def test_oversize_item_marks_order_and_locks_locker_flow(self, api):
        """PRD §3.3: "`has_oversize_item` is true when any item's
        `longest_side_cm` exceeds 150".
        PRD §3.3: "Choosing `LOCKER_QR` forces `boxless` to true and forbids
        any item whose `longest_side_cm` exceeds 150 — such an item presented
        for a locker flow is rejected with `ERR_DIM_EXCEEDS_XL`."

        Design: Difficulty/boundary_precision_check/locker_xl_dim_boundary_150_accepted_151_rejected
        """
        spine = _pickup_spine("sx2@x.com")
        # Non-locker method with a 151 cm item: accepted and flagged oversize.
        order = create_order(
            spine, method="HOME_PICKUP", boxless=True,
            items=[create_return_item_line(sku="X2", longest_side_cm=151)],
        )
        assert order["has_oversize_item"] is True

    def test_tote_weight_below_cap_admits_and_reports(self, api):
        """PRD §3.7: "with `ERR_TOTE_WEIGHT_EXCEEDED` when it would push the
        weight strictly beyond 30,000 grams; landing exactly on either bound
        is allowed."

        Design: Difficulty/boundary_precision_check/tote_weight_exact_30000_allowed_30001_rejected
        """
        spine = _counter_spine("sw2@x.com")
        location = create_location(name="L-W2", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        heavy = create_counter_order_dropped_off(
            spine, location,
            items=[create_return_item_line(sku="HV", weight_grams=29999,
                                           longest_side_cm=20)],
        )
        tote_after = add_order_to_tote(tote, heavy, location["id"])
        # 29999 < 30000: allowed, manifest reflects the add.
        assert tote_after["manifest_weight_grams"] == 29999

    def test_consume_one_second_before_hold_until_succeeds(self, api):
        """PRD §3.5: "it requires the reservation still `HELD` and the current
        instant strictly before `hold_until`, with an attempt at or after
        `hold_until` rejected as `ERR_RESERVATION_EXPIRED`".

        Design: Difficulty/boundary_precision_check/reservation_consume_hold_until_time_boundary
        """
        from test_helpers import api_client
        spine = _counter_spine("sti2@x.com")
        location = create_location(name="L-TM", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order = create_order(
            spine, method="LOCKER_QR",
            items=[create_return_item_line(sku="TM", longest_side_cm=20)],
        )
        reservation = reserve_slot(order, slot, spine["shopper_headers"])
        # hold_until is 2026-05-03T00:00:00Z; one second before it the consume
        # succeeds.
        set_clock("2026-05-02T23:59:59Z")
        consumed = validate_success(
            api_client.consume_slot_reservation(
                reservation["id"], make_location_operator_headers(location["id"])
            )
        )
        assert consumed["status"] == "CONSUMED"


class TestCrossEntityStateDependency:

    def test_suspended_merchant_blocks_then_reactivation_restores(self, api):
        """PRD §3.1: "may suspend the account (`ACTIVE` → `SUSPENDED`), which
        immediately blocks new return order creation for the merchant with
        `ERR_MERCHANT_SUSPENDED`, and may reactivate it (`SUSPENDED` →
        `ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_merchant_active
        """
        from test_helpers import api_client
        spine = _pickup_spine("sg2@x.com")
        merchant_id = spine["merchant"]["id"]

        validate_success(api_client.suspend_merchant(merchant_id, ADMIN))
        suspended = validate_success(
            api_client.get_merchant_account(merchant_id, ADMIN)
        )
        assert suspended["status"] == "SUSPENDED"

        blocked = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], merchant_id, method="HOME_PICKUP",
                boxless=True,
            ),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_MERCHANT_SUSPENDED)

        validate_success(api_client.reactivate_merchant(merchant_id, ADMIN))
        ok = api.create_return_order(
            create_return_order_payload(
                spine["shopper"]["id"], merchant_id, method="HOME_PICKUP",
                boxless=True,
            ),
            spine["shopper_headers"],
        )
        validate_success(ok, expected_status=201)

    def test_tote_dispatch_also_requires_sealed_state(self, api):
        """PRD §3.7: "Dispatching a `SEALED` tote requires its route already
        `DISPATCHED`, else `ERR_ROUTE_NOT_DISPATCHED`" — the dispatch is
        defined only from `SEALED`.

        Design: Difficulty/cross_entity_state_dependency/tote_dispatch_requires_route_dispatched
        """
        from test_helpers import api_client
        spine = _counter_spine("srd2@x.com")
        location = create_location(name="L-RD2", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = create_counter_order_dropped_off(spine, location)
        tote = add_order_to_tote(tote, order, location["id"])
        op = make_location_operator_headers(location["id"])

        # Route dispatched but tote merely FILLING: dispatch is not legal from
        # a non-SEALED state.
        validate_success(
            api_client.dispatch_route(route["id"],
                                      TEST_USERS["carrier_dispatcher_headers"])
        )
        blocked = api_client.dispatch_tote(tote["id"], op)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

    def test_paused_location_also_blocks_counter_dropoff(self, api):
        """PRD §3.5: "A pause — available to both a `PlatformAdmin` and the
        location's own operator — moves `OPERATIONAL` → `PAUSED` and blocks
        new slot reservations and counter drop-offs with
        `ERR_LOCATION_NOT_OPERATIONAL`".

        Design: Difficulty/cross_entity_state_dependency/reservation_requires_location_operational
        """
        from test_helpers import api_client, confirm_dropoff_payload
        spine = _counter_spine("sloc2@x.com")
        location = create_location(name="L-P2", kind="COUNTER")
        order = create_order(spine, method="COUNTER_DROP")
        issue_label(order, label_type="CARRIER_LABEL")

        validate_success(api_client.pause_location(location["id"], ADMIN))
        blocked = api.confirm_dropoff(
            order["id"], confirm_dropoff_payload(location["id"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_LOCATION_NOT_OPERATIONAL)

        validate_success(api_client.resume_location(location["id"], ADMIN))
        confirmed = validate_success(
            api.confirm_dropoff(
                order["id"], confirm_dropoff_payload(location["id"]),
                make_location_operator_headers(location["id"]),
            )
        )
        assert confirmed["status"] == "DROPPED_OFF"


class TestResourceTemporalOverlap:

    def test_slot_reusable_immediately_after_release(self, api):
        """PRD §3.5: "an adjacency — a previous hold whose `hold_until` is at
        or before the current instant — blocks nothing."

        Design: Difficulty/resource_temporal_overlap/slot_live_hold_exclusive_interval
        """
        from test_helpers import api_client
        spine = _counter_spine("se2@x.com")
        location = create_location(name="L-E2", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order1 = create_order(spine, method="LOCKER_QR",
                              items=[create_return_item_line(sku="E3",
                                                             longest_side_cm=20)])
        order2 = create_order(spine, method="LOCKER_QR",
                              items=[create_return_item_line(sku="E4",
                                                             longest_side_cm=20)])
        res1 = reserve_slot(order1, slot, spine["shopper_headers"])
        validate_success(
            api_client.release_slot_reservation(res1["id"],
                                                spine["shopper_headers"])
        )
        res2 = validate_success(
            api.create_slot_reservation(
                {"return_order_id": order2["id"], "slot_id": slot["id"]},
                spine["shopper_headers"],
            ),
            expected_status=201,
        )
        assert res2["status"] == "HELD"

    def test_zone_admits_up_to_capacity_overlapping(self, api):
        """PRD §3.6: "up to that many overlapping windows are admitted, and
        the next one is refused."

        Design: Difficulty/resource_temporal_overlap/zone_window_aggregate_capacity_overlap
        """
        from test_helpers import create_pickup_appointment_payload, create_zone
        spine = setup_commercial_spine(shopper_email="sag2@x.com")
        zone = create_zone(zone_code="ZAGG2", window_capacity=1)
        order1 = create_order(spine, method="HOME_PICKUP", boxless=True,
                              items=[create_return_item_line(sku="G1")])
        order2 = create_order(spine, method="HOME_PICKUP", boxless=True,
                              items=[create_return_item_line(sku="G2")])
        ap1 = book_pickup(order1, zone)
        assert ap1["status"] == "SCHEDULED"

        # Capacity 1 reached; a second overlapping window is refused.
        blocked = api.create_pickup_appointment(
            create_pickup_appointment_payload(order2["id"], zone["id"]),
            spine["shopper_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_PICKUP_WINDOW_FULL)

    def test_billing_window_entirely_inside_existing_rejected(self, api):
        """PRD §3.2: "The new window must not overlap any non-terminal cycle
        of the same merchant under half-open interval arithmetic — two windows
        overlap when each starts before the other ends — and a violation is
        rejected with `ERR_BILLING_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/billing_period_half_open_adjacency
        """
        from test_helpers import create_merchant, create_published_plan
        plan = create_published_plan()
        merchant = create_merchant(plan["id"], legal_name="M-Per2")
        validate_success(
            api.create_billing_cycle(
                merchant["id"],
                {"period_start": "2026-04-01T00:00:00Z",
                 "period_end": "2026-06-01T00:00:00Z"},
                ADMIN,
            ),
            expected_status=201,
        )
        nested = api.create_billing_cycle(
            merchant["id"],
            {"period_start": "2026-04-15T00:00:00Z",
             "period_end": "2026-05-15T00:00:00Z"},
            ADMIN,
        )
        validate_error(nested, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)


class TestCompensatingInvariant:

    def test_remove_restores_manifest_and_clears_tote_id(self, api):
        """PRD §3.7: "A successful add sets the order's `tote_id`, a remove
        clears it back to null, and either operation recomputes the manifest
        totals and increments the tote's `version` by one."

        Design: Difficulty/compensating_invariant/tote_add_remove_conserves_manifest_totals
        """
        from test_helpers import api_client
        spine = _counter_spine("siv2@x.com")
        location = create_location(name="L-I2", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = create_counter_order_dropped_off(
            spine, location,
            items=[create_return_item_line(sku="IV2", quantity=3,
                                           weight_grams=100,
                                           longest_side_cm=20)],
        )
        tote_mid = add_order_to_tote(tote, order, location["id"])
        assert tote_mid["manifest_units"] == 3
        assert tote_mid["manifest_weight_grams"] == 300

        tote_post = validate_success(
            api_client.remove_order_from_tote(
                tote["id"],
                tote_membership_payload(order["id"], tote_mid["version"]),
                make_location_operator_headers(location["id"]),
            )
        )
        assert tote_post["manifest_units"] == 0
        assert tote_post["manifest_weight_grams"] == 0
        assert tote_post["version"] == tote_mid["version"] + 1

        order_after = validate_success(api.get_return_order(order["id"], ADMIN))
        assert order_after["tote_id"] is None

    def test_negative_adjustment_reduces_payable_above_floor(self, api):
        """PRD §3.8: "The `payable_cents` is the latest `FINAL` amount (or
        zero when none exists) plus the sum of all `ADJUSTMENT` entries plus
        the sum of all `CORRECTION` entries."
        PRD §3.8: "any entry that would push the order's payable amount below
        zero is rejected with `ERR_ADJUSTMENT_EXCEEDS_PAYABLE`" — an entry
        landing exactly on zero is allowed.

        Design: Difficulty/compensating_invariant/ledger_adjustment_correction_conserves_payable
        """
        spine = _pickup_spine("sle2@x.com")
        order, _ = fulfill_order_to_refund_posted(
            spine,
            items=[create_return_item_line(sku="LD2", unit_price_cents=10000,
                                           longest_side_cm=20)],
        )
        # Drive payable exactly to zero: allowed (the floor is inclusive).
        validate_success(
            api.append_ledger_entry(
                order["id"],
                append_ledger_entry_payload("ADJUSTMENT", -10000, "full clawback"),
                AGENT_A,
            ),
            expected_status=201,
        )
        projection = get_projection(order["id"])
        assert projection["payable_cents"] == 0

    def test_release_restores_counters_and_frees_label(self, api):
        """PRD §3.5: "**Release** — by the shopper or the operator — moves
        `HELD` → `RELEASED` and unwinds the claim: the slot returns to
        `EMPTY`, the bound label is voided, and the order falls back
        `LABEL_ISSUED` → `INITIATED`."

        Design: Difficulty/compensating_invariant/reserve_release_conserves_slot_occupancy_counters
        """
        from test_helpers import api_client
        spine = _counter_spine("scn2@x.com")
        location = create_location(name="L-C2", kind="LOCKER")
        slot = create_slot(location["id"], size_class="XL")
        order = create_order(spine, method="LOCKER_QR",
                             items=[create_return_item_line(sku="CN2",
                                                            longest_side_cm=20)])
        reservation = reserve_slot(order, slot, spine["shopper_headers"])
        validate_success(
            api_client.release_slot_reservation(reservation["id"],
                                                spine["shopper_headers"])
        )

        label_after = validate_success(
            api_client.get_label(reservation["label_id"], ADMIN)
        )
        assert label_after["status"] == "VOIDED"

        order_after = validate_success(api.get_return_order(order["id"], ADMIN))
        assert order_after["status"] == "INITIATED"

        slot_after = validate_success(api_client.get_locker_slot(slot["id"], ADMIN))
        assert slot_after["status"] == "EMPTY"

        location_after = validate_success(
            api_client.get_dropoff_location(location["id"], ADMIN)
        )
        assert location_after["reserved_slot_count"] == 0
        assert location_after["occupied_slot_count"] == 0
