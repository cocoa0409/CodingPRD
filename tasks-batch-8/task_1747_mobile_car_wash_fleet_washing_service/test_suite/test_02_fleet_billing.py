"""Fleet billing: PROJECTION vs FINAL variants, per-line rounding, minimums,
claim-credit cap evaluation order, contract early termination (PRD §3.2, §3.9)."""
from test_helpers import (
    TEST_USERS, add_stop_to_route, approve_claim, confirm_order, create_customer,
    create_fleet_contract, create_route, create_site, create_technician, create_van,
    create_vehicles, create_wash_order, file_damage_claim, generate_invoice,
    get_order, get_route, invoice_event, make_customer_headers,
    make_technician_headers, order_event, pay_claim, review_claim, route_event,
    set_clock, setup_completed_order, setup_customer_site_vehicles, stop_event,
    validate_error, validate_success,
)
from test_helpers import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

CONTRACT_RATES = {
    "sedan_rate_cents": 3000,
    "suv_pickup_rate_cents": 4000,
    "van_boxtruck_rate_cents": 6000,
    "heavy_fleet_rate_cents": 10000,
}


def _complete_order_on_route(order_id, route_id, van, tech, washed_ids):
    """Append stop for a SCHEDULED order, then arrive -> start -> complete."""
    stop = add_stop_to_route(route_id, order_id)
    stop_event(route_id, stop["id"], "ARRIVE", tech["id"])
    order_event(order_id, "START", make_technician_headers(tech["id"]))
    return order_event(
        order_id, "COMPLETE", make_technician_headers(tech["id"]),
        vehicles_washed_ids=washed_ids,
    )


def _setup_fleet_scenario(num_vehicles=10, vehicle_class="SEDAN", minimum=200000,
                          loyalty_credit_pct=0.025):
    """FLEET customer + site + N vehicles + ACTIVE contract. Returns ctx dict."""
    customer = create_customer(customer_type="FLEET")
    site = create_site(customer["id"], name="YARD")
    vehicle_ids = create_vehicles(customer["id"], site["id"], num_vehicles, vehicle_class)
    contract = create_fleet_contract(
        customer["id"], monthly_minimum_cents=minimum,
        loyalty_credit_pct=loyalty_credit_pct, **CONTRACT_RATES,
    )
    return {"customer": customer, "site": site, "vehicle_ids": vehicle_ids,
            "contract": contract}


def _book_and_confirm(ctx, window_start, window_end):
    order = create_wash_order(
        ctx["customer"]["id"], ctx["site"]["id"], ctx["vehicle_ids"],
        scheduled_window_start=window_start, scheduled_window_end=window_end,
    )
    return confirm_order(order["id"])


class TestInvoiceProjectionVsFinal:
    def _scenario(self):
        """O1 and O2 COMPLETED in 2026-08 (27000 each); O3 SCHEDULED (quote 27000)."""
        ctx = _setup_fleet_scenario()
        o1 = _book_and_confirm(ctx, "2026-08-03T13:00:00Z", "2026-08-03T15:00:00Z")
        o2 = _book_and_confirm(ctx, "2026-08-03T15:00:00Z", "2026-08-03T17:00:00Z")
        o3 = _book_and_confirm(ctx, "2026-08-04T13:00:00Z", "2026-08-04T15:00:00Z")
        van = create_van(reclaim_system="ADVANCED", tank_capacity_gal=200, load_gallons=200)
        tech = create_technician(certified=True)
        route = create_route("2026-08-03", van["id"], tech["id"])
        route_event(route["id"], "PUBLISH")
        _complete_order_on_route(o1["id"], route["id"], van, tech, ctx["vehicle_ids"])
        _complete_order_on_route(o2["id"], route["id"], van, tech, ctx["vehicle_ids"])
        ctx.update({"o1": o1, "o2": o2, "o3": o3})
        return ctx

    def test_projection_counts_unfinished_orders_at_quote(self, api):
        """PRD §3.9: "A `PROJECTION` additionally includes orders in `SCHEDULED`,
        `ASSIGNED`, or `IN_PROGRESS` whose `scheduled_window_start` falls inside the
        period, priced at their booking quotes, so identical period data yields a
        different total whenever unfinished orders exist or a quote differs from its
        final."

        Design: Difficulty/dual_variant_calc/invoice_projection_vs_final
        """
        ctx = self._scenario()
        preview = generate_invoice(ctx["contract"]["id"], "2026-08", "PROJECTION")
        assert preview["status"] == "PREVIEW"
        assert preview["line_count"] == 3
        # O1+O2 at final 27000 + O3 at quote 27000
        assert preview["charges_cents"] == 81000
        # 3 x round_half_up(27000 * 0.025) = 3 x 675
        assert preview["loyalty_credits_cents"] == 2025
        # 78975 below the 200000 minimum
        assert preview["billed_cents"] == 200000
        assert preview["minimum_applied"] is True

    def test_final_counts_completed_orders_only(self, api):
        """PRD §3.9: "A `FINAL` invoice includes the contract customer's wash orders in
        `COMPLETED`, `REWASH_PENDING`, or `CLOSED` whose `completed_at` falls inside
        the period, excluding any whose `billing_status` is `WAIVED`, and prices each
        line at the contract rate card over the washed vehicle set — the final amounts
        of §3.5."

        Design: Difficulty/dual_variant_calc/invoice_projection_vs_final
        """
        ctx = self._scenario()
        final = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        assert final["status"] == "DRAFT"
        assert final["line_count"] == 2
        assert final["charges_cents"] == 54000
        # 2 x round_half_up(27000 * 0.025) = 2 x 675
        assert final["loyalty_credits_cents"] == 1350
        # 52650 below the 200000 minimum
        assert final["billed_cents"] == 200000
        assert final["minimum_applied"] is True


