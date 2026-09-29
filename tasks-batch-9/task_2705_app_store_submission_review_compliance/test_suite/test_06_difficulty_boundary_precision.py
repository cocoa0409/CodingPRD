"""Difficulty rule: boundary_precision_check.

Inclusive-versus-strict comparisons and the exact rounding mode, exercised one
step either side of the declared boundary.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_approved_commerce_item,
    add_effective_rule,
    add_mapping,
    add_submission,
    assert_decimal_equals,
    assert_posture,
    create_behavior_finding_payload,
    create_expedite_request_payload,
    create_feature_mapping_payload,
    get_success_data,
    set_clock,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# posture_index_exactly_at_floor_not_restricted
# ---------------------------------------------------------------------------
def _setup_index_at_floor(api):
    """SAFETY 5 PASSED + PRIVACY 4 PASSED + DESIGN 1 NOT_STARTED == 9/10 == 90.00."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, with_rule=False, with_submission=False, with_window=False
    )
    add_effective_rule(
        ctx, key="safety", category="SAFETY", title="Physical harm"
    )
    add_effective_rule(ctx, key="privacy", category="PRIVACY")
    add_effective_rule(
        ctx,
        key="design1",
        category="DESIGN",
        title="Minimum functionality",
        requires_feature_mapping=False,
    )
    add_effective_rule(
        ctx,
        key="design2",
        category="DESIGN",
        title="Spam and duplicate submissions",
        requires_feature_mapping=False,
    )
    add_mapping(
        ctx,
        ctx.rules["safety"],
        feature_code="CHILD_SAFETY_CONTROLS",
        advance="PASS",
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
    add_mapping(
        ctx,
        ctx.rules["design1"],
        feature_code="ONBOARDING_TOUR",
        advance=None,
        key="design1",
        risk_weight=1,
    )
    add_submission(ctx, build_number=10)
    return ctx


def _add_fourth_design_mapping(ctx):
    return add_mapping(
        ctx,
        ctx.rules["design2"],
        feature_code="STORE_LISTING_UNIQUENESS",
        advance=None,
        key="design2",
        risk_weight=1,
    )


def _expedite_payload(ctx, justification):
    return create_expedite_request_payload(
        ctx.submission_id,
        justification_category="SECURITY_FIX",
        justification=justification,
    )


def test_index_of_exactly_ninety_leaves_the_posture_open(api):
    """"Multiply each weight by its factor, sum those products, sum the weights separately,
    divide the first unrounded sum by the second unrounded sum, multiply by 100, and round
    the single result half up to two decimal places."

    Design: Difficulty/boundary_precision_check/posture_index_exactly_at_floor_not_restricted
    """
    ctx = _setup_index_at_floor(api)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(summary["feature_compliance_index"], 90.00, 2, "index")
    assert_posture(summary, "OPEN", [])
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 90.00, 2, "index on the app row"
    )
    assert_posture(ctx.app(), "OPEN", [])


def test_expedite_request_is_accepted_at_exactly_the_floor_and_consumes_no_credit(api):
    """"The request lands `REQUESTED` with `requested_at` stamped and `publisher_account_id`
    copied from the submission's app record — the account, not the submission, is the quota
    subject."

    Design: Difficulty/boundary_precision_check/posture_index_exactly_at_floor_not_restricted
    """
    ctx = _setup_index_at_floor(api)

    request = validate_success(
        api.create_expedite_request(
            _expedite_payload(
                ctx, "TLS pinning regression fix for the wallet transport layer"
            ),
            ctx.release_manager,
        ),
        201,
    )
    assert request["state"] == "REQUESTED"
    assert request["publisher_account_id"] == ctx.account_id
    assert request["requested_at"] == DEFAULT_CLOCK
    assert ctx.account()["expedite_credits_remaining"] == 2


