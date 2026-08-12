"""Tenant challenges (cyclic negotiation rounds, resolution sign rules) and
audit rights (window arithmetic, time-barring), plus the Lease's three
parallel state dimensions."""
from test_helpers import (
    ApiErrorId,
    create_audit_right_on,
    create_challenge_on,
    create_tenant_challenge_payload,
    set_clock,
    setup_active_lease,
    setup_approved_reconciliation,
    setup_closed_reconciliation,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ACCT = TEST_USERS["lease_accountant_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]


class TestChallengeCyclicReopen:
    def _setup_challenge(self, api):
        ctx = setup_approved_reconciliation()
        challenge = create_challenge_on(
            ctx["lease"]["id"], ctx["reconciliation"]["id"],
            reason_code="MATH_ERROR", claimed_overbilling_cents=1000,
        )
        return challenge

    def test_three_negotiation_rounds_increment_round_index(self, api):
        """PRD §3.9: "Negotiation proceeds in bounded rounds. A
        `LeaseAccountant` starts review, moving the challenge from `OPEN` to
        `UNDER_REVIEW`. If review stalls, the accountant may reopen the
        challenge back to `OPEN`, which increments `round_index` by one;
        reopening is allowed only while `round_index` is below 3, else
        `ERR_MAX_ROUNDS_REACHED`, so a challenge may cycle through at most three
        negotiation rounds."

        Design: Difficulty/non_linear_state_machine/tenant_challenge_cyclic_reopen
        """
        challenge = self._setup_challenge(api)
        assert challenge["round_index"] == 0
        for expected_round in (1, 2, 3):
            reviewing = validate_success(
                api.start_challenge_review(challenge["id"], ACCT)
            )
            assert reviewing["status"] == "UNDER_REVIEW"
            reopened = validate_success(api.reopen_challenge(challenge["id"], ACCT))
            assert reopened["status"] == "OPEN", (
                f"cycle must return the challenge to OPEN, got {reopened['status']}"
            )
            assert reopened["round_index"] == expected_round, (
                f"expected round_index {expected_round}, got {reopened['round_index']}"
            )

    def test_fourth_reopen_rejected_at_round_cap(self, api):
        """PRD §3.9: "If review stalls, the accountant may reopen the challenge
        back to `OPEN`, which increments `round_index` by one; reopening is
        allowed only while `round_index` is below 3, else
        `ERR_MAX_ROUNDS_REACHED`, so a challenge may cycle through at most three
        negotiation rounds."

        Design: Difficulty/non_linear_state_machine/tenant_challenge_cyclic_reopen
        """
        challenge = self._setup_challenge(api)
        for _ in range(3):
            validate_success(api.start_challenge_review(challenge["id"], ACCT))
            validate_success(api.reopen_challenge(challenge["id"], ACCT))
        validate_success(api.start_challenge_review(challenge["id"], ACCT))
        resp = api.reopen_challenge(challenge["id"], ACCT)
        validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_REACHED)


class TestChallengeResolution:
    def test_challenge_resolve_invalid_sign(self, api):
        """PRD §3.9: "Resolution is a `PortfolioManager` act carrying an
        `outcome` and a `resolution_delta_cents`, with sign rules enforced
        symmetrically: an accepted outcome requires a delta of zero or less —
        an accepted challenge means money back to the tenant, so a positive
        delta is rejected with `ERR_INVALID_RESOLUTION_SIGN` — while a rejected
        outcome requires a delta of exactly zero, any other value drawing the
        same error."

        Design: Corner/validations/challenge_resolve_invalid_sign
        """
        ctx = setup_approved_reconciliation()
        challenge = create_challenge_on(
            ctx["lease"]["id"], ctx["reconciliation"]["id"],
            reason_code="MATH_ERROR", claimed_overbilling_cents=1000,
        )
        validate_success(api.start_challenge_review(challenge["id"], ACCT))
        resp = api.resolve_challenge(
            challenge["id"],
            {"outcome": "ACCEPTED", "resolution_delta_cents": 500},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RESOLUTION_SIGN)


class TestLeaseParallelDimensions:
    def _setup_frozen_lease(self, api):
        """ACTIVE, CERTIFIED lease whose one ISSUED billing becomes DISPUTED
        through a linked challenge."""
        ctx = setup_approved_reconciliation()
        challenge = create_challenge_on(
            ctx["lease"]["id"], ctx["reconciliation"]["id"],
            recovery_billing_id=ctx["billing"]["id"],
            reason_code="GROSS_UP_DISPUTE", claimed_overbilling_cents=5000,
        )
        return ctx, challenge

    def test_dispute_freezes_posture_without_touching_lifecycle(self, api):
        """PRD §2.8: "A Lease carries three parallel state dimensions that
        evolve independently: `status` (the primary lifecycle: `DRAFT`,
        `ACTIVE`, `EXPIRED`, `TERMINATED`), `abstraction_status` (data quality:
        `PENDING`, `ABSTRACTED`, `CERTIFIED`), and `billing_posture` (financial
        health: `CURRENT`, `FROZEN`, `DELINQUENT`)."
        PRD §2.8: "When any RecoveryBilling of the lease enters `DISPUTED`, the
        lease's `billing_posture` transitions to `FROZEN`; when every
        RecoveryBilling has exited `DISPUTED`, the posture returns to
        `CURRENT`."

        Design: Difficulty/non_linear_state_machine/lease_parallel_dimensions
        """
        ctx, _ = self._setup_frozen_lease(api)
        lease = validate_success(api.get_lease(ctx["lease"]["id"], ACCT))
        assert lease["status"] == "ACTIVE", (
            f"lifecycle dimension untouched by the challenge, got {lease['status']}"
        )
        assert lease["billing_posture"] == "FROZEN", (
            f"a DISPUTED billing must freeze the posture, got {lease['billing_posture']}"
        )

    def test_dispute_freezes_posture_without_touching_abstraction(self, api):
        """PRD §2.8: "A Lease carries three parallel state dimensions that
        evolve independently: `status` (the primary lifecycle: `DRAFT`,
        `ACTIVE`, `EXPIRED`, `TERMINATED`), `abstraction_status` (data quality:
        `PENDING`, `ABSTRACTED`, `CERTIFIED`), and `billing_posture` (financial
        health: `CURRENT`, `FROZEN`, `DELINQUENT`)."
        PRD §3.9: "A new challenge begins `OPEN` with `round_index` at 0, and
        its arrival reconfigures the neighborhood: the linked reconciliation
        moves from `APPROVED` to `CHALLENGED`, a specifically linked billing
        moves from `ISSUED` to `DISPUTED`, the lease's `billing_posture` is
        recomputed — typically transitioning to `FROZEN` — and the property's
        `posture` recomputes in turn."

        Design: Difficulty/non_linear_state_machine/lease_parallel_dimensions
        """
        ctx, _ = self._setup_frozen_lease(api)
        billing = validate_success(api.get_recovery_billing(ctx["billing"]["id"], ACCT))
        assert billing["status"] == "DISPUTED", (
            f"the specifically linked billing must move to DISPUTED, got "
            f"{billing['status']}"
        )
        lease = validate_success(api.get_lease(ctx["lease"]["id"], ACCT))
        assert lease["abstraction_status"] == "CERTIFIED", (
            f"abstraction dimension untouched by the challenge, got "
            f"{lease['abstraction_status']}"
        )


class TestAuditWindow:
    def test_audit_window_close_arithmetic(self, api):
        """PRD §3.9: "A `PropertyManager` invokes an AuditRight against a closed
        reconciliation by supplying the `reconciliation_id` and the `invoked_on`
        date; the right begins `INVOKED`, and its `window_close_date` is
        computed as the date the reconciliation reached `CLOSED` plus 365 days —
        a fixed calendar rule with no rolling forward when the landing date
        falls on a weekend, and a strict boundary in which action attempted on
        the window-close date itself is already too late."
        (Close on 2027-03-15; +365 calendar days crosses the 2028 leap day, so
        the window closes on 2028-03-14.)

        Design: Corner/calculations/audit_window_close_arithmetic
        """
        ctx = setup_closed_reconciliation(close_clock="2027-03-15T00:00:00Z")
        right = create_audit_right_on(
            ctx["lease"]["id"], ctx["reconciliation"]["id"],
            invoked_on="2027-04-01",
        )
        assert right["status"] == "INVOKED"
        assert right["window_close_date"] == "2028-03-14", (
            f"2027-03-15 plus 365 days must be 2028-03-14, got "
            f"{right['window_close_date']}"
        )

    def test_audit_right_time_barred_on_window_pass(self, api):
        """PRD §3.9: "If the logical clock reaches the `window_close_date` while
        the right is still `INVOKED` or in `FIELDWORK`, the right transitions to
        `TIME_BARRED` and every `ESCALATED` challenge on the same reconciliation
        reverts to `UNDER_REVIEW`, the audit window having been missed.
        `SETTLED` and `TIME_BARRED` are terminal."
        PRD §2.7: "Advancing the clock is not a passive read: it triggers all
        date-driven system transitions whose thresholds have been crossed,
        including lease expiration, critical-date lapsing, compliance-document
        expiry, and audit-right time-barring, each as described in §3."

        Design: Corner/state_machines/audit_right_time_barred_on_window_pass
        """
        ctx = setup_closed_reconciliation(close_clock="2027-03-15T00:00:00Z")
        right = create_audit_right_on(
            ctx["lease"]["id"], ctx["reconciliation"]["id"],
            invoked_on="2027-04-01",
        )
        assert right["window_close_date"] == "2028-03-14"
        # Advance past the window close; the right auto-transitions.
        set_clock("2028-03-15T00:00:00Z")
        after = validate_success(api.get_audit_right(right["id"], PROP_MGR))
        assert after["status"] == "TIME_BARRED", (
            f"clock past window_close_date must time-bar the right, got "
            f"{after['status']}"
        )
        resp = api.start_audit_fieldwork(right["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
