"""Weekly billing, invoice math (residential flat vs commercial metered),
per-line rounding, credit application cap, idempotency, payment and standing.

Covers PRD §2.7 (rounding order), §3.9 (billing, invoices, standing).
"""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    complete_pickup,
    create_bins,
    create_plan_com,
    create_plan_res,
    create_route,
    create_subscriber,
    create_subscription,
    generate_and_get_pickups,
    get_invoice,
    get_subscriber,
    list_credit_entries,
    list_invoices_for_subscriber,
    make_subscriber_headers,
    post_credit_adjustment,
    post_weigh_ticket,
    run_billing,
    set_clock,
    setup_active_subscription,
    setup_completed_pickup,
    setup_issued_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_res_vs_com(api):
    """RES subscriber on R1 and COM subscriber on R2, both with a week
    2026-05-04 (SPRING) pickup completed at 0.5; R2 weighed at net 30.00 kg.

    RES: estimated 10.00 kg, credit 100. COM: estimated 30.00 kg, credit 150,
    final 30.00 kg, delta 0 (final credit round(30 x 5 x 1.0) = 150).
    """
    plan_res = create_plan_res()
    plan_com = create_plan_com()
    route1 = create_route(code="R1")
    route2 = create_route(code="R2")
    create_bins(2, bin_type="BIN_35L")
    create_bins(2, bin_type="BIN_240L")
    sub_r = create_subscriber("RESIDENTIAL", email="r@x.com")
    sub_c = create_subscriber("COMMERCIAL", email="c@x.com",
                              full_name="Com Sub", address="2 C St")
    subs_r = create_subscription(sub_r["id"], plan_res["id"], route1["id"])
    subs_c = create_subscription(sub_c["id"], plan_com["id"], route2["id"])
    pk_r = generate_and_get_pickups(route1["id"], subs_r["id"], ["2026-05-04"])[0]
    pk_c = generate_and_get_pickups(route2["id"], subs_c["id"], ["2026-05-04"])[0]
    complete_pickup(pk_r["id"], 0.5)
    complete_pickup(pk_c["id"], 0.5)
    post_weigh_ticket(route2["id"], "2026-05-04", 35.0, 5.0)
    run_billing("2026-05-04")
    inv_r = list_invoices_for_subscriber(sub_r["id"])[0]
    inv_c = list_invoices_for_subscriber(sub_c["id"])[0]
    return sub_r, sub_c, inv_r, inv_c


class TestResidentialVsCommercialBilling:
    def test_residential_flat_invoice(self, api):
        """PRD §3.9: "For a residential plan, a pickup in `COMPLETED` or
        `REJECTED_CONTAMINATION` produces a `WEEKLY_FLAT` line at the plan's
        `weekly_price_cents`, while a pickup in `SKIPPED`, `MISSED`,
        `CANCELLED_SYSTEM`, or `VOIDED` produces no line at all."
        PRD §3.9: "The invoice's `due_date` is fourteen days after the
        `week_start_date`, and the invoice is born `ISSUED`."

        Design: Difficulty/dual_variant_calc/invoice_amount_residential_flat_vs_commercial_metered
        """
        _, _, inv_r, _ = _setup_res_vs_com(api)
        invoice = get_invoice(inv_r["id"])
        assert_invoice(invoice)
        flat = [l for l in invoice["lines"] if l["line_type"] == "WEEKLY_FLAT"]
        assert len(flat) == 1 and flat[0]["amount_cents"] == 1200
        assert invoice["subtotal_cents"] == 1200
        assert invoice["credit_applied_cents"] == 100
        assert invoice["total_cents"] == 1100
        assert invoice["due_date"] == "2026-05-18"
        assert invoice["status"] == "ISSUED"

    def test_commercial_metered_invoice(self, api):
        """PRD §3.9: "For a commercial plan, a `COMPLETED` pickup produces a
        `METERED_BASE` line at the plan's `metered_base_cents` plus — only when
        the pickup's `final_kg` exceeds the plan's `included_kg_per_week` — an
        `OVERAGE_KG` line amounting to the plan's `per_kg_rate_cents`
        multiplied by the excess of `final_kg` over `included_kg_per_week`,
        rounded half-up to integer cents."

        Design: Difficulty/dual_variant_calc/invoice_amount_residential_flat_vs_commercial_metered
        """
        _, _, _, inv_c = _setup_res_vs_com(api)
        invoice = get_invoice(inv_c["id"])
        assert_invoice(invoice)
        base = [l for l in invoice["lines"] if l["line_type"] == "METERED_BASE"]
        overage = [l for l in invoice["lines"] if l["line_type"] == "OVERAGE_KG"]
        assert len(base) == 1 and base[0]["amount_cents"] == 3000
        assert overage == [], "final 30.00 kg is within the 40 kg allowance"
        assert invoice["subtotal_cents"] == 3000
        assert invoice["credit_applied_cents"] == 150
        assert invoice["total_cents"] == 2850