class TestInvoicePerLineRoundingPinned:
    def _scenario(self):
        """Three 10-sedan orders COMPLETED in 2026-08 (charge 27000 each),
        loyalty_credit_pct 0.0075, minimum 50000."""
        ctx = _setup_fleet_scenario(minimum=50000, loyalty_credit_pct=0.0075)
        orders = [
            _book_and_confirm(ctx, "2026-08-03T13:00:00Z", "2026-08-03T14:00:00Z"),
            _book_and_confirm(ctx, "2026-08-03T14:00:00Z", "2026-08-03T15:00:00Z"),
            _book_and_confirm(ctx, "2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z"),
        ]
        van = create_van(reclaim_system="ADVANCED", tank_capacity_gal=200, load_gallons=200)
        tech = create_technician(certified=True)
        route = create_route("2026-08-03", van["id"], tech["id"])
        route_event(route["id"], "PUBLISH")
        for order in orders:
            _complete_order_on_route(order["id"], route["id"], van, tech,
                                     ctx["vehicle_ids"])
        return ctx

    def test_loyalty_credits_rounded_per_line(self, api):
        """PRD §2.9: "Invoice arithmetic pins the rounding order: each wash-order
        line's charge is rounded half-up to integer cents first, and only then are the
        lines summed; summing exact fractions and rounding once at the end is
        forbidden, because the two orders can differ by cents. Loyalty credits are
        likewise rounded per line before summing."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_pinned
        """
        ctx = self._scenario()
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        # 3 x round_half_up(27000 * 0.0075 = 202.5) = 3 x 203 = 609;
        # sum-then-round would give round_half_up(607.5) = 608
        assert invoice["loyalty_credits_cents"] == 609
        assert invoice["charges_cents"] == 81000
        assert invoice["line_count"] == 3

    def test_billed_and_net_after_per_line_credits(self, api):
        """PRD §3.9: "The billed amount `billed_cents` is the greater of charges minus
        credits and the contract's `monthly_minimum_cents`, and `minimum_applied` is
        true exactly when charges minus credits fell below the minimum."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_pinned
        """
        ctx = self._scenario()
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        # 81000 - 609 = 80391; above the 50000 minimum
        assert invoice["billed_cents"] == 80391
        assert invoice["minimum_applied"] is False
        assert invoice["net_due_cents"] == 80391


