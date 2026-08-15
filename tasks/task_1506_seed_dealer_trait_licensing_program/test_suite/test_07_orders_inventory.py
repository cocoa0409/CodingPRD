"""Orders, order lines, and inventory: initial state, confirmation guards, the
FEFO allocation selector, lot lifecycle, and the seed-unit conservation law."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    assert_inventory_lot,
    assert_lot_seed_conservation,
    assert_seed_order,
    close_sales_at,
    complete_ticket,
    confirm_order,
    create_draft_order,
    create_inventory_lot,
    get_success_data,
    schedule_delivery,
    set_clock,
    settle_program_at,
    setup_confirmed_order,
    setup_market,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


class TestOrderInitialState:
    def test_new_order_starts_draft_unpaid_none(self, api):
        """PRD §3.5: "New orders begin in `DRAFT` with `payment_status`
        `UNPAID`, `fulfillment_status` `NONE`, all monetary amounts at zero, and
        `is_replacement` false".

        Design: Corner/state_machines/new_order_starts_draft_unpaid_none
        """
        ctx = setup_market(with_lot=False)
        order = validate_success(
            api.create_order(
                {"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
                SALESREP,
            ),
            expected_status=201,
        )
        assert_seed_order(order)
        assert order["status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"
        assert order["fulfillment_status"] == "NONE"
        assert order["is_replacement"] is False
        assert order["gross_amount_cents"] == 0
        assert order["net_amount_cents"] == 0


class TestConfirmGuards:
    def test_confirm_order_without_lines_rejected(self, api):
        """PRD §3.5: "the order must contain at least one line
        (`ERR_ORDER_HAS_NO_LINES`)".

        Design: Corner/validations/confirm_order_without_lines_rejected
        """
        ctx = setup_market(with_lot=False)
        order = create_draft_order(ctx["grower"], ctx["program"])
        resp = api.confirm_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_NO_LINES)

    def test_line_with_zero_units_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum values must be
        members of their declared sets, integer quantities must be at least 1,
        acreage must be greater than zero, and unknown body fields are rejected
        — any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.5: "Each line names a `variety_id`, a `units` quantity of at
        least one".

        Design: Corner/validations/line_with_zero_units_rejected
        """
        ctx = setup_market(with_lot=False)
        order = create_draft_order(ctx["grower"], ctx["program"])
        resp = api.add_order_line(
            order["id"], {"variety_id": ctx["variety"]["id"], "units": 0}, SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_confirm_already_confirmed_order_rejected(self, api):
        """PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".
        PRD §3.5: "the order's lifecycle moves `DRAFT → CONFIRMED`."

        Design: Corner/state_machines/confirm_already_confirmed_order_rejected
        """
        ctx = setup_confirmed_order(units=10)
        net_before = ctx["order"]["net_amount_cents"]
        resp = api.confirm_order(ctx["order"]["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        order_after = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order_after["status"] == "CONFIRMED"
        assert order_after["net_amount_cents"] == net_before, (
            "the rejected re-confirmation must not change the locked pricing"
        )

    def test_confirm_rejected_when_no_lot_can_cover_line(self, api):
        """PRD §3.5: "a single lot must cover the whole line, and splitting
        across lots is never performed."
        PRD §3.5: "An empty eligible pool fails the operation with
        `ERR_INSUFFICIENT_INVENTORY`."

        Design: Corner/validations/confirm_rejected_when_no_lot_can_cover_line
        """
        ctx = setup_market(lot_overrides={"received_units": 5})
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 10)
        resp = api.confirm_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


class TestInventoryAllocation:
    def test_inventory_allocation_fefo_selects_earliest_expiry_lot(self, api):
        """PRD §3.5: "Eligible lots are ranked by earliest `expiry_date` first
        (first-expiry, first-out), with ties broken by earliest `created_at` —
        never by id — and the first lot in that ranking is selected."

        Design: Corner/calculations/inventory_allocation_fefo_selects_earliest_expiry_lot
        """
        ctx = setup_market(with_lot=False)
        lot_late = create_inventory_lot(ctx["variety"]["id"],
                                        expiry_date="2027-12-31T00:00:00Z")
        lot_early = create_inventory_lot(ctx["variety"]["id"], warehouse_code="WH2",
                                         expiry_date="2027-06-30T00:00:00Z")
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        line = add_line(order, ctx["variety"]["id"], 50)
        confirm_order(order["id"])

        line_after = validate_success(api.get_order_line(line["id"], SALESREP))
        assert line_after["inventory_lot_id"] == lot_early["id"], (
            "FEFO: the earlier-expiry lot wins despite being created second"
        )
        assert line_after["inventory_lot_id"] != lot_late["id"]


class TestLotLifecycle:
    def test_lot_depleted_when_last_unit_delivered(self, api):
        """PRD §3.7: "the lot's status is recomputed, becoming `DEPLETED` when
        its on-hand reaches zero".

        Design: Corner/state_machines/lot_depleted_when_last_unit_delivered
        """
        ctx = setup_confirmed_order(units=30, lot_overrides={"received_units": 30})
        ticket = schedule_delivery(ctx["order"], ctx["line"], 30)
        complete_ticket(ticket["id"])
        lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert lot["on_hand_units"] == 0
        assert lot["status"] == "DEPLETED"

    def test_lot_quarantine_blocked_by_open_reservations(self, api):
        """PRD §3.7: "An administrator may quarantine an `AVAILABLE` lot — but
        only while its `reserved_units` is zero, otherwise
        `ERR_LOT_HAS_RESERVATIONS` — moving it `AVAILABLE → QUARANTINED`".

        Design: Corner/validations/lot_quarantine_blocked_by_open_reservations
        """
        ctx = setup_confirmed_order(units=10)
        resp = api.quarantine_lot(ctx["lot"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LOT_HAS_RESERVATIONS)

        get_success_data(api.cancel_order(ctx["order"]["id"], SALESREP))
        lot = validate_success(api.quarantine_lot(ctx["lot"]["id"], ADMIN))
        assert lot["status"] == "QUARANTINED"


class TestSeedUnitConservation:
    def test_conservation_through_reserve_and_deliver(self, api):
        """PRD §2.9: "For every inventory lot, `received_units` plus
        `returned_units` always equals `on_hand_units` plus `delivered_units`
        plus `written_off_units`."

        Design: Difficulty/compensating_invariant/lot_seed_units_conserved_through_reserve_deliver_return
        """
        ctx = setup_confirmed_order(units=100)
        lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert_inventory_lot(lot)
        assert (lot["on_hand_units"], lot["reserved_units"]) == (500, 100)
        assert lot["delivered_units"] == 0 and lot["returned_units"] == 0
        assert_lot_seed_conservation(lot)

        ticket = schedule_delivery(ctx["order"], ctx["line"], 40)
        complete_ticket(ticket["id"])
        lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        assert (lot["on_hand_units"], lot["reserved_units"]) == (460, 60)
        assert lot["delivered_units"] == 40
        assert lot["written_off_units"] == 0
        assert_lot_seed_conservation(lot)

    def test_conservation_after_return_restock(self, api):
        """PRD §2.9: "For every inventory lot, `received_units` plus
        `returned_units` always equals `on_hand_units` plus `delivered_units`
        plus `written_off_units`."
        PRD §3.7: "restocks the lot when the seed is resalable — that is, when
        the reason is anything other than `DAMAGED` and the lot is not
        `EXPIRED`: the lot's `on_hand_units` and `returned_units` each grow by
        the returned units".

        Design: Difficulty/compensating_invariant/lot_seed_units_conserved_through_reserve_deliver_return
        """
        ctx = setup_confirmed_order(units=100)
        ticket = schedule_delivery(ctx["order"], ctx["line"], 40)
        complete_ticket(ticket["id"])
        seed_return = get_success_data(
            api.create_return(
                {"order_id": ctx["order"]["id"], "order_line_id": ctx["line"]["id"],
                 "units": 10, "reason": "OVERSTOCK"},
                SALESREP,
            )
        )
        get_success_data(api.approve_return(seed_return["id"], ADMIN))
        get_success_data(api.receive_return(seed_return["id"], ADMIN))

        lot = validate_success(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
        # 500 + 10 == 470 + 40 + 0
        assert lot["on_hand_units"] == 470
        assert lot["delivered_units"] == 40
        assert lot["returned_units"] == 10
        assert lot["written_off_units"] == 0
        assert_lot_seed_conservation(lot)


class TestAdjudicationOrder:
    def test_state_error_beats_fiscal_error_on_confirm(self, api):
        """PRD §2.8: "The server does not collect failures; it evaluates checks
        in a fixed priority order and reports the **first** failure only."
        PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".
        PRD §2.8: "Fiscal checks come last, so a cheaper failure never masks an
        expensive one".

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_on_credit_hold_state_beats_fiscal
        """
        ctx = setup_confirmed_order(units=10)
        get_success_data(api.cancel_order(ctx["order"]["id"], SALESREP))
        get_success_data(api.hold_grower(ctx["grower"]["id"], ADMIN))

        resp = api.confirm_order(ctx["order"]["id"], SALESREP)
        # Both the state rule (order CANCELLED) and the fiscal rule (grower
        # CREDIT_HOLD) are violated; state legality (priority 7) is reported.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_rejected_confirm_leaves_no_side_effects(self, api):
        """PRD §2.8: "The server does not collect failures; it evaluates checks
        in a fixed priority order and reports the **first** failure only."
        PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_on_credit_hold_state_beats_fiscal
        """
        ctx = setup_confirmed_order(units=10)
        get_success_data(api.cancel_order(ctx["order"]["id"], SALESREP))
        get_success_data(api.hold_grower(ctx["grower"]["id"], ADMIN))

        validate_error(
            api.confirm_order(ctx["order"]["id"], SALESREP),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["status"] == "CANCELLED"
        grower = validate_success(api.get_grower(ctx["grower"]["id"], ADMIN))
        assert grower["status"] == "CREDIT_HOLD"


class TestPostSettlementLockdown:
    def test_cancel_closed_order_after_settle_rejected(self, api):
        """PRD §3.9: "every `CONFIRMED` order of the program moves to `CLOSED`".
        PRD §2.8: "The target resource must be in a state from which the
        requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`,
        HTTP 409)".
        PRD §3.5 lists cancellation paths only from `DRAFT`, `CONFIRMED`, and
        `COMPLIANCE_HOLD`.

        Design: Corner/state_machines/cancel_closed_order_after_settle_rejected
        """
        ctx = setup_confirmed_order(units=10)
        close_sales_at(ctx["program"]["id"])
        settle_program_at(ctx["program"]["id"])
        order = validate_success(api.get_order(ctx["order"]["id"], SALESREP))
        assert order["status"] == "CLOSED"

        resp = api.cancel_order(order["id"], SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
