"""Feedback survey composite scoring, the submission window, the expire-due
sweep, and the community quality trend aggregation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_quality_trend,
    get_success_data,
    make_buyer_headers,
    make_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import submit_survey_payload


def _issued_survey(api, closing_date="2026-09-20T17:00:00Z",
                   orientation_start="2026-08-25T14:00:00Z"):
    """Community + buyer + rep + home with a completed orientation.
    Returns (community, buyer, rep, home, survey)."""
    community, buyer, rep = fx.setup_base()
    home = fx.setup_home(community["id"], buyer["id"], closing_date=closing_date)
    fx.setup_completed_orientation(home["id"], rep["id"], buyer["id"], orientation_start)
    survey = fx.get_survey_for_home(home["id"])
    return community, buyer, rep, home, survey


class TestCompositeScore:
    def test_detractor_cap_branch(self, api):
        """PRD §3.8: "A detractor cap then applies: when the lowest of the three
        ratings is exactly 1, the composite becomes the lesser of the penalized
        base and 2.0; otherwise the composite is the base itself."

        Design: Difficulty/combinatorial_formula/survey_composite_conditional_detractor_cap
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        submitted = validate_success(api.submit_feedback_survey(
            survey["id"],
            submit_survey_payload(overall_rating=1, systems_demo_rating=5,
                                  timeliness_rating=5, would_recommend=True),
            make_buyer_headers(buyer["id"]),
        ))
        # base = 0.5 + 1.5 + 1.0 = 3.0, but min rating is 1 -> capped at 2.0.
        assert submitted["composite_score"] == pytest.approx(2.0, abs=0.001), (
            f"detractor cap must force 2.00, got {submitted['composite_score']}"
        )

    def test_uncapped_branch_just_above_detractor(self, api):
        """PRD §3.8: "The composite score blends the three ratings with fixed
        weights: the base is `overall_rating` multiplied by 0.5, plus
        `systems_demo_rating` multiplied by 0.3, plus `timeliness_rating`
        multiplied by 0.2."
        PRD §3.8: "A detractor cap then applies: when the lowest of the three
        ratings is exactly 1, the composite becomes the lesser of the penalized
        base and 2.0; otherwise the composite is the base itself."

        Design: Difficulty/combinatorial_formula/survey_composite_conditional_detractor_cap
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        submitted = validate_success(api.submit_feedback_survey(
            survey["id"],
            submit_survey_payload(overall_rating=2, systems_demo_rating=5,
                                  timeliness_rating=5, would_recommend=True),
            make_buyer_headers(buyer["id"]),
        ))
        # base = 1.0 + 1.5 + 1.0 = 3.5; min rating 2 -> no cap. The one-point
        # input change crosses the conditional branch: the output moves by 1.5
        # against the capped sibling, not the 0.5 the linear weights imply.
        assert submitted["composite_score"] == pytest.approx(3.5, abs=0.001), (
            f"uncapped base must be 3.50, got {submitted['composite_score']}"
        )

    def test_no_recommend_penalty(self, api):
        """PRD §3.8: "When `would_recommend` is false, a penalty of 0.5 is
        subtracted from the base."

        Design: Corner/calculations/composite_no_recommend_penalty
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        submitted = validate_success(api.submit_feedback_survey(
            survey["id"],
            submit_survey_payload(overall_rating=5, systems_demo_rating=5,
                                  timeliness_rating=5, would_recommend=False),
            make_buyer_headers(buyer["id"]),
        ))
        assert submitted["composite_score"] == pytest.approx(4.5, abs=0.001), (
            f"5.0 minus the 0.5 penalty must be 4.50, got {submitted['composite_score']}"
        )


class TestSurveyWindow:
    def test_submit_at_exact_window_close_allowed(self, api):
        """PRD §3.8: "Submission is honored only while the logical clock has not
        passed `window_closes_at`; a late submission on a still-`ISSUED` survey
        is rejected with `ERR_SURVEY_EXPIRED`"
        PRD §3.8: "its `window_closes_at` fixed at the appointment's
        `completed_at` plus the community's `survey_window_days`"

        Design: Corner/calculations/survey_window_inclusive_deadline
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        assert survey["window_closes_at"].startswith("2026-09-08T14:00"), (
            f"completion at 2026-08-25T14:00 plus 14 days must close "
            f"2026-09-08T14:00, got {survey['window_closes_at']}"
        )
        fx.set_clock("2026-09-08T14:00:00Z")
        submitted = validate_success(api.submit_feedback_survey(
            survey["id"], submit_survey_payload(), make_buyer_headers(buyer["id"])
        ))
        assert submitted["status"] == "SUBMITTED"

    def test_submit_one_minute_past_window_rejected(self, api):
        """PRD §3.8: "Submission is honored only while the logical clock has not
        passed `window_closes_at`; a late submission on a still-`ISSUED` survey
        is rejected with `ERR_SURVEY_EXPIRED`"

        Design: Corner/errors/survey_submit_past_window_returns_survey_expired
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        fx.set_clock("2026-09-08T14:01:00Z")  # one minute past the deadline
        resp = api.submit_feedback_survey(
            survey["id"],
            submit_survey_payload(overall_rating=3, systems_demo_rating=3,
                                  timeliness_rating=3),
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_EXPIRED)


