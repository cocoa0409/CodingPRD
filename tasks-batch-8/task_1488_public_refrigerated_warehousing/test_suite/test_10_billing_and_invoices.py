"""Monthly billing: storage variants, rounding order, dwell tiers, settlement,
dispute round-trip, billing checkpoint, live accrual, and ship side effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_order,
    assert_instant_equals,
    cancel_booking,
    complete_booking,
    complete_receipt,
    create_allocated_order,
    create_booking,
    create_cell,
    create_customer,
    create_customer_with_card,
    create_order,
    create_submitted_order,
    create_zone,
    decide_claim,
    file_claim,
    finalize_due_invoices,
    get_customer,
    get_finalized_invoices,
    get_invoice,
    get_lot,
    get_open_invoice,
    get_order,
    get_zone,
    list_invoices,
    make_customer_admin_headers,
    receive_stock,
    review_claim,
    run_billing,
    set_clock,
    setup_confirmed_excursion,
    setup_stocked_account,
    ship_order,
    start_booking,
    submit_order,
    validate_error,
    validate_success,
    arrive_receipt,
    schedule_receipt,
)

BILLING = TEST_USERS["billing_admin_headers"]
OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestStorageMethodVariants:
    def _setup_variant_pair(self):
        """One pallet each for a DAILY_PRORATED customer and a FULL_MONTH
        customer, both received 2026-08-05; August finalized at 2026-09-01."""
        set_clock("2026-08-01T00:00:00Z")
        cust_a, _ = create_customer_with_card("A Daily")
        cust_b, _ = create_customer_with_card("B FullMonth",
                                              storage_method="FULL_MONTH")
        zone = create_zone("FZ-1", capacity_pallets=10, dock_doors=2)
        # Advance the logical clock so the pallets' `received_at` (stamped with
        # "now" at completion, PRD §3.2/§2.4) lands on 2026-08-05 as intended.
        set_clock("2026-08-05T08:30:00Z")
        receive_stock(cust_a["id"], zone["id"], 1, lot_code="L1",
                      window_start="2026-08-05T08:00:00Z",
                      window_end="2026-08-05T10:00:00Z")
        receive_stock(cust_b["id"], zone["id"], 1, lot_code="L1",
                      window_start="2026-08-05T08:00:00Z",
                      window_end="2026-08-05T10:00:00Z")
        finalize_due_invoices("2026-09-01T00:00:00Z")
        inv_a = get_finalized_invoices(cust_a["id"])[0]
        inv_b = get_finalized_invoices(cust_b["id"])[0]
        return inv_a, inv_b

    def test_daily_prorated_charges_present_days(self, api):
        """PRD §3.9: "Under the `DAILY_PRORATED` storage method, the pallet's line
        is its present-days count multiplied by the class rate and divided by
        thirty, rounded half up to whole cents."
        PRD §3.9: "The invoice total is the sum of `storage_cents`,
        `handling_in_cents`, `handling_out_cents`, `blast_freeze_cents`, and
        `dwell_surcharge_cents`, minus `claim_credit_cents`"

        Design: Difficulty/dual_variant_calc/storage_daily_prorated_vs_full_month_diverge
        """
        inv_a, _inv_b = self._setup_variant_pair()
        invoice = get_invoice(inv_a["id"])
        # Present 2026-08-05 .. 2026-08-31 inclusive: 27 days.
        # round_half_up(27 * 3000 / 30) == 2700.
        assert invoice["storage_cents"] == 2700
        assert invoice["handling_in_cents"] == 1000
        assert invoice["total_cents"] == 3700

    def test_full_month_charges_whole_month_and_diverges(self, api):
        """PRD §3.9: "Under `FULL_MONTH`, the line is the full monthly class rate
        when the pallet was present at least one day in the period, and zero
        otherwise."

        Design: Difficulty/dual_variant_calc/storage_daily_prorated_vs_full_month_diverge
        """
        inv_a, inv_b = self._setup_variant_pair()
        invoice_b = get_invoice(inv_b["id"])
        assert invoice_b["storage_cents"] == 3000, (
            "one present day is enough for the full monthly rate")
        assert invoice_b["handling_in_cents"] == 1000
        assert invoice_b["total_cents"] == 4000
        assert invoice_b["storage_cents"] != get_invoice(inv_a["id"])["storage_cents"], (
            "the two storage methods diverge on identical presence data")


class TestStorageRoundingOrder:
    def _setup_one_day_pallets(self):
        """3 pallets received 2026-08-30 and shipped 2026-08-31 (1 chargeable
        day each); August finalized at 2026-09-01."""
        set_clock("2026-08-01T00:00:00Z")
        customer, _card = create_customer_with_card(
            "Round Co", frozen_storage_cents_per_pallet_month=1000)
        zone = create_zone("FZ-4", capacity_pallets=10, dock_doors=2)
        set_clock("2026-08-30T09:00:00Z")
        receive_stock(customer["id"], zone["id"], 3, lot_code="RL1",
                      production_date="2026-08-20",
                      window_start="2026-08-30T08:00:00Z",
                      window_end="2026-08-30T10:00:00Z")
        order = create_submitted_order(customer["id"], 3)
        allocate_order(order["id"])
        set_clock("2026-08-31T09:00:00Z")
        ship_order(order["id"])
        finalize_due_invoices("2026-09-01T00:00:00Z")
        return get_finalized_invoices(customer["id"])[0]

    def test_round_per_pallet_then_sum(self, api):
        """PRD §2.6: "Storage lines are rounded per pallet to whole cents first
        and only then summed into the invoice component; the alternative ordering
        — summing raw per-pallet values and rounding once at the end — is a
        different, rejected reading."
        PRD §3.9: "A pallet shipped or disposed mid-period therefore counts only
        through the day before its out date."

        Design: Difficulty/combinatorial_formula/storage_per_pallet_round_then_sum_order
        """
        invoice = get_invoice(self._setup_one_day_pallets()["id"])
        # 3 pallets * round_half_up(1 * 1000 / 30) == 3 * 33 == 99; the rejected
        # sum-then-round reading would give round_half_up(100.0) == 100.
        assert invoice["storage_cents"] == 99
        assert invoice["storage_cents"] != 100

    def test_invoice_components_and_total(self, api):
        """PRD §3.9: "The invoice total is the sum of `storage_cents`,
        `handling_in_cents`, `handling_out_cents`, `blast_freeze_cents`, and
        `dwell_surcharge_cents`, minus `claim_credit_cents` — integer-cent
        components combined with no further rounding"
        PRD §3.5: "A volume reaching five hundred pallets earns a twenty percent
        discount; reaching one hundred earns ten percent; below that, none."

        Design: Difficulty/combinatorial_formula/storage_per_pallet_round_then_sum_order
        """
        invoice = get_invoice(self._setup_one_day_pallets()["id"])
        assert invoice["handling_in_cents"] == 3000, "3 * 1000 at completion"
        assert invoice["handling_out_cents"] == 1500, (
            "volume 3 earns no discount: 3 * 500")
        assert invoice["total_cents"] == 4599, "99 + 3000 + 1500"


class TestDwellSurchargeMultiInput:
    def _setup_dwell_scenario(self):
        """2 CHILLED pallets received 2026-06-10; one blast-frozen 2026-08-20;
        billing runs at 07-01, 08-01, 09-01. Returns the August invoice."""
        set_clock("2026-06-01T00:00:00Z")
        customer, _card = create_customer_with_card("Dwell Co")
        zone = create_zone("CH-1", temp_class="CHILLED", capacity_pallets=10,
                           dock_doors=2)
        set_clock("2026-06-10T09:00:00Z")
        receipt = receive_stock(customer["id"], zone["id"], 2, product_code="MILK",
                                lot_code="BL", production_date="2026-05-01",
                                temp_class="CHILLED",
                                window_start="2026-06-10T08:00:00Z",
                                window_end="2026-06-10T10:00:00Z")
        finalize_due_invoices("2026-07-01T00:00:00Z")
        finalize_due_invoices("2026-08-01T00:00:00Z")
        cell = create_cell("BC-1", capacity_pallets=5, turnaround_minutes=30)
        booking = create_booking(cell["id"], receipt["lot_id"], pallet_count=1,
                                 window_start="2026-08-20T10:00:00Z",
                                 window_end="2026-08-20T12:00:00Z")
        set_clock("2026-08-20T10:30:00Z")
        start_booking(booking["id"])
        set_clock("2026-08-20T12:30:00Z")
        complete_booking(booking["id"])
        finalize_due_invoices("2026-09-01T00:00:00Z")
        finalized = get_finalized_invoices(customer["id"])
        assert len(finalized) == 3, "June, July, August invoices finalized"
        august = finalized[2]
        assert_instant_equals(august["period_start"], "2026-08-01T00:00:00Z")
        return august

    def test_dwell_tier_with_chilled_multiplier_and_blast_reset(self, api):
        """PRD §3.9: "The pallet's dwell anchor is the later of its `received_at`
        and its `last_blast_frozen_at`, so a completed blast freeze restarts the
        clock; dwell days are the whole days elapsed between that anchor and
        `period_end`. The tier percentage applied to the class rate is one hundred
        percent at one hundred twenty dwell days or more, fifty percent at ninety
        days or more, twenty-five percent at sixty days or more, and zero below
        sixty days. The zone multiplier is 1.0 for a `FROZEN` zone and 1.5 for a
        `CHILLED` zone."

        Design: Difficulty/combinatorial_formula/dwell_surcharge_tiered_multi_input_with_blast_reset
        """
        invoice = get_invoice(self._setup_dwell_scenario()["id"])
        # Un-blasted pallet: 82 dwell days -> 25% tier ->
        # round_half_up(2000 * 0.25 * 1.5) == 750. Blasted pallet: dwell clock
        # reset 2026-08-20 -> 11 days -> below 60 -> 0.
        assert invoice["dwell_surcharge_cents"] == 750
        assert invoice["blast_freeze_cents"] == 2300, "2000 base + 1 * 300"

    def test_storage_and_total_for_august(self, api):
        """PRD §3.9: "Under the `DAILY_PRORATED` storage method, the pallet's line
        is its present-days count multiplied by the class rate and divided by
        thirty, rounded half up to whole cents."
        PRD §3.9: "The invoice total is the sum of `storage_cents`,
        `handling_in_cents`, `handling_out_cents`, `blast_freeze_cents`, and
        `dwell_surcharge_cents`, minus `claim_credit_cents`"

        Design: Difficulty/combinatorial_formula/dwell_surcharge_tiered_multi_input_with_blast_reset
        """
        invoice = get_invoice(self._setup_dwell_scenario()["id"])
        # Both pallets present all 31 August days in a CHILLED zone:
        # 2 * round_half_up(31 * 2000 / 30) == 2 * 2067 == 4134.
        assert invoice["storage_cents"] == 4134
        assert invoice["total_cents"] == 7184, "4134 storage + 750 dwell + 2300 blast"


class TestDwellTierBoundary:
    def _setup_60_and_59_day_pallets(self):
        """Pallet A received 2026-07-03T00:00 (exactly 60 dwell days at the
        2026-09-01 period end); pallet B received 2026-07-04T00:00 (59 days)."""
        set_clock("2026-07-01T00:00:00Z")
        customer, _card = create_customer_with_card("Dwell B")
        zone = create_zone("CH-2", temp_class="CHILLED", capacity_pallets=10,
                           dock_doors=2)
        receipt_a = schedule_receipt(customer["id"], zone["id"],
                                     product_code="MILK", lot_code="D60",
                                     production_date="2026-06-01",
                                     temp_class="CHILLED", expected_pallets=1,
                                     window_start="2026-07-03T00:00:00Z",
                                     window_end="2026-07-03T02:00:00Z")
        receipt_b = schedule_receipt(customer["id"], zone["id"],
                                     product_code="MILK", lot_code="D59",
                                     production_date="2026-06-01",
                                     temp_class="CHILLED", expected_pallets=1,
                                     window_start="2026-07-04T00:00:00Z",
                                     window_end="2026-07-04T02:00:00Z")
        set_clock("2026-07-03T00:00:00Z")
        arrive_receipt(receipt_a["id"])
        complete_receipt(receipt_a["id"], 1)
        set_clock("2026-07-04T00:00:00Z")
        arrive_receipt(receipt_b["id"])
        complete_receipt(receipt_b["id"], 1)
        finalize_due_invoices("2026-08-01T00:00:00Z")
        finalize_due_invoices("2026-09-01T00:00:00Z")
        return get_finalized_invoices(customer["id"])

    def test_exactly_sixty_days_triggers_tier(self, api):
        """PRD §3.9: "The tier percentage applied to the class rate is one hundred
        percent at one hundred twenty dwell days or more, fifty percent at ninety
        days or more, twenty-five percent at sixty days or more, and zero below
        sixty days."
        PRD §3.9: "The dwell surcharge penalizes aged inventory, measured for each
        pallet still in custody on the period's last day — the calendar day
        immediately before `period_end`, with presence tested the same way as for
        storage."

        Design: Difficulty/boundary_precision_check/dwell_tier_at_exactly_60_days
        """
        finalized = self._setup_60_and_59_day_pallets()
        august = finalized[1]
        assert_instant_equals(august["period_start"], "2026-08-01T00:00:00Z")
        invoice = get_invoice(august["id"])
        # Only pallet A qualifies: exactly 60 days >= 60 ->
        # round_half_up(2000 * 0.25 * 1.5) == 750; pallet B at 59 days adds 0.
        assert invoice["dwell_surcharge_cents"] == 750, (
            f">= vs > boundary is exact: 60 days triggers, 59 does not; got "
            f"{invoice['dwell_surcharge_cents']}")

    def test_below_sixty_days_contributes_zero(self, api):
        """PRD §3.9: "The tier percentage applied to the class rate is one hundred
        percent at one hundred twenty dwell days or more, fifty percent at ninety
        days or more, twenty-five percent at sixty days or more, and zero below
        sixty days."

        Design: Difficulty/boundary_precision_check/dwell_tier_at_exactly_60_days
        """
        finalized = self._setup_60_and_59_day_pallets()
        july = finalized[0]
        assert_instant_equals(july["period_start"], "2026-07-01T00:00:00Z")
        invoice = get_invoice(july["id"])
        # At the July period end the pallets dwell 29 and 28 days: below 60 -> 0.
        assert invoice["dwell_surcharge_cents"] == 0


class TestInvoiceSettleBoundary:
    def _setup_finalized_8200(self):
        """2 pallets present all 31 August days: storage 2*3100, handling 2000."""
        set_clock("2026-08-01T00:00:00Z")
        sc = setup_stocked_account(customer_name="Settle Co", zone_code="FZ-16",
                                   pallets=2,
                                   window_start="2026-08-01T00:00:00Z",
                                   window_end="2026-08-01T02:00:00Z")
        finalize_due_invoices("2026-09-01T00:00:00Z")
        return sc, get_finalized_invoices(sc["customer"]["id"])[0]

    def test_settle_one_cent_short_rejected(self, api):
        """PRD §3.9: "Settlement is the terminal act: a `BillingAdmin` settles a
        `FINALIZED` invoice by paying an `amount_cents` that must equal
        `total_cents` exactly — any other amount is rejected
        `ERR_INVOICE_AMOUNT_MISMATCH` — moving the invoice to `SETTLED` and
        triggering recomputation of the customer's `outstanding_balance_cents`."

        Design: Difficulty/boundary_precision_check/invoice_settle_exact_amount_boundary
        """
        _sc, inv = self._setup_finalized_8200()
        invoice = get_invoice(inv["id"])
        # 2 * round_half_up(31 * 3000 / 30) = 6200 storage + 2000 handling_in.
        assert invoice["total_cents"] == 8200
        resp = api.settle_invoice(inv["id"], {"amount_cents": 8199}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_AMOUNT_MISMATCH,
                       expected_status=409)
        assert get_invoice(inv["id"])["status"] == "FINALIZED", (
            "a short payment leaves the invoice FINALIZED")

    def test_settle_exact_amount_succeeds(self, api):
        """PRD §3.9: "Settlement is the terminal act: a `BillingAdmin` settles a
        `FINALIZED` invoice by paying an `amount_cents` that must equal
        `total_cents` exactly — any other amount is rejected
        `ERR_INVOICE_AMOUNT_MISMATCH` — moving the invoice to `SETTLED` and
        triggering recomputation of the customer's `outstanding_balance_cents`."

        Design: Difficulty/boundary_precision_check/invoice_settle_exact_amount_boundary
        """
        sc, inv = self._setup_finalized_8200()
        resp = api.settle_invoice(inv["id"], {"amount_cents": 8199}, BILLING)
        validate_error(resp, ApiErrorId.ERR_INVOICE_AMOUNT_MISMATCH)
        settled = validate_success(
            api.settle_invoice(inv["id"], {"amount_cents": 8200}, BILLING))
        assert settled["status"] == "SETTLED", "exact payment settles the invoice"


class TestDisputeResolveConservation:
    def _setup_finalized_4100(self):
        set_clock("2026-08-01T00:00:00Z")
        sc = setup_stocked_account(customer_name="Disp Co", zone_code="FZ-24",
                                   pallets=1,
                                   window_start="2026-08-01T00:00:00Z",
                                   window_end="2026-08-01T02:00:00Z")
        finalize_due_invoices("2026-09-01T00:00:00Z")
        return sc, get_finalized_invoices(sc["customer"]["id"])[0]

    def test_dispute_resolve_returns_to_finalized(self, api):
        """PRD §3.9: "A `BillingAdmin` resolves the dispute, returning the invoice
        `DISPUTED` → `FINALIZED` with every component unchanged, so the round trip
        conserves `total_cents`."

        Design: Difficulty/compensating_invariant/dispute_resolve_cycle_conserves_invoice_total
        """
        sc, inv = self._setup_finalized_4100()
        disputed = validate_success(
            api.dispute_invoice(
                inv["id"], make_customer_admin_headers(sc["customer"]["id"])))
        assert disputed["status"] == "DISPUTED"
        resolved = validate_success(api.resolve_invoice_dispute(inv["id"], BILLING))
        assert resolved["status"] == "FINALIZED"

    def test_dispute_round_trip_conserves_amounts(self, api):
        """PRD §3.9: "while disputed, all line amounts are frozen and no component
        may change. A `BillingAdmin` resolves the dispute, returning the invoice
        `DISPUTED` → `FINALIZED` with every component unchanged, so the round trip
        conserves `total_cents`."

        Design: Difficulty/compensating_invariant/dispute_resolve_cycle_conserves_invoice_total
        """
        sc, inv = self._setup_finalized_4100()
        before = get_invoice(inv["id"])
        assert before["storage_cents"] == 3100, (
            "1 pallet * round_half_up(31 * 3000 / 30)")
        assert before["handling_in_cents"] == 1000
        assert before["total_cents"] == 4100
        validate_success(
            api.dispute_invoice(
                inv["id"], make_customer_admin_headers(sc["customer"]["id"])))
        validate_success(api.resolve_invoice_dispute(inv["id"], BILLING))
        after = get_invoice(inv["id"])
        assert after["total_cents"] == before["total_cents"]
        assert after["storage_cents"] == before["storage_cents"]
        assert after["handling_in_cents"] == before["handling_in_cents"], (
            "no component drift across the dispute loop")


class TestBillingRunCheckpoint:
    def test_billing_run_finalizes_due_invoices_once(self, api):
        """PRD §3.9: "The run finalizes every `OPEN` invoice whose `period_end`
        has been reached or passed by the logical clock, responding with a
        `finalized_count` and the list of `finalized_invoice_ids`; when nothing is
        eligible the run succeeds with a `finalized_count` of zero rather than
        erroring."
        PRD §3.9: "Finalization — `OPEN` → `FINALIZED` — records the
        `rate_card_id` of the card `ACTIVE` at run time, computes storage and
        dwell as below, recomputes `total_cents`, and opens the successor `OPEN`
        invoice covering the following month."

        Design: Corner/complexity_layers/billing_run_checkpoint_idempotent
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer("Run Co")
        set_clock("2026-09-01T00:00:00Z")
        run1 = run_billing()
        assert run1["finalized_count"] == 1, "the August invoice is due"
        run2 = run_billing()
        assert run2["finalized_count"] == 0, (
            "no period_end has passed since the first run")
        open_invoices = list_invoices(customer["id"], status="OPEN")
        assert len(open_invoices) == 1
        assert_instant_equals(open_invoices[0]["period_start"],
                              "2026-09-01T00:00:00Z")


