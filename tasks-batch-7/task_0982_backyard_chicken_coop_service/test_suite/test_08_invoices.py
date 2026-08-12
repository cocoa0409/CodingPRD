"""Invoices: pinned rounding order, sweep composition, dispute cycle, wallet
round trip, terminal lockdown, overlap/empty/adjustment guards, lines read."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, assert_invoice_money_invariants,
    create_household, create_plan, create_subscription, create_product,
    create_placed_order, generate_invoice, issue_invoice, credit_wallet,
    make_customer_headers, resolve_dispute_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestRoundingOrder:
    def _placed_999_order_with_subscription(self, api):
        """Plan (fee 2900, supply discount 10%) + subscription + 3 x 333 order."""
        plan = create_plan(plan_code="SUPPLY10", monthly_fee_cents=2900,
                           supply_discount_pct=0.10)
        household = create_household(name="H Round", address="3 Hen Ln")
        create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")
        create_product(sku="FEED-A", name="Layer Feed", unit_price_cents=333)
        order = create_placed_order(household, [("FEED-A", 1)] * 3)
        return household, order

    def test_order_discount_rounds_once_on_subtotal(self, api):
        """PRD §2.6: "A supply order's discount is rounded half up to whole
        cents exactly once, computed on the order's subtotal — never per line."
        PRD §3.8: "On success the totals are computed and frozen:
        `subtotal_cents` as the line-total sum; `discount_cents` as the
        subtotal multiplied by the household's `ACTIVE` subscription plan's
        `supply_discount_pct`, rounded half up to whole cents in a single
        rounding on the subtotal — never per line — and zero when the household
        has no active subscription; and `total_cents` as the difference."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_pinned
        """
        _, order = self._placed_999_order_with_subscription(api)
        # subtotal 999; round_half_up(999 * 0.10) = 100 (per-line rounding would give 99)
        assert order["discount_cents"] == 100
        assert order["total_cents"] == 899

    def test_invoice_tax_rounds_once_on_summed_subtotal(self, api):
        """PRD §2.6: "An invoice's tax is rounded half up to whole cents
        exactly once, computed on the invoice subtotal."
        PRD §3.9: "A successful generation creates the invoice in `DRAFT`,
        stamps every swept source's `billed_invoice_id` with the new invoice's
        id, and computes the invoice totals in a pinned order: `subtotal_cents`
        is the exact sum of the lines' `amount_cents` (including any negative
        adjustments), `tax_cents` is that subtotal multiplied by the 8.25
        percent tax rate and rounded half up to whole cents once, `total_cents`
        is subtotal plus tax, `credit_applied_cents` starts at 0, and
        `amount_due_cents` equals `total_cents`."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_pinned
        """
        household, order = self._placed_999_order_with_subscription(api)
        invoice = generate_invoice(household["id"])
        # ORDER 899 + SUBSCRIPTION_FEE 2900 = 3799; round_half_up(3799*0.0825) = 313
        assert invoice["subtotal_cents"] == 3799
        assert invoice["tax_cents"] == 313
        assert invoice["total_cents"] == 4112
        assert_invoice_money_invariants(invoice)


class TestDisputeCycle:
    def _issued_999_invoice(self, api):
        household = create_household(name="H Disp", address="5 Hen Ln")
        create_product(sku="FEED-A", name="Layer Feed", unit_price_cents=333)
        order = create_placed_order(household, [("FEED-A", 1)] * 3)
        invoice = generate_invoice(household["id"])
        assert (invoice["subtotal_cents"], invoice["tax_cents"],
                invoice["total_cents"]) == (999, 82, 1081)
        invoice = issue_invoice(invoice["id"])
        assert invoice["credit_applied_cents"] == 0, "wallet is 0 at issue"
        return household, order, invoice

    def test_resolve_dispute_appends_adjustment_and_recomputes(self, api):
        """PRD §3.9: "A valid resolution appends an `ADJUSTMENT` line whose
        `amount_cents` equals the adjustment, recomputes `subtotal_cents`,
        `tax_cents`, and `total_cents` through the same pinned composition —
        with `credit_applied_cents` frozen at whatever was applied at issue —
        recomputes `amount_due_cents` as the new total minus that frozen
        credit, and returns the invoice to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        household, order, invoice = self._issued_999_invoice(api)
        disputed = validate_success(api.dispute_invoice(
            invoice["id"], make_customer_headers(household["id"])), 200)
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(api.resolve_invoice_dispute(
            invoice["id"], resolve_dispute_payload(-100, reason="cracked eggs"),
            BILLING), 200)
        # subtotal 999-100 = 899; tax round_half_up(899*0.0825) = 74; total 973
        assert resolved["status"] == "ISSUED"
        assert resolved["subtotal_cents"] == 899
        assert resolved["tax_cents"] == 74
        assert resolved["total_cents"] == 973
        assert resolved["credit_applied_cents"] == 0, "credit frozen at issue value"
        assert resolved["amount_due_cents"] == 973

        lines, _ = validate_paginated(api.list_invoice_lines(invoice["id"], BILLING))
        adjustments = [l for l in lines if l["source_type"] == "ADJUSTMENT"]
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == -100

    def test_cycle_is_reentrant(self, api):
        """PRD §3.9: "The owning `Customer` — `X-User-ID` equal to the
        invoice's `household_id`, else `ERR_NOT_RESOURCE_OWNER` — may dispute
        an `ISSUED` invoice with an optional `reason`, moving it to
        `DISPUTED`."
        PRD §3.9: "A valid resolution appends an `ADJUSTMENT` line whose
        `amount_cents` equals the adjustment, recomputes `subtotal_cents`,
        `tax_cents`, and `total_cents` through the same pinned composition —
        with `credit_applied_cents` frozen at whatever was applied at issue —
        recomputes `amount_due_cents` as the new total minus that frozen
        credit, and returns the invoice to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        household, order, invoice = self._issued_999_invoice(api)
        customer = make_customer_headers(household["id"])
        validate_success(api.dispute_invoice(invoice["id"], customer), 200)
        validate_success(api.resolve_invoice_dispute(
            invoice["id"], resolve_dispute_payload(-100, reason="cracked eggs"),
            BILLING), 200)

        again = validate_success(api.dispute_invoice(invoice["id"], customer), 200)
        assert again["status"] == "DISPUTED", "ISSUED -> DISPUTED a second time"


class TestWalletRoundTrip:
    def _invoice_with_credited_wallet(self, api):
        household = create_household(name="H Wallet", address="16 Hen Ln")
        create_product(sku="FEED-A", name="Layer Feed", unit_price_cents=333)
        order = create_placed_order(household, [("FEED-A", 1)] * 3)
        invoice = generate_invoice(household["id"])  # total 1081
        credit_wallet(household["id"], 5000)
        return household, order, invoice

    def test_issue_debits_wallet_up_to_total(self, api):
        """PRD §3.9: "A `BillingAdmin` issues a `DRAFT` invoice (any other
        state yields `ERR_INVOICE_NOT_DRAFT`); the server sets
        `credit_applied_cents` to the smaller of the household's current
        `wallet_credit_cents` and the invoice's `total_cents`, debits that
        amount from the wallet, sets `amount_due_cents` to the remainder, sets
        `due_date` to the logical clock's date plus 14 days, stamps `issued_at`
        from the logical clock, and moves the invoice to `ISSUED`."

        Design: Difficulty/compensating_invariant/wallet_credit_issue_void_roundtrip
        """
        household, order, invoice = self._invoice_with_credited_wallet(api)
        issued = issue_invoice(invoice["id"])
        assert issued["credit_applied_cents"] == 1081, "min(5000, 1081)"
        assert issued["amount_due_cents"] == 0
        after = validate_success(api.get_household(household["id"], BILLING), 200)
        assert after["wallet_credit_cents"] == 3919, "5000 - 1081"

    def test_void_refunds_exactly_the_applied_credit(self, api):
        """PRD §3.1: "The governing invariant is that issuing an invoice and
        later voiding it leaves the wallet balance unchanged."
        PRD §3.9: "Voiding, also `BillingAdmin`-only and also requiring
        `ISSUED`, is the full unwind: the wallet is refunded exactly the
        invoice's `credit_applied_cents`, `credit_applied_cents` is zeroed,
        `amount_due_cents` becomes the full `total_cents`, and every swept
        source's `billed_invoice_id` is cleared to null so the visit,
        engagement, or order becomes billable again in a future sweep. The
        invoice lands in the terminal `VOID` state."

        Design: Difficulty/compensating_invariant/wallet_credit_issue_void_roundtrip
        """
        household, order, invoice = self._invoice_with_credited_wallet(api)
        issue_invoice(invoice["id"])
        voided = validate_success(api.void_invoice(invoice["id"], BILLING), 200)
        assert voided["status"] == "VOID"
        assert voided["credit_applied_cents"] == 0
        assert voided["amount_due_cents"] == voided["total_cents"] == 1081

        household_after = validate_success(api.get_household(household["id"], BILLING), 200)
        assert household_after["wallet_credit_cents"] == 5000, (
            "issue + void round trip leaves the wallet unchanged")

        order_after = validate_success(api.get_supply_order(order["id"], DISPATCHER), 200)
        assert order_after["billed_invoice_id"] is None, "source released for re-billing"


class TestInvoiceLifecycleGuards:
    def _paid_invoice(self, api):
        household = create_household(name="H Term", address="28 Hen Ln")
        create_product(sku="BED-1", name="Pine Shavings", category="BEDDING",
                       unit_price_cents=1000)
        order = create_placed_order(household, [("BED-1", 1)])
        invoice = generate_invoice(household["id"])
        invoice = issue_invoice(invoice["id"])
        invoice = validate_success(api.mark_invoice_paid(invoice["id"], BILLING), 200)
        return household, order, invoice

    def test_paid_invoice_is_terminal(self, api):
        """PRD §3.9: "An `ISSUED` invoice is either collected — marked `PAID`
        by a `BillingAdmin`, with non-`ISSUED` sources rejected as
        `ERR_INVOICE_NOT_ISSUED`, landing in the terminal `PAID` state —
        disputed, or voided."

        Design: Corner/state_machines/invoice_paid_terminal_lockdown
        """
        household, order, invoice = self._paid_invoice(api)
        res = api.dispute_invoice(invoice["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_INVOICE_NOT_ISSUED)
        after = validate_success(api.get_invoice(invoice["id"], BILLING), 200)
        assert after["status"] == "PAID"

    def test_overlapping_period_rejected(self, api):
        """PRD §3.9: "A household also cannot hold two non-`VOID` invoices
        whose half-open periods overlap — overlap meaning the new period starts
        before the existing one ends and ends after it starts — which is
        rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/validations/invoice_period_overlap_rejected
        """
        household = create_household(name="H IPO", address="45 Hen Ln")
        create_product(sku="BED-1", name="Pine Shavings", category="BEDDING",
                       unit_price_cents=1000)
        create_placed_order(household, [("BED-1", 1)])
        generate_invoice(household["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")

        res = api.create_invoice(
            {"household_id": household["id"],
             "period_start": "2026-05-15T00:00:00Z",
             "period_end": "2026-06-15T00:00:00Z"},
            BILLING)
        validate_error(res, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)

    def test_empty_sweep_rejected(self, api):
        """PRD §3.9: "A sweep that finds nothing rejects generation with
        `ERR_INVOICE_EMPTY` and creates no invoice."

        Design: Corner/validations/invoice_generate_empty_rejected
        """
        household = create_household(name="H Empty", address="47 Hen Ln")
        res = api.create_invoice(
            {"household_id": household["id"],
             "period_start": "2026-05-01T00:00:00Z",
             "period_end": "2026-06-01T00:00:00Z"},
            BILLING)
        validate_error(res, ApiErrorId.ERR_INVOICE_EMPTY)

    def test_zero_adjustment_rejected(self, api):
        """PRD §3.9: "Resolution is a `BillingAdmin` action on a `DISPUTED`
        invoice (else `ERR_INVOICE_NOT_DISPUTED`) carrying a signed
        `adjustment_amount_cents` and a `reason`. The adjustment must be
        nonzero and must not drive the recomputed `total_cents` below zero;
        either violation is rejected with `ERR_INVALID_ADJUSTMENT` (HTTP 422)."

        Design: Corner/validations/invalid_adjustment_zero_rejected
        """
        household = create_household(name="H Adj", address="48 Hen Ln")
        create_product(sku="BED-1", name="Pine Shavings", category="BEDDING",
                       unit_price_cents=1000)
        create_placed_order(household, [("BED-1", 1)])
        invoice = generate_invoice(household["id"])
        invoice = issue_invoice(invoice["id"])
        validate_success(api.dispute_invoice(
            invoice["id"], make_customer_headers(household["id"])), 200)

        res = api.resolve_invoice_dispute(
            invoice["id"], resolve_dispute_payload(0, reason="no-op"), BILLING)
        validate_error(res, ApiErrorId.ERR_INVALID_ADJUSTMENT)
        after = validate_success(api.get_invoice(invoice["id"], BILLING), 200)
        assert after["status"] == "DISPUTED"


class TestInvoiceLines:
    def test_lines_expose_polymorphic_sources(self, api):
        """PRD §3.9: "Each line records its owning `invoice_id`, a
        `source_type` of `VISIT`, `SITTING`, `ORDER`, `SUBSCRIPTION_FEE`,
        `CANCELLATION_FEE`, or `ADJUSTMENT`, a polymorphic `source_id` holding
        the id of the producing ServiceVisit, SittingEngagement, SupplyOrder,
        or Subscription — or the literal string 'ADJUSTMENT' for dispute
        adjustments, making it explicitly not a single-entity foreign key — a
        human-readable `description`, and a signed integer `amount_cents` (only
        `ADJUSTMENT` lines may be negative)."
        PRD §3.9: "**ORDER lines** — orders in `PLACED` or `FULFILLED` status,
        unbilled, with `placed_at`'s date in the period — contribute their
        frozen `total_cents`."
        PRD §3.9: "**SUBSCRIPTION_FEE line** — when the household has a
        subscription in `ACTIVE` or `PAUSED` status whose
        `current_period_start` falls in the period, exactly one line of the
        plan's `monthly_fee_cents` is added."

        Design: Corner/endpoints/invoice_lines_computed_read
        """
        plan = create_plan(plan_code="LR1", monthly_fee_cents=2900,
                           supply_discount_pct=0.10)
        household = create_household(name="H LR", address="50 Hen Ln")
        create_subscription(household, plan["id"], "2026-05-01T00:00:00Z")
        create_product(sku="FEED-A", name="Layer Feed", unit_price_cents=333)
        order = create_placed_order(household, [("FEED-A", 1)] * 3)  # total 899
        invoice = generate_invoice(household["id"])

        lines, meta = validate_paginated(api.list_invoice_lines(invoice["id"], BILLING))
        assert len(lines) == 2
        order_lines = [l for l in lines if l["source_type"] == "ORDER"]
        fee_lines = [l for l in lines if l["source_type"] == "SUBSCRIPTION_FEE"]
        assert len(order_lines) == 1 and order_lines[0]["amount_cents"] == 899
        assert order_lines[0]["source_id"] == order["id"]
        assert len(fee_lines) == 1 and fee_lines[0]["amount_cents"] == 2900