def test_one_more_unstarted_mapping_rounds_to_81_82_and_restricts(api):
    """"A restricted posture is narrower: it blocks only the release-advancing subset —
    queueing a submission, creating a rollout plan, starting a rollout, advancing a rollout
    phase, resuming a paused rollout, submitting a commerce item for commerce review, and
    creating an expedite request — with the code `ERR_APP_COMPLIANCE_RESTRICTED` and HTTP
    409."

    Design: Difficulty/boundary_precision_check/posture_index_exactly_at_floor_not_restricted
    """
    ctx = _setup_index_at_floor(api)
    get_success_data(
        api.create_expedite_request(
            _expedite_payload(
                ctx, "TLS pinning regression fix for the wallet transport layer"
            ),
            ctx.release_manager,
        )
    )

    fourth = _add_fourth_design_mapping(ctx)
    assert fourth["self_review_status"] == "NOT_STARTED"

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(summary["feature_compliance_index"], 81.82, 2, "index")
    assert_posture(summary, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])

    validate_error(
        api.create_expedite_request(
            _expedite_payload(
                ctx, "TLS pinning regression fix, second attempt after mapping growth"
            ),
            ctx.release_manager,
        ),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )
    rows, _meta = validate_paginated(
        api.list_expedite_requests(
            ctx.release_manager, params={"submission_id": ctx.submission_id}
        )
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# disclosure_exactly_at_pass_threshold
# ---------------------------------------------------------------------------
def _setup_two_minor_findings(api):
    """A build declaring nothing, with two OPEN MINOR findings sitting exactly on
    both in-scope boundaries: detected_at == the pre-review instant and
    scanner_confidence == 0.8000."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
        with_pre_review=False,
    )
    first = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="DEVICE_ID",
                observed_purpose="ADVERTISING",
                observed_linked_to_user=True,
                observed_tracking=True,
                severity="MINOR",
                scanner_confidence=0.8,
                detected_at=DEFAULT_CLOCK,
            ),
            ctx.policy_admin,
        )
    )
    second = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="USAGE_DATA",
                observed_purpose="ANALYTICS",
                observed_linked_to_user=False,
                observed_tracking=False,
                endpoint_domain="metrics.northwind.example",
                severity="MINOR",
                scanner_confidence=0.8,
                detected_at=DEFAULT_CLOCK,
            ),
            ctx.policy_admin,
        )
    )
    return ctx, first["id"], second["id"]


def _dismiss(api, ctx, finding_id):
    return validate_success(
        api.triage_behavior_finding(
            finding_id,
            {
                "action": "DISMISS",
                "justification": (
                    "Aggregate usage metrics are exempt under the 2026.08 reading"
                ),
            },
            ctx.policy_admin,
        ),
        200,
    )


def test_two_minor_findings_on_the_scope_boundaries_score_0_9000(api):
    """"It first sets `pre_review_checked_at` to the current instant and only then scores, so
    a finding detected at exactly this instant is inside the provisional window."

    Design: Difficulty/boundary_precision_check/disclosure_exactly_at_pass_threshold
    """
    ctx, _a_id, _b_id = _setup_two_minor_findings(api)

    reported = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(
        reported["disclosure_accuracy_score_provisional"], 0.9000, 4, "provisional"
    )
    assert reported["pre_review_passed"] is False
    assert reported["pre_review_blocking_reasons"] == ["PRIVACY_DISCLOSURE_INACCURATE"]
    assert reported["state"] == "DRAFT"
    # `ERR_PRE_REVIEW_NOT_PASSED` and the seventh-rung `ERR_INVALID_SUBMISSION_STATE` are
    # both reachable readings for a build left in `DRAFT` by a failed self-review; the PRD
    # does not pin their relative precedence.
    validate_error_is_one_of(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        [
            ApiErrorId.ERR_PRE_REVIEW_NOT_PASSED,
            ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        ],
    )


def test_dismissing_one_finding_lands_exactly_on_the_inclusive_threshold(api):
    """"When at least one code is recorded the submission stays in `DRAFT` with
    `pre_review_passed` false; when the array comes back empty the submission moves `DRAFT →
    PRE_REVIEW_PASSED`, `pre_review_passed` becomes true, and `attested_by_user_id` is
    stamped with the acting officer, who thereby becomes the subject of the
    segregation-of-duties rule at the decision gate."

    Design: Difficulty/boundary_precision_check/disclosure_exactly_at_pass_threshold
    """
    ctx, _a_id, b_id = _setup_two_minor_findings(api)
    get_success_data(api.pre_review_check(ctx.submission_id, ctx.compliance_officer))

    dismissed = _dismiss(api, ctx, b_id)
    assert dismissed["status"] == "DISMISSED"
    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_provisional"],
        0.9500,
        4,
        "provisional",
    )

    rechecked = validate_success(
        api.pre_review_check(ctx.submission_id, ctx.compliance_officer), 200
    )
    assert rechecked["pre_review_blocking_reasons"] == []
    assert rechecked["state"] == "PRE_REVIEW_PASSED"
    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"


def test_final_score_of_exactly_0_9500_still_approves(api):
    """"The provisional score is rewritten by the self-review check and by any finding or
    declaration mutation; the final score is rewritten when a reviewer claims the build and
    again at the decision gate."

    Design: Difficulty/boundary_precision_check/disclosure_exactly_at_pass_threshold
    """
    ctx, a_id, b_id = _setup_two_minor_findings(api)
    get_success_data(api.pre_review_check(ctx.submission_id, ctx.compliance_officer))
    _dismiss(api, ctx, b_id)
    get_success_data(api.pre_review_check(ctx.submission_id, ctx.compliance_officer))
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.9500, 4, "final"
    )
    decided = validate_success(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        200,
    )
    assert decided["state"] == "APPROVED"
    assert get_success_data(
        api.get_behavior_finding(a_id, ctx.policy_admin)
    )["status"] == "OPEN"


# ---------------------------------------------------------------------------
# empty_effective_mapping_set_index_zero
# ---------------------------------------------------------------------------
def _setup_no_mappings_one_draft_rule(api):
    """An app with zero mappings, and one SAFETY guideline left in DRAFT."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api, with_rule=False, with_submission=False, with_window=False
    )
    add_effective_rule(
        ctx,
        key="safety",
        publish=False,
        category="SAFETY",
        title="Physical harm",
    )
    return ctx


