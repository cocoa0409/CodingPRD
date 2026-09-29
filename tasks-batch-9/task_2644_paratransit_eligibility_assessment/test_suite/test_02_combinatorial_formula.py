"""Recommendation branch order, and the pinned rounding order of the miss ratio."""
from test_helpers import factories, validate_paginated, validate_success
from test_helpers.fixtures import (
    attended_assessment,
    create_applicant,
    ingest_trip_event,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
)


def _attended_assessment_on_a_permanent_attestation(api):
    """A rider whose accepted attestation was permanent, assessed and attended."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ivo Marchetti",
        date_of_birth="1949-02-08",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    return attended_assessment(api, applicant=rider, attests_permanent=True)


def test_the_low_score_branch_decides_before_the_distance_ceiling_branch(api):
    """A rider scoring 0 and 4 who walked 900 metres is unconditional, not ineligible.

    "Otherwise, if the lower of `board_alight_score` and `wayfinding_score` is at
    most 1, the recommendation is `UNCONDITIONAL`."

    "Branch order here is part of the contract and not an implementation detail.
    A rider scoring 0 on boarding and 4 on wayfinding who walked 900 meters with
    no heat sensitivity is `UNCONDITIONAL` by rule 2; testing the 800-meter
    ceiling of rule 5 first would have made the same rider `INELIGIBLE`."

    Design: Difficulty/combinatorial_formula/recommended_category_nested_min_max_branch_order_mode_a
    """
    context = _attended_assessment_on_a_permanent_attestation(api)

    scored = validate_success(
        api.record_scores(
            context["assessment"]["id"],
            factories.scores_payload(
                board_alight_score=0,
                wayfinding_score=4,
                distance_meters_walked=900,
                heat_sensitivity_flag=False,
                evaluator_notes="cannot mount steps; navigates well; walked 900 m on level ground",
            ),
            EVALUATOR_HEADERS,
        )
    )

    assert scored["recommended_category"] == "UNCONDITIONAL"
    assert scored["recommended_category"] != "INELIGIBLE"
    assert scored["recommended_term_days"] == 1825
    assert scored["scoring_status"] == "SCORED"
    assert scored["attendance_status"] == "ATTENDED"
    assert scored["scored_by_user_id"] == "eval-1"


def test_re_scoring_recomputes_the_recommendation_from_the_distance_floor_branch(api):
    """A second scoring on the same assessment moves the recommendation.

    "Otherwise, if `distance_meters_walked` is below 400 meters and the higher of
    `board_alight_score` and `wayfinding_score` is at least 3, the recommendation
    is `CONDITIONAL`."

    "Re-scoring is explicitly allowed while the assessment is still `SCORED` and
    not yet signed off: it is a self-loop that overwrites the four observations,
    recomputes the recommendation, and rewrites `scored_by_user_id` to whoever
    performed the latest scoring."

    Design: Difficulty/combinatorial_formula/recommended_category_nested_min_max_branch_order_mode_a
    """
    context = _attended_assessment_on_a_permanent_attestation(api)

    first = validate_success(
        api.record_scores(
            context["assessment"]["id"],
            factories.scores_payload(
                board_alight_score=0,
                wayfinding_score=4,
                distance_meters_walked=900,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        )
    )
    assert first["recommended_category"] == "UNCONDITIONAL"

    second = validate_success(
        api.record_scores(
            context["assessment"]["id"],
            factories.scores_payload(
                board_alight_score=3,
                wayfinding_score=3,
                distance_meters_walked=350,
                heat_sensitivity_flag=False,
                evaluator_notes="re-scored after supervisor review",
            ),
            EVALUATOR_HEADERS,
        )
    )

    assert second["recommended_category"] == "CONDITIONAL"
    assert second["recommended_term_days"] == 1095
    assert second["scoring_status"] == "SCORED"
    assert second["attendance_status"] == "ATTENDED"

    fetched = validate_success(
        api.get_assessment(context["assessment"]["id"], EVALUATOR_HEADERS)
    )
    assert fetched["recommended_category"] == "CONDITIONAL"
    assert fetched["scored_by_user_id"] == "eval-1"


def _three_event_stream_across_two_months(api):
    """One miss and two completed trips, spread over May and July."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Marta Quijano",
        date_of_birth="1971-07-19",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="MANUAL_WHEELCHAIR",
    )
    ingest_trip_event(api, rider["id"], trip_date="2026-05-20", event_type="NO_SHOW")
    ingest_trip_event(api, rider["id"], trip_date="2026-05-25", event_type="COMPLETED")
    july = ingest_trip_event(
        api, rider["id"], trip_date="2026-07-10", event_type="COMPLETED"
    )
    return rider, july


def test_the_miss_ratio_pools_the_whole_window_and_rounds_exactly_once(api):
    """Pooling gives 33.3 where a monthly average would have given 25.0.

    "Otherwise pool the entire window, divide once, and round once: multiply
    `chargeable_miss_count_90d` by 100, divide by `scheduled_trip_count_90d`, and
    round the single quotient half up to one decimal place."

    "Computing a ratio per calendar month, rounding each, and averaging the
    monthly percentages is expressly forbidden because it produces a different
    answer — one miss out of two trips in May and no misses out of one trip in
    July average to 25.0 monthly but pool to 33.3, and 33.3 is the authoritative
    figure."

    Design: Difficulty/combinatorial_formula/no_show_ratio_pooled_then_rounded_once_mode_b
    """
    rider, _july = _three_event_stream_across_two_months(api)

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))

    assert rider["scheduled_trip_count_90d"] == 3
    assert rider["chargeable_miss_count_90d"] == 1
    assert rider["no_show_ratio_pct"] == 33.3
    assert rider["no_show_ratio_pct"] != 25.0


def test_zero_point_event_types_move_the_ratio_without_moving_the_points(api):
    """A completed trip enlarges the denominator and contributes no points.

    "Events scored at 0 points — `COMPLETED`, `CANCEL_IN_ADVANCE` and
    `AGENCY_FAULT_NO_SHOW` — contribute nothing to either total."

    "The event is stored with `recorded_at` stamped from the logical clock,
    `excused` false, `excuse_reason` null, and `points_assessed` set to 2 for an
    unexcused `NO_SHOW`, 1 for an unexcused `LATE_CANCEL`, and 0 for every other
    event type."

    Design: Difficulty/combinatorial_formula/no_show_ratio_pooled_then_rounded_once_mode_b
    """
    rider, july = _three_event_stream_across_two_months(api)

    assert july["points_assessed"] == 0

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider["no_show_points_event_basis"] == 2

    _proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 0
