"""Distribution requests: capacity gates, PCA gates, the payment window,
terminal-state lockdown, the pending-pool conservation invariant, and
filtered pagination.

Approving a distribution requires a positive distributable pool. The pool is
zero until a capital plan is EFFECTIVE, and the stress buffer recorded at
approval exactly consumes the stressed headroom, so these tests use banks
whose plans were refreshed upward by a post-approval amendment and then
activated on the first day of the plan year (PRD §3.6, §3.4, §2.5).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    add_exposure,
    advance_clock_past,
    create_payment_period,
    create_prepared_call_report,
    create_proposed_distribution,
    approve_distribution,
    setup_accepted_report,
    setup_distributable_bank,
    setup_plan_approved,
    setup_plan_in_board_review,
    setup_plan_in_supervisory_review,
    setup_approved_distribution,
    make_capital_analyst_headers,
    set_clock,
    SUBMITTER_USER_ID,
)


class TestDistributionGates(object):
    def test_distribution_approve_depends_on_plan_approved(self, api, system_operator_headers,
                                                           capital_analyst_headers):
        """PRD §3.6: "Approval is where capacity is reserved. The attached
        plan must have reached APPROVED"

        Design: Difficulty/cross_entity_state_dependency/distribution_approve_depends_on_plan_approved
        """
        bank, period, report, scenario, plan = setup_plan_in_board_review(
            "CH-XD1-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-XD1"
        )
        assert plan["status"] == "BOARD_REVIEW"
        pay_period = create_payment_period(bank["id"])
        dist = create_proposed_distribution(
            bank["id"], plan["id"], pay_period["id"],
            distribution_kind="DIVIDEND", distribution_amount_cents=50_000_000,
            proposed_payment_date="2027-03-15",
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        res = api.approve_distribution(
            bank["id"], dist["id"], {"expected_bank_version": bank_now["version"]},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        dist_now = validate_success(
            api.get_distribution_request(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert dist_now["status"] == "PROPOSED"

    def test_distribution_approve_blocked_while_plan_in_supervisory_review(
        self, api, system_operator_headers, capital_analyst_headers
    ):
        """PRD §3.6: "Approval is where capacity is reserved. The attached
        plan must have reached APPROVED"

        Design: Difficulty/cross_entity_state_dependency/distribution_approve_depends_on_plan_approved
        """
        bank, period, report, scenario, plan = setup_plan_in_supervisory_review(
            "CH-XD1-002", 10_000_000_000, 100_000_000_000, scenario_code="BASE-XD1B"
        )
        assert plan["status"] == "SUPERVISORY_REVIEW"
        pay_period = create_payment_period(bank["id"])
        dist = create_proposed_distribution(
            bank["id"], plan["id"], pay_period["id"],
            distribution_kind="DIVIDEND", distribution_amount_cents=25_000_000,
            proposed_payment_date="2027-03-15",
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        res = api.approve_distribution(
            bank["id"], dist["id"], {"expected_bank_version": bank_now["version"]},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def _push_bucket_adverse(api, capital_analyst_headers, regulator_reviewer_headers,
                         bank, adverse_rwa_cents):
    """File and accept a later quarter whose larger RWA drops the bank's
    bucket. The capital stack is bank-wide, so the later period's report
    recomputes ratios from the same instruments over the new RWA."""
    p2 = validate_success(
        api.create_reporting_period(
            bank["id"],
            {"period_end_date": "2026-09-30", "period_year": 2026, "period_quarter": "Q3"},
            capital_analyst_headers,
        ),
        201,  # PRD §4: creation operations return 201 Created
    )
    add_exposure(bank["id"], p2["id"], exposure_at_default_cents=adverse_rwa_cents)
    report2 = create_prepared_call_report(bank["id"], p2["id"])
    # Move the Q3 period unambiguously to FILING_DUE before submitting.
    advance_clock_past("2026-09-30")
    validate_success(
        api.submit_call_report(
            bank["id"], p2["id"], report2["id"],
            make_capital_analyst_headers(SUBMITTER_USER_ID),
        )
    )
    accepted = validate_success(
        api.accept_call_report(bank["id"], p2["id"], report2["id"], regulator_reviewer_headers)
    )
    return p2, accepted


class TestDistributionPcaGate(object):
    def test_pca_gate_wins_when_bank_undercapitalized(self, api, system_operator_headers,
                                                      capital_analyst_headers, regulator_reviewer_headers):
        """PRD §3.6: "the bank must be WELL_CAPITALIZED or
        ADEQUATELY_CAPITALIZED, failing which approval is rejected with
        ERR_PCA_BLOCKS_DISTRIBUTION (HTTP 409)"
        PRD §3.6: "In any of the three undercapitalized buckets, mdba_cents is
        zero outright."

        Design: Difficulty/priority_pair_validation_conflict/pca_safety_vs_fiscal_capacity_on_distribution_approve
        """
        # Plan approved on a WELL Q2 baseline (all four ratios 1000 bps).
        # A later accepted report with RWA 142_857_142_857 (the same 10e9
        # stack) lands CET1/Tier1/total/leverage at 700/700/700/700 bps;
        # the total-capital metric's UNDERCAPITALIZED floor is 700 inclusive,
        # so the strictest bucket is UNDERCAPITALIZED.
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-PRI-001", 10_000_000_000, 100_000_000_000, scenario_code="BASE-PRI"
        )
        p2, accepted2 = _push_bucket_adverse(
            api, capital_analyst_headers, regulator_reviewer_headers,
            bank, adverse_rwa_cents=142_857_142_857,
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank_now["pca_bucket"] == "UNDERCAPITALIZED"
        assert bank_now["mdba_cents"] == 0
        pay_period = create_payment_period(bank["id"])
        dist = create_proposed_distribution(
            bank["id"], plan["id"], pay_period["id"],
            distribution_kind="DIVIDEND", distribution_amount_cents=100_000_000,
            proposed_payment_date="2027-03-15",
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        res = api.approve_distribution(
            bank["id"], dist["id"], {"expected_bank_version": bank_now["version"]},
            capital_analyst_headers,
        )
        # Both the PCA gate and the capacity check fail; the PCA safety gate
        # is evaluated earlier (§2.9: sixth vs tenth) and masks the fiscal one.
        validate_error(res, ApiErrorId.ERR_PCA_BLOCKS_DISTRIBUTION)

    def test_pca_gate_wins_over_capacity_when_critically_undercapitalized(
        self, api, system_operator_headers, capital_analyst_headers, regulator_reviewer_headers
    ):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in a fixed order, so that earlier failures mask later
        ones. ... Sixth, PCA posture gating. ... Tenth, capacity checks"

        Design: Difficulty/priority_pair_validation_conflict/pca_safety_vs_fiscal_capacity_on_distribution_approve
        """
        # Q3 RWA 250e9 against the 10e9 stack -> CET1 400 bps (UNDERCAPITALIZED
        # on CET1, SIGNIFICANT on Tier1, CRITICAL on total) -> strictest is
        # CRITICALLY_UNDERCAPITALIZED; mdba is 0, so any positive amount also
        # fails the capacity check.
        bank, period, report, scenario, plan = setup_plan_approved(
            "CH-PRI-002", 10_000_000_000, 100_000_000_000, scenario_code="BASE-PRIB"
        )
        p2, accepted2 = _push_bucket_adverse(
            api, capital_analyst_headers, regulator_reviewer_headers,
            bank, adverse_rwa_cents=250_000_000_000,
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert bank_now["pca_bucket"] == "CRITICALLY_UNDERCAPITALIZED"
        assert bank_now["mdba_cents"] == 0
        pay_period = create_payment_period(bank["id"])
        dist = create_proposed_distribution(
            bank["id"], plan["id"], pay_period["id"],
            distribution_kind="BUYBACK", distribution_amount_cents=10_000_000,
            proposed_payment_date="2027-03-15",
        )
        bank_now = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        res = api.approve_distribution(
            bank["id"], dist["id"], {"expected_bank_version": bank_now["version"]},
            capital_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_PCA_BLOCKS_DISTRIBUTION)


class TestDistributionPaymentWindow(object):
    def test_execute_exactly_at_payment_date_succeeds(self, api, system_operator_headers,
                                                      capital_analyst_headers):
        """PRD §3.6: "Execution pays the distribution out. The logical clock
        must have reached the proposed_payment_date — an early execution is
        rejected with ERR_DISTRIBUTION_NOT_YET_PAYABLE (HTTP 409) — and must
        not have passed ten days beyond it, because the payment window is the
        payment date plus ten days"

        Design: Difficulty/resource_temporal_overlap/distribution_window_half_open_interval
        """
        bank, base_period, pay_period, scenario, plan, dist = setup_approved_distribution(
            "CH-TP1-001", dist_amount_cents=50_000_000, payment_date="2027-03-15",
            scenario_code="BASE-TP1",
        )
        set_clock("2027-03-15T09:00:00Z")
        executed = validate_success(api.execute_distribution(bank["id"], dist["id"], capital_analyst_headers))
        assert executed["status"] == "EXECUTED"
        assert executed["executed_amount_cents"] == 50_000_000

    def test_execute_after_window_rejected(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.6: "and must not have passed ten days beyond it, because
        the payment window is the payment date plus ten days and a request
        whose window has closed is instead moved to EXPIRED automatically."

        Design: Difficulty/resource_temporal_overlap/distribution_window_half_open_interval
        """
        bank, base_period, pay_period, scenario, plan, dist = setup_approved_distribution(
            "CH-TP1-002", dist_amount_cents=30_000_000, payment_date="2027-03-15",
            scenario_code="BASE-TP1B",
        )
        # payment_date + 11 days: the window [03-15, 03-25] has closed.
        set_clock("2027-03-26T09:00:00Z")
        res = api.execute_distribution(bank["id"], dist["id"], capital_analyst_headers)
        assert res.status_code == 409, (
            f"Expected 409 executing after the payment window, got {res.status_code}"
        )
        dist_now = validate_success(
            api.get_distribution_request(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert dist_now["status"] in ("EXPIRED", "APPROVED_NOT_EXECUTED")

    def test_error_distribution_not_yet_payable(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.6: "The logical clock must have reached the
        proposed_payment_date — an early execution is rejected with
        ERR_DISTRIBUTION_NOT_YET_PAYABLE (HTTP 409)"

        Design: Corner/errors/error_distribution_not_yet_payable
        """
        bank, base_period, pay_period, scenario, plan, dist = setup_approved_distribution(
            "CH-NYT-001", dist_amount_cents=50_000_000, payment_date="2027-03-15",
            scenario_code="BASE-NYT",
        )
        set_clock("2027-03-01T09:00:00Z")
        res = api.execute_distribution(bank["id"], dist["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_DISTRIBUTION_NOT_YET_PAYABLE)


class TestDistributionTerminalState(object):
    def test_distribution_terminal_state_lockdown(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.6: "A successful execution moves the request
        APPROVED_NOT_EXECUTED → EXECUTED" and "An analyst may ... withdraw an
        APPROVED_NOT_EXECUTED request, moving it to WITHDRAWN"

        Design: Corner/state_machines/distribution_terminal_state_lockdown
        """
        bank, base_period, pay_period, scenario, plan, dist = setup_approved_distribution(
            "CH-TRM-001", dist_amount_cents=50_000_000, payment_date="2027-03-15",
            scenario_code="BASE-TRM",
        )
        set_clock("2027-03-15T09:00:00Z")
        executed = validate_success(api.execute_distribution(bank["id"], dist["id"], capital_analyst_headers))
        assert executed["status"] == "EXECUTED"
        # EXECUTED is terminal: withdraw is no longer a permitted transition.
        res = api.withdraw_distribution(bank["id"], dist["id"], capital_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestCompensatingInvariant(object):
    def test_approve_withdraw_conserves_pending_and_mdba(self, api, system_operator_headers,
                                                         capital_analyst_headers):
        """PRD §3.6: "On approval the request moves PROPOSED →
        APPROVED_NOT_EXECUTED, its capacity_reserved_cents is set to the full
        distribution_amount_cents, that amount is added to the bank's
        pending_distribution_cents" and "may withdraw an
        APPROVED_NOT_EXECUTED request, moving it to WITHDRAWN, subtracting its
        capacity_reserved_cents from pending_distribution_cents, zeroing the
        reservation"

        Design: Difficulty/compensating_invariant/distribution_approve_withdraw_conserves_mdba_pending
        """
        # Propose while the plan is still APPROVED (PRD §3.6 gates proposals
        # to DRAFT…APPROVED); approval happens after the pool opens.
        created = {}

        def _propose(bank_id, plan, pay_period):
            created["dist"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="DIVIDEND", distribution_amount_cents=75_000_000,
                proposed_payment_date="2027-03-15",
            )

        bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
            "CH-CP1-001", scenario_code="BASE-CP1", pre_cross_hook=_propose
        )
        dist = created["dist"]
        before = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert before["pending_distribution_cents"] == 0
        mdba_before = before["mdba_cents"]
        approved = approve_distribution(bank["id"], dist["id"])
        assert approved["status"] == "APPROVED_NOT_EXECUTED"
        mid = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert mid["pending_distribution_cents"] == 75_000_000
        withdrawn = validate_success(
            api.withdraw_distribution(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        after = validate_success(api.get_bank(bank["id"], capital_analyst_headers))
        assert after["pending_distribution_cents"] == 0
        assert after["mdba_cents"] == mdba_before

    def test_capacity_reserved_set_on_approve_and_zeroed_on_withdraw(
        self, api, system_operator_headers, capital_analyst_headers
    ):
        """PRD §3.6: "its capacity_reserved_cents is set to the full
        distribution_amount_cents" and "subtracting its
        capacity_reserved_cents from pending_distribution_cents, zeroing the
        reservation, and incrementing the bank's version"

        Design: Difficulty/compensating_invariant/distribution_approve_withdraw_conserves_mdba_pending
        """
        # Propose while the plan is still APPROVED (PRD §3.6 gates proposals
        # to DRAFT…APPROVED); approval happens after the pool opens.
        created = {}

        def _propose(bank_id, plan, pay_period):
            created["dist"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="DIVIDEND", distribution_amount_cents=75_000_000,
                proposed_payment_date="2027-03-15",
            )

        bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
            "CH-CP1-002", scenario_code="BASE-CP1B", pre_cross_hook=_propose
        )
        dist = created["dist"]
        approved = approve_distribution(bank["id"], dist["id"])
        assert approved["capacity_reserved_cents"] == 75_000_000
        withdrawn = validate_success(
            api.withdraw_distribution(bank["id"], dist["id"], capital_analyst_headers)
        )
        assert withdrawn["capacity_reserved_cents"] == 0


class TestDistributionListing(object):
    def test_list_endpoints_support_filter_and_pagination(self, api, system_operator_headers,
                                                          capital_analyst_headers):
        """PRD §2.3: "distribution requests by capital_plan_id,
        reporting_period_id, status, and distribution_kind" and "the meta
        object of a list response carries limit, offset, total_count, and
        has_more."

        Design: Corner/endpoints/list_endpoints_support_filter_and_pagination
        """
        # Propose both requests while the plan is still APPROVED (PRD §3.6
        # gates proposals to DRAFT…APPROVED).
        created = {}

        def _propose(bank_id, plan, pay_period):
            created["d1"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="DIVIDEND", distribution_amount_cents=50_000_000,
                proposed_payment_date="2027-03-15",
            )
            created["d2"] = create_proposed_distribution(
                bank_id, plan["id"], pay_period["id"],
                distribution_kind="BUYBACK", distribution_amount_cents=30_000_000,
                proposed_payment_date="2027-03-20",
            )

        bank, base_period, pay_period, scenario, plan = setup_distributable_bank(
            "CH-FLL-001", scenario_code="BASE-FLL", pre_cross_hook=_propose
        )
        d1 = created["d1"]
        d2 = created["d2"]
        approve_distribution(bank["id"], d1["id"])
        # d2 remains PROPOSED; filter by status=PROPOSED with limit=1.
        data, meta = validate_paginated(
            api.list_distribution_requests(
                bank["id"], capital_analyst_headers,
                params={"status": "PROPOSED", "limit": 1},
            )
        )
        assert len(data) == 1
        assert data[0]["id"] == d2["id"]
        assert data[0]["status"] == "PROPOSED"
        assert meta["total_count"] == 1
