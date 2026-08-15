"""Validation priority pairs (difficulty rule 5).

Each test constructs a scenario in which TWO rules are violated and asserts
that the earlier-firing check masks the later one, per the explicit ordering
the PRD states for the endpoint.

PRD §3.4 pins the accept ordering verbatim: "The checks fire in a defined
order, and the ordering matters because earlier failures mask later ones:
first the quotation must be `SENT` (else `ERR_QUOTATION_NOT_ACCEPTABLE`); then
the validity window is checked, flipping the quotation to `EXPIRED` with
`ERR_QUOTATION_EXPIRED` if the deadline has passed; then the cross-entity gate
requires the vessel call to be `IN_PORT` — a quotation cannot be accepted for
a vessel that has not arrived — else `ERR_VESSEL_CALL_NOT_IN_PORT`; then the
credit gate compares the order's total against the agent's remaining credit
per §3.9, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`; then stock sufficiency per
§3.5, surfacing `ERR_STOCK_INSUFFICIENT`; and finally cold-chain aggregate
capacity per §3.5, surfacing `ERR_COLD_CHAIN_CAPACITY_EXCEEDED`."
"""
from test_helpers import (
    ApiErrorId,
    FINANCE,
    TEST_USERS,
    api_client,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    setup_accepted_order,
    setup_invoiced_order,
    validate_error,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    confirm_delivery,
    create_agent,
    create_catalog_item,
    create_sent_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    customs_decision,
    dispatch_delivery,
    create_scheduled_delivery,
    set_clock,
)

OPS = TEST_USERS["ops_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ===========================================================================
# priority_pair_validation_conflict / state_vs_fiscal_on_quotation_accept
# ===========================================================================

class TestStateVsFiscalOnQuotationAccept:
    def test_withdrawn_quotation_accept_returns_state_error_not_credit(self, api):
        """PRD §3.4: "The checks fire in a defined order, and the ordering matters
        because earlier failures mask later ones: first the quotation must be
        `SENT` (else `ERR_QUOTATION_NOT_ACCEPTABLE`); ... then the credit gate
        compares the order's total against the agent's remaining credit per §3.9,
        surfacing `ERR_CREDIT_LIMIT_EXCEEDED`".

        A WITHDRAWN quotation whose order total (120,000) also breaches the
        agent's 1,000-cent credit limit returns ERR_QUOTATION_NOT_ACCEPTABLE —
        the fiscal check never runs on a non-SENT quotation.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_quotation_accept
        """
        agent = create_agent(name="Agent Lambda", credit_limit_cents=1000)
        water = create_catalog_item(
            sku="WATER-11", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-W11", received_qty=10000)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=1000)
        quo = create_sent_quotation(req["id"], water["id"], qty=1000, unit_price_cents=120)
        get_success_data(api_client.withdraw_quotation(quo["id"], SALES))
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])

        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_QUOTATION_NOT_ACCEPTABLE)

    def test_sent_quotation_over_credit_returns_credit_error(self, api):
        """PRD §3.4: "then the credit gate compares the order's total against the
        agent's remaining credit per §3.9, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`".
        Same fixture shape but the quotation remains SENT: with the state gate
        passed, the fiscal gate fires and the accept fails
        ERR_CREDIT_LIMIT_EXCEEDED — confirming the pair's polarity, not just its
        winner.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_quotation_accept
        """
        agent = create_agent(name="Agent Lambda", credit_limit_cents=1000)
        water = create_catalog_item(
            sku="WATER-11", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-W11", received_qty=10000)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=1000)
        quo = create_sent_quotation(req["id"], water["id"], qty=1000, unit_price_cents=120)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])

        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ===========================================================================
# priority_pair_validation_conflict / safety_vs_temporal_on_delivery_create
# ===========================================================================

def _setup_bonded_order_then_customs_rejected():
    """WHISKY order accepted while customs CLEARED; customs then REJECTED."""
    ctx = setup_accepted_order(
        qty=10, unit_price_cents=5000, requested_qty=10,
        item_overrides=dict(
            sku="WHISKY-12", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        ),
        lot_overrides=dict(lot_code="BW-12", storage_tier="BONDED_WAREHOUSE",
                           received_qty=500, capacity_qty=0),
        call_overrides=dict(foreign_going=True),
        clear_customs=True,
    )
    customs_decision(ctx["call"]["id"], "REJECTED")
    return ctx