class TestExpireDueSweep:
    def test_sweep_expires_only_overdue_issued_surveys(self, api, manager_headers):
        """PRD §3.8: "Surveys that outlive their window are reaped by an ops
        sweep a `CustomerCareManager` can invoke: every survey still `ISSUED`
        whose `window_closes_at` lies before the current logical-clock instant
        moves to the terminal `EXPIRED`, each incrementing its own `version`,
        and the sweep answers with `expired_count` and the list
        `expired_survey_ids`."
        PRD §3.8: "submitting a survey that is no longer `ISSUED` is rejected
        with `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/survey_expire_due_sweep
        """
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way")
        fx.setup_completed_orientation(h1["id"], rep["id"], buyer["id"],
                                       "2026-08-25T14:00:00Z")
        s1 = fx.get_survey_for_home(h1["id"])
        fx.setup_completed_orientation(h2["id"], rep["id"], buyer["id"],
                                       "2026-08-26T14:00:00Z")
        s2 = fx.get_survey_for_home(h2["id"])
        fx.set_clock("2026-08-27T09:00:00Z")
        resp = api.submit_feedback_survey(
            s2["id"],
            submit_survey_payload(overall_rating=4, systems_demo_rating=4,
                                  timeliness_rating=4),
            make_buyer_headers(buyer["id"]),
        )
        assert resp.status_code == 200, f"Setup failed (submit s2): {resp.text}"
        # Past s1's window (2026-09-08T14:00); s2 already terminal.
        fx.set_clock("2026-09-09T00:00:00Z")

        sweep = validate_success(api.expire_due_feedback_surveys(manager_headers))
        assert sweep["expired_count"] == 1, (
            f"only s1 was ISSUED past its window, got {sweep['expired_count']}"
        )
        s1 = get_success_data(api.get_feedback_survey(s1["id"], manager_headers))
        s2 = get_success_data(api.get_feedback_survey(s2["id"], manager_headers))
        assert s1["status"] == "EXPIRED"
        assert s2["status"] == "SUBMITTED", (
            f"the submitted survey must be untouched, got {s2['status']}"
        )
        resp = api.submit_feedback_survey(
            s1["id"],
            submit_survey_payload(overall_rating=3, systems_demo_rating=3,
                                  timeliness_rating=3),
            make_buyer_headers(buyer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestQualityTrend:
    def _three_survey_community(self, api):
        """One community, one buyer, one rep; h1 completed twice (surveys 5.00
        and 2.00) and h2 once (survey 4.00), all submitted in August 2026."""
        community, buyer, rep = fx.setup_base()
        h1 = fx.setup_home(community["id"], buyer["id"], lot_number="L-101",
                           address="1 Riverbend Way")
        h2 = fx.setup_home(community["id"], buyer["id"], lot_number="L-102",
                           address="2 Riverbend Way")

        fx.setup_completed_orientation(h1["id"], rep["id"], buyer["id"],
                                       "2026-08-25T14:00:00Z")
        s1 = fx.get_survey_for_home(h1["id"], status="ISSUED")
        resp = api.submit_feedback_survey(s1["id"], submit_survey_payload(
            overall_rating=5, systems_demo_rating=5, timeliness_rating=5,
            would_recommend=True,
        ), make_buyer_headers(buyer["id"]))
        assert resp.status_code == 200, f"Setup failed (submit s1): {resp.text}"

        # Re-orientation on h1 (allowed from ORIENTED).
        fx.setup_completed_orientation(h1["id"], rep["id"], buyer["id"],
                                       "2026-08-26T14:00:00Z")
        s2 = fx.get_survey_for_home(h1["id"], status="ISSUED")
        resp = api.submit_feedback_survey(s2["id"], submit_survey_payload(
            overall_rating=1, systems_demo_rating=5, timeliness_rating=5,
            would_recommend=True,
        ), make_buyer_headers(buyer["id"]))
        assert resp.status_code == 200, f"Setup failed (submit s2): {resp.text}"

        fx.setup_completed_orientation(h2["id"], rep["id"], buyer["id"],
                                       "2026-08-27T14:00:00Z")
        s3 = fx.get_survey_for_home(h2["id"], status="ISSUED")
        resp = api.submit_feedback_survey(s3["id"], submit_survey_payload(
            overall_rating=4, systems_demo_rating=4, timeliness_rating=4,
            would_recommend=True,
        ), make_buyer_headers(buyer["id"]))
        assert resp.status_code == 200, f"Setup failed (submit s3): {resp.text}"
        return community

    def test_response_weighted_counts_every_survey_equally(self, api, manager_headers):
        """PRD §3.8: "`response_weighted_avg_score` lets every survey weigh
        equally: the sum of their `composite_score` values divided by their
        count, rounded half up to two decimal places, null when the count is
        zero."
        PRD §3.8: "The response echoes `period_month` and reports
        `submitted_survey_count`, the number of those surveys, and
        `homes_surveyed_count`, the number of distinct homes behind them."

        Design: Difficulty/dual_variant_calc/quality_trend_response_vs_home_weighted
        """
        community = self._three_survey_community(api)
        trend = validate_success(api.get_quality_trend(
            community["id"], manager_headers, params={"period_month": "2026-08"}
        ))
        assert trend["submitted_survey_count"] == 3
        assert trend["homes_surveyed_count"] == 2
        # round_half_up((5.00 + 2.00 + 4.00) / 3, 2) = 3.67
        assert trend["response_weighted_avg_score"] == pytest.approx(3.67, abs=0.001), (
            f"response-weighted average must be 3.67, "
            f"got {trend['response_weighted_avg_score']}"
        )

    def test_home_weighted_counts_every_home_equally(self, api, manager_headers):
        """PRD §3.8: "`home_weighted_avg_score` lets every home weigh equally:
        each home's composite scores are first averaged into a per-home mean
        rounded half up to two decimal places, then those per-home means are
        averaged across the distinct homes with at least one survey, again
        rounded half up to two decimal places, and null when no home has a
        survey in the window."
        PRD §3.8: "Two weightings answer different questions, and they diverge
        whenever homes contribute unequal numbers of surveys."

        Design: Difficulty/dual_variant_calc/quality_trend_response_vs_home_weighted
        """
        community = self._three_survey_community(api)
        trend = validate_success(api.get_quality_trend(
            community["id"], manager_headers, params={"period_month": "2026-08"}
        ))
        # per-home means: h1 = (5.00 + 2.00) / 2 = 3.50; h2 = 4.00; across
        # homes: (3.50 + 4.00) / 2 = 3.75
        assert trend["home_weighted_avg_score"] == pytest.approx(3.75, abs=0.001), (
            f"home-weighted average must be 3.75, got {trend['home_weighted_avg_score']}"
        )
        assert trend["home_weighted_avg_score"] != trend["response_weighted_avg_score"], (
            "the two weightings must diverge for unequal per-home survey counts"
        )

    def test_empty_month_yields_null_averages(self, api, manager_headers):
        """PRD §3.8: "`response_weighted_avg_score` lets every survey weigh
        equally: the sum of their `composite_score` values divided by their
        count, rounded half up to two decimal places, null when the count is
        zero."
        PRD §2.6: "An average computed over an empty set is null, never zero."

        Design: Corner/calculations/trend_empty_month_null_averages
        """
        community = fx.setup_community()
        trend = validate_success(api.get_quality_trend(
            community["id"], manager_headers, params={"period_month": "2026-07"}
        ))
        assert_quality_trend(trend)
        assert trend["submitted_survey_count"] == 0
        assert trend["response_weighted_avg_score"] is None
        assert trend["home_weighted_avg_score"] is None
        assert trend["avg_warrantable_items_per_home"] is None

    def test_half_open_month_boundary(self, api, manager_headers):
        """PRD §3.8: "Requested with a `period_month` in year-month form, the
        trend examines the half-open window from the first instant of that
        month up to — but not including — the first instant of the following
        month, and considers the community's `SUBMITTED` surveys whose
        `submitted_at` falls inside it."

        Design: Corner/calculations/trend_half_open_month_boundary
        """
        _c, buyer, _r, _h, survey = _issued_survey(api)
        fx.set_clock("2026-09-01T00:00:00Z")  # exactly the September boundary
        resp = api.submit_feedback_survey(
            survey["id"], submit_survey_payload(), make_buyer_headers(buyer["id"])
        )
        assert resp.status_code == 200, f"Setup failed (submit): {resp.text}"

        august = get_success_data(
            api.get_quality_trend(_c["id"], manager_headers,
                                  params={"period_month": "2026-08"})
        )
        assert august["submitted_survey_count"] == 0, (
            f"the boundary instant belongs to September, got "
            f"{august['submitted_survey_count']}"
        )
        september = get_success_data(
            api.get_quality_trend(_c["id"], manager_headers,
                                  params={"period_month": "2026-09"})
        )
        assert september["submitted_survey_count"] == 1
        assert september["response_weighted_avg_score"] == pytest.approx(5.0, abs=0.001)
