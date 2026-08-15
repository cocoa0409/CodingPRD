"""State-machine corner cases (corner-design §state_machines).

Invalid transitions, terminal lockdown, the requisition recall cycle, and the
vessel-departure cascade.
"""
from test_helpers import (
    ApiErrorId,
    FINANCE,
    OPS,
    TEST_USERS,
    api_client,
    get_success_data,
    make_officer_headers,
    make_qa_headers,
    setup_accepted_credit_note,
    setup_accepted_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    create_agent,
    create_catalog_item,
    create_scheduled_delivery,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    dispatch_delivery,
    set_clock,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def _water(sku="WATER-C4", lot_code="DS-C4"):
    return (
        dict(sku=sku, name="Water 1L", category="PROVISIONS", bonded_eligible=False,
             requires_cold_chain=False, base_price_cents=120, duty_rate_pct=0),
        dict(lot_code=lot_code, received_qty=10000),
    )


class TestConfirmScheduledDeliveryRejected:
    def test_confirm_scheduled_delivery_rejected(self, api):
        """PRD §3.6: "Confirmation requires the delivery to be `OUT_FOR_DELIVERY`
        (else `ERR_DELIVERY_NOT_CONFIRMABLE`)". Confirm from SCHEDULED (dispatch
        skipped) fails; the delivery stays SCHEDULED.

        Design: Corner/state_machines/confirm_scheduled_delivery_rejected
        """
        item_kw, lot_kw = _water("WATER-C4", "DS-C4")
        ctx = setup_accepted_order(qty=100, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 100)
        officer = make_officer_headers(ctx["call"]["id"])
        resp = api_client.confirm_delivery(delivery["id"], {
            "receiver_name": "Cook", "signature_ref": "sig-c4",
            "confirmed_lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 100}],
        }, officer)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_CONFIRMABLE)
        delivery_after = get_success_data(api_client.get_delivery(delivery["id"], OPS))
        assert delivery_after["status"] == "SCHEDULED", "No side effects fire"


class TestAcceptDraftQuotationRejected:
    def test_accept_draft_quotation_rejected(self, api):
        """PRD §3.4: "first the quotation must be `SENT` (else
        `ERR_QUOTATION_NOT_ACCEPTABLE`)". Accept from DRAFT (never sent) fails
        even when the vessel is IN_PORT and credit is ample.

        Design: Corner/state_machines/accept_draft_quotation_rejected
        """
        agent = create_agent(name="Agent AD")
        water = create_catalog_item(
            sku="WATER-C5", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-C5", received_qty=10000)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=100)
        from test_helpers.fixtures import create_draft_quotation
        quo = create_draft_quotation(req["id"], water["id"], qty=100, unit_price_cents=120)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])

        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_QUOTATION_NOT_ACCEPTABLE)


