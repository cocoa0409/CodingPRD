"""Composite score variants and the approval threshold (PRD §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_application_under_review, create_board_ready_application,
    post_full_rubric, create_interview_payload, make_staff_headers,
    make_reviewer_headers, make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _provisional_application():
    """Application UNDER_REVIEW with rubric 90/70/80/80/80 (rubric_score 80.0)
    and a SCHEDULED but unscored interview."""
    app = create_application_under_review(school_name="DV Composite Academy",
                                          applicant_id="applicant_dv1")
    post_full_rubric(app["id"], "rev_dv1", (90, 70, 80, 80, 80))
    interview = get_success_data(api_client.schedule_interview(
        app["id"],
        create_interview_payload(scheduled_start="2026-05-10T10:00:00Z",
                                 scheduled_end="2026-05-10T11:00:00Z",
                                 panelist_user_ids=["rev_panel_dv1"]),
        STAFF))
    return app, interview


class TestCompositeProvisionalVsFinal:
    def test_provisional_composite_equals_rubric_before_interview(self, api):
        """PRD §3.1: "From the moment the rubric completes until a capacity
        interview is scored, the application carries the `PROVISIONAL` value of
        `composite_variant`, and its `composite_score` simply equals the
        `rubric_score` — the interview contributes nothing yet, and
        `interview_score` remains null."

        Design: Difficulty/dual_variant_calc/application_composite_provisional_vs_final
        """
        app, _interview = _provisional_application()
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["rubric_score"] == pytest.approx(80.0, abs=0.001)
        assert current["composite_score"] == pytest.approx(80.0, abs=0.001)
        assert current["composite_variant"] == "PROVISIONAL"
        assert current["interview_score"] is None

    def test_final_composite_recomputed_when_interview_scored(self, api):
        """PRD §3.1: "Scoring moves the interview `SCHEDULED` → `SCORED` and
        ripples back to the application: `interview_score` takes the panel's
        value, `composite_variant` flips to `FINAL`, and `composite_score` is
        recomputed as six-tenths of the `rubric_score` plus four-tenths of the
        `interview_score`, rounded half-up to one decimal place."

        Design: Difficulty/dual_variant_calc/application_composite_provisional_vs_final
        """
        app, interview = _provisional_application()
        validate_success(api.score_interview(
            interview["id"], {"panel_score": 65},
            make_reviewer_headers("rev_panel_dv1")), 200)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        # 0.6 * 80.0 + 0.4 * 65 = 48.0 + 26.0 = 74.0
        assert current["rubric_score"] == pytest.approx(80.0, abs=0.001)
        assert current["interview_score"] == 65
        assert current["composite_score"] == pytest.approx(74.0, abs=0.001)
        assert current["composite_variant"] == "FINAL"


class TestCompositeThresholdBoundary:
    def test_composite_exactly_75_approves(self, api):
        """PRD §3.1: "Approval requires the application to sit in `BOARD_REVIEW`
        and its `composite_score` to reach at least 75.0 — the threshold is
        inclusive — so a composite below 75.0 is rejected with
        `ERR_COMPOSITE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/composite_threshold_exactly_75_approves
        """
        app, _interview = create_board_ready_application(
            school_name="BP Boundary Academy A", applicant_id="applicant_bp1",
            reviewer_id="rev_bp1", rubric_scores=(75, 75, 75, 75, 75),
            panelist_id="rev_panel_bp1", panel_score=75,
            interview_start="2026-06-02T09:00:00Z",
            interview_end="2026-06-02T10:00:00Z")
        assert app["composite_score"] == pytest.approx(75.0, abs=0.001)
        decided = validate_success(
            api.decide_application(app["id"], {"outcome": "APPROVED"},
                                   make_board_headers("board_1")), 200)
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "board_1"

    def test_composite_74_6_rejected_below_threshold(self, api):
        """PRD §3.1: "Approval requires the application to sit in `BOARD_REVIEW`
        and its `composite_score` to reach at least 75.0 — the threshold is
        inclusive — so a composite below 75.0 is rejected with
        `ERR_COMPOSITE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/composite_threshold_exactly_75_approves
        """
        app, _interview = create_board_ready_application(
            school_name="BP Boundary Academy B", applicant_id="applicant_bp1",
            reviewer_id="rev_bp1", rubric_scores=(75, 75, 75, 75, 75),
            panelist_id="rev_panel_bp1", panel_score=74,
            interview_start="2026-06-02T11:00:00Z",
            interview_end="2026-06-02T12:00:00Z")
        # 0.6 * 75.0 + 0.4 * 74 = 45.0 + 29.6 = 74.6
        assert app["composite_score"] == pytest.approx(74.6, abs=0.001)
        res = api.decide_application(app["id"], {"outcome": "APPROVED"},
                                     make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_COMPOSITE_BELOW_THRESHOLD, expected_status=422)
        after = validate_success(api.get_application(app["id"], STAFF), 200)
        assert after["status"] == "BOARD_REVIEW"
        assert after["decided_by_user_id"] is None