class TestSafetyVsTemporalOnDeliveryCreate:
    def test_customs_gate_masks_window_containment(self, api):
        """PRD §3.6: "And the customs gate: if any planned line's catalog item is
        `bonded_eligible`, the vessel call's `customs_clearance_status` must be
        `CLEARED` at scheduling time, else the create is refused with
        `ERR_CUSTOMS_CLEARANCE_REQUIRED`." The customs gate is listed among the
        scheduling guards before the window rules take effect; a window ending
        after ETD would separately be `ERR_WINDOW_OUTSIDE_PORT_STAY` ("A window
        outside the stay is `ERR_WINDOW_OUTSIDE_PORT_STAY`").

        Bonded delivery while customs REJECTED AND window 2026-08-14T12:00:00Z..
        2026-08-15T12:00:00Z ending after ETD => ERR_CUSTOMS_CLEARANCE_REQUIRED.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_delivery_create
        """
        ctx = _setup_bonded_order_then_customs_rejected()
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-14T12:00:00Z",
            "window_end": "2026-08-15T12:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 10}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_CUSTOMS_CLEARANCE_REQUIRED)

    def test_window_outside_stay_fires_when_customs_clear(self, api):
        """PRD §3.6: "A window outside the stay is `ERR_WINDOW_OUTSIDE_PORT_STAY`."
        Polarity check on the same pair: with customs CLEARED (the safety gate
        passed) and the same post-ETD window, the temporal containment rule is
        the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_delivery_create
        """
        ctx = setup_accepted_order(
            qty=10, unit_price_cents=5000, requested_qty=10,
            item_overrides=dict(
                sku="WHISKY-12", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ),
            lot_overrides=dict(lot_code="BW-12", storage_tier="BONDED_WAREHOUSE",
                               received_qty=500, capacity_qty=0),
            call_overrides=dict(foreign_going=True),
            clear_customs=True,
        )
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-14T12:00:00Z",
            "window_end": "2026-08-15T12:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 10}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_PORT_STAY)


# ===========================================================================
# priority_pair_validation_conflict / referential_vs_fiscal_on_payment
# ===========================================================================

def _setup_eur_invoiced_order():
    """EUR-settled agent; WATER order 1000 x 120 delivered and invoiced at
    fx 0.9 => invoice total 108,000 EUR cents."""
    return setup_invoiced_order(
        qty=1000, unit_price_cents=120, fx_rate_to_settlement=0.9,
        agent_overrides=dict(name="Agent Nu", settlement_currency="EUR"),
        item_overrides=dict(sku="WATER-13", name="Water 1L"),
    )


class TestReferentialVsFiscalOnPayment:
    def test_missing_fx_rate_masks_overpayment(self, api):
        """PRD §3.10: "If the payment currency equals the invoice's
        `settlement_currency`, the converted amount is the tendered amount;
        otherwise the request must include a strictly positive
        `fx_rate_to_invoice_currency` — missing it is `ERR_CURRENCY_MISMATCH`".
        The overpayment rule ("If the delta exceeds 50 cents, the payment is
        rejected `ERR_PAYMENT_OVERPAYMENT`") cannot even be evaluated without a
        conversion rate, so the referential error wins.

        Invoice total 108,000 EUR cents; a 200,000 GBP payment WITHOUT
        fx_rate_to_invoice_currency => ERR_CURRENCY_MISMATCH.

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_payment
        """
        ctx = _setup_eur_invoiced_order()
        assert ctx["invoice"]["total_cents"] == 108000, (
            f"120,000 USD * 0.9 = 108,000 EUR cents; got {ctx['invoice']['total_cents']}"
        )
        resp = api_client.create_payment(
            ctx["invoice"]["id"],
            {"amount_cents": 200000, "currency": "GBP"},
            make_clerk_headers(ctx["agent"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CURRENCY_MISMATCH)

    def test_overpayment_fires_when_fx_rate_present(self, api):
        """PRD §3.10: "If the delta exceeds 50 cents, the payment is rejected
        `ERR_PAYMENT_OVERPAYMENT`." Polarity check: the same 200,000-cent
        foreign-currency payment WITH a valid fx rate converts to 180,000 EUR
        cents against a 108,000-cent outstanding — delta +72,000, far beyond
        the 50-cent tolerance — so the fiscal check fires.

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_on_payment
        """
        ctx = _setup_eur_invoiced_order()
        resp = api_client.create_payment(
            ctx["invoice"]["id"],
            {"amount_cents": 200000, "currency": "GBP", "fx_rate_to_invoice_currency": 0.9},
            make_clerk_headers(ctx["agent"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_OVERPAYMENT)
