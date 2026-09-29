"""Corner section: state_machines.

Every declared transition of the submission, rollout, credential, mapping, impact,
appeal, expedite, commerce, finding and listing machines walked once on its happy
path and once on the refusal that guards it, with the slot triple, the two standing
variants, the compliance index and the conserved share pair checked at each step.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK,
    DEFAULT_REVIEWER_ID,
    add_effective_rule,
    add_mapping,
    add_rollout_plan,
    add_submission,
    assert_decimal_equals,
    assert_posture,
    complete_content,
    create_behavior_finding_payload,
    get_success_data,
    make_appeal_board_headers,
    make_policy_admin_headers,
    make_reviewer_headers,
    new_account,
    rejection_reasons_for,
    run_pre_review,
    set_clock,
    setup_approved_ios,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
)

POOL_A_WINDOW = {"starts_at": "2026-08-01T00:00:00Z", "ends_at": "2026-09-01T00:00:00Z"}


def _instant(value):
    """Parse a rendered instant so the comparison does not depend on fraction digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_submission_create_starts_in_draft_with_the_phased_release_mode_default(api):
    """"A `ReleaseManager` creates one by supplying `expected_app_record_version` as a revision
    guard, the `app_record_id`, the `signing_credential_id` the build is signed with, a
    `build_number`, a `version_string`, and optionally a `release_mode` of `IMMEDIATE`, `PHASED` or
    `MANUAL`, which defaults to `PHASED`."

    Design: Corner/state_machines/submission_create_starts_in_draft_with_the_phased_release_mode_default
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_submission=False, window_overrides=dict(POOL_A_WINDOW)
    )
    version_before = ctx.app_version()

    created = validate_success(
        api.create_submission(
            {
                "expected_app_record_version": version_before,
                "app_record_id": ctx.app_record_id,
                "signing_credential_id": ctx.profile_id,
                "build_number": 100,
                "version_string": "1.0.0",
            },
            ctx.release_manager,
        ),
        201,
    )
    assert created["state"] == "DRAFT"
    assert created["release_mode"] == "PHASED"
    assert created["submission_channel"] == "STANDARD"
    assert created["pre_review_passed"] is False
    assert created["pre_review_blocking_reasons"] == []
    assert created["resubmission_count"] == 0
    assert created["metadata_locale_count"] == 0
    assert created["queued_at"] is None
    assert created["provisional_deadline_at"] is None
    assert created["priority_score"] is None
    assert created["priority_band"] is None
    assert created["review_window_id"] is None
    assert created["reviewed_by_user_id"] is None
    assert created["decided_at"] is None
    assert created["rejected_at"] is None
    assert ctx.app_version() == version_before + 1


def test_queue_moves_pre_review_passed_to_waiting_and_freezes_the_sla_baseline(api):
    """"Step one happens only at queue entry and never again: `queued_at` is set to the current
    instant and `provisional_deadline_at` is frozen at `queued_at` plus 48 hours."

    Design: Corner/state_machines/queue_moves_pre_review_passed_to_waiting_for_review_and_freezes_the_sla_baseline
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert _instant(queued["queued_at"]) == _instant(DEFAULT_CLOCK)
    assert _instant(queued["provisional_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority")
    assert queued["priority_band"] == "NORMAL"
    assert _instant(queued["effective_review_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )
    assert queued["review_window_id"] == ctx.window_id
    assert queued["submission_channel"] == "STANDARD"

    window = ctx.window()
    assert window["slots_reserved"] == 1
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 4


def test_claim_moves_waiting_to_in_review_and_stamps_the_segregation_subject(api):
    """"Claiming stamps `reviewed_by_user_id` with the claiming operator — the identity every later
    segregation-of-duties comparison is made against — and recomputes
    `disclosure_accuracy_score_final`, at which point late-arriving and disputed findings enter
    scope for the first time and the number the reviewer sees may differ sharply from the one the
    publisher saw."

    Design: Corner/state_machines/claim_moves_waiting_to_in_review_and_stamps_the_segregation_subject
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)

    claimed = validate_success(
        api.claim_submission(ctx.submission_id, ctx.reviewer), 200
    )
    assert claimed["state"] == "IN_REVIEW"
    assert claimed["reviewed_by_user_id"] == DEFAULT_REVIEWER_ID
    assert_decimal_equals(
        claimed["disclosure_accuracy_score_final"], 1.0000, 4, "final score"
    )

    window = ctx.window()
    assert window["slots_reserved"] == 1
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 4


def test_reject_decision_fails_the_cited_mapping_and_drives_the_index_to_zero(api):
    """"Then a four-hop cascade runs: every feature mapping of the app whose `guideline_rule_id` is
    cited by a `CRITICAL` or `MAJOR` reason moves `PASSED → FAILED`; the app's
    `feature_compliance_index` is recomputed from those changed statuses and, when it falls below
    the posture floor, the posture becomes `RESTRICTED`; every rollout plan of the app in
    `PHASE_ACTIVE` moves to `PAUSED` with `pause_reason_code` set to `POSTURE_DEGRADED`; and the
    app's `distribution_state` goes `PHASED_ROLLOUT → PAUSED` with `released_share_pct` and
    `held_back_share_pct` held at their pre-pause values."

    Design: Corner/state_machines/reject_decision_fails_the_cited_mapping_and_drives_the_index_to_zero
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    rejected = validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(
                    ctx.rules["privacy"],
                    severity="CRITICAL",
                    detail="Undisclosed device identifier collection in build 10.",
                ),
            },
            ctx.reviewer,
        ),
        200,
    )
    assert rejected["state"] == "REJECTED"
    assert _instant(rejected["decided_at"]) == _instant(DEFAULT_CLOCK)
    assert _instant(rejected["rejected_at"]) == _instant(DEFAULT_CLOCK)

    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "FAILED"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 0.00, 2, "index")
    assert_posture(app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR"])
    assert app["distribution_state"] == "NOT_DISTRIBUTED"

    standing = ctx.standing()
    assert_decimal_equals(standing["standing_score_rolling_365"], 88.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 88.00, 2, "lifetime")
    assert standing["rejection_strike_count"] == 1

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4

    rows, meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["disposition"] == "PENDING"
    assert rows[0]["appeal_disposition"] == "PENDING"


def test_metadata_reject_touches_no_mapping_index_posture_or_strike_count(api):
    """"It creates the rejection reason rows exactly as the reject branch does and stamps the same
    two timestamps, and then diverges completely: no feature mapping is touched, the
    `feature_compliance_index` and `compliance_posture` are unchanged, no rollout plan is paused,
    the app keeps distributing, and `rejection_strike_count` does not move because `MINOR` reasons
    never count as strikes."

    Design: Corner/state_machines/metadata_reject_touches_no_mapping_index_posture_or_strike_count
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    rejected = validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "METADATA_REJECT",
                "rejection_reasons": rejection_reasons_for(
                    ctx.rules["privacy"],
                    severity="MINOR",
                    reason_code="SCREENSHOT_TEXT_MISLEADING",
                    detail="The first screenshot advertises a feature not in this build.",
                ),
            },
            ctx.reviewer,
        ),
        200,
    )
    assert rejected["state"] == "METADATA_REJECTED"

    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "PASSED"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, 2, "index")
    assert_posture(app, "OPEN", [])

    standing = ctx.standing()
    assert standing["rejection_strike_count"] == 0
    assert_decimal_equals(standing["standing_score_rolling_365"], 98.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 98.00, 2, "lifetime")

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4


def test_approve_moves_in_review_to_approved_without_touching_standing(api):
    """"Every branch moves the assigned window's accounting from reserved to consumed, decrementing
    `slots_reserved` by one and incrementing `slots_consumed` by one while `slots_available` stays
    exactly where it was, and every branch recomputes both of the account's standing scores."

    Design: Corner/state_machines/approve_moves_in_review_to_approved_without_touching_standing
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    approved = validate_success(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        200,
    )
    assert approved["state"] == "APPROVED"
    assert _instant(approved["decided_at"]) == _instant(DEFAULT_CLOCK)
    assert approved["rejected_at"] is None

    standing = ctx.standing()
    assert_decimal_equals(standing["standing_score_rolling_365"], 100.00, 2, "rolling")
    assert_decimal_equals(standing["standing_score_lifetime"], 100.00, 2, "lifetime")

    app = ctx.app()
    assert_posture(app, "OPEN", [])
    assert app["distribution_state"] == "NOT_DISTRIBUTED"

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4


def test_rollout_plan_create_starts_scheduled_with_a_seven_dwell_projected_end(api):
    """"A plan is created in state `SCHEDULED` with `phase_index` 0, `released_share_pct` 0.00 and
    `held_back_share_pct` 100.00, and it advances the app record's `version` by one."

    Design: Corner/state_machines/rollout_plan_create_starts_scheduled_with_a_seven_dwell_projected_end
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    version_before = ctx.app_version()

    created = validate_success(
        api.create_rollout_plan(
            {
                "expected_app_record_version": version_before,
                "app_record_id": ctx.app_record_id,
                "submission_id": ctx.submission_id,
                "mode": "PHASED",
                "scheduled_start_at": DEFAULT_CLOCK,
            },
            ctx.release_manager,
        ),
        201,
    )
    assert created["state"] == "SCHEDULED"
    assert created["phase_index"] == 0
    assert_decimal_equals(created["released_share_pct"], 0.00, 2, "released")
    assert_decimal_equals(created["held_back_share_pct"], 100.00, 2, "held back")
    assert _instant(created["projected_end_at"]) == _instant("2026-08-08T00:00:00Z")
    assert created["phase_entered_at"] is None
    assert created["completed_at"] is None
    assert created["terminated_at"] is None
    assert ctx.app()["distribution_state"] == "NOT_DISTRIBUTED"
    assert ctx.app_version() == version_before + 1


def test_start_flips_distribution_to_phased_rollout_and_mirrors_the_share_pair(api):
    """"A phased plan then moves `SCHEDULED → PHASE_ACTIVE` with `phase_index` 0,
    `released_share_pct` 1.00, `held_back_share_pct` 99.00 and `phase_entered_at` stamped, and the
    app's `distribution_state` becomes `PHASED_ROLLOUT`."

    Design: Corner/state_machines/start_flips_distribution_to_phased_rollout_and_mirrors_the_conserved_share_pair
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    add_rollout_plan(ctx, mode="PHASED", scheduled_start_at=DEFAULT_CLOCK)

    started = validate_success(
        api.start_rollout_plan(ctx.plan_id, ctx.release_manager), 200
    )
    assert started["state"] == "PHASE_ACTIVE"
    assert started["phase_index"] == 0
    assert_decimal_equals(started["released_share_pct"], 1.00, 2, "released")
    assert_decimal_equals(started["held_back_share_pct"], 99.00, 2, "held back")
    assert _instant(started["phase_entered_at"]) == _instant(DEFAULT_CLOCK)

    app = ctx.app()
    assert app["distribution_state"] == "PHASED_ROLLOUT"
    assert app["live_submission_id"] == ctx.submission_id
    assert_decimal_equals(app["released_share_pct"], 1.00, 2, "app released")
    assert_decimal_equals(app["held_back_share_pct"], 99.00, 2, "app held back")
    assert app["listing_state"] == "DRAFT"


def test_advance_is_a_phase_active_self_loop_that_moves_exactly_one_index(api):
    """"The dwell rule requires the current instant to be at or after `phase_entered_at` plus 24
    hours, inclusively: advancing exactly 24 hours after entering the phase is legal, 23 hours and
    59 minutes is not, and the refusal is `ERR_PHASE_DWELL_NOT_MET`."

    Design: Corner/state_machines/advance_is_a_phase_active_self_loop_that_moves_exactly_one_index
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api, mode="PHASED", window_overrides=dict(POOL_A_WINDOW)
    )
    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-02T00:00:00Z"}, ctx.policy_admin), 200
    )

    advanced = validate_success(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        200,
    )
    assert advanced["state"] == "PHASE_ACTIVE"
    assert advanced["phase_index"] == 1
    assert_decimal_equals(advanced["released_share_pct"], 2.00, 2, "released")
    assert_decimal_equals(advanced["held_back_share_pct"], 98.00, 2, "held back")
    assert _instant(advanced["phase_entered_at"]) == _instant("2026-08-02T00:00:00Z")
    assert advanced["completed_at"] is None

    app = ctx.app()
    assert_decimal_equals(app["released_share_pct"], 2.00, 2, "app released")
    assert_decimal_equals(app["held_back_share_pct"], 98.00, 2, "app held back")
    assert app["distribution_state"] == "PHASED_ROLLOUT"


def _reject_current_build(ctx, api):
    """Queue, claim and REJECT the ctx build on one CRITICAL privacy reason."""
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    return validate_success(
        api.decide_submission(
            ctx.submission_id,
            {
                "outcome": "REJECT",
                "rejection_reasons": rejection_reasons_for(
                    ctx.rules["privacy"],
                    severity="CRITICAL",
                    detail="Undisclosed device identifier collection in build 10.",
                ),
            },
            ctx.reviewer,
        ),
        200,
    )


def test_queue_a_draft_submission_returns_invalid_submission_state(api):
    """"A `ReleaseManager` queues a build, optionally citing an `expedite_request_id`, and the
    submission moves `PRE_REVIEW_PASSED → WAITING_FOR_REVIEW`."

    Design: Corner/state_machines/queue_a_draft_submission_returns_invalid_submission_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api, with_pre_review=False, window_overrides=dict(POOL_A_WINDOW)
    )
    assert ctx.submission()["state"] == "DRAFT"

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )

    stalled = ctx.submission()
    assert stalled["state"] == "DRAFT"
    assert stalled["queued_at"] is None
    assert stalled["review_window_id"] is None
    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_available"] == 5


def test_claim_a_pre_review_passed_submission_returns_invalid_submission_state(api):
    """"A `PlatformReviewer` claims a queued build, moving it `WAITING_FOR_REVIEW → IN_REVIEW`."

    Design: Corner/state_machines/claim_a_pre_review_passed_submission_returns_invalid_submission_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    assert ctx.submission()["state"] == "PRE_REVIEW_PASSED"

    validate_error(
        api.claim_submission(ctx.submission_id, ctx.reviewer),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )

    stalled = ctx.submission()
    assert stalled["state"] == "PRE_REVIEW_PASSED"
    assert stalled["reviewed_by_user_id"] is None


def test_withdraw_a_queued_build_restores_the_reserved_slot_exactly(api):
    """"Withdrawal is terminal, releases any reserved slot, and refunds any expedite request of the
    build that is `REQUESTED`, `GRANTED` or `CONSUMED`."

    Design: Corner/state_machines/withdraw_a_queued_build_restores_the_reserved_slot_exactly
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    assert ctx.window()["slots_reserved"] == 1

    withdrawn = validate_success(
        api.withdraw_submission(
            ctx.submission_id, ctx.release_manager, {"reason_code": "BUILD_DEFECT"}
        ),
        200,
    )
    assert withdrawn["state"] == "DEVELOPER_WITHDRAWN"
    assert withdrawn["review_window_id"] is None

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 5


