"""Account standards and the certification review lifecycle: creation
defaults, rubric variants, mandatory floor, score boundaries, SoD, RBAC."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS, make_coalition_admin_headers,
    create_account_standard_payload, make_criteria_ratings,
    create_standard, create_institution, open_review, score_review,
    finalize_review, setup_effective_standard, setup_scored_review,
    setup_rubric_divergence, setup_two_institutions_scored,
    assert_account_standard,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]
FINALIZER = make_coalition_admin_headers("admin-finalizer")


class TestStandardCreation:
    def test_standard_created_in_draft_with_common_fields(self, api):
        """PRD §3.1: "A new standard begins in `DRAFT` status."
        PRD §2.4: "Every top-level resource carries a system-generated `id` formatted as a UUID with no type prefix, a `created_at` ISO 8601 UTC timestamp with three fractional digits marking creation, an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation, and a `version` integer that increments by one on every mutation."

        Design: Corner/entities/account_standard_creation_defaults
        """
        resp = api.create_account_standard(create_account_standard_payload(), ADMIN)
        data = validate_success(resp, 201)
        assert_account_standard(data)
        assert data["status"] == "DRAFT", "new standard must begin DRAFT"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int)


class TestReviewPrerequisites:
    def test_review_against_draft_standard_rejected(self, api):
        """PRD §3.1: "The pinned standard must be `EFFECTIVE`; opening a review against a standard in any other status is rejected with `ERR_STANDARD_NOT_EFFECTIVE`."

        Design: Corner/errors/review_against_draft_standard_rejected
        """
        std = create_standard()  # never activated -> DRAFT
        inst = create_institution()
        resp = api.create_certification_review(
            {
                "institution_id": inst["id"],
                "standard_id": std["id"],
                "period_start": "2026-02-01",
                "period_end": "2026-02-28",
                "expected_institution_version": inst["version"],
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_EFFECTIVE)
        _, meta = validate_paginated(
            api.list_certification_reviews(ADMIN, params={"institution_id": inst["id"]})
        )
        assert meta["total_count"] == 0, "no review row may be created"


class TestSegregationOfDuties:
    def test_scoring_admin_cannot_finalize(self, api):
        """PRD §3.1: "Segregation of duties is enforced: the finalizer's `X-User-ID` must differ from the recorded `scored_by_user_id`, and a matching finalizer is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_same_admin_cannot_finalize
        """
        solo = make_coalition_admin_headers("admin-solo")
        ctx = setup_scored_review(scorer=solo)  # all ratings 4 -> score 100.00
        rev_id = ctx["review"]["id"]

        resp = api.finalize_certification_review(rev_id, solo)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        resp = api.finalize_certification_review(
            rev_id, make_coalition_admin_headers("admin-second")
        )
        data = validate_success(resp, 200)
        assert data["status"] == "FINALIZED_PASS"


class TestReviewRbac:
    def test_navigator_cannot_finalize_review(self, api):
        """PRD §4: "| POST | `/api/certification-reviews/{id}/finalize` | Finalize a scored review; applies the institution outcome | CoalitionAdmin |"
        PRD §2.1: "A request whose role is not authorized for the targeted endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/navigator_cannot_finalize_review
        """
        ctx = setup_scored_review()
        rev_id = ctx["review"]["id"]
        resp = api.finalize_certification_review(rev_id, NAV)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        review = get_success_data(api.get_certification_review(rev_id, ADMIN))
        assert review["status"] == "SCORED", "rejected finalize must not move the review"


class TestRubricVariantDivergence:
    def test_identical_scores_standard_rubric_lands_conditional(self, api):
        """PRD §3.1: "Under `STANDARD_RUBRIC`, the outcome is `FAIL` when `mandatory_floor_failed` is true; otherwise `PASS` when the `weighted_score` is at least 90.00; otherwise `CONDITIONAL` when the score is at least 75.00; otherwise `FAIL`. Under `REMEDIATION_RUBRIC` the same floor applies, but the `PASS` threshold is 85.00 and the `CONDITIONAL` floor is 70.00, so an identical ratings set can land in a different band depending on the pinned rubric."
        PRD §3.1: "The `weighted_score` is one hundred times the weighted sum of the ratings divided by four, rounded half-up to two decimal places, with criterion weights of 0.25 for `FEE_COMPLIANCE`, 0.20 for `ACCESS`, 0.15 for `ALT_ID`, 0.20 for `CHEX_POLICY`, and 0.20 for `EDUCATION_SUPPORT`."

        Design: Difficulty/dual_variant_calc/certification_rubric_variant_divergence
        """
        ctx = setup_rubric_divergence()  # ratings 4/4/4/4/1 -> 85.00 on both
        rev1 = get_success_data(api.get_certification_review(ctx["review1"]["id"], ADMIN))
        rev2 = get_success_data(api.get_certification_review(ctx["review2"]["id"], ADMIN))
        assert rev1["weighted_score"] == pytest.approx(85.0, abs=0.001)
        assert rev2["weighted_score"] == pytest.approx(85.0, abs=0.001), (
            "identical ratings must yield identical arithmetic under either rubric"
        )
        assert rev1["status"] == "FINALIZED_CONDITIONAL", (
            "85.00 < 90.00 PASS floor under STANDARD_RUBRIC"
        )

    def test_identical_scores_remediation_rubric_lands_pass(self, api):
        """PRD §3.1: "Under `REMEDIATION_RUBRIC` the same floor applies, but the `PASS` threshold is 85.00 and the `CONDITIONAL` floor is 70.00, so an identical ratings set can land in a different band depending on the pinned rubric."
        PRD §3.1: "At most one standard is `EFFECTIVE` at any moment: activation automatically transitions whatever standard was previously `EFFECTIVE` to `SUPERSEDED`."

        Design: Difficulty/dual_variant_calc/certification_rubric_variant_divergence
        """
        ctx = setup_rubric_divergence()
        data = finalize_review(ctx["review2"]["id"])
        assert data["status"] == "FINALIZED_PASS", (
            "85.00 >= 85.00 PASS floor under REMEDIATION_RUBRIC"
        )
        std_s = get_success_data(api.get_account_standard(ctx["standard_s"]["id"], ADMIN))
        assert std_s["status"] == "SUPERSEDED", (
            "activating the remediation standard supersedes the prior EFFECTIVE one"
        )


class TestMandatoryFloorBranch:
    def test_floor_ratings_still_score_85(self, api):
        """PRD §3.1: "The `weighted_score` is one hundred times the weighted sum of the ratings divided by four, rounded half-up to two decimal places, with criterion weights of 0.25 for `FEE_COMPLIANCE`, 0.20 for `ACCESS`, 0.15 for `ALT_ID`, 0.20 for `CHEX_POLICY`, and 0.20 for `EDUCATION_SUPPORT`."
        PRD §3.1: "The `mandatory_floor_failed` flag is set to true when either the `FEE_COMPLIANCE` rating or the `CHEX_POLICY` rating is at most 1, and false otherwise."

        Design: Difficulty/combinatorial_formula/certification_score_mandatory_floor_branch
        """
        # 4/4/4/1/4 -> 1.0+0.8+0.6+0.2+0.8 = 3.4 -> 100*3.4/4 = 85.00
        ctx = setup_scored_review(ratings=make_criteria_ratings(chex=1))
        rev = get_success_data(api.get_certification_review(ctx["review"]["id"], ADMIN))
        assert rev["weighted_score"] == pytest.approx(85.0, abs=0.001)
        assert rev["mandatory_floor_failed"] is True, "CHEX_POLICY rating 1 <= floor 1"

    def test_floor_failure_finalizes_fail_and_decertifies(self, api):
        """PRD §3.1: "Under `STANDARD_RUBRIC`, the outcome is `FAIL` when `mandatory_floor_failed` is true; otherwise `PASS` when the `weighted_score` is at least 90.00; otherwise `CONDITIONAL` when the score is at least 75.00; otherwise `FAIL`."
        PRD §3.1: "On `FAIL`, the institution moves from `UNDER_REVIEW` to `DECERTIFIED` and a four-link cascade runs: every `AccountOpeningEvent` of the institution still in `SCHEDULED` moves to `CANCELLED`; each cancelled event's referrals in `BOOKED` move back to `DOCS_COMPLETE` with their `booked_event_id` cleared; each affected participant's `pipeline_stage` is recomputed per §3.4; and the institution's `current_review_id` is cleared."

        Design: Difficulty/combinatorial_formula/certification_score_mandatory_floor_branch
        """
        ctx = setup_scored_review(ratings=make_criteria_ratings(chex=1))
        data = finalize_review(ctx["review"]["id"])
        assert data["status"] == "FINALIZED_FAIL", (
            "floor failure overrides the 85.00 score sitting in the CONDITIONAL band"
        )
        inst = get_success_data(api.get_partner_institution(ctx["institution"]["id"], ADMIN))
        assert inst["certification_status"] == "DECERTIFIED"


class TestScoreBoundaryNinety:
    def test_exactly_90_finalizes_pass(self, api):
        """PRD §3.1: "otherwise `PASS` when the `weighted_score` is at least 90.00" (STANDARD_RUBRIC).
        PRD §3.1: "The `weighted_score` is one hundred times the weighted sum of the ratings divided by four, rounded half-up to two decimal places, with criterion weights of 0.25 for `FEE_COMPLIANCE`, 0.20 for `ACCESS`, 0.15 for `ALT_ID`, 0.20 for `CHEX_POLICY`, and 0.20 for `EDUCATION_SUPPORT`."

        Design: Difficulty/boundary_precision_check/certification_score_exactly_90_passes
        """
        # 4/4/4/4/2 -> 1.0+0.8+0.6+0.8+0.4 = 3.6 -> 90.00
        ctx = setup_two_institutions_scored(
            make_criteria_ratings(edu=2), make_criteria_ratings(fee=3, edu=3)
        )
        data = finalize_review(ctx["review1"]["id"])
        rev = get_success_data(api.get_certification_review(ctx["review1"]["id"], ADMIN))
        assert rev["weighted_score"] == pytest.approx(90.0, abs=0.001)
        assert data["status"] == "FINALIZED_PASS", (
            "90.00 >= 90.00: a strictly-greater comparison would wrongly fail it"
        )

    def test_88_75_finalizes_conditional(self, api):
        """PRD §3.1: "otherwise `PASS` when the `weighted_score` is at least 90.00; otherwise `CONDITIONAL` when the score is at least 75.00; otherwise `FAIL`."
        PRD §3.1: "The `weighted_score` is one hundred times the weighted sum of the ratings divided by four, rounded half-up to two decimal places, with criterion weights of 0.25 for `FEE_COMPLIANCE`, 0.20 for `ACCESS`, 0.15 for `ALT_ID`, 0.20 for `CHEX_POLICY`, and 0.20 for `EDUCATION_SUPPORT`."

        Design: Difficulty/boundary_precision_check/certification_score_exactly_90_passes
        """
        # 3/4/4/4/3 -> 0.75+0.8+0.6+0.8+0.6 = 3.55 -> 88.75
        ctx = setup_two_institutions_scored(
            make_criteria_ratings(edu=2), make_criteria_ratings(fee=3, edu=3)
        )
        data = finalize_review(ctx["review2"]["id"])
        rev = get_success_data(api.get_certification_review(ctx["review2"]["id"], ADMIN))
        assert rev["weighted_score"] == pytest.approx(88.75, abs=0.001)
        assert data["status"] == "FINALIZED_CONDITIONAL", (
            "88.75 < 90.00 but >= 75.00 lands in the CONDITIONAL band"
        )