class TestClaimCreditCapEvaluationOrder:
    def _scenario(self):
        """FLEET customer, 10 HEAVY_FLEET, contract min 200000 loyalty 0.025;
        three orders (charge 90000 each) COMPLETED at clock 2026-08-03;
        DC1 on order 1 (claimed 70000) APPROVED+PAID; DC2 on order 2 (claimed 15000)
        APPROVED+PAID."""
        set_clock("2026-08-03T09:00:00Z")
        ctx = _setup_fleet_scenario(vehicle_class="HEAVY_FLEET")
        orders = [
            _book_and_confirm(ctx, "2026-08-03T13:00:00Z", "2026-08-03T14:00:00Z"),
            _book_and_confirm(ctx, "2026-08-03T14:00:00Z", "2026-08-03T15:00:00Z"),
            _book_and_confirm(ctx, "2026-08-03T15:00:00Z", "2026-08-03T16:00:00Z"),
        ]
        van = create_van(reclaim_system="ADVANCED", tank_capacity_gal=200, load_gallons=200)
        tech = create_technician(certified=True)
        route = create_route("2026-08-03", van["id"], tech["id"])
        route_event(route["id"], "PUBLISH")
        for order in orders:
            _complete_order_on_route(order["id"], route["id"], van, tech,
                                     ctx["vehicle_ids"])
        dc1 = file_damage_claim(
            orders[0]["id"], ctx["customer"]["id"], area="EXTERIOR_BODY",
            claimed_amount_cents=70000, description="hood scratch",
        )
        review_claim(dc1["id"], "auditor-1")
        dc1 = approve_claim(dc1["id"], "auditor-1")
        pay_claim(dc1["id"], "auditor-2")
        dc2 = file_damage_claim(
            orders[1]["id"], ctx["customer"]["id"], area="GLASS",
            claimed_amount_cents=15000, description="windshield chip",
        )
        review_claim(dc2["id"], "auditor-1")
        approve_claim(dc2["id"], "auditor-1")
        pay_claim(dc2["id"], "auditor-2")
        ctx.update({"orders": orders, "dc1": dc1, "dc2": dc2})
        return ctx

    def test_approve_caps_at_class_cap_and_invoice_totals(self, api):
        """PRD §3.8: "`approved_amount_cents` defaults to the lesser of
        `claimed_amount_cents` and the class cap taken from the order's first
        vehicle's class — 25,000 cents for a `SEDAN`, 30,000 for an `SUV_PICKUP`,
        40,000 for a `VAN_BOXTRUCK`, and 60,000 for a `HEAVY_FLEET`"

        Design: Difficulty/combinatorial_formula/claim_credit_cap_evaluation_order
        """
        ctx = self._scenario()
        assert ctx["dc1"]["approved_amount_cents"] == 60000
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        assert invoice["charges_cents"] == 270000
        assert invoice["loyalty_credits_cents"] == 6750
        assert invoice["billed_cents"] == 263250

    def test_cap_derives_from_billed_not_net(self, api):
        """PRD §3.9: "Claim credits come last and are capped from the post-minimum
        figure: the cap is `billed_cents` multiplied by one quarter, rounded half-up —
        never derived from `net_due_cents`; the eligible pool sums
        `approved_amount_cents` over the customer's `PAID` damage claims whose orders
        completed inside the period; `claim_credits_cents` is the lesser of the pool
        and the cap; and `net_due_cents` is `billed_cents` minus
        `claim_credits_cents`."

        Design: Difficulty/combinatorial_formula/claim_credit_cap_evaluation_order
        """
        ctx = self._scenario()
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        # cap = round_half_up(263250 * 0.25) = 65813; pool = 60000 + 15000 = 75000
        assert invoice["claim_credits_cents"] == 65813
        assert invoice["net_due_cents"] == 197437


class TestInvoiceZeroOrdersStillBillsMinimum:
    def _scenario(self):
        customer = create_customer(customer_type="FLEET")
        contract = create_fleet_contract(customer["id"], monthly_minimum_cents=200000,
                                         **CONTRACT_RATES)
        return contract

    def test_zero_lines_still_bills_minimum(self, api):
        """PRD §3.9: "A period with zero included orders still bills the minimum:
        `line_count` and `charges_cents` are 0 and `billed_cents` equals
        `monthly_minimum_cents`."

        Design: Difficulty/boundary_precision_check/invoice_zero_orders_still_bills_minimum
        """
        contract = self._scenario()
        invoice = generate_invoice(contract["id"], "2026-09", "FINAL")
        assert invoice["line_count"] == 0
        assert invoice["charges_cents"] == 0
        assert invoice["billed_cents"] == 200000
        assert invoice["minimum_applied"] is True

    def test_zero_lines_no_claim_credits_net_equals_minimum(self, api):
        """PRD §3.9: "`claim_credits_cents` is the lesser of the pool and the cap; and
        `net_due_cents` is `billed_cents` minus `claim_credits_cents`."

        Design: Difficulty/boundary_precision_check/invoice_zero_orders_still_bills_minimum
        """
        contract = self._scenario()
        invoice = generate_invoice(contract["id"], "2026-09", "FINAL")
        # no PAID claims exist: eligible pool is empty
        assert invoice["claim_credits_cents"] == 0
        assert invoice["net_due_cents"] == 200000


