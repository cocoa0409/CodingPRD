"""Difficulty rule: combinatorial_formula.

Branch interaction inside an if/else chain, rounding-order sensitivity, and a
chained multi-step evaluation whose step order is load-bearing.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_effective_rule,
    add_mapping,
    age_rating_answers,
    assert_decimal_equals,
    assert_posture,
    get_success_data,
    num,
    set_clock,
    setup_base_ios,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

FLOOR_CHAIN_ANSWERS = age_rating_answers(
    violence=1,
    gambling_simulated=1,
    user_generated_content=True,
    ugc_moderation_enabled=False,
    contests=True,
)


# ---------------------------------------------------------------------------
# age_rating_floor_elif_chain_snap_up
# ---------------------------------------------------------------------------
def _setup_arcade_build(api):
    """A GAMES build whose questionnaire trips the unmoderated-UGC floor clause
    while attesting only 12."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        api,
        app_overrides={
            "bundle_id": "com.northwind.arcade",
            "display_name": "Northwind Arcade",
            "primary_category": "GAMES",
        },
        answers=FLOOR_CHAIN_ANSWERS,
        attested_age_rating=12,
        with_pre_review=False,
    )


def test_age_rating_floor_chain_applies_only_its_first_matching_clause(api):
    """"Next compute a content-independent floor as an if/else chain in which only the
    first matching clause applies: real-money gambling forces a floor of 18; failing
    that, unrestricted web access, or user-generated content without moderation enabled,
    forces 17; failing that, contests force 12; otherwise the floor is 0."

    Design: Difficulty/combinatorial_formula/age_rating_floor_elif_chain_snap_up
    """
    ctx = _setup_arcade_build(api)

    data = validate_success(
        api.set_age_rating(
            ctx.submission_id,
            {
                "age_rating_answers": FLOOR_CHAIN_ANSWERS,
                "attested_age_rating": 12,
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert data["derived_age_rating"] == 17, (
        "the unmoderated-UGC clause forces 17; the later contests clause must not "
        "overwrite it with 12"
    )
    assert data["attested_age_rating"] == 12


def test_age_rating_driving_dimension_is_floor_rule_when_the_floor_wins(api):
    """"The `age_rating_driving_dimension` becomes the literal `FLOOR_RULE` when the
    floor strictly exceeded the content base; on a tie the content dimension keeps the
    label."

    Design: Difficulty/combinatorial_formula/age_rating_floor_elif_chain_snap_up
    """
    ctx = _setup_arcade_build(api)

    data = ctx.submission()
    assert data["derived_age_rating"] == 17
    assert data["age_rating_driving_dimension"] == "FLOOR_RULE", (
        "the floor of 17 strictly exceeds the violence content base of 9"
    )


def test_understated_attestation_is_reported_then_blocks_queue_entry(api):
    """"When at least one code is recorded the submission stays in `DRAFT` with
    `pre_review_passed` false; when the array comes back empty the submission moves
    `DRAFT → PRE_REVIEW_PASSED`, `pre_review_passed` becomes true, and
    `attested_by_user_id` is stamped with the acting officer, who thereby becomes the
    subject of the segregation-of-duties rule at the decision gate."

    Design: Difficulty/combinatorial_formula/age_rating_floor_elif_chain_snap_up
    """
    ctx = _setup_arcade_build(api)

    checked = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert checked["pre_review_passed"] is False
    assert checked["pre_review_blocking_reasons"] == ["AGE_RATING_UNDERSTATED"]
    assert checked["state"] == "DRAFT"

    # Queue entry names `ERR_PRE_REVIEW_NOT_PASSED` for a build whose `pre_review_passed`
    # is false, but the same build is also sitting in `DRAFT` rather than the
    # `PRE_REVIEW_PASSED` the transition is declared from, and the PRD does not pin which
    # of the two rungs answers first.
    validate_error_is_one_of(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        [
            ApiErrorId.ERR_PRE_REVIEW_NOT_PASSED,
            ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        ],
    )


# ---------------------------------------------------------------------------
# feature_index_round_once_not_per_mapping
# ---------------------------------------------------------------------------
def _setup_two_in_progress_mappings(api):
    """One app with a SAFETY (weight 5) and a COMMERCE (weight 3) mapping, both
    left IN_PROGRESS, so the index is 2/8 of the way up."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, with_rule=False, with_submission=False, with_window=False
    )
    add_effective_rule(
        ctx,
        key="safety",
        rule_code="1.4.1",
        title="Physical harm and safety",
        category="SAFETY",
    )
    add_effective_rule(
        ctx,
        key="commerce",
        rule_code="3.1.1",
        title="In-app purchase",
        category="COMMERCE",
    )
    add_mapping(
        ctx,
        ctx.rules["safety"],
        feature_code="EMERGENCY_CONTACT",
        advance="START",
        key="safety",
        risk_weight=5,
    )
    add_mapping(
        ctx,
        ctx.rules["commerce"],
        feature_code="IAP_RESTORE",
        advance="START",
        key="commerce",
        risk_weight=3,
    )
    return ctx


def test_feature_index_divides_the_unrounded_sums_exactly_once(api):
    """"Multiply each weight by its factor, sum those products, sum the weights
    separately, divide the first unrounded sum by the second unrounded sum, multiply by
    100, and round the single result half up to two decimal places."

    Design: Difficulty/combinatorial_formula/feature_index_round_once_not_per_mapping
    """
    ctx = _setup_two_in_progress_mappings(api)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(summary["feature_compliance_index"], 25.00, 2, "index")
    assert num(summary["feature_compliance_index"]) != 25.01, (
        "rounding each per-mapping contribution first would yield 15.63 + 9.38 = 25.01"
    )


def test_in_progress_mappings_contribute_a_quarter_of_their_weight(api):
    """"Each contributing mapping has a weight equal to its `risk_weight` and a
    compliance factor determined solely by its `self_review_status`: 1.0 for `PASSED`,
    1.0 for `WAIVED_BY_PLATFORM`, 0.5 for `STALE`, 0.25 for `IN_PROGRESS`, 0.0 for
    `NOT_STARTED` and 0.0 for `FAILED`."

    Design: Difficulty/combinatorial_formula/feature_index_round_once_not_per_mapping
    """
    ctx = _setup_two_in_progress_mappings(api)

    safety = ctx.mapping(ctx.mappings["safety"])
    commerce = ctx.mapping(ctx.mappings["commerce"])
    assert safety["self_review_status"] == "IN_PROGRESS"
    assert commerce["self_review_status"] == "IN_PROGRESS"
    assert_decimal_equals(safety["risk_weight"], 5, 2, "safety risk_weight")
    assert_decimal_equals(commerce["risk_weight"], 3, 2, "commerce risk_weight")

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert summary["mapping_total"] == 2
    assert summary["mapping_passed"] == 0
    assert summary["mapping_stale"] == 0
    assert summary["mapping_failed"] == 0


def test_index_of_twenty_five_restricts_the_app_on_the_floor_code_alone(api):
    """"The index comparison uses the two-decimal rounded index and is strict, so an
    index of exactly 90.00 does **not** restrict the app."

    Design: Difficulty/combinatorial_formula/feature_index_round_once_not_per_mapping
    """
    ctx = _setup_two_in_progress_mappings(api)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_posture(summary, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    assert ctx.app()["compliance_posture"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# priority_score_single_forward_pass_no_fixed_point
# ---------------------------------------------------------------------------
def _setup_queued_then_advanced_clock(api):
    """A build queued at 2026-08-02T00:00:00Z, then the clock moved to
    2026-08-03T12:00:00Z so twelve hours remain against the frozen deadline."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"})
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    set_clock(api, "2026-08-03T12:00:00Z")
    return ctx


def test_deadline_pressure_reads_only_the_frozen_provisional_deadline(api):
    """"Step two reads that frozen deadline and nothing else — hours remaining is the
    deadline minus the current instant expressed in hours and may be negative, and
    deadline pressure is 48 minus hours remaining, divided by 48, clamped to the range
    0.0 to 1.0."

    Design: Difficulty/combinatorial_formula/priority_score_single_forward_pass_no_fixed_point
    """
    ctx = _setup_queued_then_advanced_clock(api)

    data = validate_success(
        api.get_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert data["queued_at"] == "2026-08-02T00:00:00Z"
    assert data["provisional_deadline_at"] == "2026-08-04T00:00:00Z"
    assert_decimal_equals(data["priority_score"], 72.50, 2, "priority_score")
    assert num(data["priority_score"]) != 80.00, (
        "reading the recomputed effective_review_deadline_at in step two would "
        "iterate to 80.00"
    )


def test_band_and_effective_deadline_follow_the_single_forward_pass(api):
    """"Step four assigns `priority_band`: `EXPEDITED` whenever `submission_channel` is
    `EXPEDITED`, regardless of score; otherwise `HIGH` at 70.00 or above, `NORMAL` at
    40.00 or above, and `LOW` below that, both floors inclusive."

    Design: Difficulty/combinatorial_formula/priority_score_single_forward_pass_no_fixed_point
    """
    ctx = _setup_queued_then_advanced_clock(api)

    data = ctx.submission()
    assert data["priority_band"] == "HIGH"
    assert data["effective_review_deadline_at"] == "2026-08-03T00:00:00Z", (
        "step six re-stamps queued_at plus the HIGH SLA of 24 hours"
    )
    assert data["submission_channel"] == "STANDARD"


def test_clock_advance_never_redoes_step_one(api):
    """"When the logical clock advances, steps two through six are re-evaluated for every
    submission still `WAITING_FOR_REVIEW` — pressure rises, priority moves and the band
    and effective deadline can change — but step one is never redone, so
    `provisional_deadline_at` remains the value frozen at queue entry forever."

    Design: Difficulty/combinatorial_formula/priority_score_single_forward_pass_no_fixed_point
    """
    ctx = _setup_queued_then_advanced_clock(api)

    data = ctx.submission()
    assert data["state"] == "WAITING_FOR_REVIEW"
    assert data["provisional_deadline_at"] == "2026-08-04T00:00:00Z"
    assert_decimal_equals(
        data["disclosure_accuracy_score_provisional"], 1.0000, 4, "provisional"
    )
