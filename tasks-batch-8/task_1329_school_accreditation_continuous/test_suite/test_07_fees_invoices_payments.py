"""Fees, invoices, and payments: tiered annual fee, visit-fee settlement,
payment balance conservation, fiscal violations, invoice OCC (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_reported_visit,
    api_client,
    create_annual_invoice,
    create_assignment_payload,
    create_campus,
    create_fee_schedule,
    create_invoice_payload,
    create_payment_payload,
    create_reviewer,
    create_system,
    create_visit_payload,
    get_success_data,
    post_payment,
    set_clock,
    setup_self_study_term,
    validate_error,
    validate_success,
    walk_term_to_review,
)

OFFICER = TEST_USERS["officer_headers"]
BURSAR = TEST_USERS["bursar_headers"]


class TestAnnualFeeTieredComposition:
    def test_boundary_enrollment_bills_at_large_rate(self, api):
        """PRD §3.8: "For an `ANNUAL_FEE` invoice, the billable campus count is
        the number of the system's campuses with `campus_status` of `IN_SCOPE`.
        Those with `enrollment` at or above the schedule's
        `large_campus_threshold` are billed at `large_campus_fee_cents` each;
        the remainder at `per_campus_fee_cents` each; the
        `base_system_fee_cents` is added once."

        Design: Difficulty/combinatorial_formula/annual_fee_tiered_composition_with_credit
        """
        create_fee_schedule()
        system = create_system(name="Tiered County", system_type="DISTRICT")
        for name, enrollment in (("Small Campus", 999), ("Boundary Campus", 1000),
                                 ("Large Campus", 1500)):
            create_campus(system["id"], name=name, enrollment=enrollment)

        invoice = create_annual_invoice(system["id"], billing_year=2026)
        # 999 < 1000 -> small; 1000 >= 1000 -> large (boundary); 1500 -> large.
        # 500000 + 1*120000 + 2*200000 = 1020000
        assert invoice["amount_cents"] == 1020000
        assert invoice["status"] == "ISSUED"

    def test_out_of_scope_campus_excluded_from_billable_count(self, api,
                                                              officer_headers):
        """PRD §3.8: "For an `ANNUAL_FEE` invoice, the billable campus count is
        the number of the system's campuses with `campus_status` of `IN_SCOPE`."
        PRD §3.1: "A campus with `campus_status` of `OUT_OF_SCOPE` or
        `WITHDRAWN` is excluded from composite and billing counts."

        Design: Difficulty/combinatorial_formula/annual_fee_tiered_composition_with_credit
        """
        create_fee_schedule()
        system = create_system(name="Tiered County B", system_type="DISTRICT")
        small = create_campus(system["id"], name="Small Campus", enrollment=999)
        create_campus(system["id"], name="Boundary Campus", enrollment=1000)
        create_campus(system["id"], name="Large Campus", enrollment=1500)
        get_success_data(api_client.scope_out_campus(small["id"], officer_headers))

        invoice = create_annual_invoice(system["id"], billing_year=2026)
        # billable = the two large campuses only: 500000 + 2*200000 = 900000
        assert invoice["amount_cents"] == 900000


class TestVisitFeeFinalSettlement:
    def _ctx_in_review_with_issued_visit(self):
        """REVIEW term with V1 (3 days) fully reported, V2 (2 days) requested."""
        create_fee_schedule()
        ctx = setup_self_study_term(system_name="Pine Valley Schools",
                                    system_type="DISTRICT",
                                    campuses=[("Pine Campus", 400)])
        walk_term_to_review(ctx)
        add_reported_visit(ctx, starts_on="2027-03-01T00:00:00Z",
                           ends_on="2027-03-04T00:00:00Z",
                           severity="RECOMMENDATION",
                           narrative="Strengthen distributed leadership.")
        rev_2 = create_reviewer(full_name="Vic Reviewer", email="vic@accreditor.org")
        visit_2 = get_success_data(api_client.create_visit(
            ctx["term"]["id"],
            create_visit_payload(rev_2["id"],
                                 campus_id=ctx["campuses"][0]["id"],
                                 starts_on="2027-04-10T00:00:00Z",
                                 ends_on="2027-04-12T00:00:00Z"),
            OFFICER))
        get_success_data(api_client.create_visit_assignment(
            visit_2["id"],
            create_assignment_payload(rev_2["id"], role_on_team="CHAIR"), OFFICER))
        get_success_data(api_client.confirm_visit(visit_2["id"], OFFICER))
        return ctx, visit_2

    def test_final_settlement_counts_only_report_issued_visits(self, api):
        """PRD §3.8: "the final settlement invoice, issued after a report is
        issued, counts visits in `REPORT_ISSUED` only, and the earlier
        provisional projection is discarded."
        PRD §3.8: "for each visit under the term whose status is one of
        `CONFIRMED`, `IN_FIELD`, `REPORT_DRAFT`, or `REPORT_ISSUED`, the
        whole-day difference between the exclusive `ends_on` and the inclusive
        `starts_on` is summed."

        Design: Difficulty/dual_variant_calc/visit_fee_provisional_vs_final_settlement
        """
        ctx, visit_2 = self._ctx_in_review_with_issued_visit()
        # V1 REPORT_ISSUED spans 2027-03-01..2027-03-04 = 3 days; V2 still
        # CONFIRMED (2 days) and must be excluded from the final settlement.
        resp = api_client.create_invoice(
            ctx["system"]["id"],
            create_invoice_payload(billing_year=2027, invoice_type="VISIT_FEE"),
            BURSAR)
        invoice = validate_success(resp, expected_status=201)
        assert invoice["amount_cents"] == 225000  # 3 days * 75000
        assert invoice["invoice_type"] == "VISIT_FEE"
        assert invoice["status"] == "ISSUED"

    def test_final_settlement_excludes_report_draft_visit_days(self, api):
        """PRD §3.8: "the final settlement invoice, issued after a report is
        issued, counts visits in `REPORT_ISSUED` only, and the earlier
        provisional projection is discarded."

        Design: Difficulty/dual_variant_calc/visit_fee_provisional_vs_final_settlement
        """
        ctx, visit_2 = self._ctx_in_review_with_issued_visit()
        # Drive V2 CONFIRMED -> IN_FIELD -> REPORT_DRAFT via the clock; its 2
        # days must still be excluded because no report has been issued for it.
        set_clock("2027-04-10T00:00:00Z")
        set_clock("2027-04-12T00:00:00Z")
        v2_after = get_success_data(api_client.get_visit(visit_2["id"], OFFICER))
        assert v2_after["status"] == "REPORT_DRAFT"

        resp = api_client.create_invoice(
            ctx["system"]["id"],
            create_invoice_payload(billing_year=2027, invoice_type="VISIT_FEE"),
            BURSAR)
        invoice = validate_success(resp, expected_status=201)
        assert invoice["amount_cents"] == 225000  # still only V1's 3 days


class TestPaymentBalanceConservation:
    def test_split_payments_exactly_settle_and_terminal_lockout(self, api):
        """PRD §3.8: "a partial payment moves `ISSUED` → `PARTIALLY_PAID`;
        cumulative payments reaching exactly `amount_cents` move `ISSUED` →
        `PAID` or `PARTIALLY_PAID` → `PAID`."
        PRD §3.8: "`PAID` and `VOID` are terminal."

        Design: Difficulty/compensating_invariant/payment_overpost_then_invoice_balance_conserved
        """
        create_fee_schedule()
        system = create_system(name="Ledger County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=300)
        invoice = create_annual_invoice(system["id"], billing_year=2026)
        assert invoice["amount_cents"] == 620000

        first = validate_success(
            post_payment(invoice["id"], 300000, paid_at="2026-08-02T00:00:00Z"),
            expected_status=201)
        mid = get_success_data(api_client.get_invoice(invoice["id"], BURSAR))
        assert mid["status"] == "PARTIALLY_PAID"

        validate_success(
            post_payment(invoice["id"], 320000, paid_at="2026-08-03T00:00:00Z"),
            expected_status=201)
        settled = get_success_data(api_client.get_invoice(invoice["id"], BURSAR))
        assert settled["status"] == "PAID"

        payments = get_success_data(api_client.list_payments(invoice["id"], BURSAR))
        assert sum(p["amount_cents"] for p in payments) == 620000 == settled["amount_cents"]

        # Terminal lockdown: even a 1-cent further payment is inadmissible.
        resp = post_payment(invoice["id"], 1, paid_at="2026-08-04T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_single_exact_payment_settles_from_issued(self, api):
        """PRD §3.8: "cumulative payments reaching exactly `amount_cents` move
        `ISSUED` → `PAID` or `PARTIALLY_PAID` → `PAID`."
        PRD §3.8: "`PAID` and `VOID` are terminal."

        Design: Difficulty/compensating_invariant/payment_overpost_then_invoice_balance_conserved
        """
        create_fee_schedule()
        system = create_system(name="Ledger County B", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=300)
        invoice = create_annual_invoice(system["id"], billing_year=2026)

        validate_success(
            post_payment(invoice["id"], 620000, paid_at="2026-08-02T00:00:00Z"),
            expected_status=201)
        settled = get_success_data(api_client.get_invoice(invoice["id"], BURSAR))
        assert settled["status"] == "PAID"

        payments = get_success_data(api_client.list_payments(invoice["id"], BURSAR))
        assert len(payments) == 1
        assert payments[0]["amount_cents"] == 620000 == settled["amount_cents"]

        resp = post_payment(invoice["id"], 1, paid_at="2026-08-04T00:00:00Z")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestInvoiceStateAndFiscalRules:
    def test_void_on_paid_invoice_rejected(self, api, bursar_headers):
        """PRD §3.8: "An officer of the bursar's office may void an invoice
        (`ISSUED` → `VOID`) only when no payment rows exist for it. `PAID` and
        `VOID` are terminal."

        Design: Corner/state_machines/terminal_state_lockdown_invoice_paid
        """
        create_fee_schedule()
        system = create_system(name="Paid County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        invoice = create_annual_invoice(system["id"], billing_year=2026)
        validate_success(
            post_payment(invoice["id"], invoice["amount_cents"],
                         paid_at="2026-08-02T00:00:00Z"),
            expected_status=201)
        resp = api_client.void_invoice(invoice["id"], bursar_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_overpayment_rejected(self, api):
        """PRD §3.8: "A payment that exceeds the invoice's outstanding balance
        is rejected with `ERR_FISCAL_VIOLATION`."

        Design: Corner/validations/fiscal_violation_overpayment_rejected
        """
        create_fee_schedule()
        system = create_system(name="Fiscal County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        invoice = create_annual_invoice(system["id"], billing_year=2026)
        assert invoice["amount_cents"] == 620000

        payload = create_payment_payload(620001, invoice["version"],
                                         paid_at="2026-08-02T00:00:00Z")
        resp = api_client.create_payment(invoice["id"], payload, BURSAR)
        validate_error(resp, ApiErrorId.ERR_FISCAL_VIOLATION)

    def test_stale_invoice_version_rejected(self, api):
        """PRD §2.6: "Posting a `Payment` against an invoice requires the request
        body to carry `expected_invoice_version`, the client-observed `version`
        of the target `Invoice`. If the invoice's current `version` has advanced
        — because another payment changed its outstanding balance and status —
        the post is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_invoice_version_on_payment
        """
        create_fee_schedule()
        system = create_system(name="OCC Fiscal", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        invoice = create_annual_invoice(system["id"], billing_year=2026)
        stale_version = invoice["version"]

        first = create_payment_payload(300000, stale_version,
                                       paid_at="2026-08-02T00:00:00Z")
        validate_success(api_client.create_payment(invoice["id"], first, BURSAR),
                         expected_status=201)

        # The first payment advanced the invoice version; replaying the stale
        # token must be rejected.
        second = create_payment_payload(320000, stale_version,
                                        paid_at="2026-08-03T00:00:00Z")
        resp = api_client.create_payment(invoice["id"], second, BURSAR)
        validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION)
