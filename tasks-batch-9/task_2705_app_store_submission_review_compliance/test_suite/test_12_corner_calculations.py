"""Corner section: calculations.

Every published formula pinned at the value the PRD's own arithmetic produces: the
feature compliance index and its empty-set boundary, the age-rating derivation and
its floor chain, the disclosure accuracy scores, commerce settlement, review
priority with its bands and SLAs, standing with its decay tiers, capacity-window
selection, rollout share conservation and impact severity.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    add_approved_commerce_item,
    add_effective_rule,
    add_locale,
    add_rollout_plan,
    create_behavior_finding_payload,
    create_review_capacity_window_payload,
    add_mapping,
    assert_decimal_equals,
    assert_posture,
    age_rating_answers,
    get_success_data,
    privacy_item,
    reject,
    rejection_reasons_for,
    set_clock,
    set_privacy,
    setup_approved_ios,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

EVIDENCE = "https://docs.northwind.example/evidence/ugc-reporting"


def _self_review(ctx, mapping_id, outcome, evidence_ref=None):
    """Record one self-review outcome on a mapping as the ComplianceOfficer."""
    body = {"outcome": outcome}
    if evidence_ref is not None:
        body["evidence_ref"] = evidence_ref
    return get_success_data(
        ctx.client.self_review_mapping(mapping_id, body, ctx.compliance_officer)
    )


def _setup_three_rule_app(api):
    """An OPEN-eligible app with SAFETY 1.1.4, PRIVACY 5.1.1 and DESIGN 4.0.1 effective."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_rule=False, with_submission=False, with_window=False
    )
    add_effective_rule(
        ctx,
        key="safety",
        rule_code="1.1.4",
        title="Objectionable Content",
        category="SAFETY",
        requires_feature_mapping=True,
    )
    add_effective_rule(ctx, key="privacy", rule_code="5.1.1")
    add_effective_rule(
        ctx,
        key="design",
        rule_code="4.0.1",
        title="Icon And Screenshot Quality",
        category="DESIGN",
        requires_feature_mapping=True,
    )
    return ctx


def _setup_index_of_exactly_ninety(api):
    """Weights 5 PASSED, 4 PASSED and 1 NOT_STARTED: 100 * 9 / 10 is exactly 90.00."""
    ctx = _setup_three_rule_app(api)
    add_mapping(
        ctx,
        ctx.rules["safety"],
        feature_code="UGC_REPORTING",
        advance="PASS",
        key="safety",
        evidence_ref=EVIDENCE,
        risk_weight=5,
    )
    add_mapping(
        ctx,
        ctx.rules["privacy"],
        feature_code="ACCOUNT_DELETION",
        advance="PASS",
        key="privacy",
        risk_weight=4,
    )
    add_mapping(
        ctx,
        ctx.rules["design"],
        feature_code="APP_ICON",
        advance=None,
        key="design",
        risk_weight=1,
    )
    return ctx