def test_claim_the_same_submission_twice_returns_invalid_submission_state(api):
    """"Its `state` moves through a twelve-value enum: `DRAFT`, `PRE_REVIEW_PASSED`,
    `WAITING_FOR_REVIEW`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `METADATA_REJECTED`,
    `APPEAL_PENDING`, `REJECTED_FINAL`, `BLOCKED_INVALID_SIGNING`, `DEVELOPER_WITHDRAWN` and
    `SUPERSEDED`."

    Design: Corner/state_machines/claim_the_same_submission_twice_returns_invalid_submission_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    validate_error(
        api.claim_submission(ctx.submission_id, ctx.reviewer),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )

    held = ctx.submission()
    assert held["state"] == "IN_REVIEW"
    assert held["reviewed_by_user_id"] == DEFAULT_REVIEWER_ID
    window = ctx.window()
    assert window["slots_reserved"] == 1
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 4


def test_return_to_draft_with_a_pending_reason_returns_response_required(api):
    """"Once every reason of the submission has a `disposition` other than `PENDING`, a
    `ReleaseManager` may return the build to draft — refused with `ERR_REJECTION_RESPONSE_REQUIRED`
    while any reason is still unanswered, and refused with `ERR_INVALID_APPEAL_STATE` while an
    appeal of the submission is `SUBMITTED` or `BOARD_REVIEW`."

    Design: Corner/state_machines/return_to_draft_with_a_pending_rejection_reason_returns_rejection_response_required
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    _reject_current_build(ctx, api)

    validate_error(
        api.return_submission_to_draft(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_REJECTION_RESPONSE_REQUIRED,
        409,
    )

    stalled = ctx.submission()
    assert stalled["state"] == "REJECTED"
    assert stalled["resubmission_count"] == 0
    window = ctx.window()
    assert window["slots_consumed"] == 1
    assert window["slots_available"] == 4


def test_rejected_build_loops_back_to_draft_and_increments_resubmission_count(api):
    """"Returning to draft increments `resubmission_count`, voids the attestation by clearing
    `pre_review_passed`, `pre_review_checked_at` and `attested_by_user_id`, releases the capacity
    slot by clearing `review_window_id` — which decrements the old window's `slots_consumed` and
    increments its `slots_available`, restoring the pre-queue integer — and may optionally re-point
    `signing_credential_id`, which must then name a usable credential of the same account."

    Design: Corner/state_machines/rejected_build_loops_back_to_draft_and_increments_resubmission_count
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    _reject_current_build(ctx, api)

    rows, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    validate_success(
        api.respond_to_rejection_reason(
            rows[0]["id"],
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The identifier never leaves the device and is covered by the "
                    "DEVICE_ID disclosure already in the label."
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )

    redrafted = validate_success(
        api.return_submission_to_draft(ctx.submission_id, ctx.release_manager), 200
    )
    assert redrafted["state"] == "DRAFT"
    assert redrafted["resubmission_count"] == 1
    assert redrafted["pre_review_passed"] is False
    assert redrafted["pre_review_checked_at"] is None
    assert redrafted["attested_by_user_id"] is None
    assert redrafted["review_window_id"] is None

    window = ctx.window()
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 5
    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "FAILED"
    assert ctx.app()["compliance_posture"] == "RESTRICTED"


def _plan_payload(ctx, scheduled_start_at, mode="PHASED"):
    """A rollout-plan creation body guarded by the app record's current revision."""
    return {
        "expected_app_record_version": ctx.app_version(),
        "app_record_id": ctx.app_record_id,
        "submission_id": ctx.submission_id,
        "mode": mode,
        "scheduled_start_at": scheduled_start_at,
    }


def _plan_count(ctx, api):
    """The number of rollout plans currently filed against the ctx app record."""
    _rows, meta = validate_paginated(
        api.list_rollout_plans(
            ctx.release_manager, params={"app_record_id": ctx.app_record_id}
        )
    )
    return meta["total_count"]


def test_approve_a_second_build_supersedes_the_first_and_cancels_its_scheduled_plan(api):
    """"Approval stamps `decided_at`, and any other submission of the same app already `APPROVED`
    is moved to `SUPERSEDED`, which cancels that build's `SCHEDULED` rollout plans and is refused
    if that build has a plan in `PHASE_ACTIVE`."

    Design: Corner/state_machines/approve_a_second_build_supersedes_the_first_and_cancels_its_scheduled_plan
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    first_id = ctx.submission_id
    plan_id = add_rollout_plan(ctx, scheduled_start_at=DEFAULT_CLOCK)["id"]
    assert ctx.plan(plan_id)["state"] == "SCHEDULED"

    add_submission(ctx, build_number=101, version_string="4.2.1")
    complete_content(ctx)
    run_pre_review(ctx)
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    second = validate_success(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        200,
    )

    assert second["state"] == "APPROVED"
    assert ctx.submission(first_id)["state"] == "SUPERSEDED"
    cancelled = ctx.plan(plan_id)
    assert cancelled["state"] == "CANCELLED"
    assert _instant(cancelled["terminated_at"]) == _instant(DEFAULT_CLOCK)
    assert_decimal_equals(cancelled["released_share_pct"], 0.00, label="plan released")
    assert_decimal_equals(cancelled["held_back_share_pct"], 100.00, label="plan held")
    assert ctx.app()["distribution_state"] == "NOT_DISTRIBUTED"
    window = ctx.window()
    assert window["slots_consumed"] == 2
    assert window["slots_available"] == 3


def test_rollout_plan_whose_mode_disagrees_with_the_build_returns_mode_mismatch(api):
    """"The plan's `mode` must equal the submission's `release_mode`, and a submission whose
    `release_mode` is `MANUAL` can never own a plan at all — that build is released outside the
    platform's staged machinery — so any mismatch, in either direction, is
    `ERR_ROLLOUT_MODE_MISMATCH`."

    Design: Corner/state_machines/rollout_plan_whose_mode_disagrees_with_the_build_returns_rollout_mode_mismatch
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    assert ctx.submission()["release_mode"] == "PHASED"
    guarded_version = ctx.app_version()

    validate_error(
        api.create_rollout_plan(
            _plan_payload(ctx, DEFAULT_CLOCK, mode="IMMEDIATE"), ctx.release_manager
        ),
        ApiErrorId.ERR_ROLLOUT_MODE_MISMATCH,
        409,
    )

    assert _plan_count(ctx, api) == 0
    assert ctx.app_version() == guarded_version


def test_second_rollout_plan_starting_exactly_at_the_first_projected_end_conflicts(api):
    """"A plan's interval runs from `scheduled_start_at` to `projected_end_at` and is **closed at
    both ends**, so touching endpoints *do* conflict: a new plan starting exactly when an existing
    plan is projected to end is rejected, whereas back-to-back capacity windows are always legal."

    Design: Corner/state_machines/second_rollout_plan_starting_exactly_at_the_first_projected_end_conflicts
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    first = add_rollout_plan(ctx, scheduled_start_at=DEFAULT_CLOCK)
    assert _instant(first["projected_end_at"]) == _instant("2026-08-08T00:00:00Z")

    validate_error(
        api.create_rollout_plan(
            _plan_payload(ctx, "2026-08-08T00:00:00Z"), ctx.release_manager
        ),
        ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT,
        409,
    )

    assert _plan_count(ctx, api) == 1
    assert ctx.plan(first["id"])["state"] == "SCHEDULED"


def test_hold_pause_freezes_the_shares_and_mirrors_paused_onto_the_app(api):
    """"`PAUSE` moves `PHASE_ACTIVE → PAUSED`, records the reason — the code `POSTURE_DEGRADED` is
    what the compliance cascades write here — freezes both share fields exactly as they stand, and
    drives the app to `PAUSED`."

    Design: Corner/state_machines/hold_pause_freezes_the_shares_and_mirrors_paused_onto_the_distribution_dimension
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    live_id = ctx.submission_id

    paused = validate_success(
        api.hold_rollout_plan(
            ctx.plan_id,
            {"action": "PAUSE", "pause_reason_code": "MANUAL_HOLD"},
            ctx.release_manager,
        ),
        200,
    )
    assert paused["state"] == "PAUSED"
    assert paused["pause_reason_code"] == "MANUAL_HOLD"
    assert paused["phase_index"] == 0
    assert_decimal_equals(paused["released_share_pct"], 1.00, label="plan released")
    assert_decimal_equals(paused["held_back_share_pct"], 99.00, label="plan held")

    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert app["listing_state"] == "DRAFT"
    assert app["live_submission_id"] == live_id
    assert_decimal_equals(app["released_share_pct"], 1.00, label="app released")
    assert_decimal_equals(app["held_back_share_pct"], 99.00, label="app held")


def test_rollback_without_halting_from_phase_active_returns_invalid_distribution_state(api):
    """"A cascade that would drive this dimension along an undeclared edge is
    `ERR_INVALID_DISTRIBUTION_STATE`."

    Design: Corner/state_machines/rollback_without_halting_from_phase_active_returns_invalid_distribution_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    live_id = ctx.submission_id

    validate_error(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": False},
            ctx.release_manager,
        ),
        ApiErrorId.ERR_INVALID_DISTRIBUTION_STATE,
        409,
    )

    assert ctx.plan()["state"] == "PHASE_ACTIVE"
    app = ctx.app()
    assert app["distribution_state"] == "PHASED_ROLLOUT"
    assert app["rollback_count"] == 0
    assert app["live_submission_id"] == live_id


def test_halting_rollback_zeroes_the_released_share_and_increments_rollback_count(api):
    """"In every case the plan moves to `ROLLED_BACK`, `released_share_pct` returns to 0.00 with
    `held_back_share_pct` back to exactly 100.00 and no residue, `terminated_at` is stamped, the
    app's `rollback_count` increments, `live_submission_id` is cleared, and both standing scores
    are recomputed — a rollback costs the account the clean-rollout credit it would otherwise have
    earned."

    Design: Corner/state_machines/halting_rollback_zeroes_the_released_share_and_increments_rollback_count
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))

    rolled = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert rolled["state"] == "ROLLED_BACK"
    assert_decimal_equals(rolled["released_share_pct"], 0.00, label="plan released")
    assert_decimal_equals(rolled["held_back_share_pct"], 100.00, label="plan held")
    assert _instant(rolled["terminated_at"]) == _instant(DEFAULT_CLOCK)

    app = ctx.app()
    assert app["distribution_state"] == "ROLLED_BACK"
    assert app["rollback_count"] == 1
    assert app["live_submission_id"] is None
    assert_decimal_equals(app["released_share_pct"], 0.00, label="app released")
    assert_decimal_equals(app["held_back_share_pct"], 100.00, label="app held")


def test_advance_a_paused_rollout_plan_returns_invalid_rollout_state(api):
    """"Attempting to advance a paused plan is `ERR_INVALID_ROLLOUT_STATE` even though a
    `PHASE_ACTIVE` self-loop is otherwise legal, because the undeclared transition is refused on its
    own rung."

    Design: Corner/state_machines/advance_a_paused_rollout_plan_returns_invalid_rollout_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(
        api.hold_rollout_plan(
            ctx.plan_id,
            {"action": "PAUSE", "pause_reason_code": "MANUAL_HOLD"},
            ctx.release_manager,
        ),
        200,
    )

    validate_error(
        api.advance_rollout_plan(
            ctx.plan_id, {"to_phase_index": 1}, ctx.release_manager
        ),
        ApiErrorId.ERR_INVALID_ROLLOUT_STATE,
        409,
    )

    held = ctx.plan()
    assert held["state"] == "PAUSED"
    assert held["phase_index"] == 0
    assert_decimal_equals(held["released_share_pct"], 1.00, label="plan released")
    assert_decimal_equals(held["held_back_share_pct"], 99.00, label="plan held")


def test_rollback_a_rolled_back_plan_is_refused_by_terminal_lockdown(api):
    """"`ROLLED_BACK` and `CANCELLED` are terminal; a `SCHEDULED` plan is cancelled automatically,
    with `terminated_at` stamped, when its submission is superseded, and because no share field ever
    moved there is no audience accounting to undo."

    Design: Corner/state_machines/rollback_a_rolled_back_plan_is_refused_by_terminal_lockdown
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    halt = {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True}
    validate_success(
        api.rollback_rollout_plan(ctx.plan_id, halt, ctx.release_manager), 200
    )

    validate_error(
        api.rollback_rollout_plan(ctx.plan_id, halt, ctx.release_manager),
        ApiErrorId.ERR_INVALID_ROLLOUT_STATE,
        409,
    )

    plan = ctx.plan()
    assert plan["state"] == "ROLLED_BACK"
    assert _instant(plan["terminated_at"]) == _instant(DEFAULT_CLOCK)
    assert ctx.app()["rollback_count"] == 1


def test_publish_an_already_effective_guideline_rule_is_refused(api):
    """"A rule already `EFFECTIVE` or `SUPERSEDED` cannot be published again; that is
    `ERR_INVALID_RULE_STATE`."

    The 409 code is the one the error catalogue publishes for the guideline machine, since the
    response always uses the code of the entity named in the path.

    Design: Corner/state_machines/publish_an_already_effective_guideline_rule_returns_invalid_guideline_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        with_mapping=False,
        with_submission=False,
        with_window=False,
    )
    rule_id = ctx.rules["privacy"]
    published_at = get_success_data(api.get_guideline_rule(rule_id, ctx.policy_admin))[
        "published_at"
    ]
    assert _instant(published_at) == _instant(DEFAULT_CLOCK)

    validate_error(
        api.publish_guideline_rule(rule_id, ctx.policy_admin),
        ApiErrorId.ERR_INVALID_GUIDELINE_STATE,
        409,
    )

    rule = get_success_data(api.get_guideline_rule(rule_id, ctx.policy_admin))
    assert rule["status"] == "EFFECTIVE"
    assert _instant(rule["published_at"]) == _instant(published_at)


def test_publish_a_future_dated_guideline_rule_returns_rule_not_yet_effective(api):
    """"A `PlatformPolicyAdmin` moves a rule `DRAFT → EFFECTIVE`, which requires that
    `effective_from` is at or before the current logical instant — a rule may not be published into
    the future, and attempting it is `ERR_RULE_NOT_YET_EFFECTIVE` — and, when `supersedes_rule_id`
    is set, that the superseded rule is itself currently `EFFECTIVE`, otherwise
    `ERR_GUIDELINE_RULE_NOT_EFFECTIVE`."

    Design: Corner/state_machines/publish_a_future_dated_guideline_rule_returns_rule_not_yet_effective
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        with_rule=False,
        with_submission=False,
        with_window=False,
    )
    future = add_effective_rule(
        ctx,
        key="future",
        publish=False,
        rule_code="4.0.0",
        title="Design Minimum Functionality",
        category="DESIGN",
        version_label="2026.09",
        effective_from="2026-09-01T00:00:00Z",
    )
    assert future["status"] == "DRAFT"

    validate_error(
        api.publish_guideline_rule(future["id"], ctx.policy_admin),
        ApiErrorId.ERR_RULE_NOT_YET_EFFECTIVE,
        409,
    )

    rule = get_success_data(api.get_guideline_rule(future["id"], ctx.policy_admin))
    assert rule["status"] == "DRAFT"
    assert rule["published_at"] is None


