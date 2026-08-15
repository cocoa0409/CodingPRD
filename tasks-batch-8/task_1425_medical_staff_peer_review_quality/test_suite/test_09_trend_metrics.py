"""Provider quality-trend metrics: the pinned per-case-then-window rounding
order, the half-open 365-day window, rated-set filtering, and the exact
average threshold of the focused-review trigger."""
import pytest

from test_helpers import (
    AFTER_DEADLINE,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assign_reviewer,
    create_case,
    create_provider,
    drive_case_to_notified,
    get_case,
    get_quality_trend,
    refer_external_payload,
    screen_case_in,
    seat_member,
    set_clock,
    setup_case_closed_no_response,
    setup_committee,
    submit_scores,
    validate_success,
)

QD = TEST_USERS["quality_director_headers"]


def _two_notified_cases(scores1, scores2, subject_specialty="CARDIOLOGY",
                        member_specialties=("CARDIOLOGY", "SURGERY", "PEDIATRICS")):
    """Committee + two cases for the same subject, both driven to NOTIFIED
    before either is resolved (so the resolution cascade's AUTO conflict
    declarations cannot block the second case's assignments)."""
    ctx = setup_committee(subject_specialty=subject_specialty,
                          member_specialties=member_specialties)
    case1, _, _ = drive_case_to_notified(
        ctx, scores=scores1, referral_source="PATIENT_COMPLAINT", description="case one")
    case2, _, _ = drive_case_to_notified(
        ctx, scores=scores2, referral_source="STAFF_REFERRAL",
        referred_at="2026-07-21T00:00:00Z", description="case two")
    set_clock(AFTER_DEADLINE)
    return ctx, case1, case2