def test_an_app_with_no_feature_mappings_scores_zero_not_one_hundred(api):
    """"When the contributing set is empty — an app with no mappings, or an app whose every mapping
    points at a superseded rule — the index is 0.00, not 100.00: absence of evidence is not evidence
    of compliance, and this is the boundary that keeps a brand-new app record `RESTRICTED` rather
    than `OPEN`."

    Design: Corner/calculations/an_app_with_no_feature_mappings_scores_zero_not_one_hundred
    """
    ctx = _setup_three_rule_app(api)

    app = validate_success(
        api.get_app_record(ctx.app_record_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(app["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])

    _, meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 0


def test_an_index_of_exactly_ninety_does_not_restrict_the_posture(api):
    """"The index comparison uses the two-decimal rounded index and is strict, so an index of exactly
    90.00 does **not** restrict the app."

    Design: Corner/calculations/an_index_of_exactly_ninety_does_not_restrict_the_posture
    """
    ctx = _setup_index_of_exactly_ninety(api)

    app = validate_success(
        api.get_app_record(ctx.app_record_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(app["feature_compliance_index"], 90.00, 2, "index")
    assert_posture(app, "OPEN", [])


def test_failing_the_design_mapping_leaves_the_index_at_ninety(api):
    """"Each contributing mapping has a weight equal to its `risk_weight` and a compliance factor
    determined solely by its `self_review_status`: 1.0 for `PASSED`, 1.0 for `WAIVED_BY_PLATFORM`,
    0.5 for `STALE`, 0.25 for `IN_PROGRESS`, 0.0 for `NOT_STARTED` and 0.0 for `FAILED`."

    Design: Corner/calculations/failing_the_design_mapping_leaves_the_index_at_ninety_because_both_factors_are_zero
    """
    ctx = _setup_index_of_exactly_ninety(api)
    design_mapping = ctx.mappings["design"]

    _self_review(ctx, design_mapping, "START")
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 92.50, 2, "index with IN_PROGRESS"
    )

    failed = _self_review(ctx, design_mapping, "FAIL")
    assert failed["self_review_status"] == "FAILED"

    app = ctx.app()
    assert_decimal_equals(
        app["feature_compliance_index"], 90.00, 2, "index with FAILED"
    )
    assert app["compliance_posture"] == "OPEN"


def test_the_index_divides_the_unrounded_sums_once_at_the_end(api):
    """"Multiply each weight by its factor, sum those products, sum the weights separately, divide the
    first unrounded sum by the second unrounded sum, multiply by 100, and round the single result half
    up to two decimal places. Do not round the individual products or either subtotal."

    Design: Corner/calculations/the_index_divides_the_unrounded_sums_once_at_the_end
    """
    ctx = _setup_three_rule_app(api)
    add_mapping(
        ctx,
        ctx.rules["safety"],
        feature_code="UGC_REPORTING",
        advance="START",
        key="safety",
        risk_weight=5,
    )
    add_mapping(
        ctx,
        ctx.rules["privacy"],
        feature_code="ACCOUNT_DELETION",
        advance="PASS",
        key="privacy",
        risk_weight=4,
    )

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(summary["feature_compliance_index"], 58.33, 2, "index")
    assert_posture(summary, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])


def _setup_draft_build(api):
    """One DRAFT build with no questionnaire recorded yet."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        client=api, with_content=False, with_window=False, with_pre_review=False
    )


def _set_answers(api, ctx, attested, **answers):
    """PUT the questionnaire and return the refreshed submission."""
    return validate_success(
        api.set_age_rating(
            ctx.submission_id,
            {
                "age_rating_answers": age_rating_answers(**answers),
                "attested_age_rating": attested,
            },
            ctx.compliance_officer,
        ),
        200,
    )


def test_an_all_zero_questionnaire_derives_band_zero(api):
    """"The content base is the highest such band across the six dimensions, and the driving dimension
    is the *first* dimension attaining that base in the fixed priority order violence, sexual content,
    drugs and alcohol, simulated gambling, horror, profanity — so when violence and horror are both at
    level 3, violence is named."

    Design: Corner/calculations/an_all_zero_questionnaire_derives_band_zero_labelled_violence
    """
    ctx = _setup_draft_build(api)

    scored = _set_answers(api, ctx, 4)
    assert scored["derived_age_rating"] == 0
    assert scored["age_rating_driving_dimension"] == "VIOLENCE"
    assert scored["attested_age_rating"] == 4
    assert scored["state"] == "DRAFT"


def test_simulated_gambling_at_level_two_bumps_the_raw_rating_to_seventeen(api):
    """"Then, if the simulated gambling intensity is at level 2 or higher, raise the result to at least
    17 — level 2 alone is enough, which is why simulated gambling behaves unlike every other dimension,
    whose level 2 would only have reached 12."

    Design: Corner/calculations/simulated_gambling_at_level_two_bumps_the_raw_rating_to_seventeen
    """
    ctx = _setup_draft_build(api)

    level_one = _set_answers(api, ctx, 17, gambling_simulated=1)
    assert level_one["derived_age_rating"] == 9
    assert level_one["age_rating_driving_dimension"] != "FLOOR_RULE"

    level_two = _set_answers(api, ctx, 17, gambling_simulated=2)
    assert level_two["derived_age_rating"] == 17
    assert level_two["age_rating_driving_dimension"] != "FLOOR_RULE"


def test_the_first_dimension_in_the_declared_order_wins_the_label_tie(api):
    """"First map each intensity level to a band: level 0 maps to age 0, level 1 to 9, level 2 to 12
    and level 3 to 17."

    Design: Corner/calculations/the_first_dimension_in_the_declared_order_wins_the_label_tie
    """
    ctx = _setup_draft_build(api)

    tied = _set_answers(api, ctx, 17, violence=3, horror=3)
    assert tied["derived_age_rating"] == 17
    assert tied["age_rating_driving_dimension"] == "VIOLENCE"


def test_unmoderated_user_generated_content_raises_the_floor_and_relabels(api):
    """"Next compute a content-independent floor as an if/else chain in which only the first matching
    clause applies: real-money gambling forces a floor of 18; failing that, unrestricted web access, or
    user-generated content without moderation enabled, forces 17; failing that, contests force 12;
    otherwise the floor is 0."

    Design: Corner/calculations/unmoderated_user_generated_content_raises_the_floor_and_relabels_to_floor_rule
    """
    ctx = _setup_draft_build(api)

    unmoderated = _set_answers(
        api, ctx, 17, user_generated_content=True, ugc_moderation_enabled=False
    )
    assert unmoderated["derived_age_rating"] == 17
    assert unmoderated["age_rating_driving_dimension"] == "FLOOR_RULE"

    moderated = _set_answers(
        api, ctx, 17, user_generated_content=True, ugc_moderation_enabled=True
    )
    assert moderated["derived_age_rating"] == 0
    assert moderated["age_rating_driving_dimension"] == "VIOLENCE"


def test_real_money_gambling_short_circuits_the_floor_chain_at_eighteen(api):
    """"The `age_rating_driving_dimension` becomes the literal `FLOOR_RULE` when the floor strictly
    exceeded the content base; on a tie the content dimension keeps the label."

    Design: Corner/calculations/real_money_gambling_short_circuits_the_floor_chain_at_eighteen
    """
    ctx = _setup_draft_build(api)

    gambling = _set_answers(
        api,
        ctx,
        18,
        unrestricted_web_access=True,
        real_money_gambling=True,
        contests=True,
    )
    assert gambling["derived_age_rating"] == 18
    assert gambling["age_rating_driving_dimension"] == "FLOOR_RULE"


def test_a_contest_floor_equal_to_the_content_band_keeps_the_content_label(api):
    """"Take the greater of the content base and the floor."

    Design: Corner/calculations/a_contest_floor_equal_to_the_content_band_keeps_the_content_label
    """
    ctx = _setup_draft_build(api)

    tied = _set_answers(api, ctx, 12, sexual_content=2, contests=True)
    assert tied["derived_age_rating"] == 12
    assert tied["age_rating_driving_dimension"] == "SEXUAL_CONTENT"


def _setup_queueable_build(api):
    """A DRAFT build with a complete locale, an empty privacy label and an open window."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_content=False, with_pre_review=False)
    add_locale(ctx)
    set_privacy(ctx)
    return ctx


def test_over_attesting_two_bands_above_the_derived_rating_still_queues(api):
    """"Every content rule that the self-review merely reported is enforced here as a hard error,
    re-evaluated against the *current* clock and the current rows, not against whatever the
    self-review saw."

    Design: Corner/calculations/over_attesting_two_bands_above_the_derived_rating_still_queues
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 17, sexual_content=2)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert reported["pre_review_passed"] is True
    assert reported["pre_review_blocking_reasons"] == []

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["derived_age_rating"] == 12
    assert queued["attested_age_rating"] == 17


def test_attesting_exactly_the_derived_band_passes_the_inclusive_boundary(api):
    """"`attested_age_rating` must be one of the six declared rating bands 0, 4, 9, 12, 17 and 18."

    Design: Corner/calculations/attesting_exactly_the_derived_band_passes_the_inclusive_boundary
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 12, sexual_content=2)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert reported["pre_review_passed"] is True

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["derived_age_rating"] == 12


def test_an_understated_attestation_is_reported_as_the_only_blocking_reason(api):
    """"It then evaluates the same content rules that the queue gate enforces and, instead of raising
    them, records each as a code in `pre_review_blocking_reasons`, ordered by ascending rule priority
    with ties broken by the fixed sequence `METADATA_INCOMPLETE`, `SCREENSHOT_SET_EMPTY`,
    `AGE_RATING_UNDERSTATED`, `TRACKING_CONSENT_PROMPT_MISSING`, `PRIVACY_DISCLOSURE_INACCURATE`,
    `CRITICAL_FINDING_UNRESOLVED`, `GUIDELINE_MAPPING_INCOMPLETE`, `SIGNING_CREDENTIAL_INVALID`."

    Design: Corner/calculations/an_understated_attestation_is_reported_then_refused_at_priority_fifty_five
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 12, violence=3)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert reported["pre_review_passed"] is False
    assert reported["pre_review_blocking_reasons"] == ["AGE_RATING_UNDERSTATED"]
    assert reported["state"] == "DRAFT"
    assert reported["queued_at"] is None

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_available"] == 5


def test_re_recording_the_same_questionnaire_voids_the_attestation(api):
    """"Setting the questionnaire recomputes both derived fields, and, being a content mutation, drives
    a `PRE_REVIEW_PASSED` submission back to `DRAFT` and voids the attestation."

    Design: Corner/calculations/re_recording_the_same_questionnaire_voids_the_attestation_and_blocks_the_queue
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    assert ctx.submission()["pre_review_passed"] is True

    voided = _set_answers(api, ctx, 4)
    assert voided["state"] == "DRAFT"
    assert voided["pre_review_passed"] is False
    assert voided["pre_review_checked_at"] is None
    assert voided["attested_by_user_id"] is None
    assert voided["derived_age_rating"] == 0

    # The void left the build in `DRAFT` with `pre_review_passed` false, so the refusal may
    # legitimately come from either the seventh rung or the attestation check itself.
    validate_error_is_one_of(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        [
            ApiErrorId.ERR_PRE_REVIEW_NOT_PASSED,
            ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        ],
    )
    assert ctx.submission()["review_window_id"] is None


OVER_DECLARED = [
    privacy_item("HEALTH", "APP_FUNCTIONALITY", linked=True, tracking=False),
    privacy_item("EMAIL", "APP_FUNCTIONALITY", linked=True, tracking=False),
    privacy_item("CONTACTS", "APP_FUNCTIONALITY", linked=False, tracking=False),
]


def _file_minor_usage_finding(ctx, scanner_confidence):
    """One unmatched MINOR USAGE_DATA observation detected before the pre-review instant."""
    return get_success_data(
        ctx.client.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="USAGE_DATA",
                observed_purpose="ANALYTICS",
                observed_linked_to_user=False,
                observed_tracking=False,
                endpoint_domain="metrics.northwind.example",
                severity="MINOR",
                scanner_confidence=scanner_confidence,
                detected_at="2026-07-31T00:00:00Z",
            ),
            ctx.policy_admin,
        )
    )


def test_three_over_declared_data_types_pass_self_review_but_fail_the_reviewer_gate(api):
    """"An over-disclosure term counts each declared tuple whose `data_type` appears in no finding in
    scope and charges 2 per such data type."

    Design: Corner/calculations/three_over_declared_data_types_pass_self_review_but_fail_the_reviewer_gate
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 4)
    set_privacy(ctx, declared_privacy_items=OVER_DECLARED)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"], 1.0000, 4, "provisional"
    )
    assert reported["pre_review_passed"] is True

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.9400, 4, "final"
    )

    validate_error(
        api.decide_submission(
            ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer
        ),
        ApiErrorId.ERR_PRIVACY_DISCLOSURE_INACCURATE,
        409,
    )

    stuck = ctx.submission()
    assert stuck["state"] == "IN_REVIEW"
    assert stuck["decided_at"] is None


def test_one_undisclosed_minor_finding_lands_on_the_inclusive_pass_threshold(api):
    """"The pass threshold is 0.9500 inclusive — exactly 0.9500 passes, 0.9499 fails."

    Design: Corner/calculations/one_undisclosed_minor_finding_lands_exactly_on_the_inclusive_pass_threshold
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 4)
    finding = _file_minor_usage_finding(ctx, 0.95)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )
    assert reported["pre_review_blocking_reasons"] == []

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.9500, 4, "final"
    )

    approved = validate_success(
        api.decide_submission(
            ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer
        ),
        200,
    )
    assert approved["state"] == "APPROVED"
    assert get_success_data(
        api.get_behavior_finding(finding["id"], ctx.compliance_officer)
    )["status"] == "OPEN"


