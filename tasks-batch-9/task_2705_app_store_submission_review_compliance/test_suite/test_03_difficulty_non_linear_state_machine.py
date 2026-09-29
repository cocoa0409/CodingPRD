"""Difficulty rule: non_linear_state_machine.

States revisited by the same row, two orthogonal state dimensions on one row,
and a fork whose middle branch diverges from both extremes.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_app_record,
    add_credentials,
    add_effective_rule,
    add_mapping,
    add_rollout_plan,
    add_submission,
    add_window,
    approve,
    assert_decimal_equals,
    assert_posture,
    complete_content,
    create_appeal_request_payload,
    get_success_data,
    new_account,
    run_pre_review,
    set_clock,
    setup_base_ios,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# submission_reject_redraft_requeue_reject_cycle
# ---------------------------------------------------------------------------
def _first_reason_id(api, ctx, reason_code):
    rows, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer,
            params={"submission_id": ctx.submission_id, "reason_code": reason_code},
        )
    )
    assert rows, f"expected a rejection reason with reason_code {reason_code}"
    return rows[0]["id"]


def _setup_second_rejection_cycle(api):
    """One build rejected on a MINOR reason, answered, returned to draft, re-checked,
    re-queued, re-claimed and rejected a second time."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"})
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": [
                    {
                        "guideline_rule_id": ctx.rules["privacy"],
                        "reason_code": "SCREENSHOT_QUALITY_LOW",
                        "severity": "MINOR",
                        "detail": "Phone screenshots are upscaled",
                    }
                ],
            },
            ctx.reviewer,
        )
    )
    first_reason_id = _first_reason_id(api, ctx, "SCREENSHOT_QUALITY_LOW")
    get_success_data(
        api.respond_to_rejection_reason(
            first_reason_id,
            {
                "disposition": "ACCEPTED",
                "developer_response": "New 3x screenshots attached",
            },
            ctx.compliance_officer,
        )
    )
    get_success_data(
        api.return_submission_to_draft(ctx.submission_id, ctx.release_manager)
    )
    get_success_data(api.pre_review_check(ctx.submission_id, ctx.compliance_officer))
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": [
                    {
                        "guideline_rule_id": ctx.rules["privacy"],
                        "reason_code": "SUBTITLE_MISLEADING",
                        "severity": "MINOR",
                        "detail": "Subtitle claims a feature the build does not ship",
                    }
                ],
            },
            ctx.reviewer,
        )
    )
    return ctx, first_reason_id


def test_the_same_row_reaches_rejected_a_second_time(api):
    """"Returning to draft increments `resubmission_count`, voids the attestation by
    clearing `pre_review_passed`, `pre_review_checked_at` and `attested_by_user_id`,
    releases the capacity slot by clearing `review_window_id` — which decrements the old
    window's `slots_consumed` and increments its `slots_available`, restoring the
    pre-queue integer — and may optionally re-point `signing_credential_id`, which must
    then name a usable credential of the same account."

    Design: Difficulty/non_linear_state_machine/submission_reject_redraft_requeue_reject_cycle
    """
    ctx, _first_reason_id = _setup_second_rejection_cycle(api)

    data = ctx.submission()
    assert data["state"] == "REJECTED", "the same row is revisited, not replaced"
    assert data["resubmission_count"] == 1
    assert data["rejected_at"] == "2026-08-02T00:00:00Z"
    assert data["review_window_id"] == ctx.window_id

    _rows, meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 2, "each cycle leaves its own rejection reason row"


def test_the_reserved_slot_is_returned_then_consumed_again(api):
    """"`slots_consumed` is the count whose `state` is `APPROVED`, `REJECTED`,
    `METADATA_REJECTED`, `APPEAL_PENDING`, `REJECTED_FINAL` or `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/submission_reject_redraft_requeue_reject_cycle
    """
    ctx, first_reason_id = _setup_second_rejection_cycle(api)

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4

    reason = validate_success(
        api.get_rejection_reason(first_reason_id, ctx.compliance_officer), 200
    )
    assert reason["disposition"] == "ACCEPTED"