class TestPerLineRounding:
    def _setup_two_route_commercial(self, api):
        """One COM subscriber with two subscriptions (R1, R2); week 2026-06-08
        (SUMMER) both completed at 0.7 (est 42.00 kg each, credit 252 each);
        both routes weighed at net 41.05 kg (gross 50.00, tare 8.95)."""
        plan = create_plan_com()
        route1 = create_route(code="R1")
        route2 = create_route(code="R2")
        create_bins(4, bin_type="BIN_240L")
        sub = create_subscriber("COMMERCIAL", email="c@x.com",
                                full_name="Com Sub", address="2 C St")
        subs1 = create_subscription(sub["id"], plan["id"], route1["id"])
        subs2 = create_subscription(sub["id"], plan["id"], route2["id"])
        pk1 = generate_and_get_pickups(route1["id"], subs1["id"], ["2026-06-08"])[0]
        pk2 = generate_and_get_pickups(route2["id"], subs2["id"], ["2026-06-08"])[0]
        complete_pickup(pk1["id"], 0.7)
        complete_pickup(pk2["id"], 0.7)
        post_weigh_ticket(route1["id"], "2026-06-08", 50.0, 8.95)
        post_weigh_ticket(route2["id"], "2026-06-08", 50.0, 8.95)
        run_billing("2026-06-08")
        invoice = list_invoices_for_subscriber(sub["id"])[0]
        return sub, invoice

    def test_overage_lines_rounded_per_line(self, api):
        """PRD §3.9: "Rounding order is pinned. Every line amount is an integer
        computed in isolation — round half-up per line — and the invoice's
        `subtotal_cents` is the sum of those integer line amounts; the system
        never sums unrounded amounts and rounds once at the end."
        Each overage is round_half_up(7 x 1.05) = 7, not round(14.70) = 15.

        Design: Difficulty/combinatorial_formula/commercial_invoice_per_line_rounding_then_sum
        """
        _, invoice = self._setup_two_route_commercial(api)
        invoice = get_invoice(invoice["id"])
        base = [l for l in invoice["lines"] if l["line_type"] == "METERED_BASE"]
        overage = [l for l in invoice["lines"] if l["line_type"] == "OVERAGE_KG"]
        assert sorted(l["amount_cents"] for l in base) == [3000, 3000]
        assert [l["amount_cents"] for l in overage] == [7, 7]

    def test_subtotal_is_sum_of_rounded_lines_with_credit_cap(self, api):
        """PRD §2.7: "Invoice math pins the rounding order explicitly: every
        charge line is computed and rounded to a whole cent in isolation, and
        the invoice subtotal is the sum of those integer line amounts — the
        system never sums unrounded values and rounds once at the end."
        PRD §3.9: "then `credit_applied_cents` is the smaller of the
        subscriber's current `credit_balance_cents` and one half of the
        subtotal rounded down to a whole cent".

        Design: Difficulty/combinatorial_formula/commercial_invoice_per_line_rounding_then_sum
        """
        sub, invoice = self._setup_two_route_commercial(api)
        invoice = get_invoice(invoice["id"])
        # 3000 + 3000 + 7 + 7 = 6014 (per-line rounding), not 6015.
        assert invoice["subtotal_cents"] == 6014
        # Balance: 2 x (252 - 6) = 492; cap floor(0.5 x 6014) = 3007.
        assert invoice["credit_applied_cents"] == 492
        assert invoice["total_cents"] == 5522
        assert get_subscriber(sub["id"])["credit_balance_cents"] == 0