def test_the_over_disclosure_term_turns_a_passing_score_into_a_failing_one(api):
    """"Start from 100, subtract the total undisclosed penalty, subtract the over-disclosure term where
    the variant applies it, floor the result at 0, then divide by 100 and round half up to four decimal
    places."

    Design: Corner/calculations/the_over_disclosure_term_turns_a_passing_provisional_score_into_a_failing_final_score
    """
    ctx = _setup_queueable_build(api)
    _set_answers(api, ctx, 4)
    set_privacy(ctx, declared_privacy_items=OVER_DECLARED)
    _file_minor_usage_finding(ctx, 0.90)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.8900, 4, "final"
    )

    validate_error(
        api.decide_submission(
            ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer
        ),
        ApiErrorId.ERR_PRIVACY_DISCLOSURE_INACCURATE,
        409,
    )


# ---------------------------------------------------------------------------
# commerce settlement
# ---------------------------------------------------------------------------
def _distributing_app(api):
    """A FULLY_RELEASED iOS app whose account is on the STANDARD commerce tier."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_released_ios(
        client=api,
        mode="IMMEDIATE",
        submission_overrides={"release_mode": "IMMEDIATE"},
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
    )


def _report_revenue(api, ctx, item_id, gross_cents, period_label):
    return api.report_commerce_revenue(
        item_id,
        {"reported_gross_cents": gross_cents, "period_label": period_label},
        ctx.publisher_admin,
    )


def _settlement(api, ctx, period_label):
    return validate_success(
        api.get_commerce_settlement(
            ctx.app_record_id,
            ctx.publisher_admin,
            params={"period_label": period_label},
        ),
        200,
    )


def test_a_standard_tier_line_rounds_the_half_cent_up_to_three_hundred_and_two(api):
    """"The resulting rate is stored as `commission_rate_applied`, and `commission_cents` is
    `reported_gross_cents` multiplied by that rate, rounded half up to a whole cent."

    Design: Corner/calculations/a_standard_tier_line_rounds_the_half_cent_up_to_three_hundred_and_two
    """
    ctx = _distributing_app(api)
    item = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=1005
    )

    reported = validate_success(
        _report_revenue(api, ctx, item["id"], 1005, "2026-Q1"), 200
    )
    assert_decimal_equals(reported["commission_rate_applied"], 0.30, 2, "rate")
    assert reported["commission_cents"] == 302
    assert reported["reported_gross_cents"] == 1005
    assert reported["reported_period_label"] == "2026-Q1"

    settlement = _settlement(api, ctx, "2026-Q1")
    assert settlement["period_label"] == "2026-Q1"
    assert settlement["line_count"] == 1
    assert settlement["gross_cents_total"] == 1005
    assert settlement["commission_cents_total"] == 302
    assert settlement["net_cents_total"] == 703

    assert ctx.account()["settlement_finalized_periods"] == ["2026-Q1"]


def test_a_period_with_no_approved_items_settles_to_all_zeros(api):
    """"An empty line set yields a settlement commission of 0 and a publisher net of 0."

    Design: Corner/calculations/a_period_with_no_approved_items_settles_to_all_zeros
    """
    ctx = _distributing_app(api)
    item = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=1005
    )
    validate_success(_report_revenue(api, ctx, item["id"], 1005, "2026-Q1"), 200)

    empty = _settlement(api, ctx, "2026-Q2")
    assert empty["period_label"] == "2026-Q2"
    assert empty["line_count"] == 0
    assert empty["gross_cents_total"] == 0
    assert empty["commission_cents_total"] == 0
    assert empty["net_cents_total"] == 0
    assert empty["lines"] == []


def test_a_second_revenue_report_for_the_same_period_is_refused_account_wide(api):
    """"A second report for the same item, or a report against a period already recorded in the
    account's `settlement_finalized_periods`, is refused with `ERR_REVENUE_ALREADY_REPORTED` —
    gross proceeds are stated exactly once, and commission is recomputed from that stored figure
    on every settlement read thereafter."

    Design: Corner/calculations/a_second_revenue_report_for_the_same_period_is_refused_account_wide
    """
    ctx = _distributing_app(api)
    first = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=1005
    )
    second = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=4999
    )

    booked = validate_success(
        _report_revenue(api, ctx, first["id"], 1005, "2026-Q1"), 200
    )
    assert booked["commission_cents"] == 302
    assert ctx.account()["settlement_finalized_periods"] == ["2026-Q1"]

    validate_error(
        _report_revenue(api, ctx, second["id"], 4999, "2026-Q1"),
        ApiErrorId.ERR_REVENUE_ALREADY_REPORTED,
        409,
    )
    untouched = get_success_data(
        api.get_commerce_item(second["id"], ctx.publisher_admin)
    )
    assert untouched["reported_period_label"] is None
    assert untouched["reported_gross_cents"] == 0
    assert untouched["commission_cents"] == 0

    settlement = _settlement(api, ctx, "2026-Q1")
    assert settlement["line_count"] == 1
    assert settlement["gross_cents_total"] == 1005
    assert settlement["commission_cents_total"] == 302


def test_twelve_months_of_retention_halves_the_rate_while_eleven_months_does_not(api):
    """"Each line then adjusts that rate: a `SUBSCRIPTION` item whose
    `subscriber_retention_months` is 12 or more takes the lower of the base rate and the
    retained-subscriber rate of 0.15 — 12 months qualifies, 11 does not — and an
    `EXTERNAL_PAYMENT_LINK` item has 0.03 subtracted from its rate, rounded to two decimals."

    Design: Corner/calculations/twelve_months_of_retention_halves_the_rate_while_eleven_months_does_not
    """
    ctx = _distributing_app(api)
    retained = add_approved_commerce_item(
        ctx,
        item_type="SUBSCRIPTION",
        price_tier_cents=2000,
        entitlement_class="SERVICE",
        subscriber_retention_months=12,
    )
    churning = add_approved_commerce_item(
        ctx,
        item_type="SUBSCRIPTION",
        price_tier_cents=2000,
        entitlement_class="SERVICE",
        subscriber_retention_months=11,
    )

    qualified = validate_success(
        _report_revenue(api, ctx, retained["id"], 2000, "2026-Q1"), 200
    )
    assert_decimal_equals(
        qualified["commission_rate_applied"], 0.15, 2, "retained rate"
    )
    assert qualified["commission_cents"] == 300

    short = validate_success(
        _report_revenue(api, ctx, churning["id"], 2000, "2026-Q2"), 200
    )
    assert_decimal_equals(short["commission_rate_applied"], 0.30, 2, "base rate")
    assert short["commission_cents"] == 600

    q1 = _settlement(api, ctx, "2026-Q1")
    assert q1["line_count"] == 1
    assert q1["commission_cents_total"] == 300
    assert q1["net_cents_total"] == 1700

    q2 = _settlement(api, ctx, "2026-Q2")
    assert q2["line_count"] == 1
    assert q2["commission_cents_total"] == 600
    assert q2["net_cents_total"] == 1400

    assert ctx.account()["settlement_finalized_periods"] == ["2026-Q1", "2026-Q2"]


PAY_LINK = "https://shop.northwind.example/checkout"
LINK_ENTITLED = {"entitlements": ["IN_APP_PURCHASE", "EXTERNAL_PAYMENT_LINK"]}


def _external_link_item(ctx):
    """An APPROVED EXTERNAL_PAYMENT_LINK item: zero price, SERVICE class, live URL."""
    return add_approved_commerce_item(
        ctx,
        item_type="EXTERNAL_PAYMENT_LINK",
        price_tier_cents=0,
        entitlement_class="SERVICE",
        external_link_url=PAY_LINK,
    )


def test_an_external_payment_link_pays_twenty_seven_percent_after_the_discount(api):
    """"Each line then adjusts that rate: a `SUBSCRIPTION` item whose
    `subscriber_retention_months` is 12 or more takes the lower of the base rate and the
    retained-subscriber rate of 0.15 — 12 months qualifies, 11 does not — and an
    `EXTERNAL_PAYMENT_LINK` item has 0.03 subtracted from its rate, rounded to two decimals."

    Design: Corner/calculations/an_external_payment_link_pays_twenty_seven_percent_after_the_three_point_discount
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api,
        mode="IMMEDIATE",
        submission_overrides={"release_mode": "IMMEDIATE"},
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
        cert_overrides=LINK_ENTITLED,
    )
    add_approved_commerce_item(ctx, item_type="CONSUMABLE", price_tier_cents=1005)
    link = _external_link_item(ctx)
    assert link["status"] == "APPROVED"

    reported = validate_success(
        _report_revenue(api, ctx, link["id"], 1005, "2026-Q3"), 200
    )
    assert_decimal_equals(
        reported["commission_rate_applied"], 0.27, 2, "discounted rate"
    )
    assert reported["commission_cents"] == 271

    settlement = _settlement(api, ctx, "2026-Q3")
    assert settlement["line_count"] == 1
    assert settlement["gross_cents_total"] == 1005
    assert settlement["commission_cents_total"] == 271
    assert settlement["net_cents_total"] == 734