def test_self_review_pass_directly_from_not_started_returns_invalid_mapping_state(api):
    """"An outcome that is not declared for the current status is `ERR_INVALID_MAPPING_STATE`."

    Design: Corner/state_machines/self_review_pass_directly_from_not_started_returns_invalid_mapping_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance=None,
        with_submission=False,
        with_window=False,
    )
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    assert ctx.mapping(mapping_id)["self_review_status"] == "NOT_STARTED"

    validate_error(
        api.self_review_mapping(
            mapping_id,
            {"outcome": "PASS", "evidence_ref": "https://evidence.northwind.example/ad-1"},
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_INVALID_MAPPING_STATE,
        409,
    )

    mapping = ctx.mapping(mapping_id)
    assert mapping["self_review_status"] == "NOT_STARTED"
    assert mapping["attested_at"] is None
    assert mapping["attested_by_user_id"] is None
    assert_decimal_equals(
        ctx.app()["feature_compliance_index"], 0.00, label="index"
    )


def test_self_review_pass_without_any_evidence_reference_returns_evidence_required(api):
    """"`PASS` moves `IN_PROGRESS → PASSED`, or `FAILED → PASSED`, or `STALE → PASSED` for a
    re-attestation after a rulebook change, and in every case requires a non-empty `evidence_ref`
    either already on the mapping or supplied with the request; without one the attestation is
    refused with `ERR_EVIDENCE_REQUIRED`."

    Design: Corner/state_machines/self_review_pass_without_any_evidence_reference_returns_evidence_required
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance="START",
        with_submission=False,
        with_window=False,
    )
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    assert ctx.mapping(mapping_id)["self_review_status"] == "IN_PROGRESS"

    validate_error(
        api.self_review_mapping(
            mapping_id, {"outcome": "PASS"}, ctx.compliance_officer
        ),
        ApiErrorId.ERR_EVIDENCE_REQUIRED,
        409,
    )

    assert ctx.mapping(mapping_id)["self_review_status"] == "IN_PROGRESS"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 25.00, label="index")
    assert_posture(app, "RESTRICTED")


def _credential_payload(ctx, **overrides):
    """A signing-credential creation body guarded by the account's current revision."""
    payload = {
        "expected_publisher_account_version": ctx.account_version(),
        "publisher_account_id": ctx.account_id,
        "credential_type": "DISTRIBUTION_CERT",
        "platform": "IOS",
        "key_custody": "HSM",
        "not_before": "2026-07-01T00:00:00Z",
        "not_after": "2027-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def test_waive_a_failed_mapping_with_a_nineteen_character_reason_is_refused(api):
    """"The `waiver_reason` must be at least 20 characters, so that the audit trail carries an
    actual justification; a shorter one is `ERR_EVIDENCE_REQUIRED`."

    Design: Corner/state_machines/waive_a_failed_mapping_with_a_nineteen_character_reason_returns_evidence_required
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance="FAIL",
        with_submission=False,
        with_window=False,
    )
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    short_reason = "Legacy build carveo"
    assert len(short_reason) == 19

    validate_error(
        api.waive_mapping(
            mapping_id, {"waiver_reason": short_reason}, ctx.policy_admin
        ),
        ApiErrorId.ERR_EVIDENCE_REQUIRED,
        409,
    )

    mapping = ctx.mapping(mapping_id)
    assert mapping["self_review_status"] == "FAILED"
    assert mapping["waiver_reason"] is None
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 0.00, label="index")


def test_waive_a_failed_privacy_mapping_restores_the_index_and_opens_the_posture(api):
    """"A waiver clears `staled_by_rule_id`, stamps `attested_at`, and recomputes the app's index and
    posture; a waived mapping counts as fully compliant for index purposes."

    Design: Corner/state_machines/waive_a_failed_privacy_mapping_restores_the_index_to_one_hundred_and_opens_the_posture
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance="FAIL",
        with_submission=False,
        with_window=False,
    )
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 0.00, label="index")
    assert_posture(ctx.app(), "RESTRICTED")

    reason = "Superseded by platform-side enforcement for this legacy build family."
    waived = validate_success(
        api.waive_mapping(mapping_id, {"waiver_reason": reason}, ctx.policy_admin), 200
    )
    assert waived["self_review_status"] == "WAIVED_BY_PLATFORM"
    assert waived["waiver_reason"] == reason
    assert waived["staled_by_rule_id"] is None

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, label="index")
    assert_posture(app, "OPEN")


def test_waive_a_safety_category_mapping_returns_waiver_not_permitted(api):
    """"The mapping's rule may not be in category `SAFETY` — safety findings are never waivable, and
    attempting it is `ERR_WAIVER_NOT_PERMITTED`."

    Design: Corner/state_machines/waive_a_safety_category_mapping_returns_waiver_not_permitted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        mapping_advance="FAIL",
        with_submission=False,
        with_window=False,
    )
    add_effective_rule(
        ctx,
        key="safety",
        rule_code="1.1.4",
        title="Objectionable Content",
        category="SAFETY",
    )
    add_mapping(
        ctx,
        ctx.rules["safety"],
        feature_code="UGC_REPORTING",
        advance="FAIL",
        key="safety",
    )
    safety_mapping_id = ctx.mappings["safety"]

    validate_error(
        api.waive_mapping(
            safety_mapping_id,
            {
                "waiver_reason": (
                    "Platform accepted the vendor attestation for this safety control."
                )
            },
            ctx.policy_admin,
        ),
        ApiErrorId.ERR_WAIVER_NOT_PERMITTED,
        409,
    )

    mapping = ctx.mapping(safety_mapping_id)
    assert mapping["self_review_status"] == "FAILED"
    assert mapping["waiver_reason"] is None
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 0.00, label="index")


def test_activate_a_credential_before_its_not_before_is_refused(api):
    """"A `PublisherAdmin` activating a credential moves it `PENDING_ACTIVATION → ACTIVE` only when
    the logical clock sits inside the validity interval — at or after `not_before` and strictly
    before `not_after`, otherwise `ERR_CREDENTIAL_NOT_YET_VALID` — and only when the owning account's
    `program_status` is `ACTIVE`, otherwise `ERR_PROGRAM_MEMBERSHIP_EXPIRED`."

    Design: Corner/state_machines/activate_a_credential_before_its_not_before_returns_credential_not_yet_valid
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    future_cert = validate_success(
        api.create_signing_credential(
            _credential_payload(
                ctx,
                not_before="2026-09-01T00:00:00Z",
                not_after="2027-09-01T00:00:00Z",
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    assert future_cert["status"] == "PENDING_ACTIVATION"

    validate_error(
        api.activate_signing_credential(future_cert["id"], ctx.publisher_admin),
        ApiErrorId.ERR_CREDENTIAL_NOT_YET_VALID,
        409,
    )

    assert get_success_data(
        api.get_signing_credential(future_cert["id"], ctx.publisher_admin)
    )["status"] == "PENDING_ACTIVATION"


def test_a_local_keychain_distribution_cert_never_enters_the_machine(api):
    """"A distribution certificate requires the opposite: `linked_cert_id` must be null, and its
    `key_custody` may not be `LOCAL_KEYCHAIN` — a root signing key held in a local keychain is
    never acceptable and is refused with `ERR_KEY_CUSTODY_NOT_PERMITTED`."

    Registration is where the refusal lands, so the credential state machine is never entered at
    all: no `PENDING_ACTIVATION` row exists for a locally held root key.

    Design: Corner/state_machines/activate_a_local_keychain_distribution_cert_returns_key_custody_not_permitted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)

    validate_error(
        api.create_signing_credential(
            _credential_payload(ctx, key_custody="LOCAL_KEYCHAIN"), ctx.publisher_admin
        ),
        ApiErrorId.ERR_KEY_CUSTODY_NOT_PERMITTED,
        409,
    )

    rows, meta = validate_paginated(
        api.list_signing_credentials(
            ctx.publisher_admin, {"publisher_account_id": ctx.account_id}
        )
    )
    assert meta["total_count"] == 0, "the refused registration must not have created a row"
    assert rows == []


def test_activate_a_profile_whose_linked_cert_was_revoked_is_refused(api):
    """"Revocation is the orderly counterpart, available to a `PublisherAdmin`, who may supply a
    `revocation_reason` and otherwise gets `MANUAL`."

    Design: Corner/state_machines/activate_a_profile_whose_linked_cert_was_revoked_returns_linked_cert_not_active
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    cert = validate_success(
        api.create_signing_credential(_credential_payload(ctx), ctx.publisher_admin), 201
    )
    validate_success(
        api.activate_signing_credential(cert["id"], ctx.publisher_admin), 200
    )
    profile = validate_success(
        api.create_signing_credential(
            _credential_payload(
                ctx,
                credential_type="PROVISIONING_PROFILE",
                key_custody="CLOUD_MANAGED",
                linked_cert_id=cert["id"],
            ),
            ctx.publisher_admin,
        ),
        201,
    )
    revoked = validate_success(
        api.revoke_signing_credential(cert["id"], ctx.publisher_admin), 200
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_reason"] == "MANUAL"

    validate_error(
        api.activate_signing_credential(profile["id"], ctx.publisher_admin),
        ApiErrorId.ERR_LINKED_CERT_NOT_ACTIVE,
        409,
    )

    assert get_success_data(
        api.get_signing_credential(profile["id"], ctx.publisher_admin)
    )["status"] == "PENDING_ACTIVATION"


def test_activating_a_second_distribution_cert_supersedes_the_first_one(api):
    """"Activation then supersedes: any other credential of the same account sharing the same
    `credential_type` and the same `platform` and sitting in status `ACTIVE` or `EXPIRING_SOON` is
    moved to `REVOKED` with `revocation_reason` set to `SUPERSEDED`."

    Design: Corner/state_machines/activating_a_second_distribution_cert_supersedes_the_first_one
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_app=False)
    second_cert = validate_success(
        api.create_signing_credential(
            _credential_payload(
                ctx,
                not_before="2026-07-15T00:00:00Z",
                not_after="2027-07-15T00:00:00Z",
                entitlements=["IN_APP_PURCHASE"],
            ),
            ctx.publisher_admin,
        ),
        201,
    )

    activated = validate_success(
        api.activate_signing_credential(second_cert["id"], ctx.publisher_admin), 200
    )
    assert activated["status"] == "ACTIVE"

    incumbent = get_success_data(
        api.get_signing_credential(ctx.cert_id, ctx.publisher_admin)
    )
    assert incumbent["status"] == "REVOKED"
    assert incumbent["revocation_reason"] == "SUPERSEDED"
    profile = get_success_data(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin)
    )
    assert profile["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_signing_credentials(
            ctx.publisher_admin,
            params={"publisher_account_id": ctx.account_id, "status": "ACTIVE"},
        )
    )
    active_ids = {row["id"] for row in rows}
    assert active_ids == {second_cert["id"], ctx.profile_id}
    assert meta["total_count"] == 2


def test_revoking_the_credential_that_signed_an_in_review_build_is_refused(api):
    """"An `ACTIVE` credential may be revoked only when no submission signed with it is currently in
    `WAITING_FOR_REVIEW` or `IN_REVIEW`; otherwise the request is refused with
    `ERR_CREDENTIAL_IN_USE`, precisely so that an orderly retirement cannot strand a build
    mid-review."

    Design: Corner/state_machines/revoking_the_credential_that_signed_an_in_review_build_returns_credential_in_use
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    validate_error(
        api.revoke_signing_credential(ctx.profile_id, ctx.publisher_admin),
        ApiErrorId.ERR_CREDENTIAL_IN_USE,
        409,
    )

    assert get_success_data(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin)
    )["status"] == "ACTIVE"
    assert ctx.submission()["state"] == "IN_REVIEW"


def test_revoking_an_already_revoked_credential_is_refused_by_terminal_lockdown(api):
    """"Both `EXPIRED` and `REVOKED` are terminal statuses; the recognised values of
    `revocation_reason` are `SUPERSEDED`, `MANUAL` and `COMPROMISE_CASCADE`."

    Design: Corner/state_machines/revoking_an_already_revoked_credential_is_refused_by_terminal_lockdown
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_app=False)
    revoked = validate_success(
        api.revoke_signing_credential(ctx.cert_id, ctx.publisher_admin), 200
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_reason"] == "MANUAL"

    validate_error(
        api.revoke_signing_credential(ctx.cert_id, ctx.publisher_admin),
        ApiErrorId.ERR_INVALID_CREDENTIAL_STATE,
        409,
    )

    still = get_success_data(
        api.get_signing_credential(ctx.cert_id, ctx.publisher_admin)
    )
    assert still["status"] == "REVOKED"
    assert still["revocation_reason"] == "MANUAL"


def test_report_compromise_blocks_the_in_flight_build_and_releases_its_review_slot(api):
    """"Second — caused by the first — every submission signed with one of those newly revoked
    profiles that is sitting in `WAITING_FOR_REVIEW` or `IN_REVIEW` moves to
    `BLOCKED_INVALID_SIGNING`, has its `review_window_id` cleared (which decrements that window's
    `slots_reserved` by one and increments its `slots_available` by one), and increments the revoked
    credential's `blocked_submission_count`."

    Design: Corner/state_machines/report_compromise_blocks_the_in_flight_build_and_releases_its_review_slot
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    compromised = validate_success(
        api.report_credential_compromise(
            ctx.cert_id, {"reason_code": "PRIVATE_KEY_LEAKED"}, ctx.publisher_admin
        ),
        200,
    )
    assert compromised["status"] == "COMPROMISED"
    assert _instant(compromised["compromised_at"]) == _instant(DEFAULT_CLOCK)

    profile = get_success_data(
        api.get_signing_credential(ctx.profile_id, ctx.publisher_admin)
    )
    assert profile["status"] == "REVOKED"
    assert profile["revocation_reason"] == "COMPROMISE_CASCADE"
    assert profile["blocked_submission_count"] == 1

    blocked = ctx.submission()
    assert blocked["state"] == "BLOCKED_INVALID_SIGNING"
    assert blocked["review_window_id"] is None

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_available"] == 5
    assert_posture(ctx.app(), "RESTRICTED")


def test_immediate_release_mode_start_jumps_straight_to_completed(api):
    """"An immediate plan instead goes straight from `SCHEDULED` to `COMPLETED` in a single step,
    with `phase_index` at the final index, `released_share_pct` 100.00, `held_back_share_pct` 0.00
    and `completed_at` stamped, and the app's `distribution_state` becomes `FULLY_RELEASED` — an
    immediate release never exposes a partial audience and never passes through `PHASED_ROLLOUT` at
    all."

    Design: Corner/state_machines/immediate_release_mode_start_jumps_straight_to_completed_and_fully_released
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(
        client=api,
        window_overrides=dict(POOL_A_WINDOW),
        submission_overrides={"release_mode": "IMMEDIATE"},
        build_number=100,
        version_string="4.2.0",
    )
    plan_id = add_rollout_plan(
        ctx, mode="IMMEDIATE", scheduled_start_at=DEFAULT_CLOCK
    )["id"]

    started = validate_success(
        api.start_rollout_plan(plan_id, ctx.release_manager), 200
    )
    assert started["state"] == "COMPLETED"
    assert started["phase_index"] == 6
    assert_decimal_equals(started["released_share_pct"], 100.00, label="plan released")
    assert_decimal_equals(started["held_back_share_pct"], 0.00, label="plan held")
    assert _instant(started["completed_at"]) == _instant(DEFAULT_CLOCK)

    app = ctx.app()
    assert app["distribution_state"] == "FULLY_RELEASED"
    assert app["live_submission_id"] == ctx.submission_id
    assert_decimal_equals(app["released_share_pct"], 100.00, label="app released")
    assert_decimal_equals(app["held_back_share_pct"], 0.00, label="app held")


def test_publishing_a_superseding_privacy_rule_stales_the_mapping_and_opens_an_impact(api):
    """"First, every feature mapping that pointed at the superseded rule is re-pointed at the new
    rule, and each such mapping whose `self_review_status` was `PASSED` or `WAIVED_BY_PLATFORM` is
    moved to `STALE` with `staled_by_rule_id` set to the new rule's identifier — prior attestations
    do not survive a rulebook change."

    Design: Corner/state_machines/publishing_a_superseding_privacy_rule_stales_the_mapping_and_opens_an_impact_assessment
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_submission=False, with_window=False)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    assert_decimal_equals(ctx.app()["feature_compliance_index"], 100.00, label="index")

    successor = validate_success(
        api.create_guideline_rule(
            {
                "rule_code": "5.1.2",
                "title": "Account Deletion In App",
                "category": "PRIVACY",
                "version_label": "2026.09",
                "effective_from": "2026-08-01T00:00:00Z",
                "supersedes_rule_id": ctx.rules["privacy"],
                "requires_feature_mapping": True,
            },
            ctx.policy_admin,
        ),
        201,
    )
    published = validate_success(
        api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200
    )
    assert published["status"] == "EFFECTIVE"
    assert published["impacted_app_count"] == 1

    assert get_success_data(
        api.get_guideline_rule(ctx.rules["privacy"], ctx.policy_admin)
    )["status"] == "SUPERSEDED"
    mapping = ctx.mapping(mapping_id)
    assert mapping["guideline_rule_id"] == successor["id"]
    assert mapping["self_review_status"] == "STALE"
    assert mapping["staled_by_rule_id"] == successor["id"]

    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 50.00, label="index")
    assert_posture(
        app, "RESTRICTED", ["COMPLIANCE_INDEX_BELOW_FLOOR", "OPEN_IMPACT_ASSESSMENT"]
    )

    rows, meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 1
    opened = rows[0]
    assert opened["status"] == "OPEN"
    assert opened["affected_feature_codes"] == ["ACCOUNT_DELETION"]
    assert_decimal_equals(opened["impact_severity"], 4.00, label="impact severity")
    assert _instant(opened["remediation_deadline_at"]) == _instant(
        "2026-08-31T00:00:00Z"
    )


def _rulebook_change(api):
    """Publish a superseding PRIVACY rule so one STALE mapping and one OPEN assessment exist."""
    ctx = setup_base_ios(client=api, with_submission=False, with_window=False)
    successor = validate_success(
        api.create_guideline_rule(
            {
                "rule_code": "5.1.2",
                "title": "Account Deletion In App",
                "category": "PRIVACY",
                "version_label": "2026.09",
                "effective_from": "2026-08-01T00:00:00Z",
                "supersedes_rule_id": ctx.rules["privacy"],
                "requires_feature_mapping": True,
            },
            ctx.policy_admin,
        ),
        201,
    )
    validate_success(api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200)
    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    return ctx, rows[0]["id"]


def _assess(api, ctx, assessment_id, payload):
    return validate_success(
        api.assess_impact(assessment_id, payload, ctx.compliance_officer), 200
    )


def test_assess_start_moves_the_assessment_to_in_assessment_and_stamps_the_assessor(api):
    """"`START` moves `OPEN → IN_ASSESSMENT`, stamps `assessed_by_user_id` with the acting operator
    and `assessed_at` with the current instant, and recomputes `impact_severity` against the app's
    *current* `exposure_factor` — an app that has begun distributing since the row was opened becomes
    more severe at this moment."

    Design: Corner/state_machines/assess_start_moves_the_impact_assessment_to_in_assessment_and_stamps_the_assessor
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    assert ctx.app()["distribution_state"] == "NOT_DISTRIBUTED"

    started = _assess(api, ctx, assessment_id, {"action": "START"})
    assert started["status"] == "IN_ASSESSMENT"
    assert _instant(started["assessed_at"]) == _instant(DEFAULT_CLOCK)
    assert started["assessed_by_user_id"] == ctx.compliance_officer["X-User-ID"]
    assert_decimal_equals(started["impact_severity"], 4.00, label="impact severity")
    assert_posture(ctx.app(), "RESTRICTED")


def test_accept_no_change_restores_the_stale_mapping_and_reopens_the_posture(api):
    """"Acceptance is not merely a bookkeeping close: every feature mapping named in
    `affected_feature_codes` that is still `STALE` is restored to `PASSED`, the app's
    `feature_compliance_index` is recomputed on that basis, and with no other objection outstanding
    the app's posture returns to `OPEN`."

    Design: Corner/state_machines/accept_no_change_restores_the_stale_mapping_and_reopens_the_posture
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    _assess(api, ctx, assessment_id, {"action": "START"})

    accepted = _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "ACCEPT_NO_CHANGE",
            "note": "Existing in-app deletion flow already satisfies the new wording.",
        },
    )
    assert accepted["status"] == "ACCEPTED_NO_CHANGE"

    assert ctx.mapping(mapping_id)["self_review_status"] == "PASSED"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, label="index")
    assert_posture(app, "OPEN", [])


