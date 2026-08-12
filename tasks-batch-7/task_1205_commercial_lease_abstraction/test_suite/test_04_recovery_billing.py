"""Recovery pools and recovery billings: defaults, terminal states, the
issue/void compensating invariant on cached_recovery_ytd_cents, and RBAC."""
from test_helpers import (
    ApiErrorId,
    assert_recovery_billing,
    create_billing,
    create_pool,
    create_property,
    set_clock,
    setup_active_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ACCT = TEST_USERS["lease_accountant_headers"]
PM = TEST_USERS["portfolio_manager_headers"]


class TestRecoveryPoolDefaults:
    def test_recovery_pool_gross_up_floor_default(self, api):
        """PRD §3.5: "Each pool also carries a `gross_up_floor_pct_bps`, an
        occupancy threshold in basis points from 0 to 10000 that defaults to
        9500 when not supplied; its meaning is defined in §3.6."

        Design: Corner/entities/recovery_pool_gross_up_floor_default
        """
        set_clock()
        prop = create_property()
        pool = create_pool(prop["id"], category="CAM", fiscal_year=2026,
                           budgeted_cents=1000000)
        assert pool["gross_up_floor_pct_bps"] == 9500, (
            f"default floor must be 9500, got {pool['gross_up_floor_pct_bps']}"
        )


class TestRecoveryBillingTerminalStates:
    def test_recovery_billing_invalid_transition_from_paid(self, api):
        """PRD §3.5: "Voiding is available from `DRAFT` without conditions and
        from `ISSUED` only while the billing remains unpaid; voiding an issued
        billing subtracts its `estimate_cents` from the lease's
        `cached_recovery_ytd_cents` and recomputes `billing_posture`. `PAID`
        and `VOID` are terminal."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/recovery_billing_invalid_transition_from_paid
        """
        ctx = setup_active_lease()
        billing = ctx["billing"]  # ISSUED (fixture issues after activation)
        assert billing["status"] == "ISSUED"
        resp = api.mark_recovery_billing_paid(billing["id"], ACCT)
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        resp = api.void_recovery_billing(billing["id"], ACCT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestIssueVoidInvariant:
    def _setup_two_billings(self, api):
        """Active lease; b1 (period 1, still DRAFT) and b2 (period 2, ISSUED).

        estimate per row = round_half_up(12000000 * 4000 / 10000 / 12) = 400000
        (PRD §3.5 estimate formula).
        """
        ctx = setup_active_lease(budgeted_cents=12000000,
                                 issue_billing_after_activation=False)
        b1 = ctx["billing"]
        assert b1["estimate_cents"] == 400000
        b2 = create_billing(ctx["lease"]["id"], ctx["pool"]["id"],
                            fiscal_year=2026, period_index=2)
        resp = api.issue_recovery_billing(b2["id"], ACCT)
        b2 = validate_success(resp)
        assert b2["status"] == "ISSUED"
        return ctx, b1, b2

    def test_issue_adds_estimate_to_cached_recovery_ytd(self, api):
        """PRD §3.5: "Issuing stamps `issued_at` with the current logical UTC
        time, adds the `estimate_cents` to the lease's
        `cached_recovery_ytd_cents`, recomputes the lease's `billing_posture`,
        and moves the billing to `ISSUED`."

        Design: Difficulty/compensating_invariant/recovery_billing_issue_void_invariant
        """
        ctx, b1, _ = self._setup_two_billings(api)
        before = validate_success(api.get_lease(ctx["lease"]["id"], PM))
        assert before["cached_recovery_ytd_cents"] == 400000, (
            f"only b2 issued so far, expected 400000, got "
            f"{before['cached_recovery_ytd_cents']}"
        )
        issued = validate_success(api.issue_recovery_billing(b1["id"], ACCT))
        assert issued["status"] == "ISSUED"
        after = validate_success(api.get_lease(ctx["lease"]["id"], PM))
        assert after["cached_recovery_ytd_cents"] == 800000, (
            f"b1 + b2 issued, expected 800000, got "
            f"{after['cached_recovery_ytd_cents']}"
        )

    def test_void_after_issue_restores_cached_recovery_ytd(self, api):
        """PRD §3.5: "Voiding is available from `DRAFT` without conditions and
        from `ISSUED` only while the billing remains unpaid; voiding an issued
        billing subtracts its `estimate_cents` from the lease's
        `cached_recovery_ytd_cents` and recomputes `billing_posture`."

        Design: Difficulty/compensating_invariant/recovery_billing_issue_void_invariant
        """
        ctx, b1, _ = self._setup_two_billings(api)
        validate_success(api.issue_recovery_billing(b1["id"], ACCT))
        voided = validate_success(api.void_recovery_billing(b1["id"], ACCT))
        assert voided["status"] == "VOID"
        after = validate_success(api.get_lease(ctx["lease"]["id"], PM))
        assert after["cached_recovery_ytd_cents"] == 400000, (
            "issue+void must conserve cached_recovery_ytd_cents at its "
            f"pre-issue value 400000, got {after['cached_recovery_ytd_cents']}"
        )


class TestRecoveryBillingRbac:
    def test_portfolio_manager_cannot_issue_billing(self, api):
        """PRD §2.1: "If the role is recognized but not authorized for the
        target endpoint per the authorization matrix in §4, the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        (PRD §4 assigns POST /lease-admin/recovery-billings/{billing_id}/issue
        to LeaseAccountant only.)

        Design: Corner/endpoints/portfolio_manager_cannot_issue_billing
        """
        ctx = setup_active_lease()
        extra = create_billing(ctx["lease"]["id"], ctx["pool"]["id"],
                               fiscal_year=2026, period_index=2)
        assert_recovery_billing(extra)
        resp = api.issue_recovery_billing(extra["id"], PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
