"""Guarantee renewal cycle, default cascade, coverage conservation, and terminal
lockdown (PRD §3.4, §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    setup_active_guarantee, pay_fee_payload,
    make_underwriter_headers, make_applicant_headers, TEST_USERS,
)


class TestRenewalCycle:
    """Cyclic ACTIVE -> RENEWAL_PENDING -> ACTIVE loop with renewal_count increment."""

    def _renew_and_confirm(self, api, ctx):
        uw = make_underwriter_headers("uw1")
        get_success_data(api.renew_guarantee(ctx["g_id"], uw))
        get_success_data(api.pay_fee(ctx["g_id"], pay_fee_payload(67500),
                                    make_applicant_headers(ctx["ap_id"])))
        return validate_success(api.confirm_renewal(ctx["g_id"], uw))

    def test_confirm_renewal_returns_to_active_with_incremented_count(self, api):
        """PRD §3.5: "the `Underwriter` confirms the renewal, returning the guarantee
        from `RENEWAL_PENDING` to `ACTIVE`."
        PRD §3.5: "On confirmation the guarantee's `renewal_count` increases by one".

        Design: Difficulty/non_linear_state_machine/guarantee_renewal_cycle_returns_to_active
        """
        ctx = setup_active_guarantee(api)
        confirmed = self._renew_and_confirm(api, ctx)
        assert confirmed["status"] == "ACTIVE"
        assert confirmed["renewal_count"] == 1, \
            f"expected renewal_count 1, got {confirmed['renewal_count']}"

    def test_confirm_renewal_resets_remaining_coverage(self, api):
        """PRD §3.5: "its `remaining_coverage_cents` is reset back to
        `total_coverage_cents` with `paid_out_cents` returned to 0".

        Design: Difficulty/non_linear_state_machine/guarantee_renewal_cycle_returns_to_active
        """
        ctx = setup_active_guarantee(api)
        confirmed = self._renew_and_confirm(api, ctx)
        assert confirmed["remaining_coverage_cents"] == 1349994, \
            f"expected reset coverage 1349994, got {confirmed['remaining_coverage_cents']}"


class TestDefaultCascade:
    """declare-default -> applicant.default_count -> auto ComplianceReview."""

    def test_default_marks_guarantee_and_bumps_applicant_count(self, api):
        """PRD §3.5: "moving it to the terminal `DEFAULTED` state."
        PRD §3.5: "The backing applicant's `default_count` is incremented by one."

        Design: Difficulty/transitive_cascade/guarantee_default_cascades_applicant_and_compliance
        """
        ctx = setup_active_guarantee(api)
        defaulted = validate_success(api.declare_default(ctx["g_id"],
                                                        make_underwriter_headers("uw1")))
        assert defaulted["status"] == "DEFAULTED"
        applicant = get_success_data(api.get_applicant(ctx["ap_id"],
                                                      TEST_USERS["underwriter_headers"]))
        assert applicant["default_count"] == 1, \
            f"expected default_count 1, got {applicant['default_count']}"

    def test_default_auto_creates_open_compliance_review(self, api):
        """PRD §3.5: "the mutation of the applicant in turn causes a `ComplianceReview`
        to be auto-created in `OPEN` status against this guarantee with a `reason` of
        `AUTO_DEFAULT_TRIGGER`."

        Design: Difficulty/transitive_cascade/guarantee_default_cascades_applicant_and_compliance
        """
        ctx = setup_active_guarantee(api)
        get_success_data(api.declare_default(ctx["g_id"], make_underwriter_headers("uw1")))
        data, meta = validate_paginated(api.list_compliance_reviews(
            TEST_USERS["compliance_officer_headers"], params={"guarantee_id": ctx["g_id"]}))
        assert meta["total_count"] == 1, f"expected one review, got {meta['total_count']}"
        assert data[0]["reason"] == "AUTO_DEFAULT_TRIGGER"
        assert data[0]["status"] == "OPEN"


class TestActiveCoverageConservation:
    """portfolio.total_active_coverage_cents: activate +X, default -X, back to 0."""

    def test_activation_adds_total_coverage_to_portfolio(self, api):
        """PRD §3.4: "the portfolio's `total_active_coverage_cents` is increased by this
        guarantee's `total_coverage_cents`".

        Design: Difficulty/compensating_invariant/active_coverage_conserved_activate_then_default
        """
        ctx = setup_active_guarantee(api)
        pf = get_success_data(api.get_portfolio(ctx["pf_id"],
                                               TEST_USERS["platform_admin_headers"]))
        assert pf["total_active_coverage_cents"] == 1349994, \
            f"expected 1349994 after activate, got {pf['total_active_coverage_cents']}"

    def test_default_restores_total_coverage_to_zero(self, api):
        """PRD §3.5: "The portfolio's `total_active_coverage_cents` is reduced by this
        guarantee's `total_coverage_cents`, conserving the active-coverage total."

        Design: Difficulty/compensating_invariant/active_coverage_conserved_activate_then_default
        """
        ctx = setup_active_guarantee(api)
        get_success_data(api.declare_default(ctx["g_id"], make_underwriter_headers("uw1")))
        pf = get_success_data(api.get_portfolio(ctx["pf_id"],
                                               TEST_USERS["platform_admin_headers"]))
        assert pf["total_active_coverage_cents"] == 0, \
            f"expected 0 after default, got {pf['total_active_coverage_cents']}"


class TestTerminalLockdown:
    def test_cancel_defaulted_guarantee_rejected(self, api):
        """PRD §3.5: "Either an `Underwriter` or a `ClaimsAdjuster` may declare a renter
        default on a guarantee that is in `ACTIVE`, moving it to the terminal `DEFAULTED`
        state."
        PRD §2.9: "then the target resource's own state (`ERR_INVALID_STATE`, 409, or a
        state-specific sibling)".

        Design: Corner/state_machines/cancel_defaulted_guarantee_terminal_lockdown_returns_invalid_state
        """
        ctx = setup_active_guarantee(api)
        get_success_data(api.declare_default(ctx["g_id"], make_underwriter_headers("uw1")))
        resp = api.cancel_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
