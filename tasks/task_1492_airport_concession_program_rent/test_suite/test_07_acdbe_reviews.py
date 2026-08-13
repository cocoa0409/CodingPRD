"""ACDBE participation reviews: the attainment threshold boundary, zero-sales
handling, cure sufficiency, and review-state and role gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_acdbe_review,
    create_acdbe_review,
    file_and_accept_report,
    make_tenant_headers,
    setup_active_lease,
    validate_error,
    validate_success,
)


class TestAttainmentBoundary:
    def test_attainment_exactly_at_goal_is_compliant(self, api, analyst_headers):
        """PRD §3.7: "Otherwise, attainment at or above the lease's `acdbe_goal_bp` —
        meeting the goal exactly attains it — is `COMPLIANT`, and anything below is
        `DEFICIENT`."
        PRD §3.7: "The system computes `total_gross_cents`, the year's effective
        gross summed over the lease's `ACCEPTED` and `ADJUSTED` reports, and
        `attainment_bp`, the certified revenue multiplied by ten thousand, divided by
        the total gross, and rounded half up to integer basis points."

        Design: Difficulty/boundary_precision_check/acdbe_attainment_exactly_at_goal
        """
        sc = setup_active_lease(acdbe_goal_bp=2000)
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-04", 1_000_000)
        review = create_acdbe_review(sc["lease"], period_year=2026)

        res = api.evaluate_acdbe_review(
            review["id"], {"certified_revenue_cents": 200_000}, analyst_headers
        )
        evaluated = validate_success(res, 200)
        assert evaluated["total_gross_cents"] == 1_000_000
        assert evaluated["attainment_bp"] == 2000, (
            "200,000 * 10000 / 1,000,000 = 2000 bp, exactly the goal"
        )
        assert evaluated["status"] == "COMPLIANT"

    def test_attainment_below_goal_is_deficient(self, api, analyst_headers):
        """PRD §3.7: "Otherwise, attainment at or above the lease's `acdbe_goal_bp` —
        meeting the goal exactly attains it — is `COMPLIANT`, and anything below is
        `DEFICIENT`."

        Design: Difficulty/boundary_precision_check/acdbe_attainment_exactly_at_goal
        """
        sc = setup_active_lease(acdbe_goal_bp=2000)
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-04", 1_000_000)
        review = create_acdbe_review(sc["lease"], period_year=2026)

        res = api.evaluate_acdbe_review(
            review["id"], {"certified_revenue_cents": 199_000}, analyst_headers
        )
        evaluated = validate_success(res, 200)
        assert evaluated["attainment_bp"] == 1990
        assert evaluated["status"] == "DEFICIENT"


class TestZeroSales:
    def test_acdbe_zero_sales_is_deficient(self, api, analyst_headers):
        """PRD §3.7: "When the year's total gross is zero, attainment is zero and the
        outcome is `DEFICIENT`."

        Design: Corner/calculations/acdbe_zero_sales_is_deficient
        """
        sc = setup_active_lease()
        review = create_acdbe_review(sc["lease"], period_year=2026)
        res = api.evaluate_acdbe_review(
            review["id"], {"certified_revenue_cents": 0}, analyst_headers
        )
        evaluated = validate_success(res, 200)
        assert evaluated["total_gross_cents"] == 0
        assert evaluated["attainment_bp"] == 0
        assert evaluated["status"] == "DEFICIENT"


class TestCure:
    def test_cure_insufficient_returns_cure_insufficient(self, api, analyst_headers):
        """PRD §3.7: "The owning tenant submits `cure_additional_certified_cents` —
        zero until a cure is attempted — and attainment is recomputed with the cure
        amount added to the certified revenue against the stored total gross. If the
        recomputed attainment still falls short of the goal, the cure is rejected
        with `ERR_CURE_INSUFFICIENT`; on success the review moves to `CURED`."

        Design: Corner/validations/cure_insufficient_returns_cure_insufficient
        """
        sc = setup_active_lease(acdbe_goal_bp=2000)
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-04", 1_000_000)
        review = create_acdbe_review(sc["lease"], period_year=2026)
        evaluated = validate_success(
            api.evaluate_acdbe_review(
                review["id"], {"certified_revenue_cents": 100_000}, analyst_headers
            ),
            200,
        )
        assert evaluated["status"] == "DEFICIENT"  # 1000 bp < 2000 bp goal

        # Cure of 50,000 lifts attainment to 1500 bp — still short of the goal.
        res = api.cure_acdbe_review(
            review["id"],
            {"cure_additional_certified_cents": 50_000},
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CURE_INSUFFICIENT)

        after = validate_success(
            api.get_acdbe_review(review["id"], analyst_headers), 200
        )
        assert after["status"] == "DEFICIENT"


class TestReviewStateGate:
    def test_evaluate_closed_review_returns_review_state_forbids(
        self, api, analyst_headers
    ):
        """PRD §3.7: "Evaluation is valid only from `SCHEDULED`; from any other
        status it is rejected with `ERR_REVIEW_STATE_FORBIDS`."
        PRD §3.7: "`COMPLIANT` and `CURED` are the terminal outcomes."

        Design: Corner/validations/evaluate_closed_review_returns_review_state_forbids
        """
        sc = setup_active_lease(acdbe_goal_bp=2000)
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-04", 1_000_000)
        review = create_acdbe_review(sc["lease"], period_year=2026)
        evaluated = validate_success(
            api.evaluate_acdbe_review(
                review["id"], {"certified_revenue_cents": 300_000}, analyst_headers
            ),
            200,
        )
        assert evaluated["status"] == "COMPLIANT"

        res = api.evaluate_acdbe_review(
            review["id"], {"certified_revenue_cents": 100}, analyst_headers
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_STATE_FORBIDS)


class TestReviewRbac:
    def test_auditor_cannot_evaluate_acdbe_returns_forbidden(
        self, api, auditor_headers
    ):
        """PRD §2.1: "Once authenticated, the acting role must appear in the
        endpoint's authorized role list as given in §4; otherwise the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /concessions/acdbe-reviews/{id}/evaluate is authorized to
        ConcessionAnalyst only.

        Design: Corner/rbac/auditor_cannot_evaluate_acdbe_returns_forbidden
        """
        sc = setup_active_lease()
        review = create_acdbe_review(sc["lease"], period_year=2026)
        res = api.evaluate_acdbe_review(
            review["id"], {"certified_revenue_cents": 100_000}, auditor_headers
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