class TestCreditApplicationCap:
    def test_cap_binds_at_fifty_percent(self, api):
        """PRD §3.9: "then `credit_applied_cents` is the smaller of the
        subscriber's current `credit_balance_cents` and one half of the
        subtotal rounded down to a whole cent; then `total_cents` is the
        subtotal minus the applied credit. When the applied credit is greater
        than zero, an `INVOICE_APPLICATION_DEBIT` entry of negative
        `credit_applied_cents` with the `invoice_id` set is posted and the
        subscriber's balance decreases immediately."

        Design: Corner/calculations/credit_application_cap_binds_at_fifty_percent
        """
        env = setup_issued_invoice(week_start="2026-05-04", credit_adjustment_cents=10000)
        invoice = get_invoice(env["invoice"]["id"])
        # Balance before billing: 100 + 10000 = 10100; cap floor(0.5 x 1200) = 600.
        assert invoice["subtotal_cents"] == 1200
        assert invoice["credit_applied_cents"] == 600
        assert invoice["total_cents"] == 600
        debits = [
            e for e in list_credit_entries(subscriber_id=env["subscriber"]["id"])
            if e["entry_type"] == "INVOICE_APPLICATION_DEBIT"
        ]
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -600
        assert debits[0].get("invoice_id") == invoice["id"]
        assert get_subscriber(env["subscriber"]["id"])["credit_balance_cents"] == 9500


class TestBillingRunGrouping:
    def test_grouping_per_subscriber_and_idempotent_rerun(self, api, ops_headers):
        """PRD §3.9: "the run produces at most one invoice per subscriber with
        billable activity inside it." PRD §3.9: "The run is idempotent per
        subscriber and week: a rerun skips pairs already invoiced and reports
        them in `skipped_subscriber_ids`, and the run's response carries the
        `issued_count`, the list of `invoice_ids`, and that
        `skipped_subscriber_ids` list."

        Design: Corner/endpoints/billing_run_groups_subscriptions_and_is_idempotent
        """
        plan = create_plan_res()
        route1 = create_route(code="R1")
        route2 = create_route(code="R2")
        create_bins(4)
        sub = create_subscriber()
        subs1 = create_subscription(sub["id"], plan["id"], route1["id"])
        subs2 = create_subscription(sub["id"], plan["id"], route2["id"])
        pk1 = generate_and_get_pickups(route1["id"], subs1["id"], ["2026-05-04"])[0]
        pk2 = generate_and_get_pickups(route2["id"], subs2["id"], ["2026-05-04"])[0]
        complete_pickup(pk1["id"], 0.5)
        complete_pickup(pk2["id"], 0.5)

        first = run_billing("2026-05-04")
        assert first["issued_count"] == 1
        invoices = list_invoices_for_subscriber(sub["id"])
        assert len(invoices) == 1, "two subscriptions group into one invoice"
        invoice = get_invoice(invoices[0]["id"])
        assert invoice["subtotal_cents"] == 2400
        assert invoice["credit_applied_cents"] == 200
        assert invoice["total_cents"] == 2200

        second = validate_success(
            api.run_billing({"week_start_date": "2026-05-04"}, ops_headers)
        )
        assert second["issued_count"] == 0
        assert sub["id"] in second["skipped_subscriber_ids"]
        assert len(list_invoices_for_subscriber(sub["id"])) == 1


