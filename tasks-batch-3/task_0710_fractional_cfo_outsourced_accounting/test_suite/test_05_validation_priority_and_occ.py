"""Validation precedence, optimistic-concurrency, covenant boundary, cross-entity gates.

Note: the difficulty instance
  priority_pair_validation_conflict / forecast_approve_state_beats_covenant
is SKIPPED. Its scenario requires a forecast that is simultaneously SUPERSEDED
(a state violation) and below the covenant floor. Per PRD §3.7 a forecast can only
reach APPROVED — and thus later SUPERSEDED — by first passing the covenant gate
(min_projected_balance_cents >= covenant_floor_cents), and the floor
(covenant_floor_cents) is an immutable client input that no endpoint mutates. A
SUPERSEDED forecast therefore necessarily satisfies the covenant, so the double
violation is not realizable from PRD prose (Core rule: not uniquely derivable).
"""
from test_helpers import (
    get_success_data, validate_error, validate_success, ApiErrorId,
    create_client, current_client_version,
    setup_forecast_with_min_balance, create_forecast, add_forecast_line,
    setup_allocated_payroll_run,
    api_client, TEST_USERS,
)

CFO = TEST_USERS["cfo_headers"]
BK = TEST_USERS["bookkeeper_headers"]


class TestValidationPriorityConflicts:
    def test_complete_onboarding_state_error_beats_no_ledger(self, api):
        """PRD §2.9: "For a state-transition endpoint, the system then confirms the
        target resource is in a state from which the requested transition is
        defined, yielding `ERR_INVALID_STATE` if not."
        PRD §2.9: "Only after these four gates pass does the server evaluate the
        operation's specific business constraints — onboarding completeness,
        open-close counts, December-close finalization, payroll-close finalization,
        ledger-account presence, cross-client parents, duplicate codes, duplicate
        periods, pay-period overlaps, covenant floors, underpayments, missing
        schedule dates, and the stale-version check — followed last by generic
        request-shape validation that catches a missing or wrong-typed field with
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/priority_pair_validation_conflict/complete_onboarding_state_beats_no_ledger
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        # KICKOFF_SCHEDULED (not LEDGER_SETUP) and no ledger accounts: both fail,
        # but the state gate is evaluated first.
        get_success_data(api.schedule_kickoff(cid, CFO))
        resp = api.complete_onboarding(cid, CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_complete_onboarding_at_lead_state_error_not_no_ledger(self, api):
        """PRD §2.9: "For a state-transition endpoint, the system then confirms the
        target resource is in a state from which the requested transition is
        defined, yielding `ERR_INVALID_STATE` if not."
        PRD §2.9: "Only after these four gates pass does the server evaluate the
        operation's specific business constraints — onboarding completeness,
        open-close counts, December-close finalization, payroll-close finalization,
        ledger-account presence, cross-client parents, duplicate codes, duplicate
        periods, pay-period overlaps, covenant floors, underpayments, missing
        schedule dates, and the stale-version check — followed last by generic
        request-shape validation that catches a missing or wrong-typed field with
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/priority_pair_validation_conflict/complete_onboarding_state_beats_no_ledger
        """
        # Brand-new client in LEAD with no ledger accounts: state fails before the
        # ledger-presence business check.
        client = create_client(retainer_tier="ESSENTIALS")
        resp = api.complete_onboarding(client["id"], CFO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestForecastOptimisticConcurrency:
    def test_approve_forecast_with_stale_client_version_rejected(self, api):
        """PRD §3.7: "the request must include `expected_client_version` matching
        the target client's current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "On success the forecast moves `DRAFT → APPROVED`, every other
        `APPROVED` forecast for the same client is superseded (`→ SUPERSEDED`), and
        the client's `version` is incremented."

        Design: Difficulty/optimistic_concurrency/forecast_approve_stale_client_version_rejected
        """
        client = create_client(retainer_tier="GROWTH", covenant_floor_cents=0)
        cid = client["id"]
        f1 = create_forecast(cid, opening_balance_cents=1000000)
        f2 = create_forecast(cid, opening_balance_cents=2000000)
        cver_stale = current_client_version(cid)
        # First approval advances Client.version, making cver_stale stale for f2.
        get_success_data(api.approve_forecast(
            f1["id"], {"expected_client_version": cver_stale}, CFO))
        resp = api.approve_forecast(
            f2["id"], {"expected_client_version": cver_stale}, CFO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_approve_forecast_stale_version_after_intervening_approval(self, api):
        """PRD §3.7: "The server compares that value to the client's current
        `version`; if they differ — because some other writer has advanced the
        client since the caller read it — the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/optimistic_concurrency/forecast_approve_stale_client_version_rejected
        """
        client = create_client(retainer_tier="GROWTH", covenant_floor_cents=0)
        cid = client["id"]
        f1 = create_forecast(cid, opening_balance_cents=1000000)
        f2 = create_forecast(cid, opening_balance_cents=2000000)
        cver_before = current_client_version(cid)
        # Approve f1 with the fresh version; this bumps Client.version.
        get_success_data(api.approve_forecast(
            f1["id"], {"expected_client_version": cver_before}, CFO))
        # Re-using the now-stale version on f2 must be rejected.
        resp = api.approve_forecast(
            f2["id"], {"expected_client_version": cver_before}, CFO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_approve_forecast_with_current_version_succeeds_and_supersedes(self, api):
        """PRD §3.7: "On success the forecast moves `DRAFT → APPROVED`, every other
        `APPROVED` forecast for the same client is superseded (`→ SUPERSEDED`), and
        the client's `version` is incremented."

        Design: Corner/cross_cutting_complexity_layers/forecast_approve_correct_version_succeeds_and_supersedes
        """
        client = create_client(retainer_tier="GROWTH", covenant_floor_cents=0)
        cid = client["id"]
        f1 = create_forecast(cid, opening_balance_cents=1000000)
        f2 = create_forecast(cid, opening_balance_cents=2000000)
        cver1 = current_client_version(cid)
        get_success_data(api.approve_forecast(
            f1["id"], {"expected_client_version": cver1}, CFO))
        cver2 = current_client_version(cid)
        resp = api.approve_forecast(
            f2["id"], {"expected_client_version": cver2}, CFO)
        validate_success(resp, expected_status=200)
        assert get_success_data(api.get_forecast(f2["id"], CFO))["status"] == "APPROVED"
        assert get_success_data(api.get_forecast(f1["id"], CFO))["status"] == "SUPERSEDED"


class TestRetainerOptimisticConcurrency:
    def test_issue_retainer_with_stale_client_version_rejected(self, api):
        """PRD §3.8: "the supplied `expected_client_version` must equal the client's
        current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412); this guard matters because both the surcharge eligibility and the
        included transaction volume are read off the client at the instant of
        issuance, so a tier change or a catch-up transition that bumped the client's
        `version` would otherwise let the invoice be minted off out-of-date pricing
        inputs."

        Design: Difficulty/optimistic_concurrency/retainer_issue_stale_client_version_rejected
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 9, "txn_count": 650}, BK))
        cver_stale = current_client_version(cid)
        # Scoping a catch-up project bumps Client.version, staling cver_stale.
        cp = get_success_data(api.create_catchup_project(
            cid, {"months_behind": 3, "quoted_fee_cents": 400000}, CFO))
        get_success_data(api.scope_catchup_project(cp["id"], CFO))
        resp = api.issue_retainer_invoice(
            cid, {"monthly_close_id": close["id"], "expected_client_version": cver_stale}, CFO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_issue_retainer_with_current_version_succeeds(self, api):
        """PRD §3.8: "the supplied `expected_client_version` must equal the client's
        current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412)"
        PRD §3.8: "The issued invoice begins with `status` of `ISSUED`, and issuing
        it increments the client's `version`."

        Design: Difficulty/optimistic_concurrency/retainer_issue_stale_client_version_rejected
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 9, "txn_count": 650}, BK))
        cver = current_client_version(cid)
        resp = api.issue_retainer_invoice(
            cid, {"monthly_close_id": close["id"], "expected_client_version": cver}, CFO)
        inv = validate_success(resp, expected_status=201)
        assert inv["status"] == "ISSUED"


class TestCovenantBoundary:
    def test_approve_at_floor_exactly_succeeds(self, api):
        """PRD §3.7: "The covenant gate itself requires the forecast's
        `min_projected_balance_cents` to be at or above the client's
        `covenant_floor_cents` — that is, the minimum projected balance must be
        greater than or equal to the floor"

        Design: Difficulty/boundary_precision_check/covenant_floor_inclusive_boundary
        """
        cid, fid = setup_forecast_with_min_balance(
            covenant_floor_cents=400000, opening_balance_cents=500000, outflow_cents=100000)
        forecast = get_success_data(api.get_forecast(fid, CFO))
        assert forecast["min_projected_balance_cents"] == 400000
        cver = current_client_version(cid)
        approved = get_success_data(api.approve_forecast(
            fid, {"expected_client_version": cver}, CFO))
        assert approved["status"] == "APPROVED"

    def test_approve_one_cent_below_floor_breaches(self, api):
        """PRD §3.7: "an approval whose minimum falls below the floor is rejected
        with `ERR_COVENANT_BREACH`."

        Design: Difficulty/boundary_precision_check/covenant_floor_inclusive_boundary
        """
        cid, fid = setup_forecast_with_min_balance(
            covenant_floor_cents=400000, opening_balance_cents=500000, outflow_cents=100001)
        forecast = get_success_data(api.get_forecast(fid, CFO))
        assert forecast["min_projected_balance_cents"] == 399999
        cver = current_client_version(cid)
        resp = api.approve_forecast(fid, {"expected_client_version": cver}, CFO)
        validate_error(resp, ApiErrorId.ERR_COVENANT_BREACH.value)


class TestPayrollPeriodOverlap:
    def test_overlapping_pay_period_rejected(self, api):
        """PRD §3.6: "A client's pay periods may not overlap: a new run whose
        half-open interval from `pay_period_start` up to but not including
        `pay_period_end` overlaps the interval of any existing non-`REVERSED` run
        for the same client is rejected with `ERR_PAY_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/payroll_period_half_open_overlap_rejected
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 3, "txn_count": 60}, BK))
        get_success_data(api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-03-31T00:00:00Z",
            "pay_period_start": "2026-03-01T00:00:00Z",
            "pay_period_end": "2026-04-01T00:00:00Z",
            "total_employer_cost_cents": 500000}, BK))
        resp = api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-04-14T00:00:00Z",
            "pay_period_start": "2026-03-15T00:00:00Z",
            "pay_period_end": "2026-04-15T00:00:00Z",
            "total_employer_cost_cents": 500000}, BK)
        validate_error(resp, ApiErrorId.ERR_PAY_PERIOD_OVERLAP.value)

    def test_adjacent_pay_period_allowed(self, api):
        """PRD §3.6: "Adjacency does not count as overlap — one period ending
        exactly where the next begins is allowed, because the intervals are
        half-open."

        Design: Difficulty/resource_temporal_overlap/payroll_period_half_open_overlap_rejected
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 3, "txn_count": 60}, BK))
        get_success_data(api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-03-31T00:00:00Z",
            "pay_period_start": "2026-03-01T00:00:00Z",
            "pay_period_end": "2026-04-01T00:00:00Z",
            "total_employer_cost_cents": 500000}, BK))
        resp = api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-04-30T00:00:00Z",
            "pay_period_start": "2026-04-01T00:00:00Z",
            "pay_period_end": "2026-05-01T00:00:00Z",
            "total_employer_cost_cents": 500000}, BK)
        run = validate_success(resp, expected_status=201)
        assert run["status"] == "DRAFT"


class TestMonthlyCloseDuplicatePeriod:
    def test_duplicate_non_finalized_period_rejected(self, api):
        """PRD §3.4: "Two closes for the same client and the same `(period_year,
        period_month)` may not both be non-finalized; attempting a second open close
        for a period the client already has open is rejected with
        `ERR_DUPLICATE_PERIOD`."

        Design: Difficulty/resource_temporal_overlap/monthly_close_period_cell_duplicate_rejected
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 7, "txn_count": 30}, BK))
        resp = api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 7, "txn_count": 31}, BK)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD.value)

    def test_different_period_month_allowed(self, api):
        """PRD §3.4: "Two closes for the same client and the same `(period_year,
        period_month)` may not both be non-finalized"

        Design: Difficulty/resource_temporal_overlap/monthly_close_period_cell_duplicate_rejected
        """
        client = create_client(retainer_tier="ESSENTIALS")
        cid = client["id"]
        get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 7, "txn_count": 30}, BK))
        resp = api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 8, "txn_count": 31}, BK)
        close2 = validate_success(resp, expected_status=201)
        assert close2["status"] == "OPEN"


class TestPayrollPostBlockedByFinalizedClose:
    def test_post_into_finalized_close_rejected(self, api):
        """PRD §3.6: "Posting the run is a `CFO` action permitted only from
        `ALLOCATED`, moving it `ALLOCATED → POSTED`; it requires the linked
        `MonthlyClose` not be `FINALIZED`, and posting into a finalized close is
        rejected with `ERR_CLOSE_FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/payroll_post_blocked_by_finalized_close
        """
        client = create_client(retainer_tier="GROWTH")
        cid = client["id"]
        close = get_success_data(api.create_monthly_close(
            cid, {"period_year": 2026, "period_month": 6, "txn_count": 70}, BK))
        run = get_success_data(api.create_payroll_run(cid, {
            "monthly_close_id": close["id"], "pay_date": "2026-06-30T00:00:00Z",
            "pay_period_start": "2026-06-01T00:00:00Z",
            "pay_period_end": "2026-07-01T00:00:00Z",
            "total_employer_cost_cents": 600000}, BK))
        get_success_data(api.create_payroll_allocation(
            run["id"], {"department_name": "Ops", "dept_gross_cents": 600000}, BK))
        get_success_data(api.allocate_payroll_run(run["id"], BK))
        # Finalize the linked close.
        task = get_success_data(api.create_close_task(
            close["id"], {"name": "Reconcile", "weight": 1}, BK))
        get_success_data(api.transition_close_task(task["id"], {"to_status": "DONE"}, BK))
        get_success_data(api.approve_review(close["id"], CFO))
        get_success_data(api.finalize_close(close["id"], CFO))
        resp = api.post_payroll_run(run["id"], CFO)
        validate_error(resp, ApiErrorId.ERR_CLOSE_FINALIZED.value)

    def test_post_into_non_finalized_close_succeeds(self, api):
        """PRD §3.6: "Posting the run is a `CFO` action permitted only from
        `ALLOCATED`, moving it `ALLOCATED → POSTED`"

        Design: Difficulty/cross_entity_state_dependency/payroll_post_blocked_by_finalized_close
        """
        cid, close_id, run_id, alloc_ids = setup_allocated_payroll_run(period_month=6)
        run = get_success_data(api.post_payroll_run(run_id, CFO))
        assert run["status"] == "POSTED"