class TestInvoicePreviewCannotIssue:
    def test_issue_on_preview_rejected(self, api):
        """PRD §3.9: "Issuing — a dispatcher action allowed only on a `FINAL` invoice,
        a `PREVIEW` attempt failing with `ERR_INVALID_STATE` — moves it to `ISSUED` and
        flips every included order's `billing_status` from `UNBILLED` to `INVOICED`."

        Design: Corner/state_machines/invoice_preview_cannot_issue
        """
        customer = create_customer(customer_type="FLEET")
        contract = create_fleet_contract(customer["id"], monthly_minimum_cents=50000,
                                         **CONTRACT_RATES)
        preview = generate_invoice(contract["id"], "2026-08", "PROJECTION")
        assert preview["status"] == "PREVIEW"
        resp = api.invoice_event(preview["id"], {"event_type": "ISSUE"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_invoice(preview["id"], DISPATCHER))
        assert still["status"] == "PREVIEW"


class TestInvoiceDisputeAndVoidCompensation:
    def test_dispute_then_void_reverts_order_billing(self, api):
        """PRD §3.9: "A dispute — raised by a dispatcher or by the contract's own
        customer — moves `ISSUED` → `DISPUTED`. Voiding, a dispatcher action from
        `DISPUTED`, moves the invoice to `VOID` and reverts every included order from
        `INVOICED` back to `UNBILLED` as a compensating action."

        Design: Corner/endpoints/invoice_dispute_and_void_compensation
        """
        ctx = setup_completed_order(customer_type="FLEET",
                                    contract_overrides={"monthly_minimum_cents": 50000,
                                                        **CONTRACT_RATES})
        invoice = generate_invoice(ctx["contract"]["id"], "2026-08", "FINAL")
        invoice_event(invoice["id"], "ISSUE")
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "INVOICED"
        disputed = invoice_event(
            invoice["id"], "DISPUTE", make_customer_headers(ctx["customer"]["id"]),
        )
        assert disputed["status"] == "DISPUTED"
        voided = invoice_event(invoice["id"], "VOID")
        assert voided["status"] == "VOID"
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "UNBILLED"


class TestInvoiceExistsOnRegenerate:
    def test_second_final_blocked_preview_never_blocks(self, api):
        """PRD §3.9: "Only one `FINAL`-variant invoice may exist per contract and
        period in `DRAFT`, `ISSUED`, `DISPUTED`, or `PAID`; a second generation
        attempt fails with `ERR_INVOICE_EXISTS`. `PREVIEW` rows never block
        generation, and voiding releases the period for regeneration."

        Design: Corner/errors/invoice_exists_on_regenerate
        """
        customer = create_customer(customer_type="FLEET")
        contract = create_fleet_contract(customer["id"], monthly_minimum_cents=50000,
                                         **CONTRACT_RATES)
        preview = generate_invoice(contract["id"], "2026-08", "PROJECTION")
        assert preview["status"] == "PREVIEW"
        first_final = generate_invoice(contract["id"], "2026-08", "FINAL")
        assert first_final["status"] == "DRAFT"
        resp = api.generate_invoice(
            {"fleet_contract_id": contract["id"], "period_month": "2026-08",
             "variant": "FINAL"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)


class TestEarlyTerminationFeeFourMonths:
    def test_four_full_months_fee_and_zero_at_end_date(self, api):
        """PRD §3.2: "For example, with the clock at 2026-08-14, an `end_date` of
        2026-12-31, and a minimum of 200,000 cents, the full months September through
        December number four, and the fee is 400,000 cents."
        PRD §3.2: "When the clock date is on or after `end_date`, the fee is zero."

        Design: Corner/calculations/early_termination_fee_four_months
        """
        set_clock("2026-08-14T00:00:00Z")
        customer = create_customer(customer_type="FLEET")
        contract_a = create_fleet_contract(
            customer["id"], end_date="2026-12-31", monthly_minimum_cents=200000,
            **CONTRACT_RATES,
        )
        contract_b = create_fleet_contract(
            customer["id"], end_date="2026-08-14", monthly_minimum_cents=200000,
            **CONTRACT_RATES,
        )
        terminated_a = validate_success(api.fleet_contract_event(
            contract_a["id"], {"event_type": "TERMINATE"}, ADMIN,
        ))
        assert terminated_a["status"] == "TERMINATED"
        assert terminated_a["early_termination_fee_cents"] == 400000
        terminated_b = validate_success(api.fleet_contract_event(
            contract_b["id"], {"event_type": "TERMINATE"}, ADMIN,
        ))
        assert terminated_b["early_termination_fee_cents"] == 0