def test_a_halting_rollback_removes_the_external_link_line_from_the_period(api):
    """"With `halt_distribution` true the app's `distribution_state` becomes `ROLLED_BACK`, every
    `APPROVED` commerce item of the app whose `item_type` is `EXTERNAL_PAYMENT_LINK` is torn down
    to `REMOVED`, and the next plan for the app must respect the 72-hour cooldown."

    Design: Corner/calculations/a_halting_rollback_removes_the_external_link_line_from_the_settled_period
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api,
        mode="PHASED",
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
        cert_overrides=LINK_ENTITLED,
    )
    consumable = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=1005
    )
    link = _external_link_item(ctx)
    validate_success(_report_revenue(api, ctx, link["id"], 1005, "2026-Q3"), 200)
    assert _settlement(api, ctx, "2026-Q3")["commission_cents_total"] == 271

    halted = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert halted["state"] == "ROLLED_BACK"
    assert ctx.app()["distribution_state"] == "ROLLED_BACK"

    torn_down = get_success_data(api.get_commerce_item(link["id"], ctx.publisher_admin))
    assert torn_down["status"] == "REMOVED"
    assert torn_down["reported_gross_cents"] == 1005
    assert torn_down["reported_period_label"] == "2026-Q3"
    assert get_success_data(
        api.get_commerce_item(consumable["id"], ctx.publisher_admin)
    )["status"] == "APPROVED"

    collapsed = _settlement(api, ctx, "2026-Q3")
    assert collapsed["line_count"] == 0
    assert collapsed["gross_cents_total"] == 0
    assert collapsed["commission_cents_total"] == 0
    assert collapsed["net_cents_total"] == 0


def test_a_small_business_account_stamps_fifteen_percent_and_twelve_on_the_link(api):
    """"The base rate is 0.15 when the account's `commerce_program_tier` is `SMALL_BUSINESS` and
    0.30 otherwise."

    Design: Corner/calculations/a_small_business_account_stamps_fifteen_percent_and_twelve_on_the_external_link
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        account_overrides={"commerce_program_tier": "SMALL_BUSINESS"},
        cert_overrides=LINK_ENTITLED,
        with_submission=False,
        with_window=False,
    )
    assert ctx.account()["commerce_program_tier"] == "SMALL_BUSINESS"
    assert_posture(ctx.app(), "OPEN", [])

    consumable = add_approved_commerce_item(
        ctx, item_type="CONSUMABLE", price_tier_cents=1005
    )
    assert_decimal_equals(
        consumable["commission_rate_applied"], 0.15, 2, "small-business base rate"
    )
    assert consumable["commission_cents"] == 0

    link = _external_link_item(ctx)
    assert_decimal_equals(
        link["commission_rate_applied"], 0.12, 2, "discounted small-business rate"
    )
    assert link["commission_cents"] == 0

    unreported = _settlement(api, ctx, "2026-Q1")
    assert unreported["line_count"] == 0
    assert unreported["commission_cents_total"] == 0