class TestDoubleAcceptIdempotencyTerminalLockdown:
    def test_double_accept_idempotency_terminal_lockdown(self, api):
        """PRD §3.4: "first the quotation must be `SENT` (else
        `ERR_QUOTATION_NOT_ACCEPTABLE`)" — ACCEPTED is terminal. PRD §3.4: "the
        orders created from a quotation can be listed as an array of zero or one
        element". A second accept fails and creates no second Order.

        Design: Corner/state_machines/double_accept_idempotency_terminal_lockdown
        """
        item_kw, lot_kw = _water("WATER-C6", "DS-C6")
        ctx = setup_accepted_order(qty=100, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        officer = make_officer_headers(ctx["call"]["id"])
        resp = api_client.accept_quotation(ctx["quotation"]["id"], officer)
        validate_error(resp, ApiErrorId.ERR_QUOTATION_NOT_ACCEPTABLE)
        orders = get_success_data(
            api_client.list_quotation_orders(ctx["quotation"]["id"], OPS)
        )
        assert len(orders) == 1, "No duplicate order created"
        assert orders[0]["id"] == ctx["order"]["id"]


class TestRequisitionInitialStateAndRecallCycle:
    def test_requisition_initial_state_and_recall_cycle(self, api):
        """PRD §3.3: "A new requisition is `DRAFT`." "the officer may recall a
        `SUBMITTED` requisition back to `DRAFT` — the cycle `DRAFT → SUBMITTED →
        DRAFT` is legal — but recall is blocked while any quotation on the
        requisition sits in `SENT`, surfacing `ERR_REQUISITION_HAS_LIVE_QUOTATION`;
        recalling from any state other than `SUBMITTED` is
        `ERR_REQUISITION_NOT_RECALLABLE`."

        Design: Corner/state_machines/requisition_initial_state_and_recall_cycle
        """
        agent = create_agent(name="Agent AF", credit_limit_cents=1000000)
        water = create_catalog_item(
            sku="WATER-C7", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        call = create_vessel_call(agent["id"], vessel_name="MV Flora")
        officer = make_officer_headers(call["id"])
        req = get_success_data(api_client.create_requisition(call["id"], {
            "title": "Water", "lines": [{
                "catalog_item_id": water["id"], "requested_qty": 5,
                "allows_substitution": False,
            }],
        }, officer))
        assert req["status"] == "DRAFT"

        get_success_data(api_client.submit_requisition(req["id"], officer))
        recalled = get_success_data(api_client.recall_requisition(req["id"], officer))
        assert recalled["status"] == "DRAFT", "Recall from SUBMITTED -> DRAFT (cycle)"

        resp = api_client.recall_requisition(req["id"], officer)
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_RECALLABLE)


class TestVesselDepartCascadeFailsDeliveriesAndCancelsOrders:
    def test_vessel_depart_cascade_fails_deliveries_and_cancels_orders(self, api):
        """PRD §3.7: "Every delivery of every order of the call still in
        `SCHEDULED` or `OUT_FOR_DELIVERY` becomes `FAILED`. Every order still
        `OPEN` becomes `CANCELLED`, releasing its allocations exactly as in the
        manual cancel". Lot had 10,000; after depart: delivery FAILED, order
        CANCELLED, on_hand back to 10,000 and reserved 0.

        Design: Corner/state_machines/vessel_depart_cascade_fails_deliveries_and_cancels_orders
        """
        item_kw, lot_kw = _water("WATER-C8", "DS-C8")
        ctx = setup_accepted_order(qty=300, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 300)

        get_success_data(api_client.depart_vessel_call(ctx["call"]["id"], OPS))

        delivery_after = get_success_data(api_client.get_delivery(delivery["id"], OPS))
        assert delivery_after["status"] == "FAILED", "Depart cascade fails the delivery"
        order_after = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order_after["fulfillment_status"] == "CANCELLED", (
            "Depart cascade cancels the OPEN order"
        )
        lot = get_success_data(api_client.get_stock_lot(ctx["lot"]["id"], WAREHOUSE))
        assert lot["on_hand_qty"] == 10000
        assert lot["reserved_qty"] == 0, "Reservations released by the cascade"


class TestCreditNoteRevokeFromRevokedRejected:
    def test_credit_note_revoke_from_revoked_rejected(self, api):
        """PRD §3.13: "A `FinanceController` may later revoke an `APPLIED` note
        (any other state yields `ERR_CREDIT_NOTE_NOT_REVOCABLE`)". REVOKED is
        terminal: a second revoke fails and no further invoice mutation occurs.

        Design: Corner/state_machines/credit_note_revoke_from_revoked_rejected
        """
        ctx = setup_accepted_credit_note(
            qty=100, unit_price_cents=5000, rejected_qty=10, qa_user_id="qa-lead-1",
            item_overrides=dict(
                sku="WHISKY-C9", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ),
            lot_overrides=dict(lot_code="BW-C9", storage_tier="BONDED_WAREHOUSE",
                               received_qty=500, capacity_qty=0),
            call_overrides=dict(foreign_going=True),
            clear_customs=True,
        )
        get_success_data(api_client.revoke_credit_note(ctx["credit_note"]["id"], FINANCE))
        resp = api_client.revoke_credit_note(ctx["credit_note"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_CREDIT_NOTE_NOT_REVOCABLE)
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["credited_amount_cents"] == 0, (
            "No second compensation applied"
        )
