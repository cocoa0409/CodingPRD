"""Invoice lifecycle: auto-creation content, the dispute/adjust cycle and its
total invariant, the parallel billing dimension on the order, exact payment,
and priority conflicts between validation categories."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_invoice_total_invariant,
    batch_load,
    get_invoice_for_order,
    get_order,
    make_customer_headers,
    place_order,
    schedule_load,
    set_clock,
    setup_completed_load,
    setup_confirmed_order,
    setup_issued_invoice,
    setup_standard_catalog,
    validate_error,
    validate_success,
    confirm_order,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRV1 = TEST_USERS["driver_headers"]


class TestInvoiceAutoCreation:
    def test_invoice_born_draft_with_one_load_line_per_completed_load(self, api):
        """PRD §3.9: "Invoices are born automatically in `DRAFT` when an order
        reaches `DELIVERED`, carrying the `order_id`, the `customer_id`
        denormalized from the order, and a `line_items` array of entries each
        with a `kind`, a `description`, and an `amount_cents` — one `LOAD`
        line per completed load at that load's `final_charge_cents`."

        Design: Corner/endpoints/invoice_auto_created_with_load_lines
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        invoice = get_invoice_for_order(ctx["order"]["id"])
        assert invoice["status"] == "DRAFT"
        assert invoice["customer_id"] == ctx["customer"]["id"]
        assert invoice["order_id"] == ctx["order"]["id"]
        load_lines = [l for l in invoice["line_items"] if l["kind"] == "LOAD"]
        assert len(load_lines) == 1
        assert load_lines[0]["amount_cents"] == 159300
        assert_invoice_total_invariant(invoice)
        assert invoice["total_cents"] == 159300

    def test_billing_stays_priced_until_invoice_issued(self, api):
        """PRD §3.9: "A `PlantManager` issues a draft invoice, stamping
        `issued_at` from the logical clock and moving the invoice `DRAFT →
        ISSUED`; the order's `billing_status` follows `PRICED → INVOICED`."

        Design: Corner/endpoints/invoice_auto_created_with_load_lines
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        get_invoice_for_order(ctx["order"]["id"])
        order = get_order(ctx["order"]["id"])
        assert order["delivery_status"] == "DELIVERED"
        assert order["billing_status"] == "PRICED", (
            "billing only moves to INVOICED when the invoice is issued"
        )


class TestBillingParallelDimension:
    def test_billing_cycles_while_delivery_stays_delivered(self, api):
        """PRD §3.3: "A new order is born with `delivery_status` `PLACED` and
        `billing_status` `UNPRICED`; these two dimensions are parallel and
        evolve independently — delivery runs `PLACED | CONFIRMED | SCHEDULED |
        IN_PROGRESS | DELIVERED | CANCELLED` while billing runs `UNPRICED |
        PRICED | INVOICED | DISPUTED | PAID | VOID`, with `PRICED`, `INVOICED`,
        `DISPUTED`, and `PAID` reached as billing milestones in §3.9."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_billing_independent_of_delivery
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])
        invoice = get_invoice_for_order(ctx["order"]["id"])

        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "PRICED"
        validate_success(api.issue_invoice(invoice["id"], PM), 200)
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "INVOICED"

        validate_success(api.dispute_invoice(invoice["id"], {}, customer_headers), 200)
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "DISPUTED"

        validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "wait credit", "amount_cents": -2500}
                ]},
                PM,
            ),
            200,
        )
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "INVOICED"

        validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 156800}, customer_headers),
            200,
        )
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "PAID"
        assert order["delivery_status"] == "DELIVERED", (
            "delivery stayed terminal-DELIVERED through the whole billing cycle"
        )

    def test_invoice_total_after_adjust_and_exact_payment(self, api):
        """PRD §3.9: "the adjustment lines are appended to `line_items`, the
        new `total_cents` equals the old total plus the sum of the adjustment
        amounts, the invoice returns `DISPUTED → ISSUED`, and the order's
        billing follows `DISPUTED → INVOICED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_billing_independent_of_delivery
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])
        invoice = get_invoice_for_order(ctx["order"]["id"])
        validate_success(api.issue_invoice(invoice["id"], PM), 200)
        validate_success(api.dispute_invoice(invoice["id"], {}, customer_headers), 200)
        adjusted = validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "wait credit", "amount_cents": -2500}
                ]},
                PM,
            ),
            200,
        )
        assert adjusted["total_cents"] == 156800  # 159300 - 2500
        assert_invoice_total_invariant(adjusted)

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 156800}, customer_headers),
            200,
        )
        assert paid["status"] == "PAID"


class TestDisputeAdjustCycle:
    def test_cycle_iterates_twice_with_running_total(self, api):
        """PRD §3.9: "The owning `Customer` may then dispute an issued invoice
        — optionally supplying a `reason` — moving it `ISSUED → DISPUTED` and
        the order's billing `INVOICED → DISPUTED`. A `PlantManager` resolves a
        dispute by adjusting the invoice with a non-empty `adjustment_lines`
        array (an empty array is rejected with `ERR_VALIDATION`, HTTP 400);
        the adjustment lines are appended to `line_items`, the new
        `total_cents` equals the old total plus the sum of the adjustment
        amounts, the invoice returns `DISPUTED → ISSUED`, and the order's
        billing follows `DISPUTED → INVOICED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_adjust_reissue_cycle_twice
        """
        ctx, load, invoice = setup_issued_invoice(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])
        assert invoice["total_cents"] == 159300

        validate_success(api.dispute_invoice(invoice["id"], {}, customer_headers), 200)
        first = validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "wait dispute uplift", "amount_cents": 1000}
                ]},
                PM,
            ),
            200,
        )
        assert first["status"] == "ISSUED"
        assert first["total_cents"] == 160300  # 159300 + 1000
        assert_invoice_total_invariant(first)

        # The cycle is iterable: dispute again from the re-ISSUED state.
        second_dispute = validate_success(
            api.dispute_invoice(invoice["id"], {}, customer_headers), 200
        )
        assert second_dispute["status"] == "DISPUTED"
        second = validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "goodwill", "amount_cents": -500}
                ]},
                PM,
            ),
            200,
        )
        assert second["total_cents"] == 159800  # 160300 - 500
        assert_invoice_total_invariant(second)

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 159800}, customer_headers),
            200,
        )
        assert paid["status"] == "PAID"
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "PAID"

    def test_order_billing_mirrors_each_cycle_iteration(self, api):
        """PRD §3.9: "The owning `Customer` may then dispute an issued invoice
        — optionally supplying a `reason` — moving it `ISSUED → DISPUTED` and
        the order's billing `INVOICED → DISPUTED`. A `PlantManager` resolves a
        dispute by adjusting the invoice with a non-empty `adjustment_lines`
        array (an empty array is rejected with `ERR_VALIDATION`, HTTP 400);
        the adjustment lines are appended to `line_items`, the new
        `total_cents` equals the old total plus the sum of the adjustment
        amounts, the invoice returns `DISPUTED → ISSUED`, and the order's
        billing follows `DISPUTED → INVOICED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_adjust_reissue_cycle_twice
        """
        ctx, load, invoice = setup_issued_invoice(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])
        order_id = ctx["order"]["id"]
        assert get_order(order_id)["billing_status"] == "INVOICED"

        for credit in (-700, 1200):
            validate_success(
                api.dispute_invoice(invoice["id"], {}, customer_headers), 200
            )
            assert get_order(order_id)["billing_status"] == "DISPUTED"
            adjusted = validate_success(
                api.adjust_invoice(
                    invoice["id"],
                    {"adjustment_lines": [
                        {"description": "cycle adjustment", "amount_cents": credit}
                    ]},
                    PM,
                ),
                200,
            )
            assert adjusted["status"] == "ISSUED"
            assert get_order(order_id)["billing_status"] == "INVOICED"
        assert adjusted["total_cents"] == 159300 - 700 + 1200

    def test_invoice_total_conserved_through_adjust_chain(self, api):
        """PRD §3.9: "The invariant `total_cents` equals the sum of the line
        items' `amount_cents` holds at all times."

        Design: Difficulty/compensating_invariant/invoice_total_line_conservation_through_adjust
        """
        ctx, load, invoice = setup_issued_invoice(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])

        validate_success(api.dispute_invoice(invoice["id"], {}, customer_headers), 200)
        plus = validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "after-hours premium", "amount_cents": 1000}
                ]},
                PM,
            ),
            200,
        )
        assert plus["total_cents"] == 160300, "159300 + 1000"
        assert_invoice_total_invariant(plus)

        validate_success(api.dispute_invoice(invoice["id"], {}, customer_headers), 200)
        minus = validate_success(
            api.adjust_invoice(
                invoice["id"],
                {"adjustment_lines": [
                    {"description": "goodwill credit", "amount_cents": -300}
                ]},
                PM,
            ),
            200,
        )
        assert minus["total_cents"] == 160000, "160300 - 300: no drift across the cycle"
        assert_invoice_total_invariant(minus)

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 160000}, customer_headers),
            200,
        )
        assert paid["status"] == "PAID"

    def test_exact_total_is_the_only_payable_amount(self, api):
        """PRD §3.9: "Payment is exact-change only: the owning `Customer` pays
        an issued invoice by supplying `amount_cents`, which must equal the
        invoice's `total_cents` exactly, otherwise
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Difficulty/compensating_invariant/invoice_total_line_conservation_through_adjust
        """
        ctx, load, invoice = setup_issued_invoice(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])
        assert invoice["total_cents"] == 159300

        short = api.pay_invoice(
            invoice["id"], {"amount_cents": 159299}, customer_headers
        )
        validate_error(short, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)

        exact = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 159300}, customer_headers),
            200,
        )
        assert exact["status"] == "PAID"


class TestPaymentAmountMismatch:
    def test_off_by_one_payment_rejected_then_exact_accepted(self, api):
        """PRD §3.9: "Payment is exact-change only: the owning `Customer` pays
        an issued invoice by supplying `amount_cents`, which must equal the
        invoice's `total_cents` exactly, otherwise
        `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful payment moves
        the invoice `ISSUED → PAID` and the order's billing `INVOICED → PAID`;
        the paid invoice drops out of the exposure sum, exposure is
        recomputed, and `credit_status` returns to `GOOD` if and only if the
        remaining exposure is strictly below `credit_limit_cents`."

        Design: Corner/validations/payment_amount_mismatch_rejected
        """
        ctx, load, invoice = setup_issued_invoice(indices=[("2026-08", 115.0)])
        customer_headers = make_customer_headers(ctx["customer"]["id"])

        res = api.pay_invoice(
            invoice["id"], {"amount_cents": 159299}, customer_headers
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
        still = validate_success(api.get_invoice(invoice["id"], PM), 200)
        assert still["status"] == "ISSUED"

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 159300}, customer_headers),
            200,
        )
        assert paid["status"] == "PAID"
        order = get_order(ctx["order"]["id"])
        assert order["billing_status"] == "PAID"


class TestValidationPriority:
    def test_reconfirm_reports_state_not_credit_hold(self, api):
        """PRD §2.8: "When a request violates several rules, the server
        reports the first violation in a fixed priority order."
        PRD §2.8: "State-level checks follow: the optimistic-concurrency check
        (`ERR_STALE_VERSION`), the from-state validity check
        (`ERR_INVALID_STATE`), and the terminal-state check
        (`ERR_ALREADY_TERMINAL`). Only then are business rules evaluated:
        safety rules such as segregation of duties and the batch w/c ceiling;
        referential rules such as mix-active, price-list-unique, slump
        tolerance, and index-month uniqueness; temporal rules such as window
        ordering, pour-date, break-age, batch-interval, and truck-turnaround;
        capacity and quantity constraints; and finally fiscal rules such as
        credit hold and payment-amount matching."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
        """
        catalog = setup_standard_catalog(
            customer_overrides={"credit_limit_cents": 100000}
        )
        order = place_order(
            catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
        )
        confirm_order(order["id"])  # provisional 145200
        validate_success(api.credit_review(catalog["customer"]["id"], PM), 200)
        assert get_order(order["id"])["delivery_status"] == "CONFIRMED"
        from test_helpers import get_customer

        assert get_customer(catalog["customer"]["id"])["credit_status"] == "HOLD"

        res = api.confirm_order(order["id"], DISP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        # state (from-state validity) is evaluated before the fiscal
        # credit-hold rule, so ERR_INVALID_STATE wins over ERR_CREDIT_HOLD.

    def test_reconfirm_with_clean_credit_still_reports_state(self, api):
        """PRD §3.3: "Confirmation is a `Dispatcher` action and is where
        pricing locks in. Only a `PLACED` order can be confirmed, and
        confirming enforces four further preconditions, evaluated within the
        priority framework of §2.8: the customer's `credit_status` must not be
        `HOLD` (otherwise `ERR_CREDIT_HOLD`, HTTP 402); the order's mix design
        must be `ACTIVE` (`ERR_MIX_NOT_ACTIVE`); exactly one price list in
        `ACTIVE` must exist for the order's (plant, mix design) pair
        (`ERR_PRICE_LIST_MISSING`, HTTP 409); and the `pour_date` must still
        be on or after the current logical date (`ERR_POUR_DATE_PAST`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reconfirm
        """
        # Isolated state failure: the customer's credit is never put on HOLD,
        # so only the from-state rule is armed when re-confirming.
        ctx = setup_confirmed_order()
        assert get_order(ctx["order"]["id"])["delivery_status"] == "CONFIRMED"
        res = api.confirm_order(ctx["order"]["id"], DISP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        after = get_order(ctx["order"]["id"])
        assert after["delivery_status"] == "CONFIRMED"
        assert after["version"] == ctx["order_version"], (
            "a rejected re-confirm leaves the order untouched"
        )

    def test_wc_safety_reported_before_batch_interval_conflict(self, api):
        """PRD §2.8: "Only then are business rules evaluated: safety rules
        such as segregation of duties and the batch w/c ceiling; referential
        rules such as mix-active, price-list-unique, slump tolerance, and
        index-month uniqueness; temporal rules such as window ordering,
        pour-date, break-age, batch-interval, and truck-turnaround; capacity
        and quantity constraints; and finally fiscal rules such as credit hold
        and payment-amount matching."
        PRD §3.5: "And the water/cement safety ceiling is checked up front:
        the design batch water plus the requested extra water (converted at
        8.34 pounds per gallon), divided by the cement weight, must not exceed
        the mix's `max_wc_ratio`; a batch that would push the ratio above the
        ceiling is rejected with `ERR_WC_RATIO_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_batch
        """
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-15",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load(
            ctx["order"]["id"], get_order(ctx["order"]["id"])["version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"],
        )
        batch_load(l1["id"], "2026-08-15T10:00:00Z")  # occupies [10:00, 10:30)

        # L2 at 10:15 both collides with [10:00, 10:30) AND breaches the w/c
        # ceiling (extra 50 gal -> (2030+417)/4512 = 0.542 > 0.50).
        res = api.batch_load(
            l2["id"],
            {"batch_time": "2026-08-15T10:15:00Z", "extra_batch_water_gal": 50},
            TEST_USERS["batch_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_WC_RATIO_EXCEEDED.value)

        assert get_order(ctx["order"]["id"]) is not None
        from test_helpers import get_load

        assert get_load(l2["id"])["status"] == "SCHEDULED"
        tickets = validate_success(api.get_batch_ticket(l2["id"], DISP), 200)
        assert tickets == [], "no batch ticket for a rejected batch"

    def test_wc_ceiling_breach_rejected_in_isolation(self, api):
        """PRD §3.5: "And the water/cement safety ceiling is checked up front:
        the design batch water plus the requested extra water (converted at
        8.34 pounds per gallon), divided by the cement weight, must not exceed
        the mix's `max_wc_ratio`; a batch that would push the ratio above the
        ceiling is rejected with `ERR_WC_RATIO_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_batch
        """
        ctx = setup_confirmed_order(
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-15",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load(
            ctx["order"]["id"], get_order(ctx["order"]["id"])["version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"],
        )
        batch_load(l1["id"], "2026-08-15T10:00:00Z")  # occupies [10:00, 10:30)

        # 10:30 is adjacent (no plant conflict); only the w/c ceiling fails.
        res = api.batch_load(
            l2["id"],
            {"batch_time": "2026-08-15T10:30:00Z", "extra_batch_water_gal": 50},
            TEST_USERS["batch_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_WC_RATIO_EXCEEDED.value)
        from test_helpers import get_load

        assert get_load(l2["id"])["status"] == "SCHEDULED"
