"""Final invoicing: pinned evaluation order, per-line discount rounding,
surcharge brackets, provisional-vs-final divergence, invoice lifecycle,
payment and credit conservation."""
from test_helpers import (
    ApiErrorId,
    PREMIUM_TIER,
    STANDARD_TIER,
    assert_invoice,
    get_customer,
    get_request,
    grant_credit,
    make_customer_headers,
    setup_completed_job,
    setup_in_service_request,
    setup_issued_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInvoiceGenerationGate:
    def test_invoice_generation_requires_completed_job(self, api, dispatcher_headers):
        """PRD §3.9: "Once a request reaches `COMPLETED` or `NO_SHOW`, a
        `Dispatcher` or `PlatformAdmin` generates the final invoice from actuals;
        any other state is refused with `ERR_JOB_NOT_COMPLETED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/invoice_generation_requires_completed_job
        """
        ctx = setup_in_service_request()
        resp = api.create_invoice(ctx["request"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_COMPLETED)

    def test_rejected_invoice_generation_creates_no_invoice(self, api, dispatcher_headers):
        """PRD §3.9: "Once a request reaches `COMPLETED` or `NO_SHOW`, a
        `Dispatcher` or `PlatformAdmin` generates the final invoice from actuals;
        any other state is refused with `ERR_JOB_NOT_COMPLETED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/invoice_generation_requires_completed_job
        """
        ctx = setup_in_service_request()
        validate_error(api.create_invoice(ctx["request"]["id"], dispatcher_headers),
                       ApiErrorId.ERR_JOB_NOT_COMPLETED)
        invoices, _ = validate_paginated(api.list_request_invoices(ctx["request"]["id"], dispatcher_headers))
        assert invoices == [], f"rejected generation must create no invoice row, got {invoices}"

    def test_second_invoice_for_same_request_rejected(self, api, dispatcher_headers):
        """PRD §3.9: "At most one non-`VOID` invoice may exist per request — a
        second live one draws `ERR_INVOICE_EXISTS` (HTTP 409)"

        Design: Corner/validations/second_invoice_for_same_request_rejected
        """
        ctx = setup_completed_job(labor_minutes=40)
        validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        resp = api.create_invoice(ctx["request"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)


class TestOverageTieredPricing:
    """STANDARD tier 8900/75min/110c-min; labor 90 (15 overage); parts A x2 @1200,
    B x1 @735; no subscription."""

    def _ctx(self):
        return setup_completed_job(
            tier=STANDARD_TIER, labor_minutes=90,
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:30:00Z"),
            parts=[
                {"sku": "A1", "name": "Chain", "unit_price_cents": 1200, "warranty_days": 90, "receive": 5},
                {"sku": "B1", "name": "Cable", "unit_price_cents": 735, "warranty_days": 30, "receive": 5},
            ],
            consume=[("A1", 2), ("B1", 1)])

    def test_labor_overage_and_parts_gross(self, api, dispatcher_headers):
        """PRD §3.9: "Gross labor is the tier's `base_price_cents` plus the overage
        minutes — the excess of `actual_labor_minutes` over `included_minutes`,
        floored at zero — multiplied by `overage_rate_cents_per_min`." and "Each
        distinct part consumed on the job contributes a parts line: its consumed
        quantity (from the `CONSUME` movements) times its `unit_price_cents`."

        Design: Difficulty/combinatorial_formula/final_invoice_overage_tiers_surcharge
        """
        ctx = self._ctx()
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        assert_invoice(inv)
        assert inv["labor_cents"] == 10550, (
            f"labor must be 8900 + max(0, 90-75) * 110 = 10550, got {inv['labor_cents']}")
        assert inv["parts_gross_cents"] == 3135, (
            f"parts gross must be 2*1200 + 1*735 = 3135, got {inv['parts_gross_cents']}")

    def test_invoice_total_with_surcharge_and_tax(self, api, dispatcher_headers):
        """PRD §3.9: "The `surcharge_cents` is bracketed on the pre-surcharge
        subtotal, which pins the otherwise circular question of which value
        selects the bracket: a subtotal below 10000 cents pays no surcharge; at
        least 10000 but below 20000 cents pays 500; at least 20000 cents pays
        1200." and "The `total_cents` is subtotal plus surcharge plus tax."

        Design: Difficulty/combinatorial_formula/final_invoice_overage_tiers_surcharge
        """
        ctx = self._ctx()
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        assert inv["subtotal_cents"] == 16185, f"subtotal must be 16185, got {inv['subtotal_cents']}"
        assert inv["surcharge_cents"] == 500, f"surcharge must be 500, got {inv['surcharge_cents']}"
        assert inv["tax_cents"] == 1335, (
            f"tax must be round_half_up(16685 * 0.08) = 1335, got {inv['tax_cents']}")
        assert inv["total_cents"] == 18020, f"total must be 18020, got {inv['total_cents']}"


class TestPerLineDiscountRounding:
    """FLEET 10% subscription (included 3); two distinct parts @333 cents, qty 1
    each; BASIC tier, labor 40."""

    def _ctx(self):
        return setup_completed_job(
            customer_kind="FLEET",
            subscription={"included_tunes_per_period": 3, "discount_pct": 0.10},
            labor_minutes=40,
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
            parts=[
                {"sku": "P1", "name": "Bolt", "unit_price_cents": 333, "warranty_days": 30, "receive": 2},
                {"sku": "P2", "name": "Nut", "unit_price_cents": 333, "warranty_days": 30, "receive": 2},
            ],
            consume=[("P1", 1), ("P2", 1)])

    def test_discount_rounded_per_line_then_summed(self, api, dispatcher_headers):
        """PRD §3.9: "Discounts are computed per line and rounded half up to
        integer cents before summing: the labor discount is the gross labor times
        `discount_pct` when covered, each parts-line discount is that line's total
        times `discount_pct` when covered, and `discount_cents` is their sum.
        Summing gross amounts first and rounding a single product is forbidden,
        because the results differ — two 333-cent lines at 10% discount yield 33
        plus 33, that is 66 cents, whereas rounding 666 times 0.10 once would
        yield 67."

        Design: Difficulty/combinatorial_formula/per_line_discount_rounding_order
        """
        ctx = self._ctx()
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        # Per line: labor round(4900*0.10)=490, P1 round(33.3)=33, P2 round(33.3)=33.
        # Sum-then-round over the 5566 gross would give 557 and is forbidden.
        assert inv["discount_cents"] == 556, (
            f"discount must be 490 + 33 + 33 = 556 (per-line rounding), got {inv['discount_cents']}")

    def test_discounted_invoice_totals(self, api, dispatcher_headers):
        """PRD §3.9: "The `subtotal_cents` is the callout plus the discounted labor
        plus the discounted parts." and "The `tax_cents` is 8% of subtotal plus
        surcharge, rounded half up."

        Design: Difficulty/combinatorial_formula/per_line_discount_rounding_order
        """
        ctx = self._ctx()
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        assert inv["subtotal_cents"] == 7510, (
            f"subtotal must be 2500 + 4410 + 600 = 7510, got {inv['subtotal_cents']}")
        assert inv["surcharge_cents"] == 0, f"7510 < 10000 pays no surcharge, got {inv['surcharge_cents']}"
        assert inv["tax_cents"] == 601, f"tax must be round_half_up(7510*0.08) = 601, got {inv['tax_cents']}"
        assert inv["total_cents"] == 8111, f"total must be 8111, got {inv['total_cents']}"


class TestSurchargeBrackets:
    def test_surcharge_tier1_boundary_exact_subtotal(self, api, dispatcher_headers):
        """PRD §3.9: "The boundaries are inclusive at the lower edge — a subtotal
        of exactly 10000 yields 500, exactly 20000 yields 1200."

        Design: Corner/calculations/surcharge_tier1_boundary_exact_subtotal
        """
        ctx = setup_completed_job(
            labor_minutes=40,
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
            parts=[{"sku": "T1", "name": "Tire", "unit_price_cents": 2600,
                    "warranty_days": 60, "receive": 2}],
            consume=[("T1", 1)])
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        # 2500 callout + 4900 labor + 2600 part = exactly 10000 pre-surcharge.
        assert inv["subtotal_cents"] == 10000, f"subtotal must be exactly 10000, got {inv['subtotal_cents']}"
        assert inv["surcharge_cents"] == 500, (
            f"exactly 10000 is inclusive of the tier-1 bracket: surcharge 500, got {inv['surcharge_cents']}")
        assert inv["tax_cents"] == 840, f"tax must be round_half_up(10500*0.08) = 840, got {inv['tax_cents']}"
        assert inv["total_cents"] == 11340, f"total must be 11340, got {inv['total_cents']}"

    def test_bracket_keyed_on_pre_surcharge_subtotal(self, api, dispatcher_headers):
        """PRD §3.9: "The `surcharge_cents` is bracketed on the pre-surcharge
        subtotal, which pins the otherwise circular question of which value
        selects the bracket: a subtotal below 10000 cents pays no surcharge; at
        least 10000 but below 20000 cents pays 500; at least 20000 cents pays
        1200."

        Design: Difficulty/combinatorial_formula/surcharge_bracket_evaluation_order
        """
        ctx = setup_completed_job(
            tier=PREMIUM_TIER, labor_minutes=100,
            window=("2026-05-02T10:00:00Z", "2026-05-02T13:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            parts=[{"sku": "X1", "name": "Cassette", "unit_price_cents": 2100,
                    "warranty_days": 60, "receive": 2}],
            consume=[("X1", 1)])
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        # Pre-surcharge subtotal 2500 + 14900 + 2100 = 19500 sits in [10000, 20000).
        assert inv["subtotal_cents"] == 19500, f"subtotal must be 19500, got {inv['subtotal_cents']}"
        # Keying on the post-surcharge 20000 would wrongly select the 1200 bracket.
        assert inv["surcharge_cents"] == 500, (
            f"bracket keyed on pre-surcharge 19500 must give 500, got {inv['surcharge_cents']}")

    def test_bracket_order_tax_and_total(self, api, dispatcher_headers):
        """PRD §3.9: "The `tax_cents` is 8% of subtotal plus surcharge, rounded
        half up." and "The `total_cents` is subtotal plus surcharge plus tax."

        Design: Difficulty/combinatorial_formula/surcharge_bracket_evaluation_order
        """
        ctx = setup_completed_job(
            tier=PREMIUM_TIER, labor_minutes=100,
            window=("2026-05-02T10:00:00Z", "2026-05-02T13:00:00Z"),
            planned=("2026-05-02T10:00:00Z", "2026-05-02T12:00:00Z"),
            parts=[{"sku": "X1", "name": "Cassette", "unit_price_cents": 2100,
                    "warranty_days": 60, "receive": 2}],
            consume=[("X1", 1)])
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        assert inv["tax_cents"] == 1600, (
            f"tax must be round_half_up(20000*0.08) = 1600, got {inv['tax_cents']}")
        assert inv["total_cents"] == 21600, f"total must be 21600, got {inv['total_cents']}"


class TestProvisionalVsFinal:
    """FLEET 10% subscription (included 5); STANDARD tier; parts A x2, B x1;
    labor 90."""

    def _ctx(self):
        return setup_completed_job(
            tier=STANDARD_TIER, customer_kind="FLEET",
            subscription={"included_tunes_per_period": 5, "discount_pct": 0.10},
            labor_minutes=90,
            planned=("2026-05-02T10:00:00Z", "2026-05-02T11:30:00Z"),
            parts=[
                {"sku": "A1", "name": "Chain", "unit_price_cents": 1200, "warranty_days": 90, "receive": 5},
                {"sku": "B1", "name": "Cable", "unit_price_cents": 735, "warranty_days": 30, "receive": 5},
            ],
            consume=[("A1", 2), ("B1", 1)])

    def test_provisional_quote_at_creation(self, api, dispatcher_headers):
        """PRD §3.4: "Every new request carries a provisional quote in
        `quoted_total_cents`, computed on the assumption of exactly the tier's
        `included_minutes` of labor and no parts. The net labor is the tier's
        `base_price_cents` minus — only while the request is covered — the base
        price multiplied by the subscription's `discount_pct`, rounded half up to
        cents."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx = self._ctx()
        # Provisional: 2500 + (8900 - round(890.0)) = 10510; +500 surcharge;
        # tax round(11010 * 0.08) = 881; total 10510 + 500 + 881 = 11891.
        assert ctx["request"]["quoted_total_cents"] == 11891, (
            f"provisional quote must be 11891, got {ctx['request']['quoted_total_cents']}")

    def test_final_invoice_diverges_from_provisional(self, api, dispatcher_headers):
        """PRD §3.9: "The invoice is born `DRAFT` with all monetary lines computed
        in a pinned evaluation order that must not be reordered" — using actual
        parts and actual labor, so the final total diverges from the provisional
        quote of the same request.

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx = self._ctx()
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        # Final: labor 10550 - 1055 = 9495; parts (2400-240) + (735-74) = 2821;
        # subtotal 14816; surcharge 500; tax 1225; total 16541.
        assert inv["labor_cents"] == 10550
        # Per-line discounts: labor 1055 + part A 240 + part B 74 = 1369.
        assert inv["discount_cents"] == 1369, (
            f"discount must be 1055 + 240 + 74 = 1369, got {inv['discount_cents']}")
        assert inv["subtotal_cents"] == 14816
        assert inv["total_cents"] == 16541, f"final total must be 16541, got {inv['total_cents']}"
        assert inv["total_cents"] != ctx["request"]["quoted_total_cents"], (
            "final invoice must diverge from the provisional quote for the same request")


class TestInvoiceLifecycle:
    def _setup_issued_7992(self):
        """COMPLETED job (BASIC, labor 40, no parts, no subscription): invoice
        total 7992 = 7400 subtotal + 592 tax; invoice ISSUED."""
        return setup_issued_invoice(labor_minutes=40,
                                    planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))

    def test_dispute_reissue_cycle_and_billing_mirror(self, api, dispatcher_headers):
        """PRD §3.9: "Disputing — the owning customer, supplying a
        `dispute_reason` — moves `ISSUED` to `DISPUTED` and billing to `DISPUTED`."
        and "Issuing — by a dispatcher or admin — moves a `DRAFT` or `DISPUTED`
        invoice to `ISSUED` and the request's `billing_status` to `INVOICED`;
        re-issue after a dispute follows the same path."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        ctx = self._setup_issued_7992()
        assert ctx["invoice"]["status"] == "ISSUED"
        assert ctx["invoice"]["total_cents"] == 7992
        inv_id, req_id, cust_id = ctx["invoice"]["id"], ctx["request"]["id"], ctx["customer"]["id"]

        disputed = validate_success(api.invoice_event(inv_id, {
            "event_type": "DISPUTE", "dispute_reason": "overcharge",
        }, make_customer_headers(cust_id)), 200)
        assert disputed["status"] == "DISPUTED"
        assert get_request(req_id)["billing_status"] == "DISPUTED"

        reissued = validate_success(api.invoice_event(inv_id, {"event_type": "ISSUE"}, dispatcher_headers), 200)
        assert reissued["status"] == "ISSUED"
        assert get_request(req_id)["billing_status"] == "INVOICED"

    def test_pay_closes_completed_request(self, api, dispatcher_headers):
        """PRD §3.9: "A successful payment records `credit_applied_cents` and
        `amount_paid_cents`, draws the customer's credit balance down by the
        applied amount, moves billing to `PAID`, and — when the request's
        `work_status` is `COMPLETED` — bubbles the request up to `CLOSED` inside
        the same request per §2.9."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        ctx = self._setup_issued_7992()
        inv_id, req_id, cust_id = ctx["invoice"]["id"], ctx["request"]["id"], ctx["customer"]["id"]

        # Exercise the DISPUTED -> ISSUED re-issue hop before paying.
        validate_success(api.invoice_event(inv_id, {"event_type": "DISPUTE", "dispute_reason": "overcharge"},
                                           make_customer_headers(cust_id)), 200)
        validate_success(api.invoice_event(inv_id, {"event_type": "ISSUE"}, dispatcher_headers), 200)

        paid = validate_success(api.invoice_event(inv_id, {
            "event_type": "PAY", "amount_cents": 7992,
        }, make_customer_headers(cust_id)), 200)
        assert paid["status"] == "PAID"

        req = get_request(req_id)
        assert req["billing_status"] == "PAID"
        assert req["work_status"] == "CLOSED", (
            f"COMPLETED + PAID must bubble to CLOSED, got {req['work_status']}")


class TestPayDisputedPrecedence:
    def test_pay_disputed_wrong_amount_surfaces_state_error(self, api, dispatcher_headers):
        """PRD §3.9: "Any payment or dispute aimed at an invoice not in `ISSUED`,
        and any issue or void fired from a state that does not permit it, is
        rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409)."
        PRD §2.10: "then state checks: the generic from-state rule
        `ERR_INVALID_STATE` (HTTP 409) and the more specific state guards named in
        §3. Business rules run last"

        Design: Difficulty/priority_pair_validation_conflict/pay_disputed_invoice_state_beats_payment_mismatch
        """
        ctx = setup_issued_invoice(labor_minutes=40,
                                   planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        validate_success(api.invoice_event(ctx["invoice"]["id"], {
            "event_type": "DISPUTE", "dispute_reason": "wrong amount",
        }, make_customer_headers(ctx["customer"]["id"])), 200)

        # Wrong amount AND wrong state: the state guard must surface, not the
        # fiscal ERR_PAYMENT_MISMATCH.
        resp = api.invoice_event(ctx["invoice"]["id"], {
            "event_type": "PAY", "amount_cents": 1,
        }, make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED)

    def test_pay_disputed_correct_amount_still_state_error(self, api, dispatcher_headers):
        """PRD §3.9: "Any payment or dispute aimed at an invoice not in `ISSUED`,
        and any issue or void fired from a state that does not permit it, is
        rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409)." — the state gate
        applies even when the amount happens to equal the total.

        Design: Difficulty/priority_pair_validation_conflict/pay_disputed_invoice_state_beats_payment_mismatch
        """
        ctx = setup_issued_invoice(labor_minutes=40,
                                   planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        validate_success(api.invoice_event(ctx["invoice"]["id"], {
            "event_type": "DISPUTE", "dispute_reason": "wrong amount",
        }, make_customer_headers(ctx["customer"]["id"])), 200)

        resp = api.invoice_event(ctx["invoice"]["id"], {
            "event_type": "PAY", "amount_cents": 7992,
        }, make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED)

        invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], dispatcher_headers), 200)
        assert invoice["status"] == "DISPUTED", "rejected PAY must leave the invoice DISPUTED"
        assert get_request(ctx["request"]["id"])["billing_status"] == "DISPUTED"


