"""Invoicing, payments, credit notes, and the renter credit picture."""
from test_helpers import (
    ApiErrorId,
    acquire_unit,
    apply_credit_note,
    assert_invoice,
    check_in_line,
    confirm_reservation,
    create_active_renter,
    create_catalog_item,
    create_confirmed_production,
    create_pull_list_for,
    dispatch_pull_list,
    generate_invoice,
    get_renter,
    issue_invoice,
    make_renter_contact_headers,
    pick_all_lines,
    place_reservation,
    publish_rate_card,
    record_payment,
    set_logical_clock,
    setup_dispatched_scenario,
    setup_issued_invoice_scenario,
    submit_and_get_lines,
    validate_error,
    validate_success,
)


class TestInvoiceGeneration:
    def test_error_invoice_empty_generate_rejected(self, api, accountant_headers):
        """PRD §3.8: "An empty sweep set is rejected with `ERR_INVOICE_EMPTY`."

        Design: Corner/errors/error_invoice_empty_generate_rejected
        """
        publish_rate_card(api)
        renter = create_active_renter(api, name="R")["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-09-20")

        resp = api.generate_invoice(production["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY, 409)
        assert validate_success(
            api.list_invoices(accountant_headers, params={"production_id": production["id"]})
        ) == []


class TestPerLineRoundingThenSum:
    def _setup_two_line_invoice(self, api):
        """Two qty-1 LONG_RUN reservations on a PROP item with weekly 3333: each
        reservation quotes round_half_up(3333 * 1 week * 0.8) = 2666."""
        publish_rate_card(api)
        item = create_catalog_item(
            api, name="Deco vase", period="TWENTIES", category="PROP", size_class="NONE",
            alteration_policy="PROHIBITED", replacement_value_cents=20000,
            base_daily_rate_cents=1000, base_weekly_rate_cents=3333,
        )
        acquire_unit(api, item["id"], barcode="BC-301", acquisition_cost_cents=12000)
        acquire_unit(api, item["id"], barcode="BC-302", acquisition_cost_cents=12000)
        renter = create_active_renter(api, name="Renter F", renter_type="FILM")["renter"]
        production = create_confirmed_production(api, renter, title="LR",
                                                 closing_date="2026-10-26")
        r1 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-01", window_end_date="2026-09-07")
        assert r1["quoted_charge_cents"] == 2666
        confirm_reservation(api, r1, renter)
        r2 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-08", window_end_date="2026-09-14")
        assert r2["quoted_charge_cents"] == 2666
        confirm_reservation(api, r2, renter)

        pull_list = create_pull_list_for(api, production["id"], renter)
        pull_list, lines = submit_and_get_lines(api, pull_list["id"])
        pick_all_lines(api, lines)
        dispatch_pull_list(api, pull_list["id"], at="2026-08-31T00:00:00Z")
        return {"production": production, "renter": renter, "lines": lines}

    def test_line_charges_rounded_per_line(self, api):
        """PRD §2.6: "Per-line rental charges are rounded at line-assignment time and
        stored; invoice generation sums those stored per-line integers and never re-rounds
        the sum."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = self._setup_two_line_invoice(api)
        for line in ctx["lines"]:
            # Raw per-unit charge is 2666.4; each line pins round_half_up at assignment.
            assert line["rental_charge_cents"] == 2666

    def test_invoice_sums_prerounded_lines(self, api):
        """PRD §2.6: "(The two orders genuinely differ: two lines of 2666.4 raw cents yield
        2666 + 2666 = 5332 when rounded per line, versus 5333 if the sum were rounded
        instead.)"
        PRD §3.8: "`rental_charges_cents` is the sum of swept lines' `rental_charge_cents`
        (the per-line rounded values are summed, never re-rounded)".

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
        """
        ctx = self._setup_two_line_invoice(api)
        invoice = generate_invoice(api, ctx["production"]["id"])
        assert_invoice(invoice)
        assert invoice["rental_charges_cents"] == 5332
        assert invoice["total_cents"] == 5332, (
            "sum-then-round would read 5333; the pinned per-line order reads 5332"
        )


class TestCreditRecomputePinnedOrder:
    def _setup_first_invoice(self, api):
        """Long-run dispatch with invoice1 (rental 8000) ISSUED against a renter whose
        credit limit is exactly 8000; the line is still OUT."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        acquire_unit(api, item["id"], barcode="BC-401")
        acquire_unit(api, item["id"], barcode="BC-402")
        renter = create_active_renter(api, name="Renter C", credit_limit_cents=8000)["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        reservation = place_reservation(api, production["id"], renter, item["id"], quantity=1)
        confirm_reservation(api, reservation, renter)
        pull_list = create_pull_list_for(api, production["id"], renter)
        pull_list, lines = submit_and_get_lines(api, pull_list["id"])
        pick_all_lines(api, lines)
        dispatch_pull_list(api, pull_list["id"], at="2026-08-31T00:00:00Z")

        inv1 = issue_invoice(api, generate_invoice(api, production["id"])["id"])
        assert inv1["total_cents"] == 8000
        return {"renter": renter, "production": production, "inv1": inv1,
                "line_id": lines[0]["id"]}

    def _checkin_late_and_issue_second_invoice(self, api, ctx):
        """Return the line 3 days late (fee 300 + cleaning 1500) and issue invoice2."""
        set_logical_clock(api, "2026-09-13T00:00:00Z")  # 3 days past due_back 2026-09-10
        line = check_in_line(api, ctx["line_id"])
        assert line["late_fee_cents"] == 300
        inv2 = issue_invoice(api, generate_invoice(api, ctx["production"]["id"])["id"])
        return inv2

    def test_outstanding_and_hold_progression(self, api):
        """PRD §3.8: "The renter's `outstanding_balance_cents` is recomputed as the sum of
        `balance_cents` over all of that renter's invoices in `ISSUED` or `PARTIALLY_PAID`
        status, and `credit_hold` is recomputed as true exactly when the outstanding balance
        is **strictly greater** than `credit_limit_cents` — a balance equal to the limit does
        not hold."

        Design: Difficulty/combinatorial_formula/credit_recompute_pinned_evaluation_order
        """
        ctx = self._setup_first_invoice(api)
        renter_id = ctx["renter"]["id"]

        # After invoice1 only: 8000 outstanding == 8000 limit -> strictly-greater is false.
        mid = get_renter(api, renter_id)
        assert mid["outstanding_balance_cents"] == 8000
        assert mid["credit_hold"] is False

        inv2 = self._checkin_late_and_issue_second_invoice(api, ctx)
        assert inv2["total_cents"] == 1800  # late 300 + cleaning 1500
        over = get_renter(api, renter_id)
        assert over["outstanding_balance_cents"] == 9800
        assert over["credit_hold"] is True  # 9800 > 8000

    def test_payment_to_exact_limit_clears_hold(self, api):
        """PRD §3.8: "first the invoice's `amount_paid_cents` or `credited_cents` is mutated,
        then the invoice's `balance_cents` and `total_cents` are recomputed, then the
        renter's `outstanding_balance_cents`, and finally the renter's `credit_hold`." and
        "one bringing `amount_paid_cents` level with `total_cents` moves it to `PAID`."

        Design: Difficulty/combinatorial_formula/credit_recompute_pinned_evaluation_order
        """
        ctx = self._setup_first_invoice(api)
        renter_id = ctx["renter"]["id"]
        inv2 = self._checkin_late_and_issue_second_invoice(api, ctx)
        assert get_renter(api, renter_id)["credit_hold"] is True

        paid = record_payment(api, inv2["id"], 1800)
        assert paid["status"] == "PAID"
        after = get_renter(api, renter_id)
        # One payment request cascaded: invoice PAID -> outstanding 8000 -> hold cleared,
        # because 8000 > 8000 is false under strictly-greater semantics.
        assert after["outstanding_balance_cents"] == 8000
        assert after["credit_hold"] is False


class TestCreditLimitEqualityBoundary:
    def _setup(self, api):
        """Renter limit 8000 with an ISSUED 8000 invoice; R2 (Sep 11-15) and R3
        (Sep 16-20) HELD on the same long-run production."""
        publish_rate_card(api)
        item = create_catalog_item(api, name="Tailcoat")
        for bc in ("BC-1301", "BC-1302", "BC-1303"):
            acquire_unit(api, item["id"], barcode=bc)
        renter = create_active_renter(api, name="Renter R", credit_limit_cents=8000)["renter"]
        production = create_confirmed_production(api, renter, closing_date="2026-10-26")
        r1 = place_reservation(
            api, production["id"], renter, item["id"], quantity=1,
            window_start_date="2026-09-01", window_end_date="2026-09-10",
        )
        confirm_reservation(api, r1, renter)
        pull_list = create_pull_list_for(api, production["id"], renter)
        pull_list, lines = submit_and_get_lines(api, pull_list["id"])
        pick_all_lines(api, lines)
        dispatch_pull_list(api, pull_list["id"], at="2026-08-31T00:00:00Z")
        invoice = issue_invoice(api, generate_invoice(api, production["id"])["id"])
        assert invoice["balance_cents"] == 8000

        r2 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-11", window_end_date="2026-09-15")
        r3 = place_reservation(api, production["id"], renter, item["id"], quantity=1,
                               window_start_date="2026-09-16", window_end_date="2026-09-20")
        return {"renter": renter, "production": production, "r2": r2, "r3": r3}

    def test_confirm_succeeds_at_exact_limit(self, api, house_admin_headers):
        """PRD §3.8: "`credit_hold` is recomputed as true exactly when the outstanding
        balance is **strictly greater** than `credit_limit_cents` — a balance equal to the
        limit does not hold."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary
        """
        ctx = self._setup(api)
        renter_view = get_renter(api, ctx["renter"]["id"])
        assert renter_view["outstanding_balance_cents"] == 8000
        assert renter_view["credit_hold"] is False  # 8000 == 8000 does not hold

        confirmed = validate_success(
            api.confirm_reservation(
                ctx["r2"]["id"], make_renter_contact_headers(ctx["renter"]["id"]),
            )
        )
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_fails_one_cent_below_limit(self, api, house_admin_headers):
        """PRD §3.8: "A renter on credit hold finds reservation confirmation and pull-list
        dispatch rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/credit_limit_equality_boundary
        """
        ctx = self._setup(api)
        patched = validate_success(
            api.update_renter(ctx["renter"]["id"], {"credit_limit_cents": 7999},
                              house_admin_headers)
        )
        assert patched["credit_hold"] is True  # 8000 > 7999

        resp = api.confirm_reservation(
            ctx["r3"]["id"], make_renter_contact_headers(ctx["renter"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)


class TestPaymentAndCreditGuards:
    def test_error_payment_invalid_and_exceeds_balance(self, api, accountant_headers):
        """PRD §3.8: "Recording a payment against an `ISSUED` or `PARTIALLY_PAID` invoice
        takes an `amount_cents` of at least 1 (`ERR_PAYMENT_INVALID`) and no more than the
        invoice's current `balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`)." and "one bringing
        `amount_paid_cents` level with `total_cents` moves it to `PAID`."

        Design: Corner/errors/error_payment_invalid_and_exceeds_balance
        """
        ctx = setup_issued_invoice_scenario(api)
        invoice_id = ctx["invoice"]["id"]
        assert ctx["invoice"]["balance_cents"] == 8000

        resp = api.record_payment(invoice_id, 0, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID, 422)
        resp = api.record_payment(invoice_id, 8001, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)

        paid = record_payment(api, invoice_id, 8000)
        assert paid["status"] == "PAID"

    def test_error_credit_exceeds_balance_rejected(self, api, accountant_headers):
        """PRD §3.8: "The amount must be at least 1 (`ERR_CREDIT_INVALID`) and no more than
        the current `balance_cents` (`ERR_CREDIT_EXCEEDS_BALANCE`); it accumulates into
        `credited_cents` and reduces `total_cents`. A credit equal to the full balance
        settles the invoice: from `ISSUED` or `PARTIALLY_PAID` it becomes `CREDITED`."

        Design: Corner/errors/error_credit_exceeds_balance_rejected
        """
        ctx = setup_issued_invoice_scenario(api)
        invoice_id = ctx["invoice"]["id"]

        resp = api.credit_note(invoice_id, 0, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_INVALID, 422)
        resp = api.credit_note(invoice_id, 8001, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_BALANCE, 422)

        credited = apply_credit_note(api, invoice_id, 3000)
        assert credited["total_cents"] == 5000
        assert credited["balance_cents"] == 5000
        assert credited["status"] == "ISSUED", "a partial credit leaves the invoice ISSUED"


class TestLedgerConserved:
    def test_issue_moves_outstanding_from_zero(self, api):
        """PRD §3.8: "Issuing, by an `Accountant`, requires a `total_cents` greater than zero
        (`ERR_INVOICE_EMPTY`); it moves the invoice `OPEN` → `ISSUED` and immediately pulls
        the balance into the renter's credit picture. The renter's `outstanding_balance_cents`
        is recomputed as the sum of `balance_cents` over all of that renter's invoices in
        `ISSUED` or `PARTIALLY_PAID` status".

        Design: Difficulty/compensating_invariant/ledger_conserved_across_issue_credit
        """
        ctx = setup_dispatched_scenario(api, quantity=1, num_units=1)
        renter_id = ctx["renter"]["id"]
        assert get_renter(api, renter_id)["outstanding_balance_cents"] == 0

        invoice = generate_invoice(api, ctx["production"]["id"])
        assert invoice["total_cents"] == 8000
        assert get_renter(api, renter_id)["outstanding_balance_cents"] == 0, (
            "an OPEN invoice does not yet count toward the outstanding balance"
        )

        issued = issue_invoice(api, invoice["id"])
        assert issued["status"] == "ISSUED"
        assert get_renter(api, renter_id)["outstanding_balance_cents"] == 8000

    def test_full_credit_returns_outstanding_to_zero(self, api):
        """PRD §3.8: "A credit equal to the full balance settles the invoice: from `ISSUED`
        or `PARTIALLY_PAID` it becomes `CREDITED`." and "The renter's
        `outstanding_balance_cents` is recomputed as the sum of `balance_cents` over all of
        that renter's invoices in `ISSUED` or `PARTIALLY_PAID` status".

        Design: Difficulty/compensating_invariant/ledger_conserved_across_issue_credit
        """
        ctx = setup_issued_invoice_scenario(api, num_units=1)
        renter_id = ctx["renter"]["id"]
        assert get_renter(api, renter_id)["outstanding_balance_cents"] == 8000

        credited = apply_credit_note(api, ctx["invoice"]["id"], 8000, reason="goodwill")
        assert credited["status"] == "CREDITED"
        assert credited["balance_cents"] == 0
        # Forward (issue) plus compensating (full credit) conserve the ledger at 0.
        assert get_renter(api, renter_id)["outstanding_balance_cents"] == 0