def _safety_mapping_payload(ctx):
    return create_feature_mapping_payload(
        ctx.app_record_id,
        ctx.rules["safety"],
        feature_code="CHILD_SAFETY_CONTROLS",
        risk_weight=5,
    )


def test_app_with_no_mappings_at_all_scores_zero_and_is_restricted(api):
    """"When the contributing set is empty — an app with no mappings, or an app whose every
    mapping points at a superseded rule — the index is 0.00, not 100.00: absence of evidence
    is not evidence of compliance, and this is the boundary that keeps a brand-new app record
    `RESTRICTED` rather than `OPEN`."

    Design: Difficulty/boundary_precision_check/empty_effective_mapping_set_index_zero
    """
    ctx = _setup_no_mappings_one_draft_rule(api)

    summary = validate_success(
        api.get_compliance_summary(ctx.app_record_id, ctx.compliance_officer), 200
    )
    assert_decimal_equals(summary["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(summary, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    assert summary["mapping_total"] == 0


def test_a_draft_rule_cannot_be_mapped_and_publishing_it_only_grows_the_denominator(api):
    """"A mapping may only cite a rule that is currently `EFFECTIVE` — citing a draft or
    superseded rule is `ERR_GUIDELINE_RULE_NOT_EFFECTIVE` — and the app it names must not be
    frozen."

    Design: Difficulty/boundary_precision_check/empty_effective_mapping_set_index_zero
    """
    ctx = _setup_no_mappings_one_draft_rule(api)

    validate_error(
        api.create_feature_mapping(
            _safety_mapping_payload(ctx), ctx.compliance_officer
        ),
        ApiErrorId.ERR_GUIDELINE_RULE_NOT_EFFECTIVE,
        409,
    )
    published = validate_success(
        api.publish_guideline_rule(ctx.rules["safety"], ctx.policy_admin), 200
    )
    assert published["status"] == "EFFECTIVE"

    mapping = validate_success(
        api.create_feature_mapping(
            _safety_mapping_payload(ctx), ctx.compliance_officer
        ),
        201,
    )
    assert mapping["self_review_status"] == "NOT_STARTED"
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 0.00, 2, "index at 0 earned of 5"
    )


def test_start_lifts_the_index_to_exactly_25_and_pass_to_100(api):
    """"Each contributing mapping has a weight equal to its `risk_weight` and a compliance
    factor determined solely by its `self_review_status`: 1.0 for `PASSED`, 1.0 for
    `WAIVED_BY_PLATFORM`, 0.5 for `STALE`, 0.25 for `IN_PROGRESS`, 0.0 for `NOT_STARTED` and
    0.0 for `FAILED`."

    Design: Difficulty/boundary_precision_check/empty_effective_mapping_set_index_zero
    """
    ctx = _setup_no_mappings_one_draft_rule(api)
    get_success_data(api.publish_guideline_rule(ctx.rules["safety"], ctx.policy_admin))
    mapping = get_success_data(
        api.create_feature_mapping(_safety_mapping_payload(ctx), ctx.compliance_officer)
    )

    started = validate_success(
        api.self_review_mapping(
            mapping["id"], {"outcome": "START"}, ctx.compliance_officer
        ),
        200,
    )
    assert started["self_review_status"] == "IN_PROGRESS"
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 25.00, 2, "index at the 0.25 factor"
    )

    validate_success(
        api.self_review_mapping(
            mapping["id"],
            {
                "outcome": "PASS",
                "evidence_ref": "https://evidence.northwind.example/child-safety.pdf",
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(ctx.app(), "OPEN", [])
    rows, _meta = validate_paginated(
        api.list_feature_mappings(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# retention_boundary_and_half_cent_round_half_up
# ---------------------------------------------------------------------------
def _setup_two_approved_subscriptions(api):
    """A FULLY_RELEASED app with two APPROVED subscriptions, one retained exactly 12
    months and one retained 11."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api,
        mode="IMMEDIATE",
        submission_overrides={"release_mode": "IMMEDIATE"},
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
    )
    annual = add_approved_commerce_item(
        ctx,
        item_type="SUBSCRIPTION",
        price_tier_cents=4999,
        subscriber_retention_months=12,
    )
    monthly = add_approved_commerce_item(
        ctx,
        item_type="SUBSCRIPTION",
        price_tier_cents=499,
        subscriber_retention_months=11,
    )
    return ctx, annual["id"], monthly["id"]


def _report(api, ctx, item_id, period_label, gross=6710):
    return api.report_commerce_revenue(
        item_id,
        {"reported_gross_cents": gross, "period_label": period_label},
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


def test_twelve_month_retention_takes_the_retained_rate_and_rounds_the_half_cent_up(api):
    """"Each line then adjusts that rate: a `SUBSCRIPTION` item whose
    `subscriber_retention_months` is 12 or more takes the lower of the base rate and the
    retained-subscriber rate of 0.15 — 12 months qualifies, 11 does not — and an
    `EXTERNAL_PAYMENT_LINK` item has 0.03 subtracted from its rate, rounded to two decimals."

    Design: Difficulty/boundary_precision_check/retention_boundary_and_half_cent_round_half_up
    """
    ctx, annual_id, _monthly_id = _setup_two_approved_subscriptions(api)
    assert ctx.app()["distribution_state"] == "FULLY_RELEASED"

    reported = validate_success(_report(api, ctx, annual_id, "2026-Q2"), 200)
    assert_decimal_equals(reported["commission_rate_applied"], 0.15, 2, "rate")
    assert reported["commission_cents"] == 1007, (
        "6710 * 0.15 == 1006.5 must round half up to 1007"
    )


def test_eleven_month_retention_stays_on_the_standard_rate(api):
    """"The resulting rate is stored as `commission_rate_applied`, and `commission_cents` is
    `reported_gross_cents` multiplied by that rate, rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/retention_boundary_and_half_cent_round_half_up
    """
    ctx, _annual_id, monthly_id = _setup_two_approved_subscriptions(api)

    reported = validate_success(_report(api, ctx, monthly_id, "2026-Q3"), 200)
    assert_decimal_equals(reported["commission_rate_applied"], 0.30, 2, "rate")
    assert reported["commission_cents"] == 2013, "6710 * 0.30 is exact"


def test_each_period_settles_its_single_line_and_is_recorded_on_the_account(api):
    """"A successful report appends the `period_label` to `settlement_finalized_periods` if it
    is not already present and recomputes the line's rate and commission."

    Design: Difficulty/boundary_precision_check/retention_boundary_and_half_cent_round_half_up
    """
    ctx, annual_id, monthly_id = _setup_two_approved_subscriptions(api)
    get_success_data(_report(api, ctx, annual_id, "2026-Q2"))
    get_success_data(_report(api, ctx, monthly_id, "2026-Q3"))

    q2 = _settlement(api, ctx, "2026-Q2")
    assert q2["line_count"] == 1
    assert q2["gross_cents_total"] == 6710
    assert q2["commission_cents_total"] == 1007
    assert q2["net_cents_total"] == 5703

    q3 = _settlement(api, ctx, "2026-Q3")
    assert q3["line_count"] == 1
    assert q3["gross_cents_total"] == 6710
    assert q3["commission_cents_total"] == 2013
    assert q3["net_cents_total"] == 4697

    assert ctx.account()["settlement_finalized_periods"] == ["2026-Q2", "2026-Q3"]


def test_a_second_report_for_the_same_item_is_refused(api):
    """"A second report for the same item, or a report against a period already recorded in
    the account's `settlement_finalized_periods`, is refused with
    `ERR_REVENUE_ALREADY_REPORTED` — gross proceeds are stated exactly once, and commission is
    recomputed from that stored figure on every settlement read thereafter."

    Design: Difficulty/boundary_precision_check/retention_boundary_and_half_cent_round_half_up
    """
    ctx, annual_id, _monthly_id = _setup_two_approved_subscriptions(api)
    get_success_data(_report(api, ctx, annual_id, "2026-Q2"))

    validate_error(
        _report(api, ctx, annual_id, "2026-Q4", gross=100),
        ApiErrorId.ERR_REVENUE_ALREADY_REPORTED,
        409,
    )
    assert get_success_data(
        api.get_commerce_item(annual_id, ctx.publisher_admin)
    )["reported_gross_cents"] == 6710


def test_a_period_with_no_reported_line_settles_to_zero(api):
    """"An empty line set yields a settlement commission of 0 and a publisher net of 0."

    Design: Difficulty/boundary_precision_check/retention_boundary_and_half_cent_round_half_up
    """
    ctx, annual_id, _monthly_id = _setup_two_approved_subscriptions(api)
    get_success_data(_report(api, ctx, annual_id, "2026-Q2"))

    q4 = _settlement(api, ctx, "2026-Q4")
    assert q4["line_count"] == 0
    assert q4["gross_cents_total"] == 0
    assert q4["commission_cents_total"] == 0
    assert q4["net_cents_total"] == 0