def test_require_remediation_keeps_the_posture_restricted_and_the_index_halved(api):
    """"`REQUIRE_REMEDIATION` moves the row to `REMEDIATION_REQUIRED`: the app's posture stays
    `RESTRICTED`, the stale mappings stay stale, and the deadline clock begins to matter."

    Design: Corner/state_machines/require_remediation_keeps_the_posture_restricted_and_leaves_the_index_halved
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    _assess(api, ctx, assessment_id, {"action": "START"})
    _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "REQUIRE_REMEDIATION",
            "note": "The deletion flow must be reworked for the new wording.",
        },
    )

    row = validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )
    assert row["status"] == "REMEDIATION_REQUIRED"
    assert _instant(row["remediation_deadline_at"]) == _instant("2026-08-31T00:00:00Z")
    assert row["remediated_at"] is None

    assert ctx.mapping(mapping_id)["self_review_status"] == "STALE"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 50.00, label="index")
    assert_posture(app, "RESTRICTED")


def test_mark_remediated_while_the_mapping_is_still_stale_is_refused(api):
    """"`MARK_REMEDIATED` moves the row to `REMEDIATED` from either `REMEDIATION_REQUIRED` or
    `OVERDUE`, and requires that every feature mapping named in `affected_feature_codes` now has
    `self_review_status` of `PASSED` or `WAIVED_BY_PLATFORM`; if any remains unattested the request
    is refused with `ERR_REMEDIATION_INCOMPLETE`."

    Design: Corner/state_machines/mark_remediated_while_the_mapping_is_still_stale_returns_remediation_incomplete
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    _assess(api, ctx, assessment_id, {"action": "START"})
    _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "REQUIRE_REMEDIATION",
            "note": "The deletion flow must be reworked for the new wording.",
        },
    )
    assert ctx.mapping(ctx.mappings["ACCOUNT_DELETION"])["self_review_status"] == "STALE"

    validate_error(
        api.assess_impact(
            assessment_id, {"action": "MARK_REMEDIATED"}, ctx.compliance_officer
        ),
        ApiErrorId.ERR_REMEDIATION_INCOMPLETE,
        409,
    )

    row = validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )
    assert row["status"] == "REMEDIATION_REQUIRED"
    assert row["remediated_at"] is None