class TestDisputeOpenInvoice:
    def test_dispute_on_open_invoice_rejected(self, api):
        """PRD §3.9: "After finalization, the owning `CustomerAdmin` may dispute a
        `FINALIZED` invoice, moving it to `DISPUTED`; while disputed, all line
        amounts are frozen and no component may change."
        PRD §2.9: "State validity, applied to all action endpoints: the target
        resource must stand in a valid from-state for the requested transition,
        including terminal-state lockdown, and any OCC expectation on the request
        must match; an invalid from-state is rejected `ERR_INVALID_STATE`, while
        a stale OCC expectation is rejected `ERR_STALE_VERSION`."

        Design: Corner/state_machines/dispute_open_invoice_returns_invalid_state
        """
        customer = create_customer("Disp2 Co", credit_limit_cents=50000)
        invoice = get_open_invoice(customer["id"])
        resp = api.dispute_invoice(
            invoice["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_invoice(invoice["id"])["status"] == "OPEN"


class TestImmediateAccrualVisibility:
    def test_handling_in_visible_on_next_read(self, api):
        """PRD §3.9: "While an invoice stands at `OPEN`, the handling, blast, and
        claim-credit components accrue live as their triggering events occur,
        while `storage_cents` and `dwell_surcharge_cents` hold at zero."
        PRD §3.2: "the customer's `OPEN` invoice accrues into `handling_in_cents`
        an amount equal to `actual_pallets` multiplied by the ACTIVE card's
        `handling_in_cents_per_pallet`, and the receipt stands `COMPLETED`."

        Design: Corner/consistency_model/immediate_visibility_of_accrued_charges
        """
        sc = setup_stocked_account(customer_name="Imm Co", zone_code="FZ-IM",
                                   capacity_pallets=5, pallets=2)
        invoice = get_open_invoice(sc["customer"]["id"])
        assert invoice["handling_in_cents"] == 2000, "2 * 1000 accrued at completion"
        assert invoice["storage_cents"] == 0 and invoice["dwell_surcharge_cents"] == 0
        assert invoice["total_cents"] == 2000


class TestOutstandingBalanceRead:
    def test_outstanding_balance_includes_open_accruals(self, api):
        """PRD §2.10: "A customer's `outstanding_balance_cents`, exposed on every
        read of the Customer, is the sum of `total_cents` over that customer's
        invoices standing at `FINALIZED` or `DISPUTED`, plus — from the single
        `OPEN` invoice — the accrued `handling_in_cents`, `handling_out_cents`,
        and `blast_freeze_cents`, minus its `claim_credit_cents`."

        Design: Corner/endpoints/customer_outstanding_balance_computed_read
        """
        sc = setup_stocked_account(customer_name="Bal Co", zone_code="FZ-BA",
                                   capacity_pallets=5, pallets=2)
        customer = get_customer(sc["customer"]["id"])
        assert customer["outstanding_balance_cents"] == 2000, (
            "no FINALIZED invoices; OPEN accrued handling_in 2 * 1000")


class TestShipSideEffects:
    def test_ship_executes_inventory_and_fee_effects(self, api):
        """PRD §3.5: "Every `ACTIVE` allocation on the order moves to `FULFILLED`;
        every allocated pallet moves `ALLOCATED` → `SHIPPED` with `out_at` stamped
        to now and `out_reason` set to `SHIPPED`; the zone's `in_use_pallets`
        falls by the shipped count; and each affected lot recomputes, which may
        leave a lot `DEPLETED`. The final `final_handling_out_cents` is computed
        on the ship-month volume variant described above and accrues into the
        customer's `OPEN` invoice under `handling_out_cents`; the order stands
        `SHIPPED`."

        Design: Corner/state_machines/ship_side_effects_inventory_and_fee
        """
        sc = setup_stocked_account(customer_name="Ship Co", zone_code="FZ-SH",
                                   capacity_pallets=5, pallets=2)
        order = create_allocated_order(sc["customer"]["id"], 2)
        ship_order(order["id"])
        shipped = get_order(order["id"])
        assert shipped["status"] == "SHIPPED"
        # Volume 0 + 2 -> no discount: 2 * 500.
        assert shipped["final_handling_out_cents"] == 1000
        assert get_zone(sc["zone"]["id"])["in_use_pallets"] == 0
        lot = get_lot(sc["lot_id"])
        assert lot["on_hand_pallets"] == 0 and lot["status"] == "DEPLETED"
        invoice = get_open_invoice(sc["customer"]["id"])
        assert invoice["handling_out_cents"] == 1000, "accrued immediately at ship"
