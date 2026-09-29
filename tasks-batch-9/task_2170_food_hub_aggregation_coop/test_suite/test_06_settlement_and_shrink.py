"""Settlement: billing what arrived, instalment payments, the write-off sweep,
and the rejection claim that apportions shrink between producer and hub."""

from test_helpers import (
    ALL_DOC_TYPES,
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    add_order_line,
    allocations_for_product,
    approve_claim,
    assert_receivable_identity,
    assert_shrink_split_conserved,
    book_appointment,
    close_appointment,
    create_buyer,
    create_draft_order,
    create_dock_slot,
    create_listed_product,
    create_rejection_claim_payload,
    create_route,
    create_route_stop_payload,
    file_claim,
    make_buyer_headers,
    make_compliance_officer_headers,
    onboard_active_producer,
    read_allocation,
    read_buyer,
    read_order,
    read_order_line,
    read_producer,
    read_product,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInvoicingRevaluation:
    def test_invoicing_reselects_the_tier_from_the_delivered_subtotal(self, api):
        """PRD 3.8: "In the final valuation the set of allocations that count is
        those in `DELIVERED`, and each one's valuation quantity is its
        `delivered_quantity` rather than the quantity that was reserved;
        allocations that ended `SHORT_CLOSED` or `REVERSED` are excluded,
        exactly as they are excluded from the provisional run."
        PRD 3.8: "Because the subtotal computed from delivered quantities is
        smaller than the provisional one whenever anything arrived short, the
        margin tier is re-selected from that smaller `producer_subtotal_cents`
        and may land on a **higher** basis-point rate than the provisional run
        used."

        Design: Difficulty/dual_variant_calc/order_valuation_provisional_versus_final_at_invoice
        """
        scenario = setup_scenario(stage="in_transit")
        provisional = read_order(scenario["order_id"])
        assert provisional["order_total_cents"] == 124200
        assert provisional["margin_tier_bp"] == 1500

        validate_success(
            api.record_delivery(
                scenario["order_id"],
                {
                    "line_receipts": [
                        {
                            "allocation_id": scenario["allocation_id"],
                            "delivered_quantity": 27,
                        }
                    ]
                },
                HUB,
            )
        )
        data = validate_success(api.invoice_order(scenario["order_id"], HUB))

        assert data["margin_tier_bp"] == 1800
        assert data["producer_subtotal_cents"] == 48600
        assert data["hub_margin_cents"] == 8748
        assert data["order_total_cents"] == 57348
        assert data["settlement_status"] == "INVOICED"
        assert data["fulfillment_status"] == "DELIVERED"

    def test_invoicing_freezes_the_recomputed_total_and_bills_the_buyer(self, api):
        """PRD 3.8: "That recomputed order total is then frozen into
        `invoiced_total_cents`, which never moves again. The `invoice_due_date`
        is set to the logical clock instant at invoicing plus the buyer's
        `payment_terms_days` days, the buyer's `outstanding_balance_cents` rises
        by the invoiced total, and the order moves `UNBILLED → INVOICED`."
        PRD 3.8: "Every downstream figure follows from the recomputed rollup:
        per-allocation `producer_amount_cents`, `margin_bp`, `hub_margin_cents`
        and `buyer_amount_cents`; the order's `producer_subtotal_cents`,
        `margin_tier_bp`, `hub_margin_cents` and `order_total_cents`, including
        the 2500-cent margin floor and its top-up to the largest allocation; and
        each line's `line_producer_cents`, `line_margin_cents` and
        `line_total_cents`."

        Design: Difficulty/dual_variant_calc/order_valuation_provisional_versus_final_at_invoice
        """
        scenario = setup_scenario(stage="in_transit")
        validate_success(
            api.record_delivery(
                scenario["order_id"],
                {
                    "line_receipts": [
                        {
                            "allocation_id": scenario["allocation_id"],
                            "delivered_quantity": 27,
                        }
                    ]
                },
                HUB,
            )
        )
        validate_success(api.invoice_order(scenario["order_id"], HUB))

        order = read_order(scenario["order_id"])
        assert order["invoiced_total_cents"] == 57348
        assert order["invoice_due_date"] == "2026-10-01T00:00:00.000Z"

        allocation = read_allocation(scenario["allocation_id"])
        assert allocation["producer_amount_cents"] == 48600
        assert allocation["hub_margin_cents"] == 8748
        assert allocation["buyer_amount_cents"] == 57348

        buyer = read_buyer(scenario["buyer_id"])
        assert buyer["outstanding_balance_cents"] == 57348
        assert_receivable_identity(order, buyer)

    def test_invoicing_before_delivery_is_refused(self, api):
        """PRD 3.8: "Invoicing requires an order whose `fulfillment_status` is
        `DELIVERED` and whose `settlement_status` is still `UNBILLED`; an order
        that has not been delivered, or that has already been invoiced, is
        refused with `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/invoicing_before_delivery_returns_invalid_order_state
        """
        scenario = setup_scenario(stage="aggregated")

        resp = api.invoice_order(scenario["order_id"], HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)

        order = read_order(scenario["order_id"])
        assert order["settlement_status"] == "UNBILLED"
        assert order["invoiced_total_cents"] == 0
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 0

    def test_a_short_closed_allocation_contributes_nothing_to_the_invoice(self, api):
        """PRD 3.7: "Each referenced allocation records what arrived and moves
        `STAGED → DELIVERED` when the delivered quantity is greater than zero,
        or `STAGED → SHORT_CLOSED` when it is exactly zero — and a short-closed
        allocation releases its hold, decrementing its catalog item's
        `quantity_committed`, and contributes nothing at all to any money rollup
        thereafter."
        PRD 3.8: "In the final valuation the set of allocations that count is
        those in `DELIVERED`, and each one's valuation quantity is its
        `delivered_quantity` rather than the quantity that was reserved;
        allocations that ended `SHORT_CLOSED` or `REVERSED` are excluded,
        exactly as they are excluded from the provisional run."

        Design: Corner/calculations/short_closed_allocation_is_excluded_from_the_final_invoice_valuation
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        first = create_listed_product(pid, quantity_offered=40)
        second = create_listed_product(pid, quantity_offered=40)
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        add_order_line(order["id"], buyer["id"], quantity_requested=60)
        validate_success(api.aggregate_order(order["id"], HUB))
        alloc_one = allocations_for_product(first["id"])[0]
        alloc_two = allocations_for_product(second["id"])[0]

        route = create_route(pallet_capacity=20)
        validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(order["id"], route["version"]),
                HUB,
            ),
            201,
        )
        slot = create_dock_slot(pallet_capacity=12, sanitation_buffer_minutes=45)
        appointment = book_appointment(slot["id"], pid, pallets=2)
        close_appointment(
            appointment["id"], "RECEIVED", received_pallets=2, recorded_temp_c=1.5
        )
        validate_success(api.dispatch_route(route["id"], HUB))

        validate_success(
            api.record_delivery(
                order["id"],
                {
                    "line_receipts": [
                        {"allocation_id": alloc_one["id"], "delivered_quantity": 40},
                        {"allocation_id": alloc_two["id"], "delivered_quantity": 0},
                    ]
                },
                HUB,
            )
        )
        data = validate_success(api.invoice_order(order["id"], HUB))

        assert read_allocation(alloc_one["id"])["status"] == "DELIVERED"
        assert read_allocation(alloc_one["id"])["delivered_quantity"] == 40
        short_closed = read_allocation(alloc_two["id"])
        assert short_closed["status"] == "SHORT_CLOSED"
        assert short_closed["delivered_quantity"] == 0
        assert short_closed["buyer_amount_cents"] == 0
        second_now = read_product(second["id"])
        assert second_now["quantity_committed"] == 0
        assert second_now["quantity_available"] == 40

        assert data["producer_subtotal_cents"] == 72000
        assert data["margin_tier_bp"] == 1500
        assert data["hub_margin_cents"] == 10800
        assert data["invoiced_total_cents"] == 82800


class TestParallelSettlementAxes:
    def test_a_partial_payment_leaves_the_physical_axis_at_delivered(self, api):
        """PRD 3.8: "A payment that leaves the account short of the invoiced
        total moves the order `INVOICED → PARTIALLY_PAID`, or holds it at
        `PARTIALLY_PAID → PARTIALLY_PAID` for every subsequent instalment, of
        which there may be any number; a payment that brings paid cash plus
        credit memos to exactly the invoiced total closes the order, either
        `INVOICED → PAID` in one shot or `PARTIALLY_PAID → PAID` at the end of a
        series."

        Design: Difficulty/non_linear_state_machine/buyer_order_parallel_fulfillment_and_settlement_axes
        """
        scenario = setup_scenario(stage="invoiced")
        assert scenario["order"]["invoiced_total_cents"] == 124200

        data = validate_success(
            api.create_payment(
                scenario["order_id"],
                {"amount_cents": 24200},
                make_buyer_headers(scenario["buyer_id"]),
            )
        )
        assert data["settlement_status"] == "PARTIALLY_PAID"
        assert data["fulfillment_status"] == "DELIVERED"
        assert data["paid_total_cents"] == 24200
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 100000

    def test_the_closing_payment_settles_the_order_and_credits_patronage(self, api):
        """PRD 3.8: "Reaching `PAID` is what triggers the cooperative's
        patronage credit and what closes the order physically. Every producer
        that owns a `DELIVERED` allocation on the paid order has its
        `patronage_volume_cents` increased by that allocation's
        `producer_amount_cents` — the gross figure, with no deduction for shrink
        charges. At the same moment the order moves `DELIVERED → CLOSED` on its
        fulfillment dimension and every one of its demand lines moves `DELIVERED
        → SETTLED`."

        Design: Difficulty/non_linear_state_machine/buyer_order_parallel_fulfillment_and_settlement_axes
        """
        scenario = setup_scenario(stage="invoiced")
        buyer_headers = make_buyer_headers(scenario["buyer_id"])
        validate_success(
            api.create_payment(
                scenario["order_id"], {"amount_cents": 24200}, buyer_headers
            )
        )

        data = validate_success(
            api.create_payment(
                scenario["order_id"], {"amount_cents": 100000}, buyer_headers
            )
        )
        assert data["settlement_status"] == "PAID"
        assert data["fulfillment_status"] == "CLOSED"
        assert data["paid_total_cents"] == 124200

        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 0
        line = read_order_line(scenario["order_id"], scenario["line_id"])
        assert line["status"] == "SETTLED"
        assert read_producer(scenario["producer_id"])["patronage_volume_cents"] == 108000

    def test_a_payment_beyond_the_remaining_balance_is_refused(self, api):
        """PRD 3.8: "The amount must fit inside the remaining balance — the
        invoiced total less what has already been paid less any credit memos
        issued against the order — and an over-payment is refused with
        `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/errors/payment_beyond_the_remaining_balance_returns_payment_exceeds_balance
        """
        scenario = setup_scenario(stage="invoiced")

        resp = api.create_payment(
            scenario["order_id"],
            {"amount_cents": 124201},
            make_buyer_headers(scenario["buyer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)

        order = read_order(scenario["order_id"])
        assert order["paid_total_cents"] == 0
        assert order["settlement_status"] == "INVOICED"
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 124200

    def test_the_write_off_sweep_closes_the_order_without_crediting_patronage(
        self, api
    ):
        """PRD 3.8: "When the logical clock is advanced past an order's
        `invoice_due_date` plus the write-off grace period of 30 days while a
        balance is still outstanding — that is, while the invoiced total less
        paid cash less credit memos remains greater than zero — the order is
        written off, moving `INVOICED → WRITTEN_OFF` or `PARTIALLY_PAID →
        WRITTEN_OFF`. The buyer's `outstanding_balance_cents` is reduced by the
        remaining balance, the order moves `DELIVERED → CLOSED` and its lines
        move to `SETTLED` exactly as a paid order's would, but **no patronage
        whatsoever is credited to any producer**: a member earns patronage on
        cash the hub collected, not on food it shipped."

        Design: Corner/state_machines/write_off_sweep_closes_the_order_without_crediting_patronage
        """
        scenario = setup_scenario(stage="invoiced")
        assert scenario["order"]["invoice_due_date"] == "2026-10-01T00:00:00.000Z"

        set_clock("2026-12-01T00:00:00Z")

        order = read_order(scenario["order_id"])
        assert order["settlement_status"] == "WRITTEN_OFF"
        assert order["fulfillment_status"] == "CLOSED"
        assert order["paid_total_cents"] == 0
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 0
        assert read_producer(scenario["producer_id"])["patronage_volume_cents"] == 0
        assert (
            read_order_line(scenario["order_id"], scenario["line_id"])["status"]
            == "SETTLED"
        )


class TestShrinkApportionment:
    def test_an_approved_claim_splits_the_credit_between_producer_and_hub(self, api):
        """PRD 3.8: "First the buyer's credit: `buyer_credit_cents` is the
        allocation's `buyer_amount_cents` multiplied by the claimed
        `quantity_rejected`, divided by the allocation's `delivered_quantity`,
        rounded half up to a whole cent."
        PRD 3.8: "`TEMP_ABUSE` inverts on the cold-chain evidence the hub itself
        recorded at staging: when the allocation's `temp_excursion` flag is
        true, the hub's own door logged the goods above tolerance and the hub
        therefore owns most of the loss, so the base rate charged to the
        producer is only 2000; when that flag is false, the hub's receipt was
        clean and the cold-chain failure is attributed upstream to the farm, so
        the base rate is 8000."

        Design: Difficulty/compensating_invariant/approved_credit_memo_conserves_buyer_receivable_identity
        """
        scenario = setup_scenario(stage="invoiced", recorded_temp_c=5.5)
        assert read_allocation(scenario["allocation_id"])["temp_excursion"] is True
        claim = file_claim(
            scenario["allocation_id"], scenario["buyer_id"],
            quantity_rejected=5, reason_code="TEMP_ABUSE",
        )

        data = validate_success(
            api.adjudicate_rejection_claim(
                claim["id"], {"decision": "APPROVE"},
                make_compliance_officer_headers("co-claims-3"),
            )
        )
        assert data["status"] == "APPROVED"
        assert data["producer_fault_bp"] == 2000
        assert data["buyer_credit_cents"] == 10350
        assert data["producer_charge_cents"] == 2070
        assert data["hub_absorbed_cents"] == 8280
        assert_shrink_split_conserved(data)

    def test_an_approved_credit_memo_preserves_the_receivable_identity(self, api):
        """PRD 3.8: "Approval then moves that money across four records: the
        allocation's `rejected_quantity`, `producer_charge_cents` and
        `hub_absorbed_cents` all rise by the newly computed amounts; the demand
        line's `quantity_rejected` rises by the claimed quantity; the order's
        `credit_memo_cents` rises by the buyer credit and the buyer's
        `outstanding_balance_cents` falls by the same buyer credit; and the
        producer's `shrink_charge_cents` rises by the producer charge."
        PRD 3.4: "The buyer's `outstanding_balance_cents` starts at 0 and
        thereafter tracks, across all of that buyer's orders, the invoiced total
        less the cash applied less the credit memos issued."

        Design: Difficulty/compensating_invariant/approved_credit_memo_conserves_buyer_receivable_identity
        """
        scenario = setup_scenario(stage="invoiced", recorded_temp_c=5.5)
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 124200
        claim = file_claim(
            scenario["allocation_id"], scenario["buyer_id"],
            quantity_rejected=5, reason_code="TEMP_ABUSE",
        )

        approve_claim(claim["id"])

        order = read_order(scenario["order_id"])
        buyer = read_buyer(scenario["buyer_id"])
        assert order["credit_memo_cents"] == 10350
        assert order["invoiced_total_cents"] == 124200
        assert order["paid_total_cents"] == 0
        assert buyer["outstanding_balance_cents"] == 113850
        assert_receivable_identity(order, buyer)

        allocation = read_allocation(scenario["allocation_id"])
        assert allocation["rejected_quantity"] == 5
        assert allocation["producer_charge_cents"] == 2070
        assert allocation["hub_absorbed_cents"] == 8280
        assert read_producer(scenario["producer_id"])["shrink_charge_cents"] == 2070
        line = read_order_line(scenario["order_id"], scenario["line_id"])
        assert line["quantity_rejected"] == 5

    def test_temp_abuse_fault_inverts_when_the_receipt_was_within_tolerance(
        self, api
    ):
        """PRD 3.8: "`TEMP_ABUSE` inverts on the cold-chain evidence the hub
        itself recorded at staging: when the allocation's `temp_excursion` flag
        is true, the hub's own door logged the goods above tolerance and the hub
        therefore owns most of the loss, so the base rate charged to the
        producer is only 2000; when that flag is false, the hub's receipt was
        clean and the cold-chain failure is attributed upstream to the farm, so
        the base rate is 8000."

        Design: Corner/calculations/temp_abuse_fault_inverts_when_the_dock_receipt_was_within_tolerance
        """
        scenario = setup_scenario(stage="invoiced", recorded_temp_c=1.5)
        assert read_allocation(scenario["allocation_id"])["temp_excursion"] is False
        claim = file_claim(
            scenario["allocation_id"], scenario["buyer_id"],
            quantity_rejected=5, reason_code="TEMP_ABUSE",
        )

        data = validate_success(
            api.adjudicate_rejection_claim(
                claim["id"], {"decision": "APPROVE"},
                make_compliance_officer_headers("co-claims-3"),
            )
        )
        assert data["producer_fault_bp"] == 8000
        assert data["buyer_credit_cents"] == 10350
        assert data["producer_charge_cents"] == 8280
        assert data["hub_absorbed_cents"] == 2070
        assert read_producer(scenario["producer_id"])["shrink_charge_cents"] == 8280
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 113850

    def test_audited_tier_relief_is_applied_before_the_fault_cap(self, api):
        """PRD 3.8: "Next, relief for the best-documented farms: a producer
        whose `food_safety_tier` is `TIER_AUDITED` has 1500 basis points
        subtracted from the base rate, floored at zero. Finally the cap:
        `producer_fault_bp` is the relieved rate or 9000 basis points, whichever
        is smaller. The relief is applied **before** the cap, not after, so an
        audited producer on a `SHORT_COUNT` claim carries 8500 basis points
        rather than the 9000 an unaudited producer would carry."
        PRD 3.8: "With the rate fixed, `producer_charge_cents` is the buyer
        credit multiplied by `producer_fault_bp`, divided by 10000 and rounded
        half up, and `hub_absorbed_cents` is whatever is left of the buyer
        credit after that charge — computed by subtraction, so that the
        producer's charge and the hub's absorption always add back to the buyer
        credit exactly, with the hub carrying the rounding residue."

        Design: Corner/calculations/audited_tier_relief_is_applied_before_the_producer_fault_cap
        """
        scenario = setup_scenario(
            stage="invoiced", producer_doc_types=ALL_DOC_TYPES
        )
        assert read_producer(scenario["producer_id"])["food_safety_tier"] == (
            "TIER_AUDITED"
        )
        claim = file_claim(
            scenario["allocation_id"], scenario["buyer_id"],
            quantity_rejected=5, reason_code="SHORT_COUNT",
        )

        data = validate_success(
            api.adjudicate_rejection_claim(
                claim["id"], {"decision": "APPROVE"},
                make_compliance_officer_headers("co-claims-3"),
            )
        )
        assert data["producer_fault_bp"] == 8500
        assert data["producer_fault_bp"] != 9000
        assert data["buyer_credit_cents"] == 10350
        assert data["producer_charge_cents"] == 8798
        assert data["hub_absorbed_cents"] == 1552
        assert_shrink_split_conserved(data)

    def test_a_claim_beyond_the_delivered_quantity_is_refused(self, api):
        """PRD 3.8: "The claimed quantity must also fit within what is left to
        reject — the allocation's `delivered_quantity` less its already
        `rejected_quantity` — and a claim beyond that headroom is refused with
        `ERR_REJECTION_EXCEEDS_DELIVERED`."

        Design: Corner/validations/rejection_claim_beyond_delivered_quantity_is_rejected
        """
        scenario = setup_scenario(stage="invoiced")

        resp = api.create_rejection_claim(
            create_rejection_claim_payload(
                scenario["allocation_id"], quantity_rejected=61, reason_code="DAMAGE"
            ),
            make_buyer_headers(scenario["buyer_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REJECTION_EXCEEDS_DELIVERED.value, 422)

        _, meta = validate_paginated(
            api.list_allocation_rejection_claims(scenario["allocation_id"], HUB)
        )
        assert meta["total_count"] == 0
        assert read_allocation(scenario["allocation_id"])["rejected_quantity"] == 0

    def test_adjudicating_an_already_approved_claim_is_refused(self, api):
        """PRD 3.8: "Adjudication resolves the claim exactly once — a claim not
        currently `FILED` is refused with `ERR_INVALID_CLAIM_STATE` — and the
        acting user id is recorded in `adjudicated_by_user_id` on every
        outcome."

        Design: Corner/errors/adjudicating_an_already_approved_claim_returns_invalid_claim_state
        """
        scenario = setup_scenario(stage="invoiced", recorded_temp_c=5.5)
        claim = file_claim(
            scenario["allocation_id"], scenario["buyer_id"],
            quantity_rejected=5, reason_code="TEMP_ABUSE",
        )
        approve_claim(claim["id"])

        resp = api.adjudicate_rejection_claim(
            claim["id"], {"decision": "DENY"},
            make_compliance_officer_headers("co-claims-8"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_STATE.value, 409)

        claims, _ = validate_paginated(
            api.list_allocation_rejection_claims(scenario["allocation_id"], HUB)
        )
        assert claims[0]["status"] == "APPROVED"
        assert read_order(scenario["order_id"])["credit_memo_cents"] == 10350
        assert read_producer(scenario["producer_id"])["shrink_charge_cents"] == 2070
        assert read_buyer(scenario["buyer_id"])["outstanding_balance_cents"] == 113850