class TestCaseMeanVersusScoreMean:
    def test_first_close_reports_single_case_average_without_trigger(self):
        """PRD §3.8: "Each rated case first yields a per-case average: the
        mean of its three `SUBMITTED` care appropriateness scores, rounded
        half-up to two decimal places."
        PRD §3.8: "The `avg_care_appropriateness` is the mean of those
        per-case averages, again rounded half-up to two decimal places — and
        it is null when `rated_case_count` is zero."

        Design: Difficulty/dual_variant_calc/trend_case_mean_vs_score_mean_variant
        """
        ctx, case1, _ = _two_notified_cases(((3, None), (3, None), (3, None)),
                                            ((3, None), (3, None), (2, None)))
        validate_success(api_client.close_no_response(case1["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        assert trend["rated_case_count"] == 1
        assert trend["avg_care_appropriateness"] == pytest.approx(3.00, abs=0.001)
        assert trend["focused_review_would_trigger"] is False

    def test_second_close_reports_case_mean_of_rounded_means(self):
        """PRD §3.8: "Following §2.6's pinned rounding order, the per-case
        means are rounded before they are averaged; to see why the order
        matters, consider two rated cases scored 3, 3, 3 and 3, 3, 2 — the
        pinned order reports 2.84, while averaging the six raw scores directly
        would report 2.83, and only the former is correct."

        Design: Difficulty/dual_variant_calc/trend_case_mean_vs_score_mean_variant
        """
        ctx, case1, case2 = _two_notified_cases(((3, None), (3, None), (3, None)),
                                                ((3, None), (3, None), (2, None)))
        validate_success(api_client.close_no_response(case1["id"], QD))
        validate_success(api_client.close_no_response(case2["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        assert trend["rated_case_count"] == 2
        assert trend["avg_care_appropriateness"] == pytest.approx(2.84, abs=0.001), (
            "the pinned case-mean order reports 2.84; the rejected score-mean "
            "variant would report 2.83")
        assert trend["active_focused_review_id"] is not None, (
            "an average of 2.84 is below 3.0, so the trigger must have fired")


class TestNestedRoundingOrder:
    def test_trend_average_rounds_per_case_mean_first(self):
        """PRD §2.6: "every average the system reports is rounded to exactly 2
        decimal places using the round-half-up method, and the rounding order
        is pinned — each per-case mean is rounded first, and the window-level
        average is then taken over the already-rounded per-case means (see
        §3.8)."

        Design: Difficulty/combinatorial_formula/trend_nested_rounding_order_pinned
        """
        ctx, case1, case2 = _two_notified_cases(((3, None), (3, None), (3, None)),
                                                ((3, None), (3, None), (2, None)),
                                                subject_specialty="ANESTHESIOLOGY",
                                                member_specialties=("ANESTHESIOLOGY",
                                                                    "SURGERY", "PEDIATRICS"))
        validate_success(api_client.close_no_response(case1["id"], QD))
        validate_success(api_client.close_no_response(case2["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        # round_half_up(9/3, 2) = 3.00; round_half_up(8/3, 2) = 2.67;
        # round_half_up((3.00 + 2.67) / 2, 2) = 2.84.
        assert trend["avg_care_appropriateness"] == pytest.approx(2.84, abs=0.001)

    def test_trend_counts_and_window_after_two_closes(self):
        """PRD §3.8: "The rated set behind the metrics comprises exactly those
        of the provider's cases that are in `CLOSED` or `EXTERNAL_REVIEW`,
        hold a `FINALIZED` Deliberation with a non-null `rating`, and whose
        `finalized_at` falls inside the half-open window that begins exactly
        365 days before the current logical time (exclusive) and ends at the
        current logical time (inclusive)."
        PRD §3.8: "The `major_ofi_case_count` counts rated cases whose rating
        is `MAJOR_OFI`, and the `unacceptable_case_count` counts those rated
        `UNACCEPTABLE`."

        Design: Difficulty/combinatorial_formula/trend_nested_rounding_order_pinned
        """
        ctx, case1, case2 = _two_notified_cases(((3, None), (3, None), (3, None)),
                                                ((3, None), (3, None), (2, None)),
                                                subject_specialty="ANESTHESIOLOGY",
                                                member_specialties=("ANESTHESIOLOGY",
                                                                    "SURGERY", "PEDIATRICS"))
        validate_success(api_client.close_no_response(case1["id"], QD))
        validate_success(api_client.close_no_response(case2["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        assert trend["rated_case_count"] == 2
        assert trend["major_ofi_case_count"] == 0
        assert trend["unacceptable_case_count"] == 0
        assert_instant_equals(trend["window_start"], "2025-08-16T00:00:00Z")
        assert_instant_equals(trend["window_end"], "2026-08-16T00:00:00Z")


class TestAverageThresholdBoundary:
    def test_average_exactly_at_threshold_does_not_trigger(self):
        """PRD §3.8: "the focused-review trigger evaluates four predicates
        against the freshly computed, already-rounded values, and fires when
        any one holds: `rated_case_count` is at least 3;
        `avg_care_appropriateness` is below 3.0, evaluated only when
        `rated_case_count` is greater than zero; `major_ofi_case_count` is at
        least 1; or `unacceptable_case_count` is at least 1."

        Design: Difficulty/boundary_precision_check/trend_avg_threshold_exact_boundary
        """
        ctx, case1, _ = _two_notified_cases(((3, None), (3, None), (3, None)),
                                            ((3, None), (3, None), (2, None)),
                                            subject_specialty="INTERNAL_MEDICINE",
                                            member_specialties=("INTERNAL_MEDICINE",
                                                                "CARDIOLOGY", "PEDIATRICS"))
        validate_success(api_client.close_no_response(case1["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        assert trend["avg_care_appropriateness"] == pytest.approx(3.00, abs=0.001)
        assert trend["focused_review_would_trigger"] is False, (
            "an average of exactly 3.00 is not below 3.0")
        assert trend["active_focused_review_id"] is None, (
            "no FocusedReview may be created at the exact threshold")

    def test_average_below_threshold_triggers_automatic_focused_review(self):
        """PRD §3.8: "the focused-review trigger evaluates four predicates
        against the freshly computed, already-rounded values, and fires when
        any one holds: ... `avg_care_appropriateness` is below 3.0, evaluated
        only when `rated_case_count` is greater than zero; ..."
        PRD §3.8: "When the trigger fires and the provider has no `ACTIVE`
        focused review, the server creates one with `trigger_type` `AUTOMATIC`,
        status `ACTIVE`, `opened_at` stamped, and a `trigger_snapshot` object
        capturing the evidence".

        Design: Difficulty/boundary_precision_check/trend_avg_threshold_exact_boundary
        """
        ctx, case1, case2 = _two_notified_cases(((3, None), (3, None), (3, None)),
                                                ((3, None), (3, None), (2, None)),
                                                subject_specialty="INTERNAL_MEDICINE",
                                                member_specialties=("INTERNAL_MEDICINE",
                                                                    "CARDIOLOGY", "PEDIATRICS"))
        validate_success(api_client.close_no_response(case1["id"], QD))
        validate_success(api_client.close_no_response(case2["id"], QD))
        trend = get_quality_trend(ctx["subject"]["id"])
        assert trend["avg_care_appropriateness"] == pytest.approx(2.84, abs=0.001)
        assert trend["focused_review_would_trigger"] is True
        assert trend["active_focused_review_id"] is not None


class TestRatedSetFiltering:
    def test_finalized_at_exactly_window_start_is_excluded(self):
        """PRD §3.8: "The rated set behind the metrics comprises exactly those
        of the provider's cases that are in `CLOSED` or `EXTERNAL_REVIEW`,
        hold a `FINALIZED` Deliberation with a non-null `rating`, and whose
        `finalized_at` falls inside the half-open window that begins exactly
        365 days before the current logical time (exclusive) and ends at the
        current logical time (inclusive)."
        PRD §3.8: "The `avg_care_appropriateness` is the mean of those
        per-case averages, again rounded half-up to two decimal places — and
        it is null when `rated_case_count` is zero."

        Design: Corner/calculations/trend_window_half_open_excludes_older_edge
        """
        # The case is finalized at the default clock (2026-08-01) and closed
        # after the deadline; moving the clock to 2027-08-01 puts its
        # finalized_at exactly at the window's exclusive lower bound.
        ctx = setup_case_closed_no_response(scores=((4, None), (4, None), (4, None)))
        set_clock("2027-08-01T00:00:00Z")
        trend = get_quality_trend(ctx["subject"]["id"])
        assert_instant_equals(trend["window_start"], "2026-08-01T00:00:00Z")
        assert trend["rated_case_count"] == 0, (
            "a case finalized at exactly now - 365 days falls outside the "
            "half-open window")
        assert trend["avg_care_appropriateness"] is None

    def test_screened_out_and_unrated_external_cases_are_excluded(self):
        """PRD §3.8: "Screened-out cases, cases without a finalized rating,
        and cases finalized outside the window are all excluded."
        PRD §3.7: "a case referred from `DELIBERATION` has a Deliberation
        whose `rating` is still null, so it is excluded from the rated set of
        the trend metrics".

        Design: Corner/calculations/trend_excludes_unrated_and_screened_out
        """
        subject = create_provider("Subj Excl", "PEDIATRICS")
        members = [seat_member(create_provider(n, s)["id"], "MEMBER")
                   for n, s in [("Rev B", "PEDIATRICS"), ("Rev C", "SURGERY"),
                                ("Rev D", "CARDIOLOGY")]]
        # Both cases are created before either screening decision, so the
        # cooldown armed by the screen-out cannot block the second referral.
        case1 = create_case(subject["id"], description="screened out case")
        case2 = create_case(subject["id"], referral_source="INCIDENT_REPORT",
                            referred_at="2026-07-21T00:00:00Z",
                            description="external case")
        validate_success(api_client.screen_case(
            case1["id"], {"decision": "SCREEN_OUT", "screened_out_reason": "FRIVOLOUS"}, QD))

        screen_case_in(case2["id"])
        assignments = [assign_reviewer(case2["id"], m["id"]) for m in members]
        for asg, m in zip(assignments, members):
            submit_scores(asg["id"], m["id"], case2["id"], 1)
        validate_success(api_client.refer_external(
            case2["id"], refer_external_payload(reason="beyond committee scope"), QD),
            expected_status=201)

        case2_after = get_case(case2["id"])
        assert case2_after["status"] == "EXTERNAL_REVIEW"

        trend = get_quality_trend(subject["id"])
        assert trend["rated_case_count"] == 0, (
            "SCREENED_OUT rows and unrated EXTERNAL_REVIEW rows are both "
            "excluded from the rated set")
        assert trend["avg_care_appropriateness"] is None
