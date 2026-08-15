"""Direct-bill invoicing: the ingestion fork, per-day rounding, audit decisions,
the dispute cascade, and settlement reconciliation."""
import pytest

from test_helpers import (
    ADJUSTER,
    DESK,
    NON_EXISTENT_UUID,
    RECOVERY,
    SETTLEMENT,
    ApiErrorId,
    api_client,
    assert_invoice,
    assert_recovery_case,
    get_claim_view,
    get_reservation_view,
    list_claim_communications,
    list_claim_recovery_cases,
    make_rental_partner_headers,
    setup_auto_approved_invoice_scenario,
    setup_manual_review_invoice_scenario,
    setup_returned_rental_scenario,
    submit_invoice,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInvoiceSubmission:
    def test_duplicate_invoice_number_rejected(self, api):
        """PRD §3.8: "the invoice number must be unique among that partner's
        invoices (`ERR_DUPLICATE_INVOICE_NUMBER`)"

        Design: Corner/validations/duplicate_invoice_number_rejected
        """
        ctx = setup_auto_approved_invoice_scenario(
            invoice_overrides={"fees_cents": 0})
        resp = api.create_invoice(
            {"reservation_id": ctx["reservation"]["id"],
             "invoice_number": "INV-CLEAN",
             "period_start": "2026-08-05", "period_end": "2026-08-16",
             "daily_rate_cents": 6000, "tax_cents": 4800, "fees_cents": 0},
            make_rental_partner_headers(ctx["partner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER)

    def test_invoice_not_found_rejected(self, api):
        """PRD §2.8: "Each resource type has its own not-found error:
        `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
        `ERR_COVERAGE_VERIFICATION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`,
        `ERR_RENTAL_PARTNER_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`,
        `ERR_MILESTONE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
        `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, and `ERR_RECOVERY_CASE_NOT_FOUND`."

        Design: Corner/errors/invoice_not_found_rejected
        """
        resp = api.settle_invoice(NON_EXISTENT_UUID, SETTLEMENT)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)

    def test_subresource_invoices_listed(self, api):
        """PRD §3.8: "Invoices can be listed per reservation, and the global
        invoice collection accepts an optional `rental_partner_id` filter."

        Design: Corner/endpoints/subresource_invoices_listed
        """
        ctx = setup_auto_approved_invoice_scenario(
            invoice_overrides={"fees_cents": 0})
        listed, meta = validate_paginated(api.list_reservation_invoices(
            ctx["reservation"]["id"], ADJUSTER))
        assert meta["total_count"] == 1
        assert listed[0]["invoice_number"] == "INV-CLEAN"
        assert listed[0]["status"] == "AUTO_APPROVED"


class TestInvoiceSettlementSegregation:
    def test_adjuster_cannot_settle_invoice_forbidden(self, api):
        """PRD §2.9: "The `ClaimsAdjuster` opens claims, verifies coverage,
        approves repair estimates, decides extensions and loss-of-use claims, and
        audits invoices — but can never release money. The `SettlementApprover`
        settles invoices, pays approved loss-of-use claims, and settles and closes
        claims — but can never verify coverage or audit an invoice."
        PRD §2.1: "A caller whose role is not on an endpoint's authorized list is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/adjuster_cannot_settle_invoice_forbidden
        """
        ctx = setup_auto_approved_invoice_scenario(
            invoice_overrides={"fees_cents": 0})
        resp = api.settle_invoice(ctx["invoice"]["id"], ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_invoice_settle_reconciles_reserve(self, api):
        """PRD §3.8: "On settlement the claim's `rental_reserve_cents` is debited
        by the `audited_payable_cents` — the reserve's estimate term shrinks as
        the settled-actuals term grows, per §2.6 — the reservation's
        `audited_charge_cents` accumulates the same amount with its `version`
        incrementing, the claim's `version` increments, and the invoice lands in
        its terminal `SETTLED` state."
        PRD §2.6: "Second, recording a vehicle return moves the reservation out of
        the estimate term entirely, and settling an invoice moves that same
        exposure into the settled term — the money is never double-counted or
        lost, only reclassified."

        Design: Corner/cross_cutting_complexity/invoice_settle_reconciles_reserve
        """
        ctx = setup_auto_approved_invoice_scenario()  # audited 66800
        assert get_claim_view(ctx["claim"]["id"])["rental_reserve_cents"] == 120000, (
            "The return must have released the 60000 provisional estimate"
        )
        resp = api.settle_invoice(ctx["invoice"]["id"], SETTLEMENT)
        settled = validate_success(resp, 200)
        assert settled["status"] == "SETTLED"
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["rental_reserve_cents"] == 53200, (
            f"Expected reserve 120000 - 66800 = 53200 after settlement, "
            f"got {claim['rental_reserve_cents']}"
        )
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["audited_charge_cents"] == 66800


class TestInvoiceForkJoin:
    def _setup_fork(self):
        ctx = setup_returned_rental_scenario()
        clean = submit_invoice(ctx["reservation"]["id"], ctx["partner"]["id"],
                               "INV-CLEAN", period_start="2026-08-05",
                               period_end="2026-08-15", daily_rate_cents=6000,
                               tax_cents=4800, fees_cents=2000)
        wide = submit_invoice(ctx["reservation"]["id"], ctx["partner"]["id"],
                              "INV-WIDE", period_start="2026-08-05",
                              period_end="2026-08-17", daily_rate_cents=6000,
                              tax_cents=5280, fees_cents=0)
        ctx.update(clean_invoice=clean, wide_invoice=wide)
        return ctx

    def test_clean_invoice_auto_approved_at_ingestion(self, api):
        """PRD §3.8: "Every invoice forks automatically at ingestion; there is no
        human in the loop for the fork itself."
        PRD §3.8: "An auto-approved invoice is priced immediately: its
        `audited_payable_cents` is set at ingestion to the audited final amount,
        which for an invoice passing all five criteria equals the submitted
        total."

        Design: Difficulty/non_linear_state_machine/invoice_fork_join_divergent_branches
        """
        ctx = self._setup_fork()
        clean = ctx["clean_invoice"]
        assert_invoice(clean)
        assert clean["status"] == "AUTO_APPROVED", (
            f"A clean invoice must auto-adjudicate; got {clean['status']}"
        )
        assert clean["audited_payable_cents"] == 66800, (
            f"Expected submitted total 60000 + 4800 + 2000 == 66800, "
            f"got {clean['audited_payable_cents']}"
        )

    def test_over_window_invoice_dispute_spawns_recovery(self, api):
        """PRD §3.8: "The invoice's `unauthorized_days` is the billed period's
        total day count minus the window's day count, never below zero."
        PRD §3.8: "`DISPUTE_UNNECESSARY_DAYS` instead moves the invoice to
        `DISPUTED` and opens a recovery case on the spot: the case's `source` is
        `INVOICE_DISPUTE`, its `unnecessary_days` is the invoice's
        `unauthorized_days`, and its `assessed_amount_cents` is those days
        multiplied by the lesser of the invoice's billed `daily_rate_cents` and
        the claim's `coverage_daily_limit_cents`."

        Design: Difficulty/non_linear_state_machine/invoice_fork_join_divergent_branches
        """
        ctx = self._setup_fork()
        wide = ctx["wide_invoice"]
        assert wide["status"] == "MANUAL_REVIEW"
        assert wide["unauthorized_days"] == 2, (
            f"Expected 2 unauthorized days for 12 billed vs 10 authorized, "
            f"got {wide['unauthorized_days']}"
        )

        resp = api.decide_invoice_audit(wide["id"],
                                        {"decision": "DISPUTE_UNNECESSARY_DAYS"},
                                        ADJUSTER)
        disputed = validate_success(resp, 200)
        assert disputed["status"] == "DISPUTED"

        cases = list_claim_recovery_cases(ctx["claim"]["id"])
        assert len(cases) == 1, (
            "The DISPUTED branch must divergently spawn a RecoveryCase"
        )
        assert_recovery_case(cases[0])
        assert cases[0]["source"] == "INVOICE_DISPUTE"
        assert cases[0]["unnecessary_days"] == 2
        assert cases[0]["assessed_amount_cents"] == 12000
        assert cases[0]["status"] == "OPEN"

        # The fork's other branch joins the shared terminal state.
        settled = validate_success(
            api.settle_invoice(ctx["clean_invoice"]["id"], SETTLEMENT), 200)
        assert settled["status"] == "SETTLED"


class TestInvoicePerDayRounding:
    def _setup_rounding_scenario(self):
        """ECONOMY rate 4519; 5-day window; invoice bills the sum-then-round tax
        figure 1808 instead of the pinned per-day figure 1810."""
        ctx = setup_returned_rental_scenario(
            partner_overrides={"partner_code": "RC-R", "economy_rate_cents": 4519},
            reservation_overrides={"vehicle_class": "ECONOMY",
                                   "authorized_return_date": "2026-08-10"},
            return_clock="2026-08-10T10:00:00Z",
        )
        ctx["invoice"] = submit_invoice(
            ctx["reservation"]["id"], ctx["partner"]["id"], "INV-R1",
            period_start="2026-08-05", period_end="2026-08-10",
            daily_rate_cents=4519, tax_cents=1808, fees_cents=0)
        return ctx

    def test_per_day_rounding_audit_result(self, api):
        """PRD §3.8: "The rounding order is pinned: summing all day charges first
        and rounding the tax once at the end produces different cents and is
        explicitly not the algorithm — per-day rounding wins."

        Design: Difficulty/combinatorial_formula/invoice_audit_per_day_rounding_pinned
        """
        ctx = self._setup_rounding_scenario()
        resp = api.decide_invoice_audit(ctx["invoice"]["id"],
                                        {"decision": "ADJUST_TO_AUTHORIZED"},
                                        ADJUSTER)
        audited = validate_success(resp, 200)
        assert audited["audited_payable_cents"] == 24405, (
            f"Per-day rounding must yield 5 x (4519 + 362) == 24405, "
            f"got {audited['audited_payable_cents']}"
        )
        assert audited["audited_payable_cents"] != 24403, (
            "The sum-then-round result 24403 is explicitly not the algorithm"
        )

    def test_sum_then_round_tax_routes_manual_review(self, api):
        """PRD §3.8: "An invoice is auto-adjudicated to `AUTO_APPROVED` if and
        only if all five criteria hold: ... and the billed `tax_cents` equals
        exactly the sum over the billed period's days of each day's tax, where a
        day's tax is the lesser of the billed rate and the claim's
        `coverage_daily_limit_cents`, multiplied by an 8 percent tax rate, rounded
        half up to a whole cent per day before summation. Any criterion failing
        routes the invoice to `MANUAL_REVIEW` instead, and the system computes its
        `unauthorized_days`."

        Design: Difficulty/combinatorial_formula/invoice_audit_per_day_rounding_pinned
        """
        ctx = self._setup_rounding_scenario()
        invoice = ctx["invoice"]
        assert invoice["status"] == "MANUAL_REVIEW", (
            f"Submitted tax 1808 != per-day-rounded 1810 must route to "
            f"MANUAL_REVIEW; got {invoice['status']}"
        )
        assert invoice["unauthorized_days"] == 0


class TestInvoiceRateAtLimit:
    def _setup_limit_scenario(self):
        """Partner whose ECONOMY rate equals the claim's 6000 daily limit."""
        return setup_returned_rental_scenario(
            partner_overrides={"partner_code": "RC-L", "economy_rate_cents": 6000},
            reservation_overrides={"vehicle_class": "ECONOMY",
                                   "authorized_return_date": "2026-08-10"},
            return_clock="2026-08-10T10:00:00Z",
        )

    def test_rate_equal_to_limit_fully_payable(self, api):
        """PRD §3.8: "Each calendar day inside the window is then priced in
        chronological order: the day's rate is read from the immutable
        `rate_card_snapshot` for the vehicle class in effect on that day — a class
        change with a given `effective_date` applies to every day on or after that
        date until the next change takes over — the day's charge is the lesser of
        that rate and the claim's `coverage_daily_limit_cents`, and the day's tax
        is that charge multiplied by 8 percent, rounded half up to a whole cent
        immediately, before any summation."

        Design: Difficulty/boundary_precision_check/invoice_rate_at_limit_exactly_payable
        """
        ctx = self._setup_limit_scenario()
        resp = api.create_invoice(
            {"reservation_id": ctx["reservation"]["id"],
             "invoice_number": "INV-EQ",
             "period_start": "2026-08-05", "period_end": "2026-08-10",
             "daily_rate_cents": 6000, "tax_cents": 2400, "fees_cents": 0},
            make_rental_partner_headers(ctx["partner"]["id"]),
        )
        invoice = validate_success(resp, 201)
        assert invoice["status"] == "AUTO_APPROVED", (
            f"A rate exactly at the limit must keep the whole rate payable; "
            f"got {invoice['status']}"
        )
        assert invoice["audited_payable_cents"] == 32400, (
            f"Expected 5 x (6000 + 480) == 32400, "
            f"got {invoice['audited_payable_cents']}"
        )

    def test_rate_one_cent_over_limit_audited_down(self, api):
        """PRD §3.8: "the day's rate is read from the immutable
        `rate_card_snapshot` for the vehicle class in effect on that day ... the
        day's charge is the lesser of that rate and the claim's
        `coverage_daily_limit_cents`"
        PRD §3.8: "the billed `daily_rate_cents` equals the reservation's
        currently applicable rate" is one of the five auto-adjudication criteria,
        so a mismatched billed rate routes to `MANUAL_REVIEW`.

        Design: Difficulty/boundary_precision_check/invoice_rate_at_limit_exactly_payable
        """
        ctx = self._setup_limit_scenario()
        resp = api.create_invoice(
            {"reservation_id": ctx["reservation"]["id"],
             "invoice_number": "INV-GT",
             "period_start": "2026-08-05", "period_end": "2026-08-10",
             "daily_rate_cents": 6001, "tax_cents": 2401, "fees_cents": 0},
            make_rental_partner_headers(ctx["partner"]["id"]),
        )
        invoice = validate_success(resp, 201)
        assert invoice["status"] == "MANUAL_REVIEW", (
            f"Billed rate 6001 != snapshot 6000 must force MANUAL_REVIEW; "
            f"got {invoice['status']}"
        )
        audited = validate_success(
            api.decide_invoice_audit(invoice["id"],
                                     {"decision": "ADJUST_TO_AUTHORIZED"},
                                     ADJUSTER),
            200,
        )
        assert audited["audited_payable_cents"] == 32400, (
            f"The +1 cent buys nothing: the audit re-prices from the snapshot "
            f"at min(6000, limit) per day; got {audited['audited_payable_cents']}"
        )


class TestAuditDisputeCascade:
    def test_dispute_creates_recovery_case(self, api):
        """PRD §3.8: "`DISPUTE_UNNECESSARY_DAYS` instead moves the invoice to
        `DISPUTED` and opens a recovery case on the spot: the case's `source` is
        `INVOICE_DISPUTE`, its `unnecessary_days` is the invoice's
        `unauthorized_days`, and its `assessed_amount_cents` is those days
        multiplied by the lesser of the invoice's billed `daily_rate_cents` and
        the claim's `coverage_daily_limit_cents`."

        Design: Difficulty/transitive_cascade/audit_dispute_cascade_to_recovery_balance
        """
        ctx = setup_manual_review_invoice_scenario()
        resp = api.decide_invoice_audit(ctx["invoice"]["id"],
                                        {"decision": "DISPUTE_UNNECESSARY_DAYS"},
                                        ADJUSTER)
        disputed = validate_success(resp, 200)
        assert disputed["status"] == "DISPUTED"

        cases = list_claim_recovery_cases(ctx["claim"]["id"])
        assert len(cases) == 1
        case = cases[0]
        assert_recovery_case(case)
        assert case["source"] == "INVOICE_DISPUTE"
        assert case["unnecessary_days"] == 2
        assert case["assessed_amount_cents"] == 12000, (
            f"Expected 2 x min(6000, 6000) == 12000, "
            f"got {case['assessed_amount_cents']}"
        )
        assert case["status"] == "OPEN"

    def test_dispute_raises_recovery_balance_and_logs_notice(self, api):
        """PRD §3.8: "The dispute also raises the claim's `recovery_balance_cents`
        by the assessed amount, increments the claim's `version`, and auto-logs a
        customer communication with template `RECOVERY_NOTICE`."

        Design: Difficulty/transitive_cascade/audit_dispute_cascade_to_recovery_balance
        """
        ctx = setup_manual_review_invoice_scenario()
        validate_success(
            api.decide_invoice_audit(ctx["invoice"]["id"],
                                     {"decision": "DISPUTE_UNNECESSARY_DAYS"},
                                     ADJUSTER),
            200,
        )
        claim = get_claim_view(ctx["claim"]["id"])
        assert claim["recovery_balance_cents"] == 12000, (
            f"The case creation must raise the claim recovery balance to 12000, "
            f"got {claim['recovery_balance_cents']}"
        )
        logs = list_claim_communications(ctx["claim"]["id"])
        assert any(log["template"] == "RECOVERY_NOTICE" for log in logs), (
            "The dispute must auto-log a RECOVERY_NOTICE communication"
        )
