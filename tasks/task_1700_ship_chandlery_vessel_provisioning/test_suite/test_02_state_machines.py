"""Non-linear state machines (difficulty rule 3).

Covers the Quotation SENT -> SENT revision cycle (PRD §3.4), the Order's two
independent status dimensions (PRD §2.9), and the QualityComplaint
reject/reopen cycle arming the four-eyes rule (PRD §3.12).
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
    setup_accepted_order,
    setup_invoiced_order,
)
from test_helpers.fixtures import (
    confirm_delivery,
    create_scheduled_delivery,
    dispatch_delivery,
    file_complaint,
)

SALES = TEST_USERS["sales_headers"]


# ===========================================================================
# non_linear_state_machine / quotation_revision_cycle
# ===========================================================================

class TestQuotationRevisionCycle:
    def test_revise_cycles_sent_to_sent_and_advances_counters(self, api):
        """PRD §3.4: "A quotation already `SENT` can be revised — the machine cycles
        `SENT → SENT`: the revise payload replaces `lines` and `valid_until`,
        recomputes the provisional total, and increments `revision_count`."

        One revise lap: revision_count 0 -> 1, version advances by exactly 1,
        status stays SENT.

        Design: Difficulty/non_linear_state_machine/quotation_revision_cycle
        """
        # Build a SENT quotation manually so we can revise before accepting.
        from test_helpers.fixtures import (
            arrive_vessel_call,
            create_agent,
            create_catalog_item,
            create_sent_quotation,
            create_stock_lot,
            create_submitted_requisition,
            create_vessel_call,
            set_clock,
        )
        agent = create_agent(name="Agent Zeta")
        water = create_catalog_item(
            sku="WATER-01", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-W1", received_qty=10000)
        call = create_vessel_call(agent["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=1000)
        quo = create_sent_quotation(req["id"], water["id"], qty=1000, unit_price_cents=120)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])

        before = get_success_data(api_client.get_quotation(quo["id"], SALES))
        assert before["status"] == "SENT"
        assert before["revision_count"] == 0
        revised = get_success_data(api_client.revise_quotation(quo["id"], {
            "lines": [{
                "catalog_item_id": water["id"], "qty": 900, "unit_price_cents": 110,
                "is_substitution": False,
            }],
            "valid_until": "2026-08-12T00:00:00Z",
            "expected_quotation_version": before["version"],
        }, SALES))
        assert revised["status"] == "SENT", "SENT -> SENT cycle"
        assert revised["revision_count"] == 1, "revision_count increments on each lap"
        assert revised["version"] == before["version"] + 1, (
            "version advances by exactly 1 on revise"
        )

    def test_accept_succeeds_from_post_cycle_sent_state(self, api):
        """PRD §3.4: "A quotation already `SENT` can be revised — the machine cycles
        `SENT → SENT`" — a quotation remains acceptable from the post-cycle SENT
        state. PRD §3.4: "Acceptance is the pivot of the whole system and is
        performed by the vessel's catering officer". After one revise (900 x 110,
        duty 0, no cold), accept creates the order with the re-priced total
        99,000 (subtotal 99,000 < 500,000 => rebate 0).

        Design: Difficulty/non_linear_state_machine/quotation_revision_cycle
        """
        from test_helpers.fixtures import (
            arrive_vessel_call,
            create_agent,
            create_catalog_item,
            create_sent_quotation,
            create_stock_lot,
            create_submitted_requisition,
            create_vessel_call,
            set_clock,
        )
        agent = create_agent(name="Agent Zeta")
        water = create_catalog_item(
            sku="WATER-01", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-W1", received_qty=10000)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=1000)
        quo = create_sent_quotation(req["id"], water["id"], qty=1000, unit_price_cents=120)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])

        before = get_success_data(api_client.get_quotation(quo["id"], SALES))
        get_success_data(api_client.revise_quotation(quo["id"], {
            "lines": [{
                "catalog_item_id": water["id"], "qty": 900, "unit_price_cents": 110,
                "is_substitution": False,
            }],
            "valid_until": "2026-08-12T00:00:00Z",
            "expected_quotation_version": before["version"],
        }, SALES))
        order = get_success_data(api_client.accept_quotation(quo["id"], officer))
        quotation = get_success_data(api_client.get_quotation(quo["id"], SALES))
        assert quotation["status"] == "ACCEPTED", (
            "Accept succeeds from the post-cycle SENT state"
        )
        assert order["total_cents"] == 99000, (
            f"900 x 110, duty 0, no cold, subtotal 99000 < 500000 => rebate 0; "
            f"got {order['total_cents']}"
        )


# ===========================================================================
# non_linear_state_machine / order_parallel_fulfillment_payment_dimensions
# ===========================================================================

class TestOrderParallelFulfillmentPaymentDimensions:
    def test_full_delivery_moves_fulfillment_only(self, api):
        """PRD §2.9: "`Order` pairs `fulfillment_status` (...) with
        `payment_status` (...); fulfillment moves on delivery confirms and
        cancels, payment moves on invoice issuance, payments, and credit notes".
        After a full delivery: fulfillment_status == DELIVERED while
        payment_status stays UNINVOICED.

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_dimensions
        """
        ctx = setup_accepted_order(qty=1000, unit_price_cents=120,
                                   item_overrides=dict(sku="WATER-02", name="Water 1L"))
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 1000)
        dispatch_delivery(delivery["id"])
        officer = make_officer_headers(ctx["call"]["id"])
        confirm_delivery(delivery["id"], ctx["item"]["id"], 1000, officer)

        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["payment_status"] == "UNINVOICED", (
            "Delivering in full must not disturb the payment dimension"
        )

    def test_invoice_issuance_moves_payment_only(self, api):
        """PRD §2.9: "the dimensions cross only at two gates". PRD §3.9: "the
        order's payment dimension moves `UNINVOICED → INVOICED`". After invoice
        issuance on a fully delivered order: payment_status == INVOICED while
        fulfillment_status stays DELIVERED.

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_dimensions
        """
        ctx = setup_invoiced_order(qty=1000, unit_price_cents=120,
                                   fx_rate_to_settlement=1.0,
                                   item_overrides=dict(sku="WATER-02", name="Water 1L"))
        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["payment_status"] == "INVOICED"
        assert order["fulfillment_status"] == "DELIVERED", (
            "Issuing the invoice must not disturb the fulfillment dimension"
        )
        assert ctx["invoice"]["total_cents"] == 120000


# ===========================================================================
# non_linear_state_machine / complaint_reject_reopen_cycle_with_four_eyes
# ===========================================================================

class TestComplaintRejectReopenCycleWithFourEyes:
    def test_reopen_completes_cycle_and_increments_reopen_count(self, api):
        """PRD §3.12: "The vessel may then reopen it — `REJECTED → SUBMITTED` —
        through the officer who owns the call (else `ERR_INSUFFICIENT_PERMISSIONS`);
        reopening from any other state is `ERR_COMPLAINT_NOT_REOPENABLE`, and each
        successful reopen increments `reopen_count`."

        After a reject by qa-1 and a reopen by the vessel: status == SUBMITTED
        and reopen_count == 1 (the cycle completed).

        Design: Difficulty/non_linear_state_machine/complaint_reject_reopen_cycle_with_four_eyes
        """
        ctx = setup_invoiced_order(qty=1000, unit_price_cents=120,
                                   fx_rate_to_settlement=1.0,
                                   item_overrides=dict(sku="WATER-03", name="Water 1L"))
        officer = make_officer_headers(ctx["call"]["id"])
        complaint = file_complaint(ctx["delivery"]["id"], ctx["item"]["id"], 100, officer)
        get_success_data(api_client.reject_complaint(complaint["id"], make_qa_headers("qa-1")))
        reopened = get_success_data(api_client.reopen_complaint(complaint["id"], officer))
        assert reopened["status"] == "SUBMITTED"
        assert reopened["reopen_count"] == 1

    def test_four_eyes_blocks_same_reviewer_after_reopen(self, api):
        """PRD §3.12: "Once a complaint has been reopened at least once, a
        **four-eyes rule** arms: the next reviewer must be a different person than
        `last_reviewer_user_id`, else the accept or reject fails with
        `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        After qa-1 rejected and the vessel reopened: re-review by the SAME qa-1
        fails ERR_SEGREGATION_OF_DUTIES_VIOLATION; re-review by qa-2 succeeds.

        Design: Difficulty/non_linear_state_machine/complaint_reject_reopen_cycle_with_four_eyes
        """
        ctx = setup_invoiced_order(qty=1000, unit_price_cents=120,
                                   fx_rate_to_settlement=1.0,
                                   item_overrides=dict(sku="WATER-03", name="Water 1L"))
        officer = make_officer_headers(ctx["call"]["id"])
        complaint = file_complaint(ctx["delivery"]["id"], ctx["item"]["id"], 100, officer)
        get_success_data(api_client.reject_complaint(complaint["id"], make_qa_headers("qa-1")))
        get_success_data(api_client.reopen_complaint(complaint["id"], officer))

        from test_helpers import validate_error
        resp_same = api_client.reject_complaint(complaint["id"], make_qa_headers("qa-1"))
        validate_error(resp_same, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        rejected = get_success_data(
            api_client.reject_complaint(complaint["id"], make_qa_headers("qa-2"))
        )
        assert rejected["status"] == "REJECTED", (
            "A different reviewer may decide after the reopen"
        )