def test_minor_reasons_never_cascade_to_mappings_or_strikes(api):
    """"Then a four-hop cascade runs: every feature mapping of the app whose
    `guideline_rule_id` is cited by a `CRITICAL` or `MAJOR` reason moves
    `PASSED → FAILED`; the app's `feature_compliance_index` is recomputed from those
    changed statuses and, when it falls below the posture floor, the posture becomes
    `RESTRICTED`; every rollout plan of the app in `PHASE_ACTIVE` moves to `PAUSED` with
    `pause_reason_code` set to `POSTURE_DEGRADED`; and the app's `distribution_state`
    goes `PHASED_ROLLOUT → PAUSED` with `released_share_pct` and `held_back_share_pct`
    held at their pre-pause values."

    Design: Difficulty/non_linear_state_machine/submission_reject_redraft_requeue_reject_cycle
    """
    ctx, _first_reason_id = _setup_second_rejection_cycle(api)

    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "PASSED"
    assert_posture(ctx.app(), "OPEN", [])

    account = ctx.account()
    assert_decimal_equals(account["standing_score_lifetime"], 96.00, 2, "lifetime")
    assert_decimal_equals(
        account["standing_score_rolling_365"], 96.00, 2, "rolling"
    )
    assert account["rejection_strike_count"] == 0