class TestCommercialBillingGate:
    def test_unweighed_commercial_pickup_aborts_run(self, api, ops_headers):
        """PRD §3.9: "One gate stands in front of the whole run: every
        `COMPLETED` pickup of a `COMMERCIAL` subscription in the week must
        already have a posted weigh ticket for its route and service date —
        metered billing cannot proceed on estimates — and if any such pickup is
        missing its ticket, the entire run aborts with
        `ERR_WEIGH_TICKET_PENDING`."

        Design: Corner/validations/billing_run_with_unweighed_commercial_returns_pending
        """
        env = setup_completed_pickup(
            service_date="2026-06-01", subscriber_type="COMMERCIAL", bin_count=2
        )
        resp = api.run_billing({"week_start_date": "2026-06-01"}, ops_headers)
        validate_error(resp, ApiErrorId.ERR_WEIGH_TICKET_PENDING)
        invoices, meta = validate_paginated(
            api.list_invoices(ops_headers, params={"subscriber_id": env["subscriber"]["id"]})
        )
        assert invoices == [] and meta["total_count"] == 0


class TestInvoicePaymentAndStanding:
    def test_pay_already_paid_invoice_rejected(self, api):
        """PRD §3.9: "paying requires the invoice to be `ISSUED`, otherwise
        `ERR_INVOICE_NOT_PAYABLE`, and moves it to `PAID`, incrementing its
        `version`".

        Design: Corner/state_machines/pay_already_paid_invoice_returns_not_payable
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        invoice_id = env["invoice"]["id"]
        own = make_subscriber_headers(env["subscriber"]["id"])
        paid = validate_success(api.pay_invoice(invoice_id, own))
        assert paid["status"] == "PAID"
        resp = api.pay_invoice(invoice_id, own)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE)
        invoice = get_invoice(invoice_id)
        assert invoice["status"] == "PAID"
        assert invoice["total_cents"] == 1100

    def test_standing_flips_on_overdue_and_recovers_on_pay(self, api):
        """PRD §3.9: "A subscriber is `DELINQUENT` whenever any of their
        invoices stands `ISSUED` with a `due_date` earlier than the current
        logical date, and `GOOD_STANDING` otherwise; the value is derived on
        read, never stored."
        PRD §3.9: "the subscriber's standing then recomputes on the next read
        because this invoice no longer counts as overdue."

        Design: Corner/calculations/account_standing_flips_on_overdue_and_recovers_on_pay
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        sub_id = env["subscriber"]["id"]
        set_clock("2026-05-19T00:00:00Z")  # one day past the 2026-05-18 due date
        assert get_subscriber(sub_id)["account_standing"] == "DELINQUENT"
        validate_success(
            api.pay_invoice(env["invoice"]["id"], make_subscriber_headers(sub_id))
        )
        assert get_subscriber(sub_id)["account_standing"] == "GOOD_STANDING"

    def test_invoice_immediately_readable_with_final_totals(self, api):
        """PRD §3.9: "The invoice's `due_date` is fourteen days after the
        `week_start_date`, and the invoice is born `ISSUED`." PRD §3.9: "the
        run's response carries the `issued_count`, the list of `invoice_ids`,
        and that `skipped_subscriber_ids` list. Invoices are browsable through
        a list endpoint with optional filters on `subscriber_id` and `status`,
        and individual invoices can be read."

        Design: Corner/consistency_model/immediate_consistency_invoice_visible_in_same_epoch
        """
        env = setup_completed_pickup(service_date="2026-05-04", fullness_pct=0.5)
        run = run_billing("2026-05-04")
        assert run["issued_count"] == 1
        invoice_id = run["invoice_ids"][0]
        invoice = get_invoice(invoice_id)
        assert_invoice(invoice)
        assert invoice["status"] == "ISSUED"
        assert invoice["subtotal_cents"] == 1200
        assert invoice["credit_applied_cents"] == 100
        assert invoice["total_cents"] == 1100
        assert invoice["due_date"] == "2026-05-18"
