"""Difficulty rule: dual_variant_calc.

Two named variants of one calculation evaluated against identical stored rows,
where the variants deliberately disagree and different gates read different
variants.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    assert_decimal_equals,
    create_behavior_finding_payload,
    get_success_data,
    num,
    privacy_item,
    rejection_reasons_for,
    run_pre_review,
    set_clock,
    setup_base_ios,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# disclosure_late_finding_provisional_vs_final
# ---------------------------------------------------------------------------
def _setup_late_finding(api):
    """BASE-IOS build declaring DEVICE_ID/ANALYTICS, then one MAJOR DEVICE_ID
    finding observed six hours after the pre-review instant."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        declared_privacy_items=[privacy_item("DEVICE_ID", "ANALYTICS")],
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
    )
    set_clock(api, "2026-08-01T06:00:00Z")
    finding = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="DEVICE_ID",
                observed_purpose="ADVERTISING",
                observed_linked_to_user=True,
                observed_tracking=True,
                severity="MAJOR",
                scanner_confidence=0.95,
                detected_at="2026-08-01T06:00:00Z",
            ),
            ctx.policy_admin,
        )
    )
    return ctx, finding["id"]


def test_late_finding_provisional_excludes_it_while_final_counts_it(api):
    """The provisional variant "counts only findings whose `status` is `OPEN`, whose
    `detected_at` is at or before the submission's `pre_review_checked_at`, and whose
    `scanner_confidence` is at or above 0.8000"; the final variant "counts findings
    whose `status` is `OPEN` *or* `DISPUTED`, with no time bound and no confidence
    floor".

    Design: Difficulty/dual_variant_calc/disclosure_late_finding_provisional_vs_final
    """
    ctx, _finding_id = _setup_late_finding(api)

    before = ctx.submission()
    assert before["pre_review_checked_at"] == "2026-08-01T00:00:00Z"
    assert_decimal_equals(
        before["disclosure_accuracy_score_provisional"], 1.0000, 4, "provisional"
    )

    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    after = ctx.submission()
    assert_decimal_equals(
        after["disclosure_accuracy_score_provisional"], 1.0000, 4, "provisional"
    )
    assert_decimal_equals(after["disclosure_accuracy_score_final"], 0.8000, 4, "final")
    assert num(after["disclosure_accuracy_score_provisional"]) != num(
        after["disclosure_accuracy_score_final"]
    ), "the two variants must disagree on identical stored rows"


def test_late_finding_queue_gate_reads_the_provisional_variant(api):
    """"Step one happens only at queue entry and never again: `queued_at` is set to the
    current instant and `provisional_deadline_at` is frozen at `queued_at` plus 48
    hours."

    Design: Difficulty/dual_variant_calc/disclosure_late_finding_provisional_vs_final
    """
    ctx, _finding_id = _setup_late_finding(api)

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["queued_at"] == "2026-08-01T06:00:00Z"
    assert queued["provisional_deadline_at"] == "2026-08-03T06:00:00Z"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority_score")
    assert queued["priority_band"] == "NORMAL"


def test_late_finding_approve_gate_reads_the_final_variant_only(api):
    """"`APPROVE` moves `IN_REVIEW → APPROVED` and re-checks the content gates against
    the authoritative final figures: `disclosure_accuracy_score_final` must be at or
    above 0.9500, otherwise `ERR_PRIVACY_DISCLOSURE_INACCURATE`".

    Design: Difficulty/dual_variant_calc/disclosure_late_finding_provisional_vs_final
    """
    ctx, finding_id = _setup_late_finding(api)
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    validate_error(
        api.decide_submission(
            ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer
        ),
        ApiErrorId.ERR_PRIVACY_DISCLOSURE_INACCURATE,
    )

    assert ctx.submission()["state"] == "IN_REVIEW", "a refused APPROVE changes no state"
    finding = get_success_data(api.get_behavior_finding(finding_id, ctx.policy_admin))
    assert finding["status"] == "OPEN"