class TestPaymentNotFound:
    def test_pay_nonexistent_invoice_returns_not_found(self, api, dispatcher_headers):
        """PRD §2.8: "The first identifier that does not correspond to an existing
        resource produces an `ERR_NOT_FOUND` (HTTP 404) rejection, and no later
        segment is consulted."
        PRD §2.10: "then left-to-right existence of path identifiers (§2.8)"

        Design: Corner/validations/pay_nonexistent_invoice_returns_not_found
        """
        resp = api.invoice_event("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", {
            "event_type": "PAY", "amount_cents": 1,
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCreditConservation:
    def test_credit_applied_and_amount_paid_sum_to_total(self, api, dispatcher_headers):
        """PRD §3.9: "the submitted `amount_cents` must equal `total_cents` minus
        `credit_applied_cents`, where the applied credit is the smaller of the
        customer's `account_credit_cents` and the invoice's `total_cents` when
        `use_credit` is true, and zero otherwise; a wrong amount is refused with
        `ERR_PAYMENT_MISMATCH` (HTTP 422)."

        Design: Difficulty/compensating_invariant/credit_apply_conserves_cents
        """
        ctx = setup_completed_job(labor_minutes=40,
                                  planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        grant_credit(ctx["customer"]["id"], 1000)
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        assert inv["total_cents"] == 7992
        validate_success(api.invoice_event(inv["id"], {"event_type": "ISSUE"}, dispatcher_headers), 200)

        paid = validate_success(api.invoice_event(inv["id"], {
            "event_type": "PAY", "amount_cents": 6992, "use_credit": True,
        }, make_customer_headers(ctx["customer"]["id"])), 200)
        assert paid["credit_applied_cents"] == 1000, (
            f"credit_applied must be min(1000, 7992) = 1000, got {paid['credit_applied_cents']}")
        assert paid["amount_paid_cents"] == 6992
        assert paid["credit_applied_cents"] + paid["amount_paid_cents"] == paid["total_cents"], (
            "applied credit plus cash paid must equal the invoice total")
        assert paid["status"] == "PAID"

    def test_credit_balance_drawn_down_and_request_closed(self, api, dispatcher_headers):
        """PRD §3.9: "A successful payment records `credit_applied_cents` and
        `amount_paid_cents`, draws the customer's credit balance down by the
        applied amount, moves billing to `PAID`, and — when the request's
        `work_status` is `COMPLETED` — bubbles the request up to `CLOSED` inside
        the same request per §2.9."

        Design: Difficulty/compensating_invariant/credit_apply_conserves_cents
        """
        ctx = setup_completed_job(labor_minutes=40,
                                  planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        credited = grant_credit(ctx["customer"]["id"], 1000)
        assert credited["account_credit_cents"] == 1000
        inv = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        validate_success(api.invoice_event(inv["id"], {"event_type": "ISSUE"}, dispatcher_headers), 200)
        validate_success(api.invoice_event(inv["id"], {
            "event_type": "PAY", "amount_cents": 6992, "use_credit": True,
        }, make_customer_headers(ctx["customer"]["id"])), 200)

        cust = get_customer(ctx["customer"]["id"])
        assert cust["account_credit_cents"] == 0, (
            f"credit balance must be drawn down by 1000 to 0, got {cust['account_credit_cents']}")
        req = get_request(ctx["request"]["id"])
        assert req["billing_status"] == "PAID"
        assert req["work_status"] == "CLOSED"


class TestImmediateConsistency:
    def test_invoice_response_matches_immediate_readback(self, api, dispatcher_headers):
        """PRD §3.9: "The invoice is born `DRAFT` with all monetary lines computed
        in a pinned evaluation order that must not be reordered" — the totals in
        the creation response are the same totals a subsequent read returns.
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/invoice_response_matches_immediate_readback
        """
        ctx = setup_completed_job(labor_minutes=40,
                                  planned=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"))
        created = validate_success(api.create_invoice(ctx["request"]["id"], dispatcher_headers), 201)
        fetched = validate_success(api.get_invoice(created["id"], dispatcher_headers), 200)
        assert created["total_cents"] == 7992
        assert fetched["total_cents"] == created["total_cents"], (
            f"read-back total {fetched['total_cents']} must equal creation total {created['total_cents']}")