def test_re_passing_the_staled_mapping_then_marking_remediated_closes_the_assessment(api):
    """"It sets `remediated_at` to the current instant and recomputes the app's posture, which leaves
    `FROZEN` only once no `OVERDUE` row remains against the app."

    Design: Corner/state_machines/re_passing_the_staled_mapping_then_marking_remediated_closes_the_assessment
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    _assess(api, ctx, assessment_id, {"action": "START"})
    _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "REQUIRE_REMEDIATION",
            "note": "The deletion flow must be reworked for the new wording.",
        },
    )
    validate_success(
        api.self_review_mapping(
            mapping_id,
            {
                "outcome": "PASS",
                "evidence_ref": (
                    "https://docs.northwind.example/evidence/acct-deletion-v2"
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )

    remediated = _assess(api, ctx, assessment_id, {"action": "MARK_REMEDIATED"})
    assert remediated["status"] == "REMEDIATED"
    assert _instant(remediated["remediated_at"]) == _instant(DEFAULT_CLOCK)

    assert ctx.mapping(mapping_id)["self_review_status"] == "PASSED"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 100.00, label="index")
    assert_posture(app, "OPEN")


def test_assessing_a_remediated_row_again_is_refused_by_terminal_lockdown(api):
    """"`REMEDIATED` and `ACCEPTED_NO_CHANGE` are terminal."

    Design: Corner/state_machines/assessing_a_remediated_row_again_is_refused_by_terminal_lockdown
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _rulebook_change(api)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    _assess(api, ctx, assessment_id, {"action": "START"})
    _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "REQUIRE_REMEDIATION",
            "note": "The deletion flow must be reworked for the new wording.",
        },
    )
    validate_success(
        api.self_review_mapping(
            mapping_id,
            {
                "outcome": "PASS",
                "evidence_ref": (
                    "https://docs.northwind.example/evidence/acct-deletion-v2"
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )
    _assess(api, ctx, assessment_id, {"action": "MARK_REMEDIATED"})

    validate_error(
        api.assess_impact(
            assessment_id, {"action": "MARK_REMEDIATED"}, ctx.compliance_officer
        ),
        ApiErrorId.ERR_INVALID_IMPACT_STATE,
        409,
    )

    assert validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )["status"] == "REMEDIATED"


def _publish_successor(api, ctx):
    """Publish a PRIVACY successor to the ctx rule and return the assessment it opens."""
    successor = validate_success(
        api.create_guideline_rule(
            {
                "rule_code": "5.1.2",
                "title": "Account Deletion In App",
                "category": "PRIVACY",
                "version_label": "2026.09",
                "effective_from": "2026-08-01T00:00:00Z",
                "supersedes_rule_id": ctx.rules["privacy"],
                "requires_feature_mapping": True,
            },
            ctx.policy_admin,
        ),
        201,
    )
    validate_success(api.publish_guideline_rule(successor["id"], ctx.policy_admin), 200)
    rows, _meta = validate_paginated(
        api.list_impact_assessments(
            ctx.compliance_officer, params={"app_record_id": ctx.app_record_id}
        )
    )
    return rows[0]["id"]


def _remediation_required(api):
    """A REMEDIATION_REQUIRED assessment with its one mapping still STALE."""
    ctx, assessment_id = _rulebook_change(api)
    _assess(api, ctx, assessment_id, {"action": "START"})
    _assess(
        api,
        ctx,
        assessment_id,
        {
            "action": "REQUIRE_REMEDIATION",
            "note": "The deletion flow must be reworked for the new wording.",
        },
    )
    return ctx, assessment_id


def test_accept_no_change_on_a_two_code_privacy_assessment_is_too_severe(api):
    """"`ACCEPT_NO_CHANGE` instead terminates the row at `ACCEPTED_NO_CHANGE`, and it is gated twice:
    the rule's `category` must not be `SAFETY`, and `impact_severity` must be at or below 6.00 — the
    ceiling is inclusive, so a severity of exactly 6.00 may be accepted while 6.01 may not, and a
    breach is refused with `ERR_IMPACT_TOO_SEVERE`."

    Design: Corner/state_machines/accept_no_change_on_a_two_code_privacy_assessment_returns_impact_too_severe
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, with_submission=False, with_window=False)
    add_mapping(
        ctx,
        ctx.rules["privacy"],
        feature_code="DATA_EXPORT",
        advance="PASS",
        key="export",
        evidence_ref="https://docs.northwind.example/evidence/data-export",
    )
    assessment_id = _publish_successor(api, ctx)
    _assess(api, ctx, assessment_id, {"action": "START"})

    validate_error(
        api.assess_impact(
            assessment_id,
            {
                "action": "ACCEPT_NO_CHANGE",
                "note": "Both flows already comply with the new wording.",
            },
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_IMPACT_TOO_SEVERE,
        409,
    )

    row = validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )
    assert row["status"] == "IN_ASSESSMENT"
    assert_decimal_equals(row["impact_severity"], 8.00, label="impact severity")
    assert row["affected_feature_codes"] == ["ACCOUNT_DELETION", "DATA_EXPORT"]
    assert ctx.mapping(ctx.mappings["ACCOUNT_DELETION"])["self_review_status"] == "STALE"
    assert ctx.mapping(ctx.mappings["export"])["self_review_status"] == "STALE"


def test_landing_exactly_on_the_remediation_deadline_keeps_the_row_required(api):
    """"The boundary is strict: landing exactly on the deadline leaves the row
    `REMEDIATION_REQUIRED`, and only the next tick past it trips the transition."

    Design: Corner/state_machines/landing_exactly_on_the_remediation_deadline_keeps_the_row_remediation_required
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _remediation_required(api)

    sweep = validate_success(
        api.set_clock_raw(
            {"current_utc": "2026-08-31T00:00:00Z"}, ctx.policy_admin
        ),
        200,
    )
    assert sweep["assessments_overdue_count"] == 0
    assert sweep["postures_frozen_count"] == 0

    assert validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )["status"] == "REMEDIATION_REQUIRED"
    assert_posture(ctx.app(), "RESTRICTED")


def test_one_second_past_the_remediation_deadline_freezes_the_app(api):
    """"Going overdue is the harshest automatic consequence in the system — the app's posture becomes
    `FROZEN`, which blocks every publisher write on the app and all of its children, and every
    rollout plan of the app that is `PHASE_ACTIVE` is paused with `pause_reason_code` set to
    `POSTURE_DEGRADED`."

    Design: Corner/state_machines/one_second_past_the_remediation_deadline_freezes_the_app_through_the_sweep
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _remediation_required(api)

    sweep = validate_success(
        api.set_clock_raw(
            {"current_utc": "2026-08-31T00:00:01Z"}, ctx.policy_admin
        ),
        200,
    )
    assert sweep["assessments_overdue_count"] == 1
    assert sweep["postures_frozen_count"] == 1
    assert sweep["credentials_warned_count"] == 0
    assert sweep["credentials_expired_count"] == 0
    assert sweep["accounts_expired_count"] == 0
    assert sweep["rollouts_paused_count"] == 0

    assert validate_success(
        api.get_impact_assessment(assessment_id, ctx.compliance_officer), 200
    )["status"] == "OVERDUE"
    assert_posture(ctx.app(), "FROZEN", ["IMPACT_OVERDUE"])


def test_remediating_an_overdue_assessment_is_the_only_write_allowed_while_frozen(api):
    """"Remediating an overdue assessment is deliberately exempt from the posture gate and is
    therefore the *only* publisher action permitted while an app is frozen — without that exemption a
    frozen app could never dig itself out."

    Design: Corner/state_machines/remediating_an_overdue_assessment_is_the_only_write_allowed_while_frozen
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, assessment_id = _remediation_required(api)
    mapping_id = ctx.mappings["ACCOUNT_DELETION"]
    validate_success(
        api.self_review_mapping(
            mapping_id,
            {
                "outcome": "PASS",
                "evidence_ref": (
                    "https://docs.northwind.example/evidence/acct-deletion-v2"
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )
    validate_success(
        api.set_clock_raw({"current_utc": "2026-08-31T00:00:01Z"}, ctx.policy_admin),
        200,
    )
    assert_posture(ctx.app(), "FROZEN", ["IMPACT_OVERDUE"])

    # `FAIL` is a declared transition out of `PASSED`, so the seventh rung passes and the
    # frozen posture on the eighth is what refuses the write.
    validate_error(
        api.self_review_mapping(
            mapping_id, {"outcome": "FAIL"}, ctx.compliance_officer
        ),
        ApiErrorId.ERR_APP_COMPLIANCE_FROZEN,
        409,
    )

    remediated = _assess(api, ctx, assessment_id, {"action": "MARK_REMEDIATED"})
    assert remediated["status"] == "REMEDIATED"
    assert _instant(remediated["remediated_at"]) == _instant("2026-08-31T00:00:01Z")
    assert_posture(ctx.app(), "OPEN", [])


def test_filing_an_appeal_on_a_contested_reason_drives_the_build_to_appeal_pending(api):
    """"Filing creates the appeal in state `SUBMITTED` with `filed_at` and `filed_by_user_id`
    stamped, and moves the submission `REJECTED → APPEAL_PENDING`."

    Design: Corner/state_machines/filing_an_appeal_on_a_contested_reason_drives_the_build_to_appeal_pending
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    _reject_current_build(ctx, api)
    rows, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    reason_id = rows[0]["id"]
    validate_success(
        api.respond_to_rejection_reason(
            reason_id,
            {
                "disposition": "CONTESTED",
                "developer_response": (
                    "The identifier never leaves the device and is covered by the "
                    "DEVICE_ID disclosure already in the label."
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )

    appeal = validate_success(
        api.create_appeal_request(
            {
                "submission_id": ctx.submission_id,
                "appeal_type": "GUIDELINE_INTERPRETATION",
                "argument": (
                    "The identifier is device-local and the disclosure already covers it."
                ),
                "cited_rejection_reason_ids": [reason_id],
            },
            ctx.compliance_officer,
        ),
        201,
    )
    assert appeal["state"] == "SUBMITTED"
    assert _instant(appeal["filed_at"]) == _instant(DEFAULT_CLOCK)
    assert appeal["filed_by_user_id"] == ctx.compliance_officer["X-User-ID"]
    assert appeal["overturn_ratio"] is None

    build = ctx.submission()
    assert build["state"] == "APPEAL_PENDING"
    assert _instant(build["rejected_at"]) == _instant(DEFAULT_CLOCK)


def test_appealing_a_reason_still_in_pending_disposition_is_refused(api):
    """"Every cited reason must belong to this submission and have `disposition` `CONTESTED`; a reason
    still `PENDING`, already `ACCEPTED`, or whose `appeal_disposition` is already decided, is
    `ERR_REJECTION_NOT_CONTESTED`."

    Design: Corner/state_machines/appealing_a_reason_still_in_pending_disposition_returns_rejection_not_contested
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    _reject_current_build(ctx, api)
    rows, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    reason_id = rows[0]["id"]
    assert rows[0]["disposition"] == "PENDING"

    validate_error(
        api.create_appeal_request(
            {
                "submission_id": ctx.submission_id,
                "appeal_type": "GUIDELINE_INTERPRETATION",
                "argument": "We disagree with the privacy label finding.",
                "cited_rejection_reason_ids": [reason_id],
            },
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_REJECTION_NOT_CONTESTED,
        409,
    )

    assert ctx.submission()["state"] == "REJECTED"
    _appeals, meta = validate_paginated(
        api.list_appeal_requests(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    assert meta["total_count"] == 0


CONTEST_RESPONSE = (
    "The identifier never leaves the device and is covered by the DEVICE_ID "
    "disclosure already in the label."
)
APPEAL_ARGUMENT = "The identifier is device-local and the disclosure already covers it."


def _contested_rejection(api):
    """A REJECTED build whose single CRITICAL reason has been contested by the publisher."""
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    _reject_current_build(ctx, api)
    rows, _meta = validate_paginated(
        api.list_rejection_reasons(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    reason_id = rows[0]["id"]
    validate_success(
        api.respond_to_rejection_reason(
            reason_id,
            {"disposition": "CONTESTED", "developer_response": CONTEST_RESPONSE},
            ctx.compliance_officer,
        ),
        200,
    )
    return ctx, reason_id


def _appeal_body(ctx, reason_id, argument=APPEAL_ARGUMENT):
    return {
        "submission_id": ctx.submission_id,
        "appeal_type": "GUIDELINE_INTERPRETATION",
        "argument": argument,
        "cited_rejection_reason_ids": [reason_id],
    }


def _appeal_count(ctx, api):
    _rows, meta = validate_paginated(
        api.list_appeal_requests(
            ctx.compliance_officer, params={"submission_id": ctx.submission_id}
        )
    )
    return meta["total_count"]


def _reason(ctx, api, reason_id):
    return get_success_data(
        api.get_rejection_reason(reason_id, ctx.compliance_officer)
    )


def test_filing_a_second_appeal_while_one_is_live_returns_appeal_already_open(api):
    """"And no other appeal of the submission may be `SUBMITTED` or `BOARD_REVIEW` — one live appeal
    at a time, otherwise `ERR_APPEAL_ALREADY_OPEN`."

    Design: Corner/state_machines/filing_a_second_appeal_while_one_is_live_returns_appeal_already_open
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )

    validate_error(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        ApiErrorId.ERR_APPEAL_ALREADY_OPEN,
        409,
    )

    assert _appeal_count(ctx, api) == 1
    assert ctx.submission()["state"] == "APPEAL_PENDING"


def test_an_appeal_filed_exactly_fourteen_days_after_rejection_is_still_in_window(api):
    """"The filing must happen within 14 days of `rejected_at`, inclusive — an appeal filed at exactly
    `rejected_at` plus 14 days is accepted, later is `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/state_machines/an_appeal_filed_exactly_fourteen_days_after_rejection_is_still_in_window
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    set_clock(api, "2026-08-15T00:00:00Z")

    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(
                ctx, reason_id, "Filed on the last admissible day of the window."
            ),
            ctx.compliance_officer,
        ),
        201,
    )
    assert appeal["state"] == "SUBMITTED"
    assert _instant(appeal["filed_at"]) == _instant("2026-08-15T00:00:00Z")
    assert ctx.submission()["state"] == "APPEAL_PENDING"


def test_an_appeal_filed_one_second_past_the_window_is_refused(api):
    """"Three gates apply."

    The window is inclusive at `rejected_at` plus 14 days, so one second later the filing is
    refused and the build is stranded in `REJECTED`.

    Design: Corner/state_machines/an_appeal_filed_one_second_past_the_window_returns_appeal_window_expired
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    set_clock(api, "2026-08-15T00:00:01Z")

    validate_error(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id, "Filed one second too late."),
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED,
        409,
    )

    assert ctx.submission()["state"] == "REJECTED"
    assert _appeal_count(ctx, api) == 0


def test_board_review_then_overturn_restores_the_failed_mapping_and_approves(api):
    """"`OVERTURNED` sets `overturned_rejection_reason_ids` to the full cited list and `overturn_ratio`
    to 1.00, marks every cited reason `OVERTURNED` so that it leaves the standing penalty scope,
    returns every feature mapping that the original rejection cascade drove to `FAILED` back to
    `IN_PROGRESS` — to `IN_PROGRESS`, not to `PASSED`, so the publisher must re-attest — recomputes the
    index and posture, and drives the submission `APPEAL_PENDING → APPROVED`."

    Design: Corner/state_machines/board_review_then_overturn_restores_the_failed_mapping_and_approves_the_build
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )

    heard = validate_success(
        api.board_review_appeal(appeal["id"], ctx.appeal_board), 200
    )
    assert heard["state"] == "BOARD_REVIEW"
    assert _instant(heard["board_started_at"]) == _instant(DEFAULT_CLOCK)

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": "OVERTURNED",
                "rationale": (
                    "The observed identifier is covered by the existing DEVICE_ID "
                    "disclosure."
                ),
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert decided["state"] == "OVERTURNED"
    assert_decimal_equals(decided["overturn_ratio"], 1.00, label="overturn ratio")
    assert decided["overturned_rejection_reason_ids"] == [reason_id]

    assert ctx.submission()["state"] == "APPROVED"
    assert _reason(ctx, api, reason_id)["appeal_disposition"] == "OVERTURNED"
    assert ctx.mapping(ctx.mappings["privacy"])["self_review_status"] == "IN_PROGRESS"
    app = ctx.app()
    assert_decimal_equals(app["feature_compliance_index"], 25.00, label="index")
    assert_posture(app, "RESTRICTED")

    standing = ctx.standing()
    assert_decimal_equals(
        standing["standing_score_rolling_365"], 100.00, label="rolling standing"
    )
    assert standing["penalty_event_count"] == 0
    assert_decimal_equals(standing["credit_total"], 3, label="credit total")


def test_deciding_an_appeal_as_the_original_reviewer_is_refused(api):
    """"Both the board-review step and the decision require the acting operator to differ from the
    submission's `reviewed_by_user_id`: the reviewer who rejected the build may neither hear nor judge
    the appeal against it."

    Design: Corner/state_machines/deciding_an_appeal_as_the_original_reviewer_returns_segregation_of_duties_violation
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )
    validate_success(api.board_review_appeal(appeal["id"], ctx.appeal_board), 200)

    validate_error(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": "UPHELD",
                "rationale": "Attempted by the reviewer who issued the rejection.",
            },
            make_appeal_board_headers(DEFAULT_REVIEWER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
        409,
    )

    assert get_success_data(
        api.get_appeal_request(appeal["id"], ctx.compliance_officer)
    )["state"] == "BOARD_REVIEW"
    assert ctx.submission()["state"] == "APPEAL_PENDING"
    assert _reason(ctx, api, reason_id)["appeal_disposition"] == "PENDING"


def test_upholding_the_appeal_drives_the_build_to_rejected_final(api):
    """"`UPHELD` marks every cited reason `UPHELD` with `overturn_ratio` 0.00, leaves all penalties in
    scope, and drives the submission to `REJECTED_FINAL`, which is terminal: that build can never be
    revived and the publisher must create a new submission with a higher `build_number`."

    Design: Corner/state_machines/upholding_the_appeal_drives_the_build_to_rejected_final_and_keeps_the_penalty
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )
    validate_success(api.board_review_appeal(appeal["id"], ctx.appeal_board), 200)

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": "UPHELD",
                "rationale": "The disclosure genuinely omits the observed purpose.",
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert decided["state"] == "UPHELD"
    assert_decimal_equals(decided["overturn_ratio"], 0.00, label="overturn ratio")
    assert decided["overturned_rejection_reason_ids"] == []

    assert ctx.submission()["state"] == "REJECTED_FINAL"
    assert _reason(ctx, api, reason_id)["appeal_disposition"] == "UPHELD"

    standing = ctx.standing()
    assert_decimal_equals(
        standing["standing_score_rolling_365"], 88.00, label="rolling standing"
    )
    assert standing["rejection_strike_count"] == 1


EXPEDITE_JUSTIFICATION = (
    "Wallet transfers fail for EU customers on the shipped build."
)


def _expedite_payload(ctx):
    return {
        "submission_id": ctx.submission_id,
        "justification_category": "CRITICAL_BUG",
        "justification": EXPEDITE_JUSTIFICATION,
    }


def _granted_expedite(api, ctx):
    """File and grant one expedite request against the ctx build."""
    request = validate_success(
        api.create_expedite_request(_expedite_payload(ctx), ctx.release_manager), 201
    )
    granted = validate_success(
        api.decide_expedite_request(
            request["id"],
            {
                "outcome": "GRANT",
                "decision_rationale": (
                    "Payment regression justifies expedited handling."
                ),
            },
            ctx.appeal_board,
        ),
        200,
    )
    return request, granted


def test_partially_overturning_with_the_whole_cited_set_returns_validation(api):
    """"`PARTIALLY_OVERTURNED` requires `overturned_rejection_reason_ids` to be a non-empty *strict*
    subset of the cited list, otherwise `ERR_VALIDATION`; those reasons become `OVERTURNED` and the
    remainder `UPHELD`, only the mappings tied to overturned reasons return to `IN_PROGRESS`, and the
    submission goes back to `REJECTED` so the publisher may respond and return it to draft —
    critically, `rejected_at` is **not** refreshed, so the original appeal window keeps running and
    does not reopen."

    Design: Corner/state_machines/partially_overturning_with_the_whole_cited_set_returns_validation
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )
    validate_success(api.board_review_appeal(appeal["id"], ctx.appeal_board), 200)

    validate_error(
        api.decide_appeal(
            appeal["id"],
            {
                "outcome": "PARTIALLY_OVERTURNED",
                "rationale": "Attempting to overturn the entire cited set.",
                "overturned_rejection_reason_ids": [reason_id],
            },
            ctx.appeal_board,
        ),
        ApiErrorId.ERR_VALIDATION,
        422,
    )

    row = get_success_data(api.get_appeal_request(appeal["id"], ctx.compliance_officer))
    assert row["state"] == "BOARD_REVIEW"
    assert row["overturn_ratio"] is None
    assert ctx.submission()["state"] == "APPEAL_PENDING"


def test_withdrawing_an_appeal_returns_the_build_to_rejected_unrefreshed(api):
    """"A `ComplianceOfficer` may instead withdraw an appeal that is still `SUBMITTED`, optionally
    citing a `reason_code`; the appeal becomes `WITHDRAWN`, which is terminal, and the submission
    returns to `REJECTED`, again without refreshing `rejected_at`."

    Design: Corner/state_machines/withdrawing_an_appeal_returns_the_build_to_rejected_without_refreshing_rejected_at
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )

    withdrawn = validate_success(
        api.withdraw_appeal(
            appeal["id"],
            ctx.compliance_officer,
            {"reason_code": "DEVELOPER_RECONSIDERED"},
        ),
        200,
    )
    assert withdrawn["state"] == "WITHDRAWN"

    build = ctx.submission()
    assert build["state"] == "REJECTED"
    assert _instant(build["rejected_at"]) == _instant(DEFAULT_CLOCK)
    assert _reason(ctx, api, reason_id)["appeal_disposition"] == "PENDING"


def test_board_review_on_a_withdrawn_appeal_is_refused_by_terminal_lockdown(api):
    """"And no other appeal of the submission may be `SUBMITTED` or `BOARD_REVIEW` — one live appeal
    at a time, otherwise `ERR_APPEAL_ALREADY_OPEN`."

    A withdrawn appeal is terminal, so taking it into board review is refused on the appeal
    machine's own rung.

    Design: Corner/state_machines/board_review_on_a_withdrawn_appeal_is_refused_by_terminal_lockdown
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx, reason_id = _contested_rejection(api)
    appeal = validate_success(
        api.create_appeal_request(
            _appeal_body(ctx, reason_id), ctx.compliance_officer
        ),
        201,
    )
    validate_success(
        api.withdraw_appeal(
            appeal["id"],
            ctx.compliance_officer,
            {"reason_code": "DEVELOPER_RECONSIDERED"},
        ),
        200,
    )

    validate_error(
        api.board_review_appeal(appeal["id"], ctx.appeal_board),
        ApiErrorId.ERR_INVALID_APPEAL_STATE,
        409,
    )

    row = get_success_data(api.get_appeal_request(appeal["id"], ctx.compliance_officer))
    assert row["state"] == "WITHDRAWN"
    assert row["board_started_at"] is None


def test_granting_an_expedite_request_consumes_exactly_one_of_the_two_credits(api):
    """"`GRANT` moves `REQUESTED → GRANTED`, stamps `granted_at`, records `decided_by_user_id`, and
    decreases `expedite_credits_remaining` by exactly one; it is refused with
    `ERR_EXPEDITE_QUOTA_EXHAUSTED` when no credit remains and with `ERR_STANDING_TOO_LOW` when
    standing has since fallen below the floor, and the deciding operator must differ from the
    submission's `reviewed_by_user_id`."

    Design: Corner/state_machines/granting_an_expedite_request_consumes_exactly_one_of_the_two_credits
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    assert ctx.standing()["expedite_credits_remaining"] == 2

    request = validate_success(
        api.create_expedite_request(_expedite_payload(ctx), ctx.release_manager), 201
    )
    assert request["state"] == "REQUESTED"
    assert request["granted_at"] is None
    assert ctx.standing()["expedite_credits_remaining"] == 2

    granted = validate_success(
        api.decide_expedite_request(
            request["id"],
            {
                "outcome": "GRANT",
                "decision_rationale": (
                    "Payment regression justifies expedited handling."
                ),
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert granted["state"] == "GRANTED"
    assert _instant(granted["granted_at"]) == _instant(DEFAULT_CLOCK)
    assert granted["decided_by_user_id"] == ctx.appeal_board["X-User-ID"]

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 1
    assert standing["credits_used_in_window"] == 1


def test_queueing_with_the_granted_expedite_shortens_the_sla_to_twelve_hours(api):
    """"Step five maps the band to an SLA: 12 hours for `EXPEDITED`, 24 for `HIGH`, 48 for `NORMAL`
    and 96 for `LOW`."

    Design: Corner/state_machines/queueing_with_the_granted_expedite_consumes_it_and_shortens_the_sla_to_twelve_hours
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    request, _granted = _granted_expedite(api, ctx)

    queued = validate_success(
        api.queue_submission(
            ctx.submission_id,
            ctx.release_manager,
            {"expedite_request_id": request["id"]},
        ),
        200,
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["submission_channel"] == "EXPEDITED"
    assert_decimal_equals(queued["priority_score"], 50.00, 2, "priority")
    assert queued["priority_band"] == "EXPEDITED"
    assert _instant(queued["provisional_deadline_at"]) == _instant(
        "2026-08-03T00:00:00Z"
    )
    assert _instant(queued["effective_review_deadline_at"]) == _instant(
        "2026-08-01T12:00:00Z"
    )

    consumed = get_success_data(
        api.get_expedite_request(request["id"], ctx.release_manager)
    )
    assert consumed["state"] == "CONSUMED"
    assert _instant(consumed["consumed_at"]) == _instant(DEFAULT_CLOCK)
    assert ctx.standing()["expedite_credits_remaining"] == 1


def test_withdrawing_the_expedited_build_refunds_the_credit_and_the_slot(api):
    """"A granted request is `CONSUMED` at queue entry, and a `REQUESTED`, `GRANTED` or `CONSUMED`
    request becomes `REFUNDED` with `refunded_at` stamped when the cited submission is withdrawn,
    restoring the credit to its pre-grant value."

    Design: Corner/state_machines/withdrawing_the_expedited_build_refunds_the_credit_and_the_review_slot_together
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    request, _granted = _granted_expedite(api, ctx)
    validate_success(
        api.queue_submission(
            ctx.submission_id,
            ctx.release_manager,
            {"expedite_request_id": request["id"]},
        ),
        200,
    )

    withdrawn = validate_success(
        api.withdraw_submission(
            ctx.submission_id, ctx.release_manager, {"reason_code": "BUILD_DEFECT"}
        ),
        200,
    )
    assert withdrawn["state"] == "DEVELOPER_WITHDRAWN"
    assert withdrawn["review_window_id"] is None

    refunded = get_success_data(
        api.get_expedite_request(request["id"], ctx.release_manager)
    )
    assert refunded["state"] == "REFUNDED"
    assert _instant(refunded["refunded_at"]) == _instant(DEFAULT_CLOCK)

    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_consumed"] == 0
    assert window["slots_available"] == 5

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 2
    assert standing["credits_used_in_window"] == 0


def _item_payload(ctx, **overrides):
    """A CommerceItem creation body for the ctx app record."""
    payload = {
        "app_record_id": ctx.app_record_id,
        "item_type": "CONSUMABLE",
        "reference_name": "Coin Pack 100",
        "price_tier_cents": 1005,
        "entitlement_class": "DIGITAL_CONTENT",
    }
    payload.update(overrides)
    return payload


def test_denying_an_expedite_request_is_terminal_and_consumes_no_credit(api):
    """"`DENY` moves the request from `REQUESTED` to `DENIED`, which is terminal and consumes
    nothing."

    The design's `MARKETING_DEADLINE` category is not one the PRD publishes, so the request is
    filed under `TIME_SENSITIVE_EVENT` and the decision carries the PRD's `decision_rationale`.

    Design: Corner/state_machines/denying_an_expedite_request_is_terminal_and_consumes_no_credit
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    request = validate_success(
        api.create_expedite_request(
            dict(_expedite_payload(ctx), justification_category="TIME_SENSITIVE_EVENT"),
            ctx.release_manager,
        ),
        201,
    )

    denied = validate_success(
        api.decide_expedite_request(
            request["id"],
            {
                "outcome": "DENY",
                "decision_rationale": (
                    "Marketing deadlines are not an expedite justification."
                ),
            },
            ctx.appeal_board,
        ),
        200,
    )
    assert denied["state"] == "DENIED"
    assert denied["granted_at"] is None

    validate_error(
        api.decide_expedite_request(
            request["id"],
            {
                "outcome": "GRANT",
                "decision_rationale": "Second attempt on a terminal row.",
            },
            ctx.appeal_board,
        ),
        ApiErrorId.ERR_INVALID_EXPEDITE_STATE,
        409,
    )
    reread = get_success_data(
        api.get_expedite_request(request["id"], ctx.release_manager)
    )
    assert reread["state"] == "DENIED"
    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 2
    assert standing["credits_used_in_window"] == 0


def test_a_third_grant_in_the_rolling_window_returns_expedite_quota_exhausted(api):
    """"`expedite_credits_remaining` is 2 minus that count, so remaining plus used always equals 2
    at every observable instant."

    The third grant is the one the PRD refuses at zero credits, and the design's
    `CRITICAL_BUG_FIX` category is spelled `CRITICAL_BUG` in the PRD's enumeration.

    Design: Corner/state_machines/a_third_grant_in_the_rolling_window_returns_expedite_quota_exhausted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))

    def file_request(category, justification):
        return validate_success(
            api.create_expedite_request(
                {
                    "submission_id": ctx.submission_id,
                    "justification_category": category,
                    "justification": justification,
                },
                ctx.release_manager,
            ),
            201,
        )

    def grant(request_id, rationale):
        return api.decide_expedite_request(
            request_id,
            {"outcome": "GRANT", "decision_rationale": rationale},
            ctx.appeal_board,
        )

    first = file_request("CRITICAL_BUG", "First expedite: wallet transfer regression.")
    validate_success(grant(first["id"], "Granted on the wallet regression."), 200)
    second = file_request("SECURITY_FIX", "Second expedite: token refresh vulnerability.")
    validate_success(grant(second["id"], "Granted on the token vulnerability."), 200)
    third = file_request("SECURITY_FIX", "Third expedite: one credit past the ceiling.")

    validate_error(
        grant(third["id"], "Should be refused by the quota."),
        ApiErrorId.ERR_EXPEDITE_QUOTA_EXHAUSTED,
        409,
    )
    reread = get_success_data(api.get_expedite_request(third["id"], ctx.release_manager))
    assert reread["state"] == "REQUESTED"
    assert reread["granted_at"] is None
    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 0
    assert standing["credits_used_in_window"] == 2


def test_commerce_item_submit_then_approve_stamps_the_standard_thirty_percent_rate(api):
    """"`APPROVE` moves `SUBMITTED → APPROVED` and recomputes `commission_rate_applied` and
    `commission_cents` from whatever gross is already stored; `REJECT` moves `SUBMITTED →
    REJECTED` and requires a non-empty `rejection_note`, otherwise `ERR_VALIDATION`."

    The rate itself comes from the settlement rule: "The base rate is 0.15 when the account's
    `commerce_program_tier` is `SMALL_BUSINESS` and 0.30 otherwise."

    Design: Corner/state_machines/commerce_item_submit_then_approve_stamps_the_standard_thirty_percent_rate
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    item = validate_success(
        api.create_commerce_item(_item_payload(ctx), ctx.publisher_admin), 201
    )
    assert item["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_commerce_item(item["id"], ctx.publisher_admin), 200
    )
    assert submitted["status"] == "SUBMITTED"

    approved = validate_success(
        api.review_commerce_item(
            item["id"], {"outcome": "APPROVE"}, make_reviewer_headers("u-reviewer-2")
        ),
        200,
    )
    assert approved["status"] == "APPROVED"
    assert_decimal_equals(
        approved["commission_rate_applied"], 0.30, label="commission_rate_applied"
    )
    assert approved["commission_cents"] == 0
    assert approved["reported_period_label"] is None


def test_an_external_payment_link_for_digital_content_is_not_permitted(api):
    """"Pure shape breaches — a non-zero price on an external link, a stray URL on an in-app
    purchase — are `ERR_VALIDATION` on the schema rung; the policy breaches are
    `ERR_EXTERNAL_LINK_NOT_PERMITTED`, namely selling digital content through an external link,
    and submitting an external link when the account's `ACTIVE` distribution certificate does not
    carry the `EXTERNAL_PAYMENT_LINK` entitlement."

    Design: Corner/state_machines/an_external_payment_link_for_digital_content_returns_external_link_not_permitted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_error(
        api.create_commerce_item(
            _item_payload(
                ctx,
                item_type="EXTERNAL_PAYMENT_LINK",
                reference_name="Web Checkout",
                price_tier_cents=0,
                entitlement_class="DIGITAL_CONTENT",
                external_link_url="https://pay.northwind.example/checkout",
            ),
            ctx.publisher_admin,
        ),
        ApiErrorId.ERR_EXTERNAL_LINK_NOT_PERMITTED,
        409,
    )
    _items, meta = validate_paginated(
        api.list_commerce_items(
            ctx.publisher_admin, {"app_record_id": ctx.app_record_id}
        )
    )
    assert meta["total_count"] == 0


def test_rejecting_a_commerce_item_needs_a_note_and_resubmission_clears_it(api):
    """"A `PublisherAdmin` submits an item for review, moving it `DRAFT → SUBMITTED` or `REJECTED →
    SUBMITTED` and clearing any `rejection_note`; submission is blocked by both the `FROZEN` and
    the `RESTRICTED` posture and re-checks the external-link entitlement."

    The refused first review is the PRD's other half of the same rule: "`REJECT` moves `SUBMITTED
    → REJECTED` and requires a non-empty `rejection_note`, otherwise `ERR_VALIDATION`."

    Design: Corner/state_machines/rejecting_a_commerce_item_needs_a_note_and_resubmission_clears_it
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    reviewer = make_reviewer_headers("u-reviewer-2")
    item = validate_success(
        api.create_commerce_item(_item_payload(ctx), ctx.publisher_admin), 201
    )
    validate_success(api.submit_commerce_item(item["id"], ctx.publisher_admin), 200)

    validate_error(
        api.review_commerce_item(item["id"], {"outcome": "REJECT"}, reviewer),
        ApiErrorId.ERR_VALIDATION,
        422,
    )
    still_open = get_success_data(
        api.get_commerce_item(item["id"], ctx.publisher_admin)
    )
    assert still_open["status"] == "SUBMITTED"

    note = "Reference name must not promise bonus coins."
    rejected = validate_success(
        api.review_commerce_item(
            item["id"], {"outcome": "REJECT", "rejection_note": note}, reviewer
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_note"] == note

    resubmitted = validate_success(
        api.submit_commerce_item(item["id"], ctx.publisher_admin), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["rejection_note"] is None


def test_a_halting_rollback_removes_only_the_external_payment_link_item(api):
    """"With `halt_distribution` true the app's `distribution_state` becomes `ROLLED_BACK`, every
    `APPROVED` commerce item of the app whose `item_type` is `EXTERNAL_PAYMENT_LINK` is torn down
    to `REMOVED`, and the next plan for the app must respect the 72-hour cooldown."

    Design: Corner/state_machines/a_halting_rollback_removes_only_the_external_payment_link_item
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(
        client=api,
        window_overrides=dict(POOL_A_WINDOW),
        cert_overrides={"entitlements": ["IN_APP_PURCHASE", "EXTERNAL_PAYMENT_LINK"]},
    )
    reviewer = make_reviewer_headers("u-reviewer-2")

    def approved_item(**overrides):
        row = validate_success(
            api.create_commerce_item(_item_payload(ctx, **overrides), ctx.publisher_admin),
            201,
        )
        validate_success(api.submit_commerce_item(row["id"], ctx.publisher_admin), 200)
        return validate_success(
            api.review_commerce_item(row["id"], {"outcome": "APPROVE"}, reviewer), 200
        )

    consumable = approved_item()
    external = approved_item(
        item_type="EXTERNAL_PAYMENT_LINK",
        reference_name="Web Checkout",
        price_tier_cents=0,
        entitlement_class="PHYSICAL_GOOD",
        external_link_url="https://pay.northwind.example/checkout",
    )
    assert consumable["status"] == "APPROVED"
    assert external["status"] == "APPROVED"

    plan = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert plan["state"] == "ROLLED_BACK"
    assert (
        get_success_data(api.get_commerce_item(external["id"], ctx.publisher_admin))[
            "status"
        ]
        == "REMOVED"
    )
    assert (
        get_success_data(api.get_commerce_item(consumable["id"], ctx.publisher_admin))[
            "status"
        ]
        == "APPROVED"
    )
    assert ctx.app()["distribution_state"] == "ROLLED_BACK"


def test_approving_a_build_while_a_commerce_item_is_still_submitted_is_refused(api):
    """"This queue is coupled to the build queue in one direction: a build may not be approved while
    any commerce item of its app is still `SUBMITTED`."

    Design: Corner/state_machines/approving_a_build_while_a_commerce_item_is_still_submitted_is_refused
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    item = validate_success(
        api.create_commerce_item(_item_payload(ctx), ctx.publisher_admin), 201
    )
    validate_success(api.submit_commerce_item(item["id"], ctx.publisher_admin), 200)

    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    validate_error(
        api.decide_submission(ctx.submission_id, {"outcome": "APPROVE"}, ctx.reviewer),
        ApiErrorId.ERR_INVALID_COMMERCE_ITEM_STATE,
        409,
    )
    assert ctx.submission()["state"] == "IN_REVIEW"
    assert (
        get_success_data(api.get_commerce_item(item["id"], ctx.publisher_admin))["status"]
        == "SUBMITTED"
    )


def test_an_in_scope_major_finding_moves_the_provisional_but_not_the_null_final_score(api):
    """"The provisional variant, `disclosure_accuracy_score_provisional`, counts only findings whose
    `status` is `OPEN`, whose `detected_at` is at or before the submission's
    `pre_review_checked_at`, and whose `scanner_confidence` is at or above 0.8000; it does **not**
    apply the over-disclosure term, because declaring more than was observed costs a publisher
    nothing at self-review time."

    The final variant stays null because the PRD pins when each variant is written: "The
    provisional score is rewritten by the self-review check and by any finding or declaration
    mutation; the final score is rewritten when a reviewer claims the build and again at the
    decision gate."

    Design: Corner/state_machines/an_in_scope_major_finding_moves_the_provisional_score_but_not_the_null_final_score
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    before = ctx.submission()
    assert before["state"] == "PRE_REVIEW_PASSED"
    assert before["disclosure_accuracy_score_final"] is None

    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                endpoint_domain="ads.example.net",
                scanner_confidence=0.9,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    assert finding["status"] == "OPEN"

    after = ctx.submission()
    assert_decimal_equals(
        after["disclosure_accuracy_score_provisional"],
        0.8000,
        places=4,
        label="disclosure_accuracy_score_provisional",
    )
    assert after["disclosure_accuracy_score_final"] is None
    assert after["state"] == "PRE_REVIEW_PASSED"


def test_disputing_the_finding_makes_the_two_disclosure_variants_diverge(api):
    """"Disputing a finding removes it from the provisional scope but leaves it in the final scope,
    so a publisher who disputes everything watches the provisional score rise while the final score
    does not move at all."

    The reachable route is pinned by the rewrite points: the reviewer claims the build first, so
    the final variant is written at 1.0000 while no finding exists; filing the finding then rewrites
    only the provisional variant, and the `DISPUTE` triage — which "recomputes both disclosure
    scores" — is what first lets the two numbers disagree.

    Design: Corner/state_machines/disputing_the_finding_makes_the_two_disclosure_variants_diverge
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)

    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                endpoint_domain="ads.example.net",
                scanner_confidence=0.9,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    filed = ctx.submission()
    assert_decimal_equals(
        filed["disclosure_accuracy_score_provisional"], 0.8000, places=4,
        label="provisional after the finding",
    )
    assert_decimal_equals(
        filed["disclosure_accuracy_score_final"], 1.0000, places=4,
        label="final before the claim is redone",
    )

    disputed = validate_success(
        api.triage_behavior_finding(
            finding["id"],
            {
                "action": "DISPUTE",
                "justification": (
                    "The identifier is hashed per-install and is never joined to an account."
                ),
            },
            ctx.compliance_officer,
        ),
        200,
    )
    assert disputed["status"] == "DISPUTED"
    assert _instant(disputed["triaged_at"]) == _instant(DEFAULT_CLOCK)
    assert disputed["triaged_by_user_id"] == ctx.compliance_officer["X-User-ID"]

    after = ctx.submission()
    assert_decimal_equals(
        after["disclosure_accuracy_score_provisional"], 1.0000, places=4,
        label="provisional after the dispute",
    )
    assert_decimal_equals(
        after["disclosure_accuracy_score_final"], 0.8000, places=4,
        label="final after the dispute",
    )


def test_a_finding_below_the_confidence_floor_is_invisible_to_the_provisional_variant(api):
    """"The final variant, `disclosure_accuracy_score_final`, counts findings whose `status` is
    `OPEN` *or* `DISPUTED`, with no time bound and no confidence floor, and it *does* apply the
    over-disclosure term."

    At 0.7999 the finding sits one ten-thousandth below the provisional variant's inclusive 0.8000
    floor, so filing it before the claim leaves the provisional score untouched while the claim
    writes the penalised final score.

    Design: Corner/state_machines/a_finding_below_the_confidence_floor_is_invisible_to_the_provisional_variant
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="USAGE_DATA",
                observed_purpose="ANALYTICS",
                observed_linked_to_user=False,
                observed_tracking=False,
                endpoint_domain="metrics.example.net",
                scanner_confidence=0.7999,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    assert finding["status"] == "OPEN"
    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_provisional"], 1.0000, places=4,
        label="provisional below the confidence floor",
    )

    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    after = ctx.submission()
    assert_decimal_equals(
        after["disclosure_accuracy_score_provisional"], 1.0000, places=4,
        label="disclosure_accuracy_score_provisional",
    )
    assert_decimal_equals(
        after["disclosure_accuracy_score_final"], 0.8000, places=4,
        label="disclosure_accuracy_score_final",
    )


LATE_DETECTION = "2026-08-01T01:00:00Z"
DISPUTE_JUSTIFICATION = (
    "The identifier is hashed per-install and is never joined to an account."
)


def _late_finding_then_claim(api, ctx, **overrides):
    """File a finding the scanner reported after the attestation, then queue and claim.

    A late `detected_at` is outside the provisional variant's window, so the queue gate still
    sees a clean provisional score while the claim writes the penalised final score.
    """
    set_clock(api, LATE_DETECTION)
    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                endpoint_domain="ads.example.net",
                scanner_confidence=0.9,
                detected_at=LATE_DETECTION,
                **overrides,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    return finding


def test_reconciling_without_a_matching_declared_tuple_is_refused(api):
    """"`RECONCILE` requires that the submission's `declared_privacy_items` now contains a tuple
    matching the finding on all four attributes — `data_type` equal to `data_type`, purpose equal to
    `observed_purpose`, linked-to-user equal to `observed_linked_to_user` and tracking equal to
    `observed_tracking`."

    Design: Corner/state_machines/reconciling_without_a_matching_declared_tuple_returns_disclosure_still_missing
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    finding = _late_finding_then_claim(api, ctx)

    validate_error(
        api.triage_behavior_finding(
            finding["id"],
            {
                "action": "RECONCILE",
                "justification": "Claiming the label already covers this.",
            },
            ctx.policy_admin,
        ),
        ApiErrorId.ERR_DISCLOSURE_STILL_MISSING,
        409,
    )
    reread = get_success_data(api.get_behavior_finding(finding["id"], ctx.policy_admin))
    assert reread["status"] == "OPEN"
    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_final"], 0.8000, places=4,
        label="disclosure_accuracy_score_final",
    )


def test_dismissing_a_disputed_finding_restores_both_variants_to_one(api):
    """"A `ComplianceOfficer` may take `action` `DISPUTE`, moving a finding `OPEN → DISPUTED`; a
    `PlatformPolicyAdmin` may take `RECONCILE`, moving `OPEN → RECONCILED` or `DISPUTED →
    RECONCILED`, or `DISMISS`, moving `OPEN → DISMISSED` or `DISPUTED → DISMISSED`."

    `DISMISSED` is the one terminal outside both penalty scopes: the provisional variant counts only
    `OPEN` findings and the final variant counts `OPEN` or `DISPUTED`, so the pair that diverged
    under the dispute collapses back to a clean 1.0000 apiece.

    Design: Corner/state_machines/dismissing_a_disputed_finding_restores_both_variants_to_one
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(api.queue_submission(ctx.submission_id, ctx.release_manager), 200)
    validate_success(api.claim_submission(ctx.submission_id, ctx.reviewer), 200)
    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                endpoint_domain="ads.example.net",
                scanner_confidence=0.9,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    validate_success(
        api.triage_behavior_finding(
            finding["id"],
            {"action": "DISPUTE", "justification": DISPUTE_JUSTIFICATION},
            ctx.compliance_officer,
        ),
        200,
    )
    diverged = ctx.submission()
    assert_decimal_equals(
        diverged["disclosure_accuracy_score_provisional"], 1.0000, places=4,
        label="provisional under the dispute",
    )
    assert_decimal_equals(
        diverged["disclosure_accuracy_score_final"], 0.8000, places=4,
        label="final under the dispute",
    )

    dismissed = validate_success(
        api.triage_behavior_finding(
            finding["id"],
            {
                "action": "DISMISS",
                "justification": (
                    "Scanner attributed a third-party SDK request to the wrong bundle."
                ),
            },
            ctx.policy_admin,
        ),
        200,
    )
    assert dismissed["status"] == "DISMISSED"
    after = ctx.submission()
    assert_decimal_equals(
        after["disclosure_accuracy_score_provisional"], 1.0000, places=4,
        label="disclosure_accuracy_score_provisional",
    )
    assert_decimal_equals(
        after["disclosure_accuracy_score_final"], 1.0000, places=4,
        label="disclosure_accuracy_score_final",
    )


def test_an_open_critical_finding_freezes_the_app_posture(api):
    """"A finding lands `OPEN` with `triaged_by_user_id`, `triage_justification` and `triaged_at`
    null, and a `CRITICAL` finding immediately recomputes the app's posture, which freezes the app."

    The frozen tier's third code is the matching one: "`CRITICAL_FINDING_OPEN` when any behaviour
    finding belonging to any submission of this app has severity `CRITICAL` and status `OPEN` or
    `DISPUTED`", and it wins outright even though every mapping still passes. The PRD writes the
    final variant only when a reviewer claims the build and again at the decision gate, and a frozen
    app can never be queued, so the observable score here is the provisional one.

    Design: Corner/state_machines/an_open_critical_finding_freezes_the_app_posture
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                data_type="PRECISE_LOCATION",
                observed_purpose="THIRD_PARTY_SHARING",
                endpoint_domain="broker.example.net",
                severity="CRITICAL",
                scanner_confidence=0.95,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    assert finding["severity"] == "CRITICAL"
    assert finding["status"] == "OPEN"
    assert finding["triaged_by_user_id"] is None
    assert finding["triage_justification"] is None
    assert finding["triaged_at"] is None

    app = ctx.app()
    assert_posture(app, "FROZEN", ["CRITICAL_FINDING_OPEN"])
    assert_decimal_equals(
        app["feature_compliance_index"], 100.00, label="feature_compliance_index"
    )
    assert_decimal_equals(
        ctx.submission()["disclosure_accuracy_score_provisional"], 0.6000, places=4,
        label="disclosure_accuracy_score_provisional",
    )


def test_disputing_an_already_disputed_finding_returns_invalid_finding_state(api):
    """"`RECONCILED` and `DISMISSED` are terminal, and an action not declared for the current status
    is `ERR_INVALID_FINDING_STATE`."

    `DISPUTE` is declared only for `OPEN`, so the second attempt is refused and the stored
    `triage_justification` keeps the wording of the first one.

    Design: Corner/state_machines/disputing_an_already_disputed_finding_returns_invalid_finding_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    finding = validate_success(
        api.create_behavior_finding(
            create_behavior_finding_payload(
                ctx.submission_id,
                endpoint_domain="ads.example.net",
                scanner_confidence=0.9,
            ),
            ctx.policy_admin,
        ),
        201,
    )
    validate_success(
        api.triage_behavior_finding(
            finding["id"],
            {"action": "DISPUTE", "justification": DISPUTE_JUSTIFICATION},
            ctx.compliance_officer,
        ),
        200,
    )

    validate_error(
        api.triage_behavior_finding(
            finding["id"],
            {"action": "DISPUTE", "justification": "Second dispute attempt."},
            ctx.compliance_officer,
        ),
        ApiErrorId.ERR_INVALID_FINDING_STATE,
        409,
    )
    reread = get_success_data(api.get_behavior_finding(finding["id"], ctx.policy_admin))
    assert reread["status"] == "DISPUTED"
    assert reread["triage_justification"] == DISPUTE_JUSTIFICATION


def _drive_listing(api, ctx, action, headers=None):
    return api.drive_listing(
        ctx.app_record_id, {"listing_action": action}, headers or ctx.publisher_admin
    )


def test_completing_metadata_then_listing_leaves_the_distribution_dimension_untouched(api):
    """"Every one of these advances the app record's `version` by one, and none of them ever touches
    `distribution_state`, `live_submission_id` or the two share fields — delisting a store page
    leaves an in-flight rollout running untouched."

    Design: Corner/state_machines/completing_metadata_then_listing_leaves_the_distribution_dimension_untouched
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    before = ctx.app()

    complete = validate_success(_drive_listing(api, ctx, "COMPLETE_METADATA"), 200)
    assert complete["listing_state"] == "METADATA_COMPLETE"
    assert complete["version"] == before["version"] + 1

    listed = validate_success(_drive_listing(api, ctx, "LIST"), 200)
    assert listed["listing_state"] == "LISTED"
    assert listed["version"] == before["version"] + 2
    assert listed["distribution_state"] == "PHASED_ROLLOUT"
    assert_decimal_equals(listed["released_share_pct"], 1.00, label="released_share_pct")
    assert_decimal_equals(
        listed["held_back_share_pct"], 99.00, label="held_back_share_pct"
    )
    assert listed["live_submission_id"] == ctx.submission_id

    plan = ctx.plan()
    assert plan["state"] == "PHASE_ACTIVE"
    assert plan["phase_index"] == 0


def test_listing_before_any_distribution_returns_app_not_distributed(api):
    """"`LIST` moves `METADATA_COMPLETE → LISTED`, or `DELISTED → LISTED`, and requires two things:
    the posture must not be `FROZEN`, and `distribution_state` must not be `NOT_DISTRIBUTED` — a
    store page may only go live once a build is actually being distributed, and attempting it before
    then is `ERR_APP_NOT_DISTRIBUTED`."

    Design: Corner/state_machines/listing_before_any_distribution_returns_app_not_distributed
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_approved_ios(client=api, window_overrides=dict(POOL_A_WINDOW))

    complete = validate_success(_drive_listing(api, ctx, "COMPLETE_METADATA"), 200)
    assert complete["listing_state"] == "METADATA_COMPLETE"

    validate_error(
        _drive_listing(api, ctx, "LIST"), ApiErrorId.ERR_APP_NOT_DISTRIBUTED, 409
    )
    app = ctx.app()
    assert app["listing_state"] == "METADATA_COMPLETE"
    assert app["distribution_state"] == "NOT_DISTRIBUTED"


def test_completing_metadata_with_no_locale_at_all_returns_metadata_incomplete(api):
    """"`COMPLETE_METADATA` moves `DRAFT → METADATA_COMPLETE`, and requires that at least one
    submission of this app owns a primary metadata locale that is itself complete; otherwise the
    operation is refused with `ERR_METADATA_INCOMPLETE`, or with `ERR_SCREENSHOT_SET_INCOMPLETE` when
    the shortfall is specifically in the screenshot counts."

    Design: Corner/state_machines/completing_metadata_with_no_locale_at_all_returns_metadata_incomplete
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        with_content=False,
        with_pre_review=False,
        window_overrides=dict(POOL_A_WINDOW),
    )
    assert ctx.submission()["metadata_locale_count"] == 0

    validate_error(
        _drive_listing(api, ctx, "COMPLETE_METADATA"),
        ApiErrorId.ERR_METADATA_INCOMPLETE,
        409,
    )
    assert ctx.app()["listing_state"] == "DRAFT"


def test_delisting_the_store_page_keeps_the_rollout_running(api):
    """"`DELIST` moves `LISTED → DELISTED` with no preconditions at all, and is the only listing
    action a `PlatformPolicyAdmin` may take."

    Design: Corner/state_machines/delisting_the_store_page_keeps_the_rollout_running
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(_drive_listing(api, ctx, "COMPLETE_METADATA"), 200)
    validate_success(_drive_listing(api, ctx, "LIST"), 200)

    delisted = validate_success(_drive_listing(api, ctx, "DELIST"), 200)
    assert delisted["listing_state"] == "DELISTED"
    assert delisted["distribution_state"] == "PHASED_ROLLOUT"
    assert_decimal_equals(
        delisted["released_share_pct"], 1.00, label="released_share_pct"
    )
    assert_decimal_equals(
        delisted["held_back_share_pct"], 99.00, label="held_back_share_pct"
    )
    assert ctx.plan()["state"] == "PHASE_ACTIVE"


def test_returning_a_delisted_app_to_draft_while_a_plan_is_live_is_refused(api):
    """"`RETURN_TO_DRAFT` moves `DELISTED → DRAFT`, and is refused with `ERR_INVALID_ROLLOUT_STATE`
    while any rollout plan of the app is `SCHEDULED`, `PHASE_ACTIVE` or `PAUSED`."

    Design: Corner/state_machines/returning_a_delisted_app_to_draft_while_a_plan_is_live_returns_invalid_rollout_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    validate_success(_drive_listing(api, ctx, "COMPLETE_METADATA"), 200)
    validate_success(_drive_listing(api, ctx, "LIST"), 200)
    validate_success(_drive_listing(api, ctx, "DELIST"), 200)

    validate_error(
        _drive_listing(api, ctx, "RETURN_TO_DRAFT"),
        ApiErrorId.ERR_INVALID_ROLLOUT_STATE,
        409,
    )
    assert ctx.app()["listing_state"] == "DELISTED"
    assert ctx.plan()["state"] == "PHASE_ACTIVE"


def test_delisting_straight_from_draft_returns_invalid_listing_state(api):
    """"An action that is not declared for the current `listing_state` is
    `ERR_INVALID_LISTING_STATE`."

    Design: Corner/state_machines/delisting_straight_from_draft_returns_invalid_listing_state
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    assert ctx.app()["listing_state"] == "DRAFT"

    validate_error(
        _drive_listing(api, ctx, "DELIST"), ApiErrorId.ERR_INVALID_LISTING_STATE, 409
    )
    assert ctx.app()["listing_state"] == "DRAFT"


def test_resuming_a_paused_rollout_while_the_posture_is_restricted_is_refused(api):
    """"`RESUME` moves `PAUSED → PHASE_ACTIVE`, requires the posture to be `OPEN` (otherwise
    `ERR_APP_COMPLIANCE_RESTRICTED`), clears `pause_reason_code`, and re-stamps `phase_entered_at` to
    the resume instant — which means the **full 24-hour dwell restarts from the resume**, so a pause
    does not bank time toward the next advance."

    The pause here is written by the rejection cascade of a later build, which is the PRD's own
    source for the `POSTURE_DEGRADED` code.

    Design: Corner/state_machines/resuming_a_paused_rollout_while_the_posture_is_restricted_returns_compliance_restricted
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_released_ios(client=api, window_overrides=dict(POOL_A_WINDOW))
    add_submission(ctx, build_number=101, version_string="4.2.1")
    complete_content(ctx)
    run_pre_review(ctx)
    _reject_current_build(ctx, api)

    paused = ctx.plan()
    assert paused["state"] == "PAUSED"
    assert paused["pause_reason_code"] == "POSTURE_DEGRADED"
    app = ctx.app()
    assert app["distribution_state"] == "PAUSED"
    assert_posture(app, "RESTRICTED")

    validate_error(
        api.hold_rollout_plan(ctx.plan_id, {"action": "RESUME"}, ctx.release_manager),
        ApiErrorId.ERR_APP_COMPLIANCE_RESTRICTED,
        409,
    )
    still = ctx.plan()
    assert still["state"] == "PAUSED"
    assert still["pause_reason_code"] == "POSTURE_DEGRADED"
    after = ctx.app()
    assert after["distribution_state"] == "PAUSED"
    assert_posture(after, "RESTRICTED")


def test_the_clock_sweep_walks_a_credential_from_active_through_warning_to_expired(api):
    """"When the clock lands within the final 168 hours before `not_after` — that is, one week out —
    an `ACTIVE` credential moves to `EXPIRING_SOON`."

    The far boundary is the other half of the same rule: "the interval is half-open, so landing
    exactly on `not_after` expires the credential", and the sweep only counts the rows it actually
    moved, so repeating the same instant reports nothing.

    Design: Corner/state_machines/the_clock_sweep_walks_a_credential_from_active_through_expiring_soon_to_expired
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = new_account(api)
    cert = validate_success(
        api.create_signing_credential(_credential_payload(ctx), ctx.publisher_admin), 201
    )
    activated = validate_success(
        api.activate_signing_credential(cert["id"], ctx.publisher_admin), 200
    )
    assert activated["status"] == "ACTIVE"

    warned = set_clock(api, "2027-06-24T00:00:00Z")
    assert warned["credentials_warned_count"] == 1
    assert warned["credentials_expired_count"] == 0
    assert (
        get_success_data(api.get_signing_credential(cert["id"], ctx.publisher_admin))[
            "status"
        ]
        == "EXPIRING_SOON"
    )

    again = set_clock(api, "2027-06-24T00:00:00Z")
    assert again["credentials_warned_count"] == 0

    expired = set_clock(api, "2027-07-01T00:00:00Z")
    assert expired["credentials_expired_count"] == 1
    assert (
        get_success_data(api.get_signing_credential(cert["id"], ctx.publisher_admin))[
            "status"
        ]
        == "EXPIRED"
    )


def test_setting_the_clock_backwards_returns_clock_not_monotonic(api):
    """"The clock is monotonic: a `current_utc` earlier than the currently stored value is rejected
    with `ERR_CLOCK_NOT_MONOTONIC` and HTTP 409."

    The value it is compared against is the mandatory default, because "until the clock is explicitly
    set, it reads `2026-08-01T00:00:00Z`, and it never advances on its own."

    Design: Corner/state_machines/setting_the_clock_backwards_returns_clock_not_monotonic
    """
    headers = make_policy_admin_headers()
    validate_error(
        api.set_clock("2026-07-31T23:59:59Z", headers),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC,
        409,
    )
    accepted = validate_success(api.set_clock(DEFAULT_CLOCK, headers), 200)
    assert _instant(accepted["current_utc"]) == _instant(DEFAULT_CLOCK)


def test_membership_lapses_only_strictly_past_paid_through_and_renewal_reverses_it(api):
    """"When the logical clock passes an account's `membership_paid_through_at`, the sweep moves
    `program_status` from `ACTIVE` to `EXPIRED`, which immediately shows up as the restricted-tier
    reason `MEMBERSHIP_EXPIRED` on every app the account owns."

    Renewal is the compensating action: "On success `membership_paid_through_at` becomes the supplied
    `paid_through_at`, `program_status` returns from `EXPIRED` to `ACTIVE`, the compliance posture of
    every app record of the account is recomputed, and the account's `version` advances by one."

    Design: Corner/state_machines/membership_lapses_only_strictly_past_paid_through_and_renewal_reverses_it
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(
        client=api,
        account_overrides={"membership_paid_through_at": "2026-09-01T00:00:00Z"},
        with_submission=False,
        with_window=False,
    )
    assert_posture(ctx.app(), "OPEN", [])

    on_the_boundary = set_clock(api, "2026-09-01T00:00:00Z")
    assert on_the_boundary["accounts_expired_count"] == 0
    assert ctx.account()["program_status"] == "ACTIVE"

    one_second_later = set_clock(api, "2026-09-01T00:00:01Z")
    assert one_second_later["accounts_expired_count"] == 1
    assert ctx.account()["program_status"] == "EXPIRED"
    assert_posture(ctx.app(), "RESTRICTED", ["MEMBERSHIP_EXPIRED"])

    renewed = validate_success(
        api.renew_membership(
            ctx.account_id,
            {
                "expected_publisher_account_version": ctx.account_version(),
                "paid_through_at": "2027-09-01T00:00:00Z",
            },
            ctx.publisher_admin,
        ),
        200,
    )
    assert renewed["program_status"] == "ACTIVE"
    assert _instant(renewed["membership_paid_through_at"]) == _instant(
        "2027-09-01T00:00:00Z"
    )
    assert_posture(ctx.app(), "OPEN", [])


def test_closing_the_only_open_window_makes_the_next_queue_call_capacity_starved(api):
    """"If no window is eligible the queue call is refused with `ERR_NO_REVIEW_CAPACITY` and nothing
    at all changes."

    Eligibility is what the close removes: "Eligible windows are those whose `status` is `OPEN`, whose
    `platform` equals the app's `platform`, whose half-open interval contains the current instant —
    `starts_at` at or before it and `ends_at` strictly after it — and whose `slots_available` is at
    least 1."

    Design: Corner/state_machines/closing_the_only_open_window_makes_the_next_queue_call_capacity_starved
    """
    set_clock(api, DEFAULT_CLOCK)
    ctx = setup_base_ios(client=api, window_overrides=dict(POOL_A_WINDOW))

    closed = validate_success(
        api.close_review_capacity_window(ctx.window_id, ctx.policy_admin), 200
    )
    assert closed["status"] == "CLOSED"
    assert closed["slots_available"] == 5

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_NO_REVIEW_CAPACITY,
        409,
    )
    submission = ctx.submission()
    assert submission["state"] == "PRE_REVIEW_PASSED"
    assert submission["review_window_id"] is None
    window = ctx.window()
    assert window["slots_reserved"] == 0
    assert window["slots_available"] == 5