# ---------------------------------------------------------------------------
# standing_rolling_vs_lifetime_decay
# ---------------------------------------------------------------------------
def _setup_aged_critical_rejection(api):
    """One CRITICAL rejection reason recorded at 2026-08-02, then the clock moved
    121 whole days forward to 2026-12-01."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api)
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(ctx.rules["privacy"]),
            },
            ctx.reviewer,
        )
    )
    set_clock(api, "2026-12-01T00:00:00Z")
    return ctx


def test_standing_rolling_decays_the_121_day_old_penalty_but_lifetime_does_not(api):
    """"`standing_score_rolling_365` counts only rows dated at or after 365 days before
    the current instant, with the lower bound inclusive, and decays each penalty by 1.0
    when it is at most 90 days old, 0.5 when older than 90 but at most 180 days, and
    0.25 when older than 180 days, where age is the whole number of complete days since
    `recorded_at`."

    Design: Difficulty/dual_variant_calc/standing_rolling_vs_lifetime_decay
    """
    ctx = _setup_aged_critical_rejection(api)

    standing = validate_success(
        api.get_standing(ctx.account_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(standing["standing_score_rolling_365"], 94.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert num(standing["standing_score_rolling_365"]) != num(
        standing["standing_score_lifetime"]
    ), "the two scopes must disagree once a rejection is more than 90 days old"


def test_standing_summary_reports_both_penalty_totals_side_by_side(api):
    """"The account's reputation is readable side by side through a standing summary,
    which evaluates both standing variants against the same stored rows and returns
    `standing_score_rolling_365`, `standing_score_lifetime`, `expedite_credits_remaining`,
    `credits_used_in_window`, `rejection_strike_count`, `penalty_event_count` (how many
    rejection reasons are in penalty scope), `decayed_penalty_total`,
    `undecayed_penalty_total` and `credit_total`."

    Design: Difficulty/dual_variant_calc/standing_rolling_vs_lifetime_decay
    """
    ctx = _setup_aged_critical_rejection(api)

    standing = validate_success(
        api.get_standing(ctx.account_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(standing["decayed_penalty_total"], 6.00, 2, "decayed total")
    assert_decimal_equals(
        standing["undecayed_penalty_total"], 12.00, 2, "undecayed total"
    )
    assert standing["penalty_event_count"] == 1
    assert standing["rejection_strike_count"] == 1
    assert_decimal_equals(standing["credit_total"], 0.00, 2, "credit total")


def test_account_row_stores_the_undecayed_lifetime_variant(api):
    """"Each carries weight 12 if `CRITICAL`, 6 if `MAJOR` and 2 if `MINOR`, multiplied
    by a decay factor."

    Design: Difficulty/dual_variant_calc/standing_rolling_vs_lifetime_decay
    """
    ctx = _setup_aged_critical_rejection(api)

    account = validate_success(
        api.get_publisher_account(ctx.account_id, ctx.publisher_admin), 200
    )
    assert_decimal_equals(account["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert_decimal_equals(
        account["standing_score_rolling_365"], 94.00, 2, "rolling"
    )


# ---------------------------------------------------------------------------
# disclosure_disputed_and_over_disclosure_divergence
# ---------------------------------------------------------------------------
def _setup_disputed_and_over_disclosed(api):
    """Two declared tuples, one MAJOR DEVICE_ID finding disputed before the
    pre-review check runs, and no finding at all on the declared PRECISE_LOCATION."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        api,
        declared_privacy_items=[
            privacy_item("DEVICE_ID", "ANALYTICS"),
            privacy_item("PRECISE_LOCATION", "APP_FUNCTIONALITY"),
        ],
        window_overrides={"ends_at": "2026-09-01T00:00:00Z"},
        with_pre_review=False,
    )
    finding = get_success_data(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="DEVICE_ID",
                observed_purpose="ADVERTISING",
                observed_linked_to_user=True,
                observed_tracking=True,
                severity="MAJOR",
                scanner_confidence=0.99,
                detected_at="2026-08-01T00:00:00Z",
            ),
            ctx.policy_admin,
        )
    )
    get_success_data(
        api.triage_behavior_finding(
            finding["id"],
            {
                "action": "DISPUTE",
                "justification": (
                    "Ad SDK removed in build 10; scanner matched a stale bundle"
                ),
            },
            ctx.compliance_officer,
        )
    )
    run_pre_review(ctx)
    return ctx, finding["id"]


def test_dispute_lifts_the_provisional_score_but_not_the_final_one(api):
    """"Disputing a finding removes it from the provisional scope but leaves it in the
    final scope, so a publisher who disputes everything watches the provisional score
    rise while the final score does not move at all."

    Design: Difficulty/dual_variant_calc/disclosure_disputed_and_over_disclosure_divergence
    """
    ctx, finding_id = _setup_disputed_and_over_disclosed(api)

    finding = get_success_data(api.get_behavior_finding(finding_id, ctx.policy_admin))
    assert finding["status"] == "DISPUTED"

    after_pre_review = ctx.submission()
    assert_decimal_equals(
        after_pre_review["disclosure_accuracy_score_provisional"],
        1.0000,
        4,
        "provisional",
    )
    assert after_pre_review["pre_review_passed"] is True


def test_final_variant_alone_charges_the_over_disclosure_term(api):
    """"An over-disclosure term counts each declared tuple whose `data_type` appears in
    no finding in scope and charges 2 per such data type."

    Design: Difficulty/dual_variant_calc/disclosure_disputed_and_over_disclosure_divergence
    """
    ctx, _finding_id = _setup_disputed_and_over_disclosed(api)

    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert claimed["state"] == "IN_REVIEW"
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 0.7800, 4, "final"
    )
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_provisional"], 1.0000, 4, "provisional"
    )


def test_disputed_critical_free_build_still_fails_approve_on_the_final_score(api):
    """"The pass threshold is 0.9500 inclusive — exactly 0.9500 passes, 0.9499 fails."

    Design: Difficulty/dual_variant_calc/disclosure_disputed_and_over_disclosure_divergence
    """
    ctx, _finding_id = _setup_disputed_and_over_disclosed(api)
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    validate_error(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        ApiErrorId.ERR_PRIVACY_DISCLOSURE_INACCURATE,
    )
    assert ctx.submission()["state"] == "IN_REVIEW"
