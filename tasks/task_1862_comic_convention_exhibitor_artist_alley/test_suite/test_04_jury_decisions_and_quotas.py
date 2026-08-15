"""Jury scoring, composite computation, quorum, decisions, and quota caps."""
import pytest

from test_helpers import (
    CLOCK_JURY_REVIEW,
    SCORES_40,
    SCORES_60,
    STANDARD_SCORES,
    TEST_USERS,
    ApiErrorId,
    advance_phase,
    assert_application,
    assert_jury_score,
    create_application,
    decide,
    get_application,
    get_quota,
    make_juror_headers,
    post_jury_score,
    post_scores,
    register_exhibitor,
    set_clock,
    setup_decided_application,
    setup_jury_review_application,
    setup_open_convention,
    setup_two_applications_decided,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestJuryScoreCreation:
    def test_jury_score_immutable_no_version_field(self, api):
        """PRD §2.4: "Two resources are immutable after creation and carry only
        `id` and `created_at`: the JuryScore and the DockDoor. Both `updated_at`
        and `version` are absent on those two resources, and no operation
        modifies them once created."
        PRD §3.4: "The posting juror's `X-User-ID` is recorded as the score's
        `juror_user_id`."

        Design: Corner/entities/jury_score_immutable_no_version_field
        """
        bundle = setup_jury_review_application()  # SUBMITTED, JURY_REVIEW phase
        app_id = bundle["application"]["id"]
        resp = api.create_jury_score(
            {
                "application_id": app_id,
                "originality": 80,
                "craft": 90,
                "category_fit": 70,
                "professionalism": 60,
            },
            make_juror_headers("juror-1"),
        )
        data = validate_success(resp, 201)
        assert_jury_score(data)
        assert data["juror_user_id"] == "juror-1"
        # 0.35*80 + 0.25*90 + 0.25*70 + 0.15*60 = 77.00
        assert data["weighted_total"] == pytest.approx(77.00, abs=0.005)

    def test_first_jury_score_moves_application_under_review(self, api):
        """PRD §3.4: "The very first score posted for an application moves it
        automatically from `SUBMITTED` to `UNDER_REVIEW`."

        Design: Corner/state_machines/first_jury_score_moves_application_under_review
        """
        bundle = setup_jury_review_application()  # SUBMITTED, no scores yet
        app_id = bundle["application"]["id"]
        assert bundle["application"]["status"] == "SUBMITTED"
        post_jury_score(app_id, "juror-1", 80, 90, 70, 60)
        assert get_application(app_id)["status"] == "UNDER_REVIEW"


class TestJuryIntegrityGuards:
    def test_jury_conflict_of_interest_rejected(self, api, director_headers):
        """PRD §3.4: "Two guards protect the panel's integrity: a juror whose
        identifier appears in the application's `conflicted_juror_user_ids` may
        not score it (`ERR_JURY_CONFLICT_OF_INTEREST`), and a juror who has
        already scored the application may not score it again
        (`ERR_DUPLICATE_JURY_SCORE`)."

        Design: Corner/validations/jury_conflict_of_interest_rejected
        """
        bundle = setup_jury_review_application(
            conflicted_juror_user_ids=["juror-9"],
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        resp = api.create_jury_score(
            {
                "application_id": app_id,
                "originality": 80,
                "craft": 80,
                "category_fit": 80,
                "professionalism": 80,
            },
            make_juror_headers("juror-9"),
        )
        validate_error(resp, ApiErrorId.ERR_JURY_CONFLICT_OF_INTEREST)
        scores, meta = validate_paginated(
            api.list_jury_scores(director_headers, params={"application_id": app_id})
        )
        assert meta["total_count"] == 0, "no JuryScore may be persisted"
        assert get_application(app_id)["status"] == "SUBMITTED"

    def test_duplicate_jury_score_same_juror_rejected(self, api):
        """PRD §3.4: "Two guards protect the panel's integrity: a juror whose
        identifier appears in the application's `conflicted_juror_user_ids` may
        not score it (`ERR_JURY_CONFLICT_OF_INTEREST`), and a juror who has
        already scored the application may not score it again
        (`ERR_DUPLICATE_JURY_SCORE`)."

        Design: Corner/validations/duplicate_jury_score_same_juror_rejected
        """
        bundle = setup_jury_review_application(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        post_jury_score(app_id, "juror-1", 80, 90, 70, 60)  # weighted 77.00
        resp = api.create_jury_score(
            {
                "application_id": app_id,
                "originality": 10,
                "craft": 10,
                "category_fit": 10,
                "professionalism": 10,
            },
            make_juror_headers("juror-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURY_SCORE)
        # The composite still reflects only the original 77.00 score.
        composite = get_application(app_id)["jury_composite_score"]
        assert composite == pytest.approx(77.00, abs=0.005)


class TestDecisionBands:
    def test_accept_below_score_threshold_rejected(self, api):
        """PRD §3.4: "An acceptance requires a `jury_composite_score` of at
        least 70.00 (`ERR_SCORE_BELOW_THRESHOLD`) and room in the category — the
        quota's `accepted_count` still below `max_accepted`
        (`ERR_CATEGORY_QUOTA_FULL`)."
        PRD §3.4: "In band terms: at 70.00 or above, acceptance is permitted; at
        least 50.00 but below 70.00, only waitlisting or rejection remain; below
        50.00, only rejection is possible."

        Design: Corner/validations/accept_below_score_threshold_rejected
        """
        bundle = setup_jury_review_application(
            scores=SCORES_60,
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_id = bundle["application"]["id"]
        assert bundle["application"]["jury_composite_score"] == pytest.approx(60.00)
        resp = api.decide_application(
            app_id, {"decision": "ACCEPTED"}, TEST_USERS["director_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD)
        assert get_application(app_id)["status"] == "UNDER_REVIEW"

    def test_decide_rejected_path_with_low_scores(self, api):
        """PRD §3.4: "A rejection carries no score floor."
        PRD §3.4: "Rejection moves it to the terminal `JURIED_REJECTED` and
        additionally turns every `PENDING` neighbor request in which this
        application's exhibitor is requester or target to `MOOT`."

        Design: Corner/state_machines/decide_rejected_path_with_low_scores
        """
        bundle = setup_decided_application(
            decision="REJECTED",
            scores=SCORES_40,
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app = bundle["application"]
        assert_application(app)
        assert app["status"] == "JURIED_REJECTED"
        assert app["jury_composite_score"] == pytest.approx(40.00, abs=0.005)
        assert app["decided_at"] is not None
        quota = get_quota(bundle["convention"]["id"], "DEALER")
        assert quota["accepted_count"] == 0
        assert quota["waitlisted_count"] == 0


class TestQuotaCaps:
    def test_category_quota_full_blocks_second_accept(self, api):
        """PRD §3.4: "An acceptance requires a `jury_composite_score` of at
        least 70.00 (`ERR_SCORE_BELOW_THRESHOLD`) and room in the category — the
        quota's `accepted_count` still below `max_accepted`
        (`ERR_CATEGORY_QUOTA_FULL`)."

        Design: Corner/validations/category_quota_full_blocks_second_accept
        """
        # A accepted (fills DEALER max_accepted 1); B fully scored (77.67) but
        # left UNDER_REVIEW.
        bundle = setup_two_applications_decided(
            decision_a="ACCEPTED",
            decision_b=None,
            scores_a=STANDARD_SCORES,
            scores_b=STANDARD_SCORES,
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        app_b_id = bundle["application_b"]["id"]
        assert bundle["application_b"]["status"] == "UNDER_REVIEW"
        resp = api.decide_application(
            app_b_id, {"decision": "ACCEPTED"}, TEST_USERS["director_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_CATEGORY_QUOTA_FULL)
        assert get_application(app_b_id)["status"] == "UNDER_REVIEW"
        quota = get_quota(bundle["convention"]["id"], "DEALER")
        assert quota["accepted_count"] == 1
        assert quota["waitlisted_count"] == 0

    def test_waitlist_full_blocks_second_waitlist(self, api):
        """PRD §3.4: "A waitlisting requires a composite of at least 50.00
        (`ERR_SCORE_BELOW_THRESHOLD`) and the quota's `waitlisted_count` below
        `max_waitlisted` (`ERR_WAITLIST_FULL`)."

        Design: Corner/validations/waitlist_full_blocks_second_waitlist
        """
        bundle = setup_open_convention(
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        conv_id = bundle["convention"]["id"]
        ex_a = register_exhibitor(legal_name="Dealer A LLC", category="DEALER")
        ex_b = register_exhibitor(legal_name="Dealer B LLC", category="DEALER")
        ex_c = register_exhibitor(legal_name="Dealer C LLC", category="DEALER")
        app_a = create_application(conv_id, ex_a["id"], category="DEALER")
        app_b = create_application(conv_id, ex_b["id"], category="DEALER")
        app_c = create_application(conv_id, ex_c["id"], category="DEALER")
        submit_application(app_a["id"], ex_a["id"])
        submit_application(app_b["id"], ex_b["id"])
        submit_application(app_c["id"], ex_c["id"])
        set_clock(CLOCK_JURY_REVIEW)
        advance_phase(conv_id)
        post_scores(app_a["id"], STANDARD_SCORES)
        post_scores(app_b["id"], SCORES_60)
        post_scores(app_c["id"], SCORES_60)
        decide(app_a["id"], "ACCEPTED")
        decide(app_b["id"], "WAITLISTED")
        # C's composite 60.00 satisfies the score band; only the cap blocks.
        resp = api.decide_application(
            app_c["id"], {"decision": "WAITLISTED"}, TEST_USERS["director_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_WAITLIST_FULL)
        assert get_application(app_c["id"])["status"] == "UNDER_REVIEW"

    def test_quota_patch_below_accepted_count_rejected(self, api, director_headers):
        """PRD §3.1: "The director may later adjust a quota's `max_accepted` or
        `max_waitlisted`, but lowering `max_accepted` below the live
        `accepted_count` is rejected with `ERR_QUOTA_BELOW_ACCEPTED`."

        Design: Corner/validations/quota_patch_below_accepted_count_rejected
        """
        bundle = setup_decided_application(
            decision="ACCEPTED",
            category_quotas=[
                {"category": "DEALER", "max_accepted": 1, "max_waitlisted": 1}
            ],
            dock_doors=[],
        )
        quota = get_quota(bundle["convention"]["id"], "DEALER")
        assert quota["accepted_count"] == 1
        resp = api.patch_category_quota(
            quota["id"], {"max_accepted": 0}, director_headers
        )
        validate_error(resp, ApiErrorId.ERR_QUOTA_BELOW_ACCEPTED)
        assert get_quota(bundle["convention"]["id"], "DEALER")["max_accepted"] == 1


class TestCompositeAndQuorum:
    def test_weighted_totals_and_composite_computation(self, api):
        """PRD §3.4: "Each score's `weighted_total` is 35 percent of
        `originality` plus 25 percent of `craft` plus 25 percent of
        `category_fit` plus 15 percent of `professionalism`, rounded half-up to
        two decimal places."
        PRD §3.4: "The application's `jury_composite_score` is the mean of the
        `weighted_total` values across its distinct-juror scores, itself rounded
        half-up to two decimal places — the per-juror rounding happens before
        the mean is taken — and it stays null until the first score exists."

        Design: Difficulty/combinatorial_formula/jury_composite_weighted_quorum_gating
        """
        bundle = setup_jury_review_application()
        app_id = bundle["application"]["id"]
        first = post_jury_score(app_id, "juror-1", 80, 90, 70, 60)
        assert first["weighted_total"] == pytest.approx(77.00, abs=0.005)
        post_jury_score(app_id, "juror-2", 90, 80, 80, 80)  # 83.50
        post_jury_score(app_id, "juror-3", 70, 70, 80, 70)  # 72.50
        composite = get_application(app_id)["jury_composite_score"]
        # round_half_up((77.00 + 83.50 + 72.50) / 3) = round_half_up(77.6666...)
        assert composite == pytest.approx(77.67, abs=0.005)

    def test_decide_accepted_with_qualifying_composite(self, api):
        """PRD §3.4: "An acceptance requires a `jury_composite_score` of at
        least 70.00 (`ERR_SCORE_BELOW_THRESHOLD`) and room in the category — the
        quota's `accepted_count` still below `max_accepted`
        (`ERR_CATEGORY_QUOTA_FULL`)."
        PRD §3.4: "Acceptance moves the application to `JURIED_ACCEPTED` and
        increments the quota's `accepted_count`; waitlisting moves it to
        `JURIED_WAITLISTED` and increments `waitlisted_count`."

        Design: Difficulty/combinatorial_formula/jury_composite_weighted_quorum_gating
        """
        bundle = setup_jury_review_application(scores=STANDARD_SCORES)
        app_id = bundle["application"]["id"]
        decided = decide(app_id, "ACCEPTED")
        assert decided["status"] == "JURIED_ACCEPTED"
        assert decided["jury_composite_score"] == pytest.approx(77.67, abs=0.005)
        quota = get_quota(bundle["convention"]["id"], "DEALER")
        assert quota["accepted_count"] == 1

    def test_decide_with_two_scores_rejected_by_quorum(self, api):
        """PRD §3.4: "Every decision first requires a quorum: at least three
        scores from distinct `juror_user_id` values must exist, or the attempt
        is rejected with `ERR_JURY_QUORUM_NOT_MET`."

        Design: Difficulty/boundary_precision_check/jury_quorum_exactly_three_scores
        """
        bundle = setup_jury_review_application(scores=STANDARD_SCORES[:2])
        app_id = bundle["application"]["id"]
        resp = api.decide_application(
            app_id, {"decision": "ACCEPTED"}, TEST_USERS["director_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_JURY_QUORUM_NOT_MET)
        assert get_application(app_id)["status"] == "UNDER_REVIEW"

    def test_decide_with_three_scores_admitted(self, api):
        """PRD §3.4: "Every decision first requires a quorum: at least three
        scores from distinct `juror_user_id` values must exist, or the attempt
        is rejected with `ERR_JURY_QUORUM_NOT_MET`."
        PRD §3.4: "An acceptance requires a `jury_composite_score` of at least
        70.00 (`ERR_SCORE_BELOW_THRESHOLD`) and room in the category — the
        quota's `accepted_count` still below `max_accepted`
        (`ERR_CATEGORY_QUOTA_FULL`)."

        Design: Difficulty/boundary_precision_check/jury_quorum_exactly_three_scores
        """
        bundle = setup_jury_review_application(scores=STANDARD_SCORES[:2])
        app_id = bundle["application"]["id"]
        resp = api.decide_application(
            app_id, {"decision": "ACCEPTED"}, TEST_USERS["director_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_JURY_QUORUM_NOT_MET)
        # The third distinct-juror score admits the decision.
        post_jury_score(app_id, "juror-3", 70, 70, 80, 70)
        decided = decide(app_id, "ACCEPTED")
        assert decided["status"] == "JURIED_ACCEPTED"
        assert decided["jury_composite_score"] == pytest.approx(77.67, abs=0.005)
