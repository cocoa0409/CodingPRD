"""Reconciliation lifecycle: pool gate, segregation, challenge gate,
validation-priority, and the estimate-vs-final recovery variants with gross-up."""
from test_helpers import (
    ApiErrorId,
    create_billing,
    create_pool,
    create_reconciliation_payload,
    create_tenant_challenge_payload,
    make_lease_accountant_headers,
    make_portfolio_manager_headers,
    record_actuals,
    set_clock,
    setup_active_lease,
    setup_approved_reconciliation,
    setup_posted_reconciliation,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ACCT = TEST_USERS["lease_accountant_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]


class TestReconciliationLifecycle:
    def test_reconciliation_initial_state_open(self, api):
        """PRD §3.6: "At fiscal year-end, a `LeaseAccountant` opens a
        Reconciliation for a lease and `fiscal_year`; it begins in `OPEN`."

        Design: Corner/state_machines/reconciliation_initial_state_open
        """
        ctx = setup_active_lease()
        resp = api.create_reconciliation(
            ctx["lease"]["id"], create_reconciliation_payload(fiscal_year=2026), ACCT,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "OPEN", f"expected OPEN, got {data['status']}"

    def test_reconciliation_approve_segregation_of_duties(self, api):
        """PRD §3.6: "Approval is segregation-controlled: a `PortfolioManager`
        approves a `POSTED` reconciliation, but only if the approver's
        `X-User-ID` differs from `posted_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; approval records `approved_by_user_id` and
        moves the reconciliation to `APPROVED`."

        Design: Corner/validations/reconciliation_approve_segregation_of_duties
        """
        poster = make_lease_accountant_headers("acct-1")
        ctx = setup_posted_reconciliation(poster_headers=poster)
        # Same operator id, now acting as PortfolioManager, attempts approval.
        resp = api.approve_reconciliation(
            ctx["reconciliation"]["id"], make_portfolio_manager_headers("acct-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_err_open_challenge_blocks_recon_close(self, api):
        """PRD §3.6: "Closing an `APPROVED` reconciliation requires that no
        TenantChallenge referencing it is in `OPEN`, `UNDER_REVIEW`, or
        `ESCALATED` status, else `ERR_OPEN_CHALLENGE`."

        Design: Corner/errors/err_open_challenge_blocks_recon_close
        """
        ctx = setup_approved_reconciliation()
        validate_success(
            api.create_tenant_challenge(
                ctx["lease"]["id"],
                create_tenant_challenge_payload(
                    reconciliation_id=ctx["reconciliation"]["id"],
                    reason_code="MATH_ERROR", claimed_overbilling_cents=100,
                ),
                PROP_MGR,
            ),
            201,
        )
        resp = api.close_reconciliation(ctx["reconciliation"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_CHALLENGE)


class TestReconciliationPostPoolGate:
    def _setup_two_pools_one_open(self, api):
        """Active lease; CAM pool actuals recorded, TAX pool actuals missing."""
        ctx = setup_active_lease(budgeted_cents=1200000)
        tax_pool = create_pool(ctx["property"]["id"], category="TAX",
                               fiscal_year=2026, budgeted_cents=600000)
        record_actuals(ctx["pool"]["id"], 1200000)
        resp = api.create_reconciliation(
            ctx["lease"]["id"], create_reconciliation_payload(fiscal_year=2026), ACCT,
        )
        ctx["reconciliation"] = validate_success(resp, 201)
        ctx["tax_pool"] = tax_pool
        return ctx

    def test_post_blocked_until_all_pools_closed(self, api):
        """PRD §3.6: "A `LeaseAccountant` may post the reconciliation only when
        every RecoveryPool on the lease's property for that fiscal year has its
        `actual_cents` populated, else the post is rejected with
        `ERR_POOL_NOT_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/reconciliation_post_requires_pools_closed
        """
        ctx = self._setup_two_pools_one_open(api)
        resp = api.post_reconciliation(ctx["reconciliation"]["id"], ACCT)
        validate_error(resp, ApiErrorId.ERR_POOL_NOT_CLOSED)

    def test_post_succeeds_after_all_pool_actuals_recorded(self, api):
        """PRD §3.6: "A `LeaseAccountant` may post the reconciliation only when
        every RecoveryPool on the lease's property for that fiscal year has its
        `actual_cents` populated, else the post is rejected with
        `ERR_POOL_NOT_CLOSED`."
        PRD §3.6: "Posting also records the acting operator as
        `posted_by_user_id`, moves the reconciliation to `POSTED`, and — when
        the true-up is positive, meaning the tenant underpaid — generates one
        additional RecoveryBilling for the delta in `DRAFT` status with
        `period_index` 13, the true-up period."

        Design: Difficulty/cross_entity_state_dependency/reconciliation_post_requires_pools_closed
        """
        ctx = self._setup_two_pools_one_open(api)
        validate_error(
            api.post_reconciliation(ctx["reconciliation"]["id"], ACCT),
            ApiErrorId.ERR_POOL_NOT_CLOSED,
        )
        record_actuals(ctx["tax_pool"]["id"], 600000)
        data = validate_success(
            api.post_reconciliation(ctx["reconciliation"]["id"], ACCT)
        )
        assert data["status"] == "POSTED", (
            f"after all pool actuals are recorded, post must succeed; got {data['status']}"
        )


class TestReconCloseValidationPriority:
    def test_double_close_fires_state_not_fiscal(self, api):
        """PRD §2.11: "Every request passes through a fixed validation pipeline,
        and the order is part of the contract: an earlier failure masks every
        later check, so the error a client observes is always the earliest
        applicable one."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409)." (The fiscal gate on
        reconciliation close is the twelfth stage.)

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_recon_close
        """
        ctx = setup_approved_reconciliation()
        validate_success(api.close_reconciliation(ctx["reconciliation"]["id"], PM))
        # Reconciliation is now CLOSED (terminal); a second close is a state
        # violation and must surface ERR_INVALID_STATE, not a fiscal gate error.
        resp = api.close_reconciliation(ctx["reconciliation"]["id"], PM)
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert data["error_id"] != ApiErrorId.ERR_OPEN_CHALLENGE

    def test_close_from_open_is_invalid_state(self, api):
        """PRD §3.6: "Closing an `APPROVED` reconciliation requires that no
        TenantChallenge referencing it is in `OPEN`, `UNDER_REVIEW`, or
        `ESCALATED` status, else `ERR_OPEN_CHALLENGE`."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409)."
        (Close is defined only from APPROVED or CHALLENGED; an OPEN
        reconciliation fails the state check before any fiscal gate.)

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_recon_close
        """
        ctx = setup_active_lease()
        recon = validate_success(
            api.create_reconciliation(
                ctx["lease"]["id"], create_reconciliation_payload(fiscal_year=2026),
                ACCT,
            ),
            201,
        )
        resp = api.close_reconciliation(recon["id"], PM)
        data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert data["error_id"] != ApiErrorId.ERR_OPEN_CHALLENGE


class TestRecoveryEstimateVsFinalWithGrossUp:
    """Single CAM pool, occupancy 4000 bps below the 9500 bps gross-up floor.

    estimate per period row = round_half_up(12000000 * 4000 / 10000 / 12)
    = 400000 (PRD §3.5). Grossed-up actual = round_half_up(10000000 * 9500 /
    4000) = 23750000; yearly share = round_half_up(23750000 * 4000 / 10000)
    = 9500000; waterfall row 1 = round_half_up(9500000 / 12) = 791667
    (PRD §3.6 steps 2-4).
    """

    def _setup(self, api):
        ctx = setup_active_lease(
            budgeted_cents=12000000, gross_up_floor_pct_bps=9500,
        )
        record_actuals(ctx["pool"]["id"], 10000000)
        recon = validate_success(
            api.create_reconciliation(
                ctx["lease"]["id"], create_reconciliation_payload(fiscal_year=2026),
                ACCT,
            ),
            201,
        )
        ctx["reconciliation"] = recon
        return ctx

    def test_estimate_variant_uses_budget_and_final_null_until_posted(self, api):
        """PRD §3.5: "The estimate projects the full-year budget into the
        period: the pool's `budgeted_cents` is multiplied by the lease's
        `pro_rata_share_bps`, divided by 10000, divided by the twelve billing
        periods of the year, and rounded half-up to whole cents."
        PRD §3.6: "Until a reconciliation is posted, every billing's
        `final_cents` remains null."

        Design: Difficulty/dual_variant_calc/recovery_billing_estimate_vs_final_with_gross_up
        """
        ctx = self._setup(api)
        billing = validate_success(
            api.get_recovery_billing(ctx["billing"]["id"], ACCT)
        )
        assert billing["estimate_cents"] == 400000, (
            f"estimate must project the budget: expected 400000, got "
            f"{billing['estimate_cents']}"
        )
        assert billing["final_cents"] is None, (
            f"final_cents must remain null before posting, got {billing['final_cents']}"
        )

    def test_final_variant_uses_grossed_up_actuals(self, api):
        """PRD §3.6: "Second, the gross-up rule is evaluated per pool: if the
        occupancy rate is below the pool's `gross_up_floor_pct_bps` and the
        pool's category is one of the variable categories `CAM` or `UTILITIES`,
        the pool's actual is scaled up — the `actual_cents` multiplied by the
        floor in basis points and divided by the observed occupancy rate in
        basis points, rounded half-up to whole cents — and the gross-up is
        recorded as having fired for that pool; in all other cases the pool's
        unadjusted `actual_cents` is used."
        PRD §3.6: "The reconciliation's `gross_up_applied` flag records whether
        any pool's gross-up rule fired."

        Design: Difficulty/dual_variant_calc/recovery_billing_estimate_vs_final_with_gross_up
        """
        ctx = self._setup(api)
        recon = validate_success(
            api.post_reconciliation(ctx["reconciliation"]["id"], ACCT)
        )
        assert recon["gross_up_applied"] is True, (
            "occupancy 4000 bps < floor 9500 bps on a CAM pool must fire gross-up"
        )
        billing = validate_success(
            api.get_recovery_billing(ctx["billing"]["id"], ACCT)
        )
        assert billing["final_cents"] == 791667, (
            f"row 1 of the waterfall must be round_half_up(9500000/12)=791667, "
            f"got {billing['final_cents']}"
        )
        assert billing["final_cents"] != billing["estimate_cents"], (
            "the final variant (grossed-up actuals) must diverge from the "
            "estimate variant (budget)"
        )


class TestReconciliationFinalGrossUpWaterfall:
    """CAM pool (variable, grossed up) plus TAX pool (fixed, not grossed up).

    CAM: grossed-up actual 23750000, yearly share 9500000; waterfall rows 1-11
    get round_half_up(9500000/12) = 791667, row 12 gets the remainder
    9500000 - 11*791667 = 791663 (PRD §3.6 step 4).
    """

    def _setup(self, api):
        ctx = setup_active_lease(
            budgeted_cents=12000000, gross_up_floor_pct_bps=9500,
            issue_billing_after_activation=False,
        )
        tax_pool = create_pool(ctx["property"]["id"], category="TAX",
                               fiscal_year=2026, budgeted_cents=2400000,
                               gross_up_floor_pct_bps=9500)
        cam_b1 = ctx["billing"]  # period_index 1, DRAFT
        cam_b12 = create_billing(ctx["lease"]["id"], ctx["pool"]["id"],
                                 fiscal_year=2026, period_index=12)
        # Lease is already ACTIVE from setup_active_lease; issue both rows now.
        from test_helpers import issue_billing as _issue
        _issue(cam_b1["id"])
        _issue(cam_b12["id"])
        record_actuals(ctx["pool"]["id"], 10000000)
        record_actuals(tax_pool["id"], 2000000)
        recon = validate_success(
            api.create_reconciliation(
                ctx["lease"]["id"], create_reconciliation_payload(fiscal_year=2026),
                ACCT,
            ),
            201,
        )
        posted = validate_success(api.post_reconciliation(recon["id"], ACCT))
        return ctx, cam_b1, cam_b12, posted

    def test_gross_up_fires_and_first_row_share(self, api):
        """PRD §3.6: "Fourth, that yearly share is allocated across the pool's
        twelve monthly billing rows as a waterfall: rows one through eleven each
        receive the yearly share divided by twelve and rounded half-up, and the
        twelfth row receives the remainder, so the rows sum to the yearly share
        exactly — the final period absorbs all rounding residue."
        PRD §3.6: "The reconciliation's `gross_up_applied` flag records whether
        any pool's gross-up rule fired."

        Design: Difficulty/combinatorial_formula/reconciliation_final_gross_up_waterfall
        """
        _, cam_b1, _, posted = self._setup(api)
        assert posted["gross_up_applied"] is True, (
            "4000 bps occupancy below the 9500 bps floor on CAM must fire gross-up"
        )
        row1 = validate_success(api.get_recovery_billing(cam_b1["id"], ACCT))
        assert row1["final_cents"] == 791667, (
            f"row 1 must receive round_half_up(9500000/12)=791667, got "
            f"{row1['final_cents']}"
        )

    def test_remainder_row_preserves_yearly_share_total(self, api):
        """PRD §3.6: "Fourth, that yearly share is allocated across the pool's
        twelve monthly billing rows as a waterfall: rows one through eleven each
        receive the yearly share divided by twelve and rounded half-up, and the
        twelfth row receives the remainder, so the rows sum to the yearly share
        exactly — the final period absorbs all rounding residue."

        Design: Difficulty/combinatorial_formula/reconciliation_final_gross_up_waterfall
        """
        _, cam_b1, cam_b12, _ = self._setup(api)
        row1 = validate_success(api.get_recovery_billing(cam_b1["id"], ACCT))
        row12 = validate_success(api.get_recovery_billing(cam_b12["id"], ACCT))
        assert row12["final_cents"] == 791663, (
            f"row 12 absorbs the remainder 9500000 - 11*791667 = 791663, got "
            f"{row12['final_cents']}"
        )
        assert 11 * row1["final_cents"] + row12["final_cents"] == 9500000, (
            "waterfall invariant: rows must sum to the yearly share exactly"
        )
