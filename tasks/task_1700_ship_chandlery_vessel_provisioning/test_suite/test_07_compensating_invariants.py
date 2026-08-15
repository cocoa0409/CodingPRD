"""Compensating invariants (difficulty rule 9).

Three conserved quantities across forward/compensating action pairs:
stock units (accept/cancel), invoice money (credit apply/payment/revoke),
and agent risk exposure (accept/cancel).
"""
from test_helpers import (
    FINANCE,
    TEST_USERS,
    api_client,
    get_success_data,
    list_credit_notes,
    make_officer_headers,
    make_qa_headers,
    pay_invoice,
    setup_accepted_credit_note,
    setup_accepted_order,
)
from test_helpers.fixtures import (
    create_scheduled_delivery,
    dispatch_delivery,
    file_complaint,
    confirm_delivery,
)

OPS = TEST_USERS["ops_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def _water(sku, lot_code):
    return (
        dict(sku=sku, name="Water 1L", category="PROVISIONS", bonded_eligible=False,
             requires_cold_chain=False, base_price_cents=120, duty_rate_pct=0),
        dict(lot_code=lot_code, received_qty=10000),
    )


# ===========================================================================
# compensating_invariant / stock_conservation_reserve_release
# ===========================================================================

class TestStockConservationReserveRelease:
    def test_accept_moves_on_hand_to_reserved_conserving_sum(self, api):
        """PRD §3.5: "Every allocated unit moves from `on_hand_qty` to
        `reserved_qty` on the contributing lot." Lot received 10,000; order for
        400 accepted: on_hand 9,600 + reserved 400 == 10,000 (conservation
        across the forward action).

        Design: Difficulty/compensating_invariant/stock_conservation_reserve_release
        """
        item_kw, lot_kw = _water("WATER-22", "DS-W22")
        ctx = setup_accepted_order(
            qty=400, unit_price_cents=120, item_overrides=item_kw, lot_overrides=lot_kw,
        )
        lot = get_success_data(api_client.get_stock_lot(ctx["lot"]["id"], WAREHOUSE))
        assert lot["on_hand_qty"] == 9600
        assert lot["reserved_qty"] == 400
        assert lot["on_hand_qty"] + lot["reserved_qty"] == 10000

    def test_cancel_restores_both_fields_exactly(self, api):
        """PRD §3.7: "Cancellation is a compensating cascade: ... every allocation
        is released (`reserved_qty` returns to `on_hand_qty` on each lot)".
        After cancel: on_hand 10,000 and reserved 0 — the compensating action
        restores both fields exactly.

        Design: Difficulty/compensating_invariant/stock_conservation_reserve_release
        """
        item_kw, lot_kw = _water("WATER-22", "DS-W22")
        ctx = setup_accepted_order(
            qty=400, unit_price_cents=120, item_overrides=item_kw, lot_overrides=lot_kw,
        )
        get_success_data(api_client.cancel_order(ctx["order"]["id"], OPS))
        lot = get_success_data(api_client.get_stock_lot(ctx["lot"]["id"], WAREHOUSE))
        assert lot["on_hand_qty"] == 10000
        assert lot["reserved_qty"] == 0, (
            "Compensating cancel restores both fields exactly (no drift)"
        )


# ===========================================================================
# compensating_invariant / invoice_money_conservation_credit_cycle
# ===========================================================================

def _setup_credit_then_payment():
    """Duty-free WHISKY invoice 480,000; complaint (10 units) accepted =>
    credit 47,500 applied. Returns the context."""
    return setup_accepted_credit_note(
        qty=100, unit_price_cents=5000, rejected_qty=10, qa_user_id="qa-lead-1",
        item_overrides=dict(
            sku="WHISKY-23", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        ),
        lot_overrides=dict(lot_code="BW-23", storage_tier="BONDED_WAREHOUSE",
                           received_qty=500, capacity_qty=0),
        call_overrides=dict(foreign_going=True),
        clear_customs=True,
    )


class TestInvoiceMoneyConservationCreditCycle:
    def test_conservation_holds_after_credit_and_payment(self, api):
        """PRD §3.9: "An invoice's `outstanding_cents` is always `total_cents`
        minus `paid_amount_cents` minus `credited_amount_cents` minus
        `fx_writeoff_cents`; the invariant that paid plus credited plus write-off
        plus outstanding equals the total holds at every observable instant."

        Invoice 480,000 with credit 47,500 applied: 0 + 47,500 + 0 + 432,500 ==
        480,000. Then a 200,000 payment: 200,000 + 47,500 + 0 + 232,500 ==
        480,000.

        Design: Difficulty/compensating_invariant/invoice_money_conservation_credit_cycle
        """
        ctx = _setup_credit_then_payment()
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["paid_amount_cents"] == 0
        assert invoice["credited_amount_cents"] == 47500
        assert invoice["fx_writeoff_cents"] == 0
        assert invoice["outstanding_cents"] == 432500
        assert 0 + 47500 + 0 + 432500 == invoice["total_cents"]

        pay_invoice(ctx["invoice"]["id"], ctx["agent"]["id"], 200000, currency="USD")
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["paid_amount_cents"] == 200000
        assert invoice["credited_amount_cents"] == 47500
        assert invoice["outstanding_cents"] == 232500
        assert 200000 + 47500 + 0 + 232500 == invoice["total_cents"]

    def test_conservation_holds_after_revoke(self, api):
        """PRD §3.13: "Revocation flips the note to `REVOKED`, subtracts
        `amount_cents` from the invoice's `credited_amount_cents`, recomputes the
        outstanding balance". After credit 47,500 + payment 200,000 + revoke:
        200,000 + 0 + 0 + 280,000 == 480,000 — compensation exact.

        Design: Difficulty/compensating_invariant/invoice_money_conservation_credit_cycle
        """
        ctx = _setup_credit_then_payment()
        pay_invoice(ctx["invoice"]["id"], ctx["agent"]["id"], 200000, currency="USD")
        get_success_data(api_client.revoke_credit_note(ctx["credit_note"]["id"], FINANCE))

        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["paid_amount_cents"] == 200000
        assert invoice["credited_amount_cents"] == 0
        assert invoice["fx_writeoff_cents"] == 0
        assert invoice["outstanding_cents"] == 280000
        assert 200000 + 0 + 0 + 280000 == invoice["total_cents"], (
            "Apply-then-revoke leaves the invoice exactly consistent"
        )


# ===========================================================================
# compensating_invariant / agent_exposure_accept_cancel_pair
# ===========================================================================

class TestAgentExposureAcceptCancelPair:
    def test_accept_adds_order_total_to_committed(self, api):
        """PRD §2.7: "`committed_exposure_cents` is the sum of `total_cents` over
        the agent's orders whose `payment_status` is `UNINVOICED` and whose
        `fulfillment_status` is one of `OPEN`, `PARTIALLY_DELIVERED`, or
        `DELIVERED`...". PRD §3.4: "The agent's `committed_exposure_cents` is
        recomputed to include the new order total." Order 400 x 120 = 48,000:
        committed jumps from 0 to exactly 48,000.

        Design: Difficulty/compensating_invariant/agent_exposure_accept_cancel_pair
        """
        item_kw, lot_kw = _water("WATER-24", "DS-W24")
        ctx = setup_accepted_order(
            qty=400, unit_price_cents=120, item_overrides=item_kw, lot_overrides=lot_kw,
            agent_overrides=dict(name="Agent Omega"),
        )
        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent["committed_exposure_cents"] == 48000, (
            "Order leg added exactly once"
        )

    def test_cancel_nets_exposure_to_zero(self, api):
        """PRD §3.7: "the agent's settled and committed exposures are recomputed,
        dropping this order's total from the committed leg." Accept (48,000)
        then cancel: committed returns to exactly 0 — the pair conserves
        exposure with zero drift.

        Design: Difficulty/compensating_invariant/agent_exposure_accept_cancel_pair
        """
        item_kw, lot_kw = _water("WATER-24", "DS-W24")
        ctx = setup_accepted_order(
            qty=400, unit_price_cents=120, item_overrides=item_kw, lot_overrides=lot_kw,
            agent_overrides=dict(name="Agent Omega"),
        )
        get_success_data(api_client.cancel_order(ctx["order"]["id"], OPS))
        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent["committed_exposure_cents"] == 0
        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["fulfillment_status"] == "CANCELLED"
