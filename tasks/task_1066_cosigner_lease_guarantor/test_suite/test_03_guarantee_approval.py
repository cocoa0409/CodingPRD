"""Guarantee approval: affordability boundary, exposure gate, validation precedence,
and access control (PRD §3.4, §2.1, §2.9)."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    setup_quoted_guarantee, create_portfolio, create_applicant, create_quoted_guarantee,
    make_underwriter_headers, TEST_USERS, build_user_headers,
)


class TestRentToIncomeBoundary:
    """rent_to_income_ratio of exactly 0.40 is rejected (inclusive failure side)."""

    def test_ratio_exactly_040_rejected(self, api):
        """PRD §3.4: "The boundary is inclusive on the failure side: a ratio of exactly
        0.40 is rejected, and only a ratio strictly under 0.40 (such as 0.399999)
        passes; a violation raises `ERR_RENT_TO_INCOME_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/rent_to_income_inclusive_boundary_rejects_exactly_040
        """
        ctx = setup_quoted_guarantee(
            api, applicant_overrides={"credit_score": 740, "annual_income_cents": 6_000_000,
                                      "monthly_obligations_cents": 100_000},
            guarantee_overrides={"monthly_rent_cents": 200_000, "coverage_months": 6,
                                 "term_months": 12})
        resp = api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_RENT_TO_INCOME_EXCEEDED.value)

    def test_ratio_exactly_040_leaves_guarantee_quoted(self, api):
        """PRD §3.4: "Approving a guarantee advances it from `QUOTED` to `APPROVED`".
        PRD §3.4: "a ratio of exactly 0.40 is rejected ... a violation raises
        `ERR_RENT_TO_INCOME_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/rent_to_income_inclusive_boundary_rejects_exactly_040
        """
        ctx = setup_quoted_guarantee(
            api, applicant_overrides={"credit_score": 740, "annual_income_cents": 6_000_000,
                                      "monthly_obligations_cents": 100_000},
            guarantee_overrides={"monthly_rent_cents": 200_000, "coverage_months": 6,
                                 "term_months": 12})
        api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        fetched = get_success_data(api.get_guarantee(ctx["g_id"],
                                                    make_underwriter_headers("uw1")))
        assert fetched["status"] == "QUOTED", \
            f"a rejected approve must leave status QUOTED, got {fetched['status']}"


class TestApproveValidationPrecedence:
    """business_referential (priority 8) masks business_fiscal (priority 12)."""

    def _setup_unverified_tiny_cap(self, api):
        pf = create_portfolio(api, exposure_cap_cents=1)
        ap = create_applicant(api, credit_score=740, annual_income_cents=12_000_000,
                             monthly_obligations_cents=200_000)  # NOT verified
        g = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1",
                                    monthly_rent_cents=249_999, coverage_months=6,
                                    term_months=12)
        return g

    def test_unverified_applicant_masks_exposure_breach(self, api):
        """PRD §2.9: "then cross-entity referential preconditions (409), then compliance
        holds (409), then temporal-window rules (409), then unit-overlap rules (409),
        then fiscal gates (409)".
        PRD §3.4: "The backing applicant must be `VERIFIED`; an approval attempted while
        the applicant is still `DRAFT` or has been `DECLINED` is rejected with
        `ERR_APPLICANT_NOT_VERIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_referential_beats_fiscal_exposure
        """
        g = self._setup_unverified_tiny_cap(api)
        resp = api.approve_guarantee(g["id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_VERIFIED.value)

    def test_unverified_masking_leaves_guarantee_quoted(self, api):
        """PRD §3.4: "an approval attempted while the applicant is still `DRAFT` or has
        been `DECLINED` is rejected with `ERR_APPLICANT_NOT_VERIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_referential_beats_fiscal_exposure
        """
        g = self._setup_unverified_tiny_cap(api)
        api.approve_guarantee(g["id"], make_underwriter_headers("uw1"))
        fetched = get_success_data(api.get_guarantee(g["id"], make_underwriter_headers("uw1")))
        assert fetched["status"] == "QUOTED"


class TestExposureCapGate:
    def test_projected_exposure_exceeds_cap_rejected(self, api):
        """PRD §3.4: "If the projected figure would strictly exceed the portfolio's
        `exposure_cap_cents`, the approval is refused; a projection that lands exactly on
        the cap is allowed."

        Design: Corner/validations/approve_exposure_cap_exceeded_isolated_returns_409
        """
        ctx = setup_quoted_guarantee(
            api, portfolio_overrides={"exposure_cap_cents": 100},
            applicant_overrides={"credit_score": 740, "annual_income_cents": 12_000_000,
                                 "monthly_obligations_cents": 200_000},
            guarantee_overrides={"monthly_rent_cents": 200_000, "coverage_months": 6,
                                 "term_months": 12})
        resp = api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_CAP_EXCEEDED.value)


class TestApproveStateAndAccess:
    def test_approve_already_approved_rejected(self, api):
        """PRD §3.4: "Approving a guarantee advances it from `QUOTED` to `APPROVED`".
        PRD §2.9: "then the target resource's own state (`ERR_INVALID_STATE`, 409, or a
        state-specific sibling)".

        Design: Corner/state_machines/approve_already_approved_guarantee_returns_invalid_state
        """
        ctx = setup_quoted_guarantee(api)
        get_success_data(api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        resp = api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_recovery_agent_cannot_approve_guarantee(self, api):
        """PRD §2.1: "When the headers are valid but the role is not permitted to perform
        the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/validations/forbidden_role_recovery_agent_approves_guarantee_returns_403
        """
        ctx = setup_quoted_guarantee(api)
        resp = api.approve_guarantee(ctx["g_id"], build_user_headers("ra1", "RecoveryAgent"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_get_nonexistent_guarantee_returns_404(self, api):
        """PRD §2.9: "then resource existence (`ERR_NOT_FOUND`, 404)".

        Design: Corner/entities/guarantee_not_found_returns_404
        """
        resp = api.get_guarantee("00000000-0000-4000-8000-000000000000",
                                TEST_USERS["underwriter_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
        roles the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api.create_portfolio({"name": "NoAuth", "exposure_cap_cents": 1_000_000}, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
