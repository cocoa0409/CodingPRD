"""Client billing: dual visit-billing variants, pinned per-line rounding
order, invoice input-set filtering, rework zero-billing conservation, OCC on
finalize, and invoice lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_rework_loop,
    create_client,
    create_invoice,
    create_project,
    file_exception,
    finalize_invoice,
    get_invoice_for_project,
    get_project,
    make_scenario,
    validate_error,
    validate_success,
    verify_visit,
    visit_store,
    void_invoice,
)

PM = TEST_USERS["pm_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestVisitBillingVariants:
    def test_visit_billing_per_store_vs_hourly_same_duration(self, api):
        """PRD 3.7: "Under `PER_STORE`, a verified non-rework visit bills the
        client's flat `per_store_rate_cents` regardless of how long the rep was
        on site. Under `HOURLY`, a verified non-rework visit bills the on-site
        time prorated against the negotiated rate: the visit's
        `on_site_minutes` multiplied by the client's `hourly_rate_cents`,
        divided by 60, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/visit_billing_per_store_vs_hourly
        """
        scn_ps = make_scenario(
            client_overrides={"name": "PerStore Client", "billing_model": "PER_STORE",
                              "per_store_rate_cents": 3500},
        )
        scn_hr = make_scenario(
            client_overrides={"name": "Hourly Client", "billing_model": "HOURLY",
                              "hourly_rate_cents": 4200},
        )
        asg_ps, visit_ps = visit_store(
            scn_ps,
            window=("2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T10:00:00Z", "2026-08-05T11:35:00Z"),
        )
        asg_hr, visit_hr = visit_store(
            scn_hr,
            window=("2026-08-06T09:00:00Z", "2026-08-06T12:00:00Z"),
            on_site=("2026-08-06T10:00:00Z", "2026-08-06T11:35:00Z"),
        )
        billed_ps = validate_success(api.verify_store_visit(visit_ps["id"], PM))
        billed_hr = validate_success(api.verify_store_visit(visit_hr["id"], PM))
        assert billed_ps["on_site_minutes"] == 95
        assert billed_hr["on_site_minutes"] == 95
        assert billed_ps["billable_amount_cents"] == 3500, (
            f"PER_STORE bills the flat 3500, got {billed_ps['billable_amount_cents']}"
        )
        assert billed_hr["billable_amount_cents"] == 6650, (
            f"HOURLY: round_half_up(95 * 4200 / 60) = 6650, "
            f"got {billed_hr['billable_amount_cents']}"
        )
        assert billed_ps["billable_amount_cents"] != billed_hr["billable_amount_cents"]

    def test_per_store_billing_independent_of_duration(self, api):
        """PRD 3.7: "Two visits of different durations therefore bill different
        amounts under `HOURLY` but identical amounts under `PER_STORE`."

        Design: Difficulty/dual_variant_calc/visit_billing_per_store_vs_hourly
        """
        scn = make_scenario(num_stores=2)  # PER_STORE, 3500 flat
        asg_1, visit_1 = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:35:00Z"),  # 30 min
        )
        asg_2, visit_2 = visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T11:35:00Z"),  # 90 min
        )
        v1 = validate_success(api.verify_store_visit(visit_1["id"], PM))
        v2 = validate_success(api.verify_store_visit(visit_2["id"], PM))
        assert v1["on_site_minutes"] == 30
        assert v2["on_site_minutes"] == 90
        assert v1["billable_amount_cents"] == 3500
        assert v2["billable_amount_cents"] == 3500, (
            "PER_STORE billing is duration-independent"
        )


class TestInvoiceRoundingOrder:
    def test_invoice_line_total_sums_per_visit_rounded_amounts(self, api):
        """PRD 3.7: "The line total is an exact integer sum: the
        `billable_amount_cents` of every visit of the project whose
        `verification_status` is `VERIFIED` — `REJECTED` and `PENDING_REVIEW`
        visits are excluded, and rework visits contribute their 0. Because each
        line was already rounded to whole cents at verification, the sum is
        never re-rounded."
        PRD 2.7: "Rounding is pinned, not opportunistic: where a calculation
        produces a fractional cent, the rule is round-half-up to a whole cent,
        applied exactly at the point each calculation specifies, and never
        re-applied to figures that were already rounded upstream."

        Design: Difficulty/combinatorial_formula/invoice_total_line_level_rounding_order
        """
        scn = make_scenario(
            num_stores=2,
            client_overrides={"name": "Round Client", "billing_model": "HOURLY",
                              "hourly_rate_cents": 4199},
        )
        asg_1, visit_1 = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            on_site=("2026-08-05T09:10:00Z", "2026-08-05T09:20:00Z"),  # 10 min
        )
        asg_2, visit_2 = visit_store(
            scn, store_idx=1,
            window=("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T11:00:00Z", "2026-08-05T11:25:00Z"),  # 25 min
        )
        v1 = validate_success(api.verify_store_visit(visit_1["id"], PM))
        v2 = validate_success(api.verify_store_visit(visit_2["id"], PM))
        assert v1["billable_amount_cents"] == 700, (
            f"round_half_up(10 * 4199 / 60) = 700, got {v1['billable_amount_cents']}"
        )
        assert v2["billable_amount_cents"] == 1750, (
            f"round_half_up(25 * 4199 / 60) = 1750, got {v2['billable_amount_cents']}"
        )
        invoice = get_invoice_for_project(scn["project"]["id"])
        assert invoice["line_total_cents"] == 2450, (
            f"per-line round then sum: 700 + 1750 = 2450 (sum-then-round would "
            f"give 2449), got {invoice['line_total_cents']}"
        )

    def test_open_invoice_line_total_recomputed_on_later_verify(self, api):
        """PRD 3.7: "A `BillingClerk` may create an `OPEN` invoice manually
        with `client_id`, `project_id`, and an optional `adjustment_cents`
        (defaulting to 0); the invoice's `line_total_cents` is computed at
        creation from currently verified visits." and "While an invoice is
        `OPEN`, any further visit verification on the project recomputes
        `line_total_cents`."

        Design: Difficulty/combinatorial_formula/invoice_total_line_level_rounding_order
        """
        scn = make_scenario(
            num_stores=2,
            client_overrides={"name": "Round Client", "billing_model": "HOURLY",
                              "hourly_rate_cents": 4199},
        )
        asg_1, visit_1 = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            on_site=("2026-08-05T09:10:00Z", "2026-08-05T09:20:00Z"),
        )
        verify_visit(visit_1["id"])
        invoice = create_invoice(scn["client"]["id"], scn["project"]["id"])
        assert invoice["line_total_cents"] == 700, (
            f"manual invoice opens with the one VERIFIED visit: 700, "
            f"got {invoice['line_total_cents']}"
        )
        asg_2, visit_2 = visit_store(
            scn, store_idx=1,
            window=("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T11:00:00Z", "2026-08-05T11:25:00Z"),
        )
        verify_visit(visit_2["id"])
        after = validate_success(api.get_invoice(invoice["id"], BC))
        assert after["line_total_cents"] == 2450, (
            f"recompute while OPEN folds in the second verified visit: 2450, "
            f"got {after['line_total_cents']}"
        )


class TestReworkZeroBillingConservation:
    def test_rework_verify_adds_zero_to_invoice_line_total(self, api):
        """PRD 3.7: "A rework visit bills at exactly 0 —
        `billable_amount_cents` is 0 whenever `is_rework` is true, and stays
        unset while the visit awaits review."
        PRD 3.7: "The line total is an exact integer sum: the
        `billable_amount_cents` of every visit of the project whose
        `verification_status` is `VERIFIED` — `REJECTED` and `PENDING_REVIEW`
        visits are excluded, and rework visits contribute their 0."

        Design: Difficulty/compensating_invariant/invoice_total_conserved_under_verify_then_rework_zero_billing
        """
        scn = make_scenario(num_stores=2, scope_type="RESET")
        # store 1: initial visit rejected (no billing), store 2: verified 3500
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:55:00Z"),
            outcome="reject",
        )
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:55:00Z"),
            outcome="verify",
        )
        # rework loop on store 1; the rework visit verifies at 0
        auth, rework_asg, rework_visit = complete_rework_loop(
            scn, store_idx=0,
            window=("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"),
            on_site=("2026-08-06T09:05:00Z", "2026-08-06T09:55:00Z"),
        )
        assert rework_visit["is_rework"] is True
        resp = api.verify_store_visit(rework_visit["id"], PM)
        verified_rw = validate_success(resp)
        assert verified_rw["billable_amount_cents"] == 0, (
            f"rework visit must bill 0, got {verified_rw['billable_amount_cents']}"
        )
        project = get_project(scn["project"]["id"])
        assert project["status"] == "RECONCILING"
        invoice = get_invoice_for_project(scn["project"]["id"])
        assert invoice["line_total_cents"] == 3500, (
            f"reject + rework-verify round trip adds exactly 0; only the "
            f"non-rework verified visit contributes, got "
            f"{invoice['line_total_cents']}"
        )

    def test_finalize_after_rework_loop_bills_only_non_rework_visit(self, api):
        """PRD 3.7: "On finalization the invoice's `line_total_cents` is
        recomputed, its `grand_total_cents` — unset while the invoice is
        `OPEN` — is set to the line total plus the adjustment, the invoice
        moves to `FINALIZED`, the project cascades `RECONCILING` to
        `COMPLETED`, and both the invoice's and the project's versions
        increment."

        Design: Difficulty/compensating_invariant/invoice_total_conserved_under_verify_then_rework_zero_billing
        """
        scn = make_scenario(num_stores=2, scope_type="RESET")
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:55:00Z"),
            outcome="reject",
        )
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:55:00Z"),
            outcome="verify",
        )
        auth, rework_asg, rework_visit = complete_rework_loop(
            scn, store_idx=0,
            window=("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"),
            on_site=("2026-08-06T09:05:00Z", "2026-08-06T09:55:00Z"),
        )
        verify_visit(rework_visit["id"])
        invoice = get_invoice_for_project(scn["project"]["id"])
        finalized = finalize_invoice(invoice["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["grand_total_cents"] == 3500, (
            f"grand total = line total 3500 + adjustment 0, got "
            f"{finalized['grand_total_cents']}"
        )
        project = get_project(scn["project"]["id"])
        assert project["status"] == "COMPLETED", (
            f"finalizing cascades project RECONCILING -> COMPLETED, "
            f"got {project['status']}"
        )


class TestInvoiceInputSet:
    def test_invoice_line_total_counts_only_verified(self, api):
        """PRD 3.7: "The line total is an exact integer sum: the
        `billable_amount_cents` of every visit of the project whose
        `verification_status` is `VERIFIED` — `REJECTED` and `PENDING_REVIEW`
        visits are excluded, and rework visits contribute their 0."
        PRD 3.7: "the invoice's `line_total_cents` is computed at creation
        from currently verified visits."

        Design: Corner/calculations/invoice_input_set_excludes_rejected_and_pending
        """
        scn = make_scenario(num_stores=3)
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:55:00Z"),
            outcome="verify",
        )
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:55:00Z"),
            outcome="reject",
        )
        asg_3, visit_3 = visit_store(
            scn, store_idx=2,
            window=("2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z"),
            on_site=("2026-08-05T12:05:00Z", "2026-08-05T12:55:00Z"),
        )
        assert visit_3["verification_status"] == "PENDING_REVIEW"
        invoice = create_invoice(scn["client"]["id"], scn["project"]["id"])
        assert invoice["line_total_cents"] == 3500, (
            f"only the VERIFIED visit counts (REJECTED and PENDING_REVIEW "
            f"excluded), got {invoice['line_total_cents']}"
        )


class TestFinalizeGate:
    def test_finalize_blocked_by_open_exception(self, api):
        """PRD 3.4: "Open exceptions are a billing blocker: while any exception
        on any visit of the project remains `OPEN`, the project's invoice
        cannot be finalized, and the attempt is rejected with
        `ERR_OPEN_EXCEPTIONS` (HTTP 409)."

        Design: Corner/validations/finalize_blocked_by_open_exception
        """
        scn = make_scenario()
        asg, visit = visit_store(scn, outcome="verify")
        file_exception(visit["id"], exception_type="VOID", sku_count=2,
                       severity="HIGH")
        invoice = get_invoice_for_project(scn["project"]["id"])
        resp = api.finalize_invoice(
            invoice["id"], {"expected_invoice_version": invoice["version"]}, BC
        )
        validate_error(resp, ApiErrorId.ERR_OPEN_EXCEPTIONS)


class TestInvoiceTerminalLockdown:
    def test_finalize_void_invoice_rejected(self, api):
        """PRD 3.7: "An `OPEN` invoice may instead be voided by a
        `BillingClerk`, moving it to `VOID`; `FINALIZED` and `VOID` are
        terminal."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/terminal_invoice_void_lockdown
        """
        client = create_client(name="Void Client")
        project = create_project(client["id"], title="Void Proj")
        invoice = create_invoice(client["id"], project["id"])
        void_invoice(invoice["id"])
        resp = api.finalize_invoice(
            invoice["id"], {"expected_invoice_version": invoice["version"]}, BC
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDuplicateInvoice:
    def test_duplicate_manual_invoice_rejected(self, api):
        """PRD 3.7: "Only one live invoice may exist per project — manual
        creation while an `OPEN` or `FINALIZED` invoice already exists for the
        project is rejected with `ERR_DUPLICATE_INVOICE` (HTTP 409)."

        Design: Corner/errors/error_duplicate_invoice_triggerable
        """
        client = create_client(name="DI Client")
        project = create_project(client["id"], title="DI Proj")
        create_invoice(client["id"], project["id"])
        resp = api.create_invoice(
            {"client_id": client["id"], "project_id": project["id"]}, BC
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE)


class TestInvoiceFinalizeOcc:
    def test_finalize_with_stale_invoice_version_rejected(self, api):
        """PRD 2.8: "Finalizing an invoice requires the request to carry
        `expected_invoice_version`, equal to the invoice's current `version`
        as the caller last observed it. If the invoice's version has advanced
        since that read — for example because a newly verified visit was folded
        into `line_total_cents` — the finalize request is rejected with
        `ERR_STALE_INVOICE_VERSION` (HTTP 412), preventing the caller from
        locking an outdated grand total."

        Design: Corner/cross_cutting_layers/occ_invoice_finalize_stale
        """
        scn = make_scenario(num_stores=2)
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:55:00Z"),
            outcome="verify",
        )
        invoice = create_invoice(scn["client"]["id"], scn["project"]["id"])
        stale_version = invoice["version"]
        # a second verification folds into line_total_cents, advancing version
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:55:00Z"),
            outcome="verify",
        )
        resp = api.finalize_invoice(
            invoice["id"], {"expected_invoice_version": stale_version}, BC
        )
        validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION)