# ---------------------------------------------------------------------------
# app_record_listing_and_distribution_independent_dimensions
# ---------------------------------------------------------------------------
def _setup_listed_and_rolling_out(api):
    """An app that is both LISTED on the listing dimension and PHASED_ROLLOUT on the
    distribution dimension, then delisted."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"})
    set_clock(api, "2026-08-02T00:00:00Z")
    approve(ctx)
    add_rollout_plan(
        ctx, mode="PHASED", scheduled_start_at="2026-08-02T00:00:00Z", start=True
    )
    get_success_data(
        api.drive_listing(
            ctx.app_record_id,
            {"listing_action": "COMPLETE_METADATA"},
            ctx.publisher_admin,
        )
    )
    get_success_data(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "LIST"}, ctx.publisher_admin
        )
    )
    return ctx


def test_delist_moves_only_the_listing_dimension(api):
    """"Every one of these advances the app record's `version` by one, and none of them
    ever touches `distribution_state`, `live_submission_id` or the two share fields —
    delisting a store page leaves an in-flight rollout running untouched."

    Design: Difficulty/non_linear_state_machine/app_record_listing_and_distribution_independent_dimensions
    """
    ctx = _setup_listed_and_rolling_out(api)

    data = validate_success(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "DELIST"}, ctx.publisher_admin
        ),
        200,
    )
    assert data["listing_state"] == "DELISTED"
    assert data["distribution_state"] == "PHASED_ROLLOUT"
    assert_decimal_equals(data["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(data["held_back_share_pct"], 99.00, 2, "held back")
    assert data["live_submission_id"] == ctx.submission_id


def test_the_rollout_plan_keeps_running_through_the_delist(api):
    """"A phased plan then moves `SCHEDULED → PHASE_ACTIVE` with `phase_index` 0,
    `released_share_pct` 1.00, `held_back_share_pct` 99.00 and `phase_entered_at`
    stamped, and the app's `distribution_state` becomes `PHASED_ROLLOUT`."

    Design: Difficulty/non_linear_state_machine/app_record_listing_and_distribution_independent_dimensions
    """
    ctx = _setup_listed_and_rolling_out(api)
    get_success_data(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "DELIST"}, ctx.publisher_admin
        )
    )

    plan = ctx.plan()
    assert plan["state"] == "PHASE_ACTIVE"
    assert plan["phase_index"] == 0
    assert_decimal_equals(plan["released_share_pct"], 1.00, 2, "plan released")


def test_return_to_draft_is_refused_while_a_plan_is_phase_active(api):
    """"`RETURN_TO_DRAFT` moves `DELISTED → DRAFT`, and is refused with
    `ERR_INVALID_ROLLOUT_STATE` while any rollout plan of the app is `SCHEDULED`,
    `PHASE_ACTIVE` or `PAUSED`."

    Design: Difficulty/non_linear_state_machine/app_record_listing_and_distribution_independent_dimensions
    """
    ctx = _setup_listed_and_rolling_out(api)
    get_success_data(
        api.drive_listing(
            ctx.app_record_id, {"listing_action": "DELIST"}, ctx.publisher_admin
        )
    )

    validate_error(
        api.drive_listing(
            ctx.app_record_id,
            {"listing_action": "RETURN_TO_DRAFT"},
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_INVALID_ROLLOUT_STATE,
    )
    assert ctx.app()["listing_state"] == "DELISTED", (
        "the refused action changed nothing"
    )


# ---------------------------------------------------------------------------
# appeal_partially_overturned_fork_divergence
# ---------------------------------------------------------------------------
def _setup_appeal_in_board_review(api):
    """A build rejected on two MAJOR reasons, one per guideline, both contested and
    both cited in an appeal that the board has taken up."""
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    add_credentials(ctx)
    add_app_record(ctx)
    add_effective_rule(ctx, key="privacy")
    add_mapping(
        ctx,
        ctx.rules["privacy"],
        feature_code="ACCOUNT_DELETION",
        advance="PASS",
        key="privacy",
        risk_weight=4,
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
        ctx.rules["commerce"],
        feature_code="IAP_RESTORE",
        advance="PASS",
        key="commerce",
        risk_weight=3,
        evidence_ref="https://evidence.northwind.example/iap-restore.pdf",
    )
    add_submission(ctx)
    complete_content(ctx)
    add_window(ctx, ends_at="2026-09-01T00:00:00Z")
    run_pre_review(ctx)
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.claim_submission(ctx.submission_id, ctx.reviewer))
    get_success_data(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": [
                    {
                        "guideline_rule_id": ctx.rules["privacy"],
                        "reason_code": "PRIVACY_LABEL_MISMATCH",
                        "severity": "MAJOR",
                        "detail": "Declared label omits the analytics SDK",
                    },
                    {
                        "guideline_rule_id": ctx.rules["commerce"],
                        "reason_code": "IAP_RESTORE_MISSING",
                        "severity": "MAJOR",
                        "detail": "No restore-purchases control",
                    },
                ],
            },
            ctx.reviewer,
        )
    )
    privacy_reason_id = _first_reason_id(api, ctx, "PRIVACY_LABEL_MISMATCH")
    commerce_reason_id = _first_reason_id(api, ctx, "IAP_RESTORE_MISSING")
    get_success_data(
        api.respond_to_rejection_reason(
            privacy_reason_id,
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The analytics SDK is disabled in this build; the label is accurate"
                ),
            },
            ctx.compliance_officer,
        )
    )
    get_success_data(
        api.respond_to_rejection_reason(
            commerce_reason_id,
            {
                "disposition": "CONTESTED",
                "developer_response": "Restore is reachable from the paywall footer",
            },
            ctx.compliance_officer,
        )
    )
    appeal = get_success_data(
        api.create_appeal_request(
            create_appeal_request_payload(
                ctx.submission_id,
                [privacy_reason_id, commerce_reason_id],
                appeal_type="FACTUAL_ERROR",
                argument=(
                    "Both findings rest on a stale build artifact scanned before the "
                    "release candidate was uploaded."
                ),
            ),
            ctx.compliance_officer,
        )
    )
    get_success_data(api.board_review_appeal(appeal["id"], ctx.appeal_board))
    return ctx, appeal["id"], privacy_reason_id, commerce_reason_id


def _decide_partial(api, ctx, appeal_id, overturned_ids):
    return api.decide_appeal(
        appeal_id,
        {
            "outcome": "PARTIALLY_OVERTURNED",
            "rationale": (
                "The privacy finding is withdrawn; the missing restore control stands."
            ),
            "overturned_rejection_reason_ids": list(overturned_ids),
        },
        ctx.appeal_board,
    )


def test_partial_overturn_ratio_is_overturned_over_cited(api):
    """"`overturn_ratio` is the count of overturned reasons divided by the count of cited
    reasons, rounded to two decimals, and is null before any decision."

    Design: Difficulty/non_linear_state_machine/appeal_partially_overturned_fork_divergence
    """
    ctx, appeal_id, privacy_reason_id, _commerce_reason_id = (
        _setup_appeal_in_board_review(api)
    )

    data = validate_success(
        _decide_partial(api, ctx, appeal_id, [privacy_reason_id]), 200
    )
    assert data["state"] == "PARTIALLY_OVERTURNED"
    assert_decimal_equals(data["overturn_ratio"], 0.50, 2, "overturn_ratio")
    assert data["decided_by_user_id"] == "u-board-1"


def test_partial_overturn_returns_the_build_to_rejected_without_refreshing_it(api):
    """"`PARTIALLY_OVERTURNED` requires `overturned_rejection_reason_ids` to be a
    non-empty *strict* subset of the cited list, otherwise `ERR_VALIDATION`; those
    reasons become `OVERTURNED` and the remainder `UPHELD`, only the mappings tied to
    overturned reasons return to `IN_PROGRESS`, and the submission goes back to
    `REJECTED` so the publisher may respond and return it to draft — critically,
    `rejected_at` is **not** refreshed, so the original appeal window keeps running and
    does not reopen."

    Design: Difficulty/non_linear_state_machine/appeal_partially_overturned_fork_divergence
    """
    ctx, appeal_id, privacy_reason_id, commerce_reason_id = (
        _setup_appeal_in_board_review(api)
    )
    get_success_data(_decide_partial(api, ctx, appeal_id, [privacy_reason_id]))

    privacy_reason = validate_success(
        api.get_rejection_reason(privacy_reason_id, ctx.compliance_officer), 200
    )
    commerce_reason = validate_success(
        api.get_rejection_reason(commerce_reason_id, ctx.compliance_officer), 200
    )
    assert privacy_reason["appeal_disposition"] == "OVERTURNED"
    assert commerce_reason["appeal_disposition"] == "UPHELD"

    submission = ctx.submission()
    assert submission["state"] == "REJECTED"
    assert submission["rejected_at"] == "2026-08-02T00:00:00Z"


def test_only_the_overturned_reason_restores_its_mapping(api):
    """"Credit is added: 3 points per appeal of the account in an overturning terminal
    state — `OVERTURNED` or `PARTIALLY_OVERTURNED` — decided inside the window, plus 2
    points per rollout plan of the account's apps that reached `COMPLETED` inside the
    window on an app whose `rollback_count` is 0."

    Design: Difficulty/non_linear_state_machine/appeal_partially_overturned_fork_divergence
    """
    ctx, appeal_id, privacy_reason_id, _commerce_reason_id = (
        _setup_appeal_in_board_review(api)
    )
    get_success_data(_decide_partial(api, ctx, appeal_id, [privacy_reason_id]))

    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "IN_PROGRESS"
    assert ctx.mapping(ctx.mappings["commerce"])["self_review_status"] == "FAILED"

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 14.29, 2, "index")
    assert app["compliance_posture"] == "RESTRICTED"

    account = ctx.account()
    assert_decimal_equals(account["standing_score_lifetime"], 97.00, 2, "lifetime")
    assert_decimal_equals(account["standing_score_rolling_365"], 97.00, 2, "rolling")
