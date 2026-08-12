"""Satisfaction surveys: one-per-booking uniqueness and dual quality-score variants."""
from test_helpers import (
    COORD,
    ApiErrorId,
    add_window,
    assert_hours,
    check_in_booking,
    check_out_visit,
    confirm_booking,
    create_active_caregiver,
    create_active_provider,
    create_explicit_booking,
    create_program,
    create_survey_payload,
    decide_visit,
    api_client,
    get_success_data,
    issue_voucher,
    make_caregiver_headers,
    set_clock,
    setup_verified_service,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_survey_rejected(api):
    """PRD §3.12: "Only one survey is permitted per booking; a second attempt is
    rejected with `ERR_DUPLICATE_SURVEY` (HTTP 409)."

    Design: Corner/errors/duplicate_survey_rejected
    """
    ctx = setup_verified_service()  # booking COMPLETED
    cg_headers = make_caregiver_headers(ctx["caregiver"]["id"])
    first = validate_success(
        api.create_satisfaction_survey(ctx["booking"]["id"],
                                       create_survey_payload(rating=4, would_rebook=True),
                                       cg_headers),
        201)
    assert first["rating"] == 4

    res = api.create_satisfaction_survey(
        ctx["booking"]["id"],
        create_survey_payload(rating=1, would_rebook=False, comments="changed my mind"),
        cg_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SURVEY, expected_status=409)

    surveys, meta = validate_paginated(
        api.list_satisfaction_surveys(COORD, params={"booking_id": ctx["booking"]["id"]}))
    assert len(surveys) == 1
    assert meta["total_count"] == 1


class TestProviderQualityDualScores:
    def _two_rated_visits(self, api):
        """Booking1 completed 2026-05-01 08:00-09:00 and rated 2 at 2026-05-01T09:00Z;
        booking2 completed 2026-06-30 08:00-09:00 and rated 5 at 2026-06-30T09:00Z."""
        program = create_program()
        ctx = create_active_caregiver(program=program)
        provider = create_active_provider()
        window = add_window(provider["id"], "2026-05-01T00:00:00Z",
                            "2026-06-30T23:59:00Z", 4)
        cg_id = ctx["caregiver"]["id"]

        # --- Visit 1: Friday 2026-05-01 08:00-09:00, rating 2 at 09:00 ---
        voucher1 = issue_voucher(ctx["allocation"]["id"], cg_id, 5)
        booking1 = create_explicit_booking(voucher1["id"], cg_id, provider["id"],
                                           window["id"],
                                           "2026-05-01T08:00:00Z", "2026-05-01T09:00:00Z")
        confirm_booking(booking1["id"], provider["id"])
        visit1 = check_in_booking(booking1["id"], provider["id"], "2026-05-01T08:30:00Z")
        check_out_visit(visit1["id"], provider["id"], "2026-05-01T09:00:00Z",
                        {"tasks_completed": ["meal_prep"]})
        decide_visit(visit1["id"], "VERIFY")
        get_success_data(api.create_satisfaction_survey(
            booking1["id"], create_survey_payload(rating=2, would_rebook=False),
            make_caregiver_headers(cg_id)))

        # --- Visit 2: Tuesday 2026-06-30 08:00-09:00, rating 5 at 09:00 ---
        set_clock("2026-06-30T08:00:00Z")
        voucher2 = issue_voucher(ctx["allocation"]["id"], cg_id, 5)
        booking2 = create_explicit_booking(voucher2["id"], cg_id, provider["id"],
                                           window["id"],
                                           "2026-06-30T08:00:00Z", "2026-06-30T09:00:00Z")
        confirm_booking(booking2["id"], provider["id"])
        visit2 = check_in_booking(booking2["id"], provider["id"], "2026-06-30T08:00:00Z")
        check_out_visit(visit2["id"], provider["id"], "2026-06-30T09:00:00Z",
                        {"tasks_completed": ["meal_prep"]})
        decide_visit(visit2["id"], "VERIFY")
        get_success_data(api.create_satisfaction_survey(
            booking2["id"], create_survey_payload(rating=5, would_rebook=True),
            make_caregiver_headers(cg_id)))
        return provider

    def test_simple_score_is_unweighted_mean(self, api):
        """PRD §3.12: "`quality_score_simple` is the unweighted mean of all the
        provider's survey ratings, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/provider_quality_simple_vs_recency_weighted
        """
        provider = self._two_rated_visits(api)
        after = validate_success(api.get_provider(provider["id"], COORD), 200)
        # (2 + 5) / 2 = 3.50
        assert_hours(after["quality_score_simple"], 3.50, "quality_score_simple")

    def test_weighted_score_decays_old_ratings(self, api):
        """PRD §3.12: "`quality_score_weighted` is a recency-decay weighted mean: each
        survey's rating is weighted by 0.5 raised to the power of (whole days between
        the survey's `created_at` and now, divided by 30) — that is, a 30-day half-life
        — and the weighted score is the sum of weighted ratings divided by the sum of
        weights, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/provider_quality_simple_vs_recency_weighted
        """
        provider = self._two_rated_visits(api)
        after = validate_success(api.get_provider(provider["id"], COORD), 200)
        # Rating 2 is 60 days old (weight 0.25); rating 5 is fresh (weight 1.0):
        # (0.25 x 2 + 1.0 x 5) / 1.25 = 4.40 — deliberately different from simple 3.50.
        assert_hours(after["quality_score_weighted"], 4.40, "quality_score_weighted")
        assert after["quality_score_weighted"] != after["quality_score_simple"]
