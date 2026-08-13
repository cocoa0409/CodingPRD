"""K-1 package lifecycle: parallel prep/delivery dimensions, generation
prerequisites, approval segregation, delivery timeliness, completion bubble-up,
reopen cascade, investor acknowledgement, and staleness at tax-year approve."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, PREPARER_USER_ID, REVIEWER_USER_ID,
    make_tax_preparer_headers, make_tax_reviewer_headers, make_investor_headers,
    create_fund, create_partner, create_tax_year, close_books, get_tax_year,
    create_allocation_run, create_and_lock_final_run, submit_tax_year_review,
    approve_tax_year, generate_k1_packages, walk_k1_to_delivered,
    setup_k1_generated, setup_k1_delivered, create_and_confirm_transfer,
    settle_transfer, set_clock, get_k1_package, get_allocation_run,
    create_k1_amendment_payload, parse_instant,
    assert_k1_package,
)
from datetime import datetime, timezone

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]
REP = TEST_USERS["investor_services_rep_headers"]

SINGLE_LP = [
    {
        "key": "lp", "legal_name": "LP", "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED", "residency_state": "CA",
        "ownership_pct_bps": 10000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
]

TWO_PARTNERS = [
    {
        "key": "p1", "legal_name": "P1", "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED", "residency_state": "CA",
        "ownership_pct_bps": 5000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
    {
        "key": "p2", "legal_name": "P2", "partner_type": "US_ENTITY",
        "partner_class": "LIMITED", "residency_state": "DE",
        "ownership_pct_bps": 5000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
]


class TestParallelPrepDeliveryDimensions:
    def test_report_bounced_moves_delivery_axis_only(self, api):
        """PRD §3.8: "A K-1 package carries two independent state dimensions.
        The `prep_status` dimension — `GENERATED`, `REVIEWED`, `APPROVED`,
        `DELIVERED`, and terminal `SUPERSEDED` — governs content approval. The
        `delivery_status` dimension — `PENDING`, `SENT`, `ACKNOWLEDGED`, and
        `BOUNCED` — governs transmission. The two move independently except
        that delivery moves both in a single transition."
        PRD §3.8: "Alternatively, an `InvestorServicesRep` may report the
        delivery as bounced with an optional `reason`, moving delivery from
        `SENT` to `BOUNCED`, and may later resend with an optional new
        `delivery_method`, moving delivery from `BOUNCED` back to `SENT` while
        refreshing `delivered_at` and recomputing `is_late`."

        Design: Difficulty/non_linear_state_machine/k1_package_parallel_prep_delivery_dimensions
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        k1 = scenario["k1"]
        assert k1["prep_status"] == "DELIVERED" and k1["delivery_status"] == "SENT"
        resp = api.report_k1_bounced(k1["id"], REP)
        bounced = validate_success(resp, 200)
        assert bounced["delivery_status"] == "BOUNCED"
        assert bounced["prep_status"] == "DELIVERED", (
            "report-bounced must leave the prep axis untouched"
        )

    def test_resend_restores_sent_and_recomputes_is_late(self, api):
        """PRD §3.8: "Alternatively, an `InvestorServicesRep` may report the
        delivery as bounced with an optional `reason`, moving delivery from
        `SENT` to `BOUNCED`, and may later resend with an optional new
        `delivery_method`, moving delivery from `BOUNCED` back to `SENT` while
        refreshing `delivered_at` and recomputing `is_late`."
        PRD §3.8: "the package is late when `delivered_at` falls strictly after
        the tax year’s `k1_delivery_deadline`, while delivery exactly at the
        deadline timestamp is on time."

        Design: Difficulty/non_linear_state_machine/k1_package_parallel_prep_delivery_dimensions
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        k1 = scenario["k1"]
        validate_success(api.report_k1_bounced(k1["id"], REP), 200)
        resp = api.resend_k1(k1["id"], REP)
        resent = validate_success(resp, 200)
        assert resent["delivery_status"] == "SENT"
        assert resent["prep_status"] == "DELIVERED"
        # default clock 2026-08-01 is strictly after the 2026-03-15 deadline
        assert resent["is_late"] is True


class TestApproveStateBeatsStaleFiscal:
    def _scenario(self, api):
        """APPROVED year with K-1s generated (GP's package still GENERATED) and
        a settled LP1 -> LP3 transfer that has pushed the LOCKED run to STALE."""
        fund = create_fund()
        gp = create_partner(
            fund["id"], legal_name="GP1", partner_type="US_ENTITY",
            partner_class="GENERAL", residency_state="DE", ownership_pct_bps=1000,
            capital_commitment_cents=10000000,
        )
        lp1 = create_partner(
            fund["id"], legal_name="LP1", partner_type="US_INDIVIDUAL",
            residency_state="CA", ownership_pct_bps=6000,
            capital_commitment_cents=60000000,
        )
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        run = create_and_lock_final_run(ty["id"])
        submit_tax_year_review(ty["id"])
        approve_tax_year(ty["id"])
        packages = generate_k1_packages(ty["id"])
        k1_gp = packages[0]
        assert k1_gp["partner_id"] == gp["id"]
        lp3 = create_partner(
            fund["id"], legal_name="LP3", partner_type="US_INDIVIDUAL",
            residency_state="NY", ownership_pct_bps=1, capital_commitment_cents=1,
        )
        transfer = create_and_confirm_transfer(
            fund["id"], lp1["id"], lp3["id"],
            pct_bps=100, effective_date="2025-06-01", settlement_date="2025-06-10",
        )
        settle_transfer(transfer["id"])
        assert get_allocation_run(run["id"])["status"] == "STALE"
        return k1_gp

    def test_approve_generated_k1_reports_state_error_not_stale(self, api):
        """PRD §2.8: "Every request is evaluated against a fixed validation
        pipeline and is rejected with the first failing check in the order
        below; later checks never mask earlier ones."
        PRD §2.8: "State-transition legality — the requested transition is
        declared from the resource’s current state, else
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.8: "Allocation prerequisites — a locked, non-stale `FINAL` run
        is required for K-1 generation, K-1 package approval, tax-year
        submit-review and approval, and composite filing, else
        `ERR_ALLOCATION_NOT_LOCKED` or `ERR_ALLOCATION_STALE`."

        Design: Difficulty/priority_pair_validation_conflict/k1_approve_state_beats_stale_fiscal
        """
        k1_gp = self._scenario(api)
        resp = api.approve_k1(k1_gp["id"], make_tax_reviewer_headers(REVIEWER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_failed_approve_leaves_prep_status_generated(self, api):
        """PRD §3.8: "A `TaxReviewer` then approves the package, moving
        preparation from `REVIEWED` to `APPROVED`: the approver’s `X-User-ID`
        must differ from `submitted_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; the snapshot run must remain `LOCKED` and
        not `STALE`, else `ERR_ALLOCATION_STALE`; and the tax year must be
        `APPROVED`, else `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/priority_pair_validation_conflict/k1_approve_state_beats_stale_fiscal
        """
        k1_gp = self._scenario(api)
        validate_error(
            api.approve_k1(k1_gp["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        after = get_k1_package(k1_gp["id"])
        assert after["prep_status"] == "GENERATED", (
            f"rejected approve must not move prep_status: {after['prep_status']}"
        )


class TestDeliveryAndCompletion:
    def test_deliver_exactly_at_deadline_is_not_late(self, api):
        """PRD §3.8: "the package is late when `delivered_at` falls strictly
        after the tax year’s `k1_delivery_deadline`, while delivery exactly at
        the deadline timestamp is on time."
        PRD §3.1: "Creation also fixes the year’s delivery deadline:
        `k1_delivery_deadline` is March 15 of the year following the tax year
        at 23:59:59 UTC, moving to September 15 of that following year at
        23:59:59 UTC when `federal_extension_filed` is true."

        Design: Corner/state_machines/deliver_exactly_at_deadline_is_not_late
        """
        scenario = setup_k1_generated(partner_specs=SINGLE_LP)
        k1 = scenario["k1_packages"][0]
        validate_success(api.submit_k1_review(k1["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200)
        validate_success(api.approve_k1(k1["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200)
        set_clock("2026-03-15T23:59:59Z")
        delivered = validate_success(api.deliver_k1(k1["id"], {"delivery_method": "PORTAL"}, REP), 200)
        assert delivered["prep_status"] == "DELIVERED"
        assert delivered["is_late"] is False, "delivery exactly at the deadline is on time"
        ty = get_tax_year(scenario["tax_year"]["id"])
        deadline = parse_instant(ty["k1_delivery_deadline"])
        assert deadline == datetime(2026, 3, 15, 23, 59, 59, tzinfo=timezone.utc)

    def test_tax_year_completes_when_last_k1_delivered(self, api):
        """PRD §3.5: "Completion is automatic: once at least one K-1 package
        exists for the year and every non-`SUPERSEDED` package has reached
        preparation `DELIVERED`, the year moves from `APPROVED` to `COMPLETED`
        and its `version` increments."
        PRD §3.8: "When the delivery leaves every non-`SUPERSEDED` package of
        the tax year in preparation `DELIVERED`, the year bubbles up from
        `APPROVED` to `COMPLETED`."

        Design: Corner/state_machines/tax_year_completes_when_last_k1_delivered
        """
        scenario = setup_k1_generated(partner_specs=TWO_PARTNERS)
        ty_id = scenario["tax_year"]["id"]
        k1a, k1b = scenario["k1_packages"]
        for package in (k1a, k1b):
            validate_success(api.submit_k1_review(package["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200)
            validate_success(api.approve_k1(package["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200)
        validate_success(api.deliver_k1(k1a["id"], {"delivery_method": "MAIL"}, REP), 200)
        assert get_tax_year(ty_id)["status"] == "APPROVED", (
            "one outstanding package must hold the year at APPROVED"
        )
        validate_success(api.deliver_k1(k1b["id"], {"delivery_method": "PORTAL"}, REP), 200)
        assert get_tax_year(ty_id)["status"] == "COMPLETED", (
            "last outstanding delivery must bubble the year to COMPLETED"
        )


class TestReopenCascade:
    def test_reopen_stales_run_and_reverts_reviewed_k1(self, api):
        """PRD §3.5: "A `FundTaxAdmin` may move an `APPROVED` year back to
        `BOOKS_CLOSED`, but only while no K-1 package of the year has reached
        preparation `DELIVERED`, else `ERR_K1_ALREADY_GENERATED`. Reopening
        cascades: the year’s `LOCKED` run becomes `STALE` as the first hop,
        and — as the second hop caused by that staleness — every package of the
        year in `REVIEWED` or `APPROVED` preparation reverts to `GENERATED`."

        Design: Corner/state_machines/reopen_stales_run_and_reverts_reviewed_k1
        """
        scenario = setup_k1_generated(partner_specs=SINGLE_LP)
        k1 = scenario["k1_packages"][0]
        validate_success(api.submit_k1_review(k1["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200)
        ty_id = scenario["tax_year"]["id"]
        resp = api.reopen_tax_year(ty_id, ADMIN)
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "BOOKS_CLOSED"
        assert get_allocation_run(scenario["run"]["id"])["status"] == "STALE"
        assert get_k1_package(k1["id"])["prep_status"] == "GENERATED", (
            "REVIEWED package must revert to GENERATED when its run goes STALE"
        )


class TestGenerationPrerequisites:
    def test_second_k1_generation_rejected(self, api):
        """PRD §3.8: "At most one generation set of non-`SUPERSEDED` packages
        may exist per tax year, so a second generation over live packages is
        rejected with `ERR_K1_ALREADY_GENERATED`."

        Design: Corner/validations/second_k1_generation_rejected
        """
        scenario = setup_k1_generated(partner_specs=SINGLE_LP)
        resp = api.generate_k1({"tax_year_id": scenario["tax_year"]["id"]}, PREPARER)
        validate_error(resp, ApiErrorId.ERR_K1_ALREADY_GENERATED)

    def test_generation_without_locked_run_rejected(self, api):
        """PRD §3.8: "Generation requires the year to be `APPROVED` — any other
        status is rejected with `ERR_INVALID_STATE_TRANSITION` — and requires a
        `LOCKED` `FINAL` run that is not `STALE`, else
        `ERR_ALLOCATION_NOT_LOCKED` or `ERR_ALLOCATION_STALE`."
        PRD §2.8: "Every request is evaluated against a fixed validation
        pipeline and is rejected with the first failing check in the order
        below; later checks never mask earlier ones."

        Design: Corner/errors/generation_without_locked_run_rejected
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        create_allocation_run(ty["id"], run_kind="FINAL")  # COMPUTED, never locked
        resp = api.generate_k1({"tax_year_id": ty["id"]}, PREPARER)
        # the state guard (year not APPROVED) fires ahead of the fiscal guard
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        data, meta = validate_paginated(
            api.list_k1_packages(PREPARER, params={"tax_year_id": ty["id"]})
        )
        assert meta["total_count"] == 0, "no package may be created by the rejected call"


class TestK1ApprovalSegregation:
    def test_k1_approve_by_submitter_rejected_sod(self, api):
        """PRD §3.8: "A `TaxReviewer` then approves the package, moving
        preparation from `REVIEWED` to `APPROVED`: the approver’s `X-User-ID`
        must differ from `submitted_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; the snapshot run must remain `LOCKED` and
        not `STALE`, else `ERR_ALLOCATION_STALE`; and the tax year must be
        `APPROVED`, else `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/validations/k1_approve_by_submitter_rejected_sod
        """
        scenario = setup_k1_generated(partner_specs=SINGLE_LP)
        k1 = scenario["k1_packages"][0]
        # submitted by a preparer whose user id is rev_1
        validate_success(
            api.submit_k1_review(k1["id"], make_tax_preparer_headers(REVIEWER_USER_ID)), 200,
        )
        resp = api.approve_k1(k1["id"], make_tax_reviewer_headers(REVIEWER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_k1_package(k1["id"])["prep_status"] == "REVIEWED"


class TestInvestorAcknowledge:
    def test_investor_acknowledge_own_vs_other_k1(self, api):
        """PRD §3.8: "After sending, the investor acknowledges receipt —
        delivery moves from `SENT` to `ACKNOWLEDGED`, a terminal delivery state
        — and only the partner themselves may do this: the `Investor` actor’s
        `X-User-ID` must equal the package’s `partner_id`, else
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/investor_acknowledge_own_vs_other_k1
        """
        scenario = setup_k1_generated(partner_specs=TWO_PARTNERS)
        p1 = scenario["partners"]["p1"]
        p2 = scenario["partners"]["p2"]
        k1_1, k1_2 = scenario["k1_packages"]
        assert k1_1["partner_id"] == p1["id"] and k1_2["partner_id"] == p2["id"]
        walk_k1_to_delivered(k1_1["id"])
        walk_k1_to_delivered(k1_2["id"])
        resp_other = api.acknowledge_k1(k1_2["id"], make_investor_headers(p1["id"]))
        validate_error(resp_other, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp_own = api.acknowledge_k1(k1_2["id"], make_investor_headers(p2["id"]))
        acknowledged = validate_success(resp_own, 200)
        assert acknowledged["delivery_status"] == "ACKNOWLEDGED"
        assert acknowledged["prep_status"] == "DELIVERED", (
            "acknowledge touches only the delivery axis"
        )


class TestAmendmentPreconditions:
    def test_amendment_on_undelivered_k1_returns_k1_not_delivered(self, api):
        """PRD §3.8: "The target package’s preparation must be `DELIVERED`,
        else `ERR_K1_NOT_DELIVERED`, and at most one amendment not yet `ISSUED`
        may exist per package, else `ERR_AMENDMENT_ALREADY_ACTIVE`."

        Design: Corner/state_machines/amendment_on_undelivered_k1_returns_k1_not_delivered
        """
        scenario = setup_k1_generated(partner_specs=SINGLE_LP)
        k1 = scenario["k1_packages"][0]
        resp = api.create_k1_amendment(
            create_k1_amendment_payload(k1["id"], reason="PARTNER_DATA_FIX"), PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_K1_NOT_DELIVERED)
        data, meta = validate_paginated(api.list_k1_amendments(k1["id"], PREPARER))
        assert meta["total_count"] == 0, "no amendment may persist after the rejection"


class TestTaxYearApproveStaleness:
    def test_tax_year_approve_with_stale_run_returns_allocation_stale(self, api):
        """PRD §3.5: "A `TaxReviewer` then approves the year, moving it from
        `UNDER_REVIEW` to `APPROVED`; approval requires that the year’s locked
        `FINAL` run is not `STALE`, else `ERR_ALLOCATION_STALE`."

        Design: Corner/validations/tax_year_approve_with_stale_run_returns_allocation_stale
        """
        fund = create_fund()
        create_partner(
            fund["id"], legal_name="GP1", partner_type="US_ENTITY",
            partner_class="GENERAL", residency_state="DE", ownership_pct_bps=1000,
        )
        lp1 = create_partner(
            fund["id"], legal_name="LP1", partner_type="US_INDIVIDUAL",
            residency_state="CA", ownership_pct_bps=9000,
        )
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        run = create_and_lock_final_run(ty["id"])
        submit_tax_year_review(ty["id"])
        lp3 = create_partner(
            fund["id"], legal_name="LP3", partner_type="US_INDIVIDUAL",
            residency_state="NY", ownership_pct_bps=1, capital_commitment_cents=1,
        )
        transfer = create_and_confirm_transfer(
            fund["id"], lp1["id"], lp3["id"],
            pct_bps=100, effective_date="2025-06-01", settlement_date="2025-06-10",
        )
        settle_transfer(transfer["id"])
        resp = api.approve_tax_year(ty["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_STALE)
        assert get_tax_year(ty["id"])["status"] == "UNDER_REVIEW"
        assert get_allocation_run(run["id"])["status"] == "STALE"