# ---------------------------------------------------------------------------
# review priority: bands, pressure and SLAs
# ---------------------------------------------------------------------------
def _instant(value):
    """Parse a rendered instant so the comparison does not depend on fraction digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_queued_build(api):
    """One build WAITING_FOR_REVIEW at the default instant on a perfect account."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority at entry")
    assert queued["priority_band"] == "NORMAL"
    assert _instant(queued["provisional_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )
    assert _instant(queued["effective_review_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )
    return ctx


def test_thirty_two_hours_of_deadline_pressure_lands_the_score_on_exactly_seventy(api):
    """"Step four assigns `priority_band`: `EXPEDITED` whenever `submission_channel` is
    `EXPEDITED`, regardless of score; otherwise `HIGH` at 70.00 or above, `NORMAL` at 40.00 or
    above, and `LOW` below that, both floors inclusive."

    Design: Corner/calculations/thirty_two_hours_of_deadline_pressure_lands_the_score_on_exactly_seventy
    """
    ctx = _setup_queued_build(api)

    ticked = validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T08:00:00Z"}, ctx.policy_admin), 200
    )
    assert _instant(ticked["current_utc"]) == _instant("2026-08-02T08:00:00Z")

    promoted = ctx.submission()
    assert_decimal_equals(promoted["priority_score"], 70.00, 2, "priority at 32h")
    assert promoted["priority_band"] == "HIGH"
    assert _instant(promoted["effective_review_deadline_at"]) == _instant(
        "2026-08-02T00:00:00Z"
    )
    assert _instant(promoted["provisional_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )


def test_one_hour_short_of_the_boundary_the_band_is_still_normal(api):
    """"Then `priority_score` is 0.50 times standing plus 0.30 times urgency *minus* 0.20 times
    risk, rounded half up to two decimals and clamped to 0.00 through 100.00."

    Design: Corner/calculations/one_hour_short_of_the_boundary_the_band_is_still_normal
    """
    ctx = _setup_queued_build(api)

    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T07:00:00Z"}, ctx.policy_admin), 200
    )

    pending = ctx.submission()
    assert_decimal_equals(pending["priority_score"], 69.38, 2, "priority at 31h")
    assert pending["priority_band"] == "NORMAL"
    assert _instant(pending["effective_review_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )


def test_negative_hours_remaining_clamp_the_pressure_and_cap_the_score_at_eighty(api):
    """"Step two reads that frozen deadline and nothing else — hours remaining is the deadline
    minus the current instant expressed in hours and may be negative, and deadline pressure is 48
    minus hours remaining, divided by 48, clamped to the range 0.0 to 1.0."

    Design: Corner/calculations/negative_hours_remaining_clamp_the_pressure_and_cap_the_score_at_eighty
    """
    ctx = _setup_queued_build(api)

    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-04T00:00:00Z"}, ctx.policy_admin), 200
    )
    capped = ctx.submission()
    assert_decimal_equals(capped["priority_score"], 80.00, 2, "clamped priority")
    assert capped["priority_band"] == "HIGH"
    assert _instant(capped["effective_review_deadline_at"]) == _instant(
        "2026-08-02T00:00:00Z"
    )

    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-10T00:00:00Z"}, ctx.policy_admin), 200
    )
    still_capped = ctx.submission()
    assert_decimal_equals(
        still_capped["priority_score"], 80.00, 2, "priority six days later"
    )
    assert still_capped["state"] == "WAITING_FOR_REVIEW"
    assert _instant(still_capped["provisional_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )


def test_a_ninety_five_percent_disclosure_score_docks_one_point_of_priority(api):
    """"Step three combines three components each on a 0-to-100 scale: the standing component is
    the account's `standing_score_lifetime`; the urgency component is 100 times deadline pressure;
    the risk component is 100 times one minus `disclosure_accuracy_score_provisional`."

    Design: Corner/calculations/a_ninety_five_percent_disclosure_score_docks_one_point_of_review_priority
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_pre_review=False)
    _file_minor_usage_finding(ctx, 0.95)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )
    assert reported["pre_review_blocking_reasons"] == []

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert_decimal_equals(queued["priority_score"], 49.00, 2, "docked priority")
    assert queued["priority_band"] == "NORMAL"
    assert_decimal_equals(
        queued["disclosure_accuracy_score_provisional"], 0.9500, 4, "provisional"
    )
    assert _instant(queued["effective_review_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )


# ---------------------------------------------------------------------------
# program standing: the two variants and the decay tiers
# ---------------------------------------------------------------------------
def _setup_one_critical_rejection(api):
    """One build REJECTED at the default instant on a single CRITICAL reason."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api)
    rejected = reject(
        ctx,
        rejection_reasons_for(
            ctx.rules["privacy"],
            severity="CRITICAL",
            detail="Undisclosed device identifier collection observed in build 100.",
        ),
    )
    assert rejected["state"] == "REJECTED"
    return ctx


def test_one_critical_rejection_docks_twelve_points_from_both_standing_variants(api):
    """"Each carries weight 12 if `CRITICAL`, 6 if `MAJOR` and 2 if `MINOR`, multiplied by a decay
    factor."

    Design: Corner/calculations/one_critical_rejection_docks_twelve_points_from_both_standing_variants
    """
    ctx = _setup_one_critical_rejection(api)

    standing = ctx.standing()
    assert_decimal_equals(standing["standing_score_rolling_365"], 88.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert_decimal_equals(standing["decayed_penalty_total"], 12.00, 2, "decayed")
    assert_decimal_equals(standing["undecayed_penalty_total"], 12.00, 2, "undecayed")
    assert_decimal_equals(standing["credit_total"], 0.00, 2, "credit")
    assert standing["rejection_strike_count"] == 1
    assert standing["penalty_event_count"] == 1


def test_at_exactly_ninety_days_the_penalty_is_undecayed_and_at_ninety_one_it_halves(api):
    """"`standing_score_rolling_365` counts only rows dated at or after 365 days before the current
    instant, with the lower bound inclusive, and decays each penalty by 1.0 when it is at most 90
    days old, 0.5 when older than 90 but at most 180 days, and 0.25 when older than 180 days, where
    age is the whole number of complete days since `recorded_at`."

    Design: Corner/calculations/at_exactly_ninety_days_the_penalty_is_undecayed_and_at_ninety_one_it_halves
    """
    ctx = _setup_one_critical_rejection(api)

    validate_success(
        api.set_clock_raw({"current_utc": "2026-10-30T00:00:00Z"}, ctx.policy_admin), 200
    )
    day_ninety = ctx.standing()
    assert_decimal_equals(
        day_ninety["standing_score_rolling_365"], 88.00, 2, "rolling on day 90"
    )
    assert_decimal_equals(
        day_ninety["standing_score_lifetime"], 88.00, 2, "lifetime on day 90"
    )
    assert_decimal_equals(
        day_ninety["decayed_penalty_total"], 12.00, 2, "undecayed on day 90"
    )

    validate_success(
        api.set_clock_raw({"current_utc": "2026-10-31T00:00:00Z"}, ctx.policy_admin), 200
    )
    day_ninety_one = ctx.standing()
    assert_decimal_equals(
        day_ninety_one["standing_score_rolling_365"], 94.00, 2, "rolling on day 91"
    )
    assert_decimal_equals(
        day_ninety_one["standing_score_lifetime"], 88.00, 2, "lifetime on day 91"
    )
    assert_decimal_equals(
        day_ninety_one["decayed_penalty_total"], 6.00, 2, "halved penalty"
    )
    assert_decimal_equals(
        day_ninety_one["undecayed_penalty_total"], 12.00, 2, "undecayed"
    )


def test_past_one_hundred_and_eighty_days_the_penalty_decays_to_a_quarter(api):
    """"`standing_score_lifetime` has no window at all — every row of the account's history counts
    — and applies no decay whatsoever."

    Design: Corner/calculations/past_one_hundred_and_eighty_days_the_penalty_decays_to_a_quarter
    """
    ctx = _setup_one_critical_rejection(api)

    validate_success(
        api.set_clock_raw({"current_utc": "2027-01-28T00:00:00Z"}, ctx.policy_admin), 200
    )
    day_one_eighty = ctx.standing()
    assert_decimal_equals(
        day_one_eighty["standing_score_rolling_365"], 94.00, 2, "rolling on day 180"
    )
    assert_decimal_equals(
        day_one_eighty["decayed_penalty_total"], 6.00, 2, "half decay on day 180"
    )
    assert_decimal_equals(
        day_one_eighty["standing_score_lifetime"], 88.00, 2, "lifetime on day 180"
    )

    validate_success(
        api.set_clock_raw({"current_utc": "2027-01-29T00:00:00Z"}, ctx.policy_admin), 200
    )
    day_one_eighty_one = ctx.standing()
    assert_decimal_equals(
        day_one_eighty_one["standing_score_rolling_365"], 97.00, 2, "rolling on day 181"
    )
    assert_decimal_equals(
        day_one_eighty_one["decayed_penalty_total"], 3.00, 2, "quarter decay"
    )
    assert_decimal_equals(
        day_one_eighty_one["standing_score_lifetime"], 88.00, 2, "lifetime on day 181"
    )
    assert_decimal_equals(
        day_one_eighty_one["undecayed_penalty_total"], 12.00, 2, "undecayed"
    )


def test_the_rolling_window_drops_the_penalty_entirely_one_day_past_a_year(api):
    """"The penalty set is every rejection reason recorded against this account's submissions whose
    `appeal_disposition` is not `OVERTURNED` and whose `recorded_at` falls inside the variant's
    window."

    Design: Corner/calculations/the_rolling_window_drops_the_penalty_entirely_one_day_past_a_year
    """
    ctx = _setup_one_critical_rejection(api)

    validate_success(
        api.set_clock_raw({"current_utc": "2027-08-01T00:00:00Z"}, ctx.policy_admin), 200
    )
    on_the_bound = ctx.standing()
    assert_decimal_equals(
        on_the_bound["standing_score_rolling_365"], 97.00, 2, "rolling on day 365"
    )
    assert_decimal_equals(
        on_the_bound["decayed_penalty_total"], 3.00, 2, "quarter decay on day 365"
    )
    assert on_the_bound["rejection_strike_count"] == 1

    validate_success(
        api.set_clock_raw({"current_utc": "2027-08-02T00:00:00Z"}, ctx.policy_admin), 200
    )
    outside = ctx.standing()
    assert_decimal_equals(
        outside["standing_score_rolling_365"], 100.00, 2, "rolling past the window"
    )
    assert_decimal_equals(
        outside["decayed_penalty_total"], 0.00, 2, "no penalty in scope"
    )
    assert outside["rejection_strike_count"] == 0
    assert_decimal_equals(
        outside["standing_score_lifetime"], 88.00, 2, "lifetime is permanent"
    )
    assert_decimal_equals(
        outside["undecayed_penalty_total"], 12.00, 2, "undecayed is permanent"
    )


# ---------------------------------------------------------------------------
# capacity windows: the selector and the pool ceiling
# ---------------------------------------------------------------------------
POOL_A_WINDOW = {"starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-09-01T00:00:00Z"}


def _setup_pre_review_passed(api):
    """One build PRE_REVIEW_PASSED with a single live IOS POOL_A window of 5 slots."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"
    return ctx


def _open_window(ctx, **overrides):
    return validate_success(
        ctx.client.create_review_capacity_window(
            create_review_capacity_window_payload(**overrides), ctx.policy_admin
        ),
        201,
    )


def test_the_window_with_the_most_free_slots_wins_the_reservation(api):
    """"Among the eligible, rank by `slots_available` descending, then by `starts_at` ascending, and
    break any remaining tie by `created_at` ascending; never by `id`."

    Design: Corner/calculations/the_window_with_the_most_free_slots_wins_the_reservation
    """
    ctx = _setup_pre_review_passed(api)
    roomier = _open_window(
        ctx, reviewer_pool_code="POOL_B", capacity_slots=6, **POOL_A_WINDOW
    )
    assert roomier["slots_available"] == 6

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["review_window_id"] == roomier["id"]

    chosen = ctx.window(roomier["id"])
    assert chosen["slots_reserved"] == 1
    assert chosen["slots_available"] == 5
    passed_over = ctx.window()
    assert passed_over["slots_reserved"] == 0
    assert passed_over["slots_available"] == 5


def test_a_window_that_has_not_started_yet_is_invisible_to_the_selector(api):
    """"Eligible windows are those whose `status` is `OPEN`, whose `platform` equals the app's
    `platform`, whose half-open interval contains the current instant — `starts_at` at or before it
    and `ends_at` strictly after it — and whose `slots_available` is at least 1."

    Design: Corner/calculations/a_window_that_has_not_started_yet_is_invisible_to_the_selector
    """
    ctx = _setup_pre_review_passed(api)
    future = _open_window(
        ctx,
        reviewer_pool_code="POOL_B",
        starts_at="2026-08-02T00:00:00Z",
        ends_at="2026-09-01T00:00:00Z",
        capacity_slots=8,
    )
    assert future["status"] == "OPEN"

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["review_window_id"] == ctx.window_id

    untouched = ctx.window(future["id"])
    assert untouched["slots_reserved"] == 0
    assert untouched["slots_available"] == 8
    assert ctx.window()["slots_available"] == 4


def test_an_android_window_never_absorbs_an_ios_submission(api):
    """"If no window is eligible the queue call is refused with `ERR_NO_REVIEW_CAPACITY` and nothing
    at all changes."

    Design: Corner/calculations/an_android_window_never_absorbs_an_ios_submission
    """
    ctx = _setup_pre_review_passed(api)
    android = _open_window(
        ctx, platform="ANDROID", capacity_slots=10, **POOL_A_WINDOW
    )
    closed = validate_success(
        api.close_review_capacity_window(ctx.window_id, ctx.policy_admin), 200
    )
    assert closed["status"] == "CLOSED"

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_NO_REVIEW_CAPACITY,
        409,
    )

    assert ctx.window(android["id"])["slots_reserved"] == 0
    stalled = ctx.submission()
    assert stalled["state"] == "PRE_REVIEW_PASSED"
    assert stalled["review_window_id"] is None


def test_aggregate_pool_capacity_of_exactly_ten_passes_and_eleven_is_refused(api):
    """"Intersection is half-open, so adjacency never counts — a window ending exactly when another
    begins is always legal — and the ceiling is inclusive: a total of exactly 10 passes while 11
    fails."

    Design: Corner/calculations/aggregate_pool_capacity_of_exactly_ten_passes_and_eleven_is_refused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_submission=False, window_overrides=dict(POOL_A_WINDOW)
    )

    second = _open_window(
        ctx,
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-09-15T00:00:00Z",
        capacity_slots=5,
    )
    assert second["capacity_slots"] == 5
    assert second["slots_available"] == 5

    validate_error(
        api.create_review_capacity_window(
            create_review_capacity_window_payload(
                starts_at="2026-08-20T00:00:00Z",
                ends_at="2026-08-21T00:00:00Z",
                capacity_slots=1,
            ),
            ctx.policy_admin,
        ),
        ApiErrorId.ERR_REVIEW_POOL_OVERSUBSCRIBED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_review_capacity_windows(
            ctx.policy_admin,
            params={"platform": "IOS", "reviewer_pool_code": "POOL_A"},
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_two_windows_that_merely_touch_endpoints_do_not_intersect(api):
    """"Creation is subject to a pool-level ceiling: summed across every `OPEN` window of the same
    `platform` and `reviewer_pool_code` whose interval intersects the new one, total
    `capacity_slots` may not exceed 10, and a breach is refused with
    `ERR_REVIEW_POOL_OVERSUBSCRIBED`."

    Design: Corner/calculations/two_windows_that_merely_touch_endpoints_do_not_intersect
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_submission=False, window_overrides=dict(POOL_A_WINDOW)
    )

    adjacent = _open_window(
        ctx,
        starts_at="2026-09-01T00:00:00Z",
        ends_at="2026-10-01T00:00:00Z",
        capacity_slots=10,
    )
    assert adjacent["capacity_slots"] == 10
    assert adjacent["slots_available"] == 10
    assert adjacent["status"] == "OPEN"
    assert ctx.window()["capacity_slots"] == 5


# ---------------------------------------------------------------------------
# rollout occupancy and the rollback cooldown
# ---------------------------------------------------------------------------
def _plan_payload(ctx, scheduled_start_at, expected_version=None):
    return {
        "expected_app_record_version": (
            expected_version if expected_version is not None else ctx.app_version()
        ),
        "app_record_id": ctx.app_record_id,
        "submission_id": ctx.submission_id,
        "mode": "PHASED",
        "scheduled_start_at": scheduled_start_at,
    }


def test_a_new_plan_starting_exactly_when_the_old_one_ends_still_conflicts(api):
    """"A plan's interval runs from `scheduled_start_at` to `projected_end_at` and is **closed at
    both ends**, so touching endpoints *do* conflict: a new plan starting exactly when an existing
    plan is projected to end is rejected, whereas back-to-back capacity windows are always legal."

    Design: Corner/calculations/a_new_plan_starting_exactly_when_the_old_one_ends_still_conflicts
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api)

    scheduled = add_rollout_plan(ctx, mode="PHASED", scheduled_start_at=DEFAULT_CLOCK)
    assert scheduled["state"] == "SCHEDULED"
    assert _instant(scheduled["projected_end_at"]) == _instant("2026-08-08T00:00:00Z")

    version_before = ctx.app_version()
    validate_error(
        api.create_rollout_plan(
            _plan_payload(ctx, "2026-08-08T00:00:00Z", version_before),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )

    rows, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert ctx.app_version() == version_before


def test_the_seventy_two_hour_rollback_cooldown_edge_is_legal_one_second_earlier_is_not(api):
    """"Against a plan in `ROLLED_BACK` a one-sided cooldown applies instead: the new
    `scheduled_start_at` must be at or after that plan's `terminated_at` plus 72 hours, and the
    comparison is strict, so scheduling exactly at the buffer edge is legal."

    Design: Corner/calculations/the_seventy_two_hour_rollback_cooldown_edge_is_legal_one_second_earlier_is_not
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api, mode="PHASED", window_overrides=dict(POOL_A_WINDOW)
    )
    halted = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert halted["state"] == "ROLLED_BACK"
    assert _instant(halted["terminated_at"]) == _instant(DEFAULT_CLOCK)

    version_before = ctx.app_version()
    validate_error(
        api.create_rollout_plan(
            _plan_payload(ctx, "2026-08-03T23:59:59Z", version_before),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )

    on_the_edge = validate_success(
        api.create_rollout_plan(
            _plan_payload(ctx, "2026-08-04T00:00:00Z", version_before),
            ctx.release_manager,
        ),
        201,
    )
    assert on_the_edge["state"] == "SCHEDULED"
    assert _instant(on_the_edge["scheduled_start_at"]) == _instant(
        "2026-08-04T00:00:00Z"
    )
    assert _instant(on_the_edge["projected_end_at"]) == _instant(
        "2026-08-11T00:00:00Z"
    )


def test_the_released_and_held_back_shares_sum_to_one_hundred_through_the_ladder(api):
    """"A successful advance sets `phase_index`, re-stamps `phase_entered_at`, sets
    `released_share_pct` to the share at the new index and `held_back_share_pct` to 100.00 minus it,
    and mirrors both onto the app record."

    Design: Corner/calculations/the_released_and_held_back_shares_sum_to_one_hundred_through_advance_and_rollback
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api, mode="PHASED", window_overrides=dict(POOL_A_WINDOW)
    )
    opening = ctx.plan()
    assert opening["state"] == "PHASE_ACTIVE"
    assert opening["phase_index"] == 0
    assert_decimal_equals(opening["released_share_pct"], 1.00, 2, "phase 0 released")
    assert_decimal_equals(opening["held_back_share_pct"], 99.00, 2, "phase 0 held back")

    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T00:00:00Z"}, ctx.policy_admin), 200
    )
    first = validate_success(
        api.advance_rollout_plan(ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager),
        200,
    )
    assert first["phase_index"] == 1
    assert_decimal_equals(first["released_share_pct"], 2.00, 2, "phase 1 released")
    assert_decimal_equals(first["held_back_share_pct"], 98.00, 2, "phase 1 held back")

    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-03T00:00:00Z"}, ctx.policy_admin), 200
    )
    second = validate_success(
        api.advance_rollout_plan(ctx.plan_id, {"to_phase_index": 2}, ctx.release_manager),
        200,
    )
    assert second["phase_index"] == 2
    assert_decimal_equals(second["released_share_pct"], 5.00, 2, "phase 2 released")
    assert_decimal_equals(second["held_back_share_pct"], 95.00, 2, "phase 2 held back")
    mirrored = ctx.app()
    assert_decimal_equals(mirrored["released_share_pct"], 5.00, 2, "app released")
    assert_decimal_equals(mirrored["held_back_share_pct"], 95.00, 2, "app held back")

    rolled_back = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert_decimal_equals(
        rolled_back["released_share_pct"], 0.00, 2, "released after rollback"
    )
    assert_decimal_equals(
        rolled_back["held_back_share_pct"], 100.00, 2, "held back after rollback"
    )
    restored = ctx.app()
    assert_decimal_equals(
        restored["released_share_pct"], 0.00, 2, "app released after rollback"
    )
    assert_decimal_equals(
        restored["held_back_share_pct"], 100.00, 2, "app held back after rollback"
    )
    assert restored["rollback_count"] == 1


def test_a_distributed_app_multiplies_the_impact_severity_onto_the_ceiling(api):
    """"`impact_severity` is the rule's `severity_weight` multiplied by the count of entries in
    `affected_feature_codes` multiplied by `exposure_factor`, with the single product rounded half up
    to two decimal places."

    Design: Corner/calculations/a_distributed_app_multiplies_the_impact_severity_onto_the_inclusive_ceiling
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api, mode="PHASED", window_overrides=dict(POOL_A_WINDOW)
    )
    assert ctx.app()["distribution_state"] == "PHASED_ROLLOUT"

    successor = add_effective_rule(
        ctx,
        key="privacy_v2",
        title="Account Deletion In App",
        version_label="2026.09",
        effective_from=DEFAULT_CLOCK,
        supersedes_rule_id=ctx.rules["privacy"],
    )
    assert successor["impacted_app_count"] == 1

    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 1
    assessment_id = rows[0]["id"]

    started = validate_success(
        api.assess_impact(assessment_id, {"action": "START"}, ctx.compliance_officer),
        200,
    )
    assert started["status"] == "IN_ASSESSMENT"
    assert_decimal_equals(started["impact_severity"], 6.00, 2, "severity")
    assert started["affected_feature_codes"] == ["ACCOUNT_DELETION"]
    assert _instant(started["remediation_deadline_at"]) == _instant(
        "2026-08-31T00:00:00Z"
    )

    accepted = validate_success(
        api.assess_impact(
            assessment_id,
            {
                "action": "ACCEPT_NO_CHANGE",
                "note": "The existing deletion flow already satisfies the reworded rule.",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert accepted["status"] == "ACCEPTED_NO_CHANGE"
    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "PASSED"
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 100.00, 2, "index after acceptance"
    )
