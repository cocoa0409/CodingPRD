"""Difficulty rule: compensating_invariant.

Three conserved quantities — review slots, expedite credits and audience share —
each with one action that compensates a prior action exactly and one that does not.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    ApiErrorId,
    add_submission,
    assert_expedite_credit_conservation,
    assert_slot_conservation,
    complete_content,
    create_expedite_request_payload,
    num,
    run_pre_review,
    set_clock,
    setup_base_ios,
    setup_released_ios,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)


# ---------------------------------------------------------------------------
# review_slot_conservation_queue_then_withdraw
# ---------------------------------------------------------------------------
def _setup_five_slot_window(api):
    """One PRE_REVIEW_PASSED build and one OPEN five-slot window covering the clock."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_base_ios(
        client=api, window_overrides={"ends_at": "2026-09-01T00:00:00Z"}
    )


def _second_build(api, ctx, build_number=11, version_string="1.0.1"):
    """Add and pre-review a sibling build on the same app record."""
    data = add_submission(ctx, build_number=build_number, version_string=version_string)
    complete_content(ctx, data["id"])
    run_pre_review(ctx, data["id"])
    return data["id"]


def _counters(api, ctx):
    window = ctx.window()
    assert_slot_conservation(window)
    return (
        window["slots_reserved"],
        window["slots_consumed"],
        window["slots_available"],
    )


def test_queue_reserves_one_slot_and_stamps_the_window_pointer(api):
    """"Queue entry reserves — reserved up one, available down one — and its compensating
    actions, withdrawal and return-to-draft, must restore `slots_available` to the exact integer
    it held before the reservation."

    Design: Difficulty/compensating_invariant/review_slot_conservation_queue_then_withdraw
    """
    ctx = _setup_five_slot_window(api)

    assert _counters(api, ctx) == (0, 0, 5)

    queued = validate_success(
        api.queue_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert queued["state"] == "WAITING_FOR_REVIEW"
    assert queued["review_window_id"] == ctx.window_id
    assert _counters(api, ctx) == (1, 0, 4)


def test_withdrawal_restores_the_exact_pre_queue_slot_integer(api):
    """"`slots_available` is `capacity_slots` minus both."

    Design: Difficulty/compensating_invariant/review_slot_conservation_queue_then_withdraw
    """
    ctx = _setup_five_slot_window(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    assert _counters(api, ctx) == (1, 0, 4)

    withdrawn = validate_success(
        api.withdraw_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert withdrawn["state"] == "DEVELOPER_WITHDRAWN"
    assert withdrawn["review_window_id"] is None
    assert _counters(api, ctx) == (0, 0, 5)

    validate_error(
        api.queue_submission(ctx.submission_id, ctx.release_manager),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE,
        409,
    )
    assert _counters(api, ctx) == (0, 0, 5)


def test_a_claim_moves_state_without_moving_the_accounting_bucket(api):
    """"`slots_reserved` is the count of submissions assigned to the window whose `state` is
    `WAITING_FOR_REVIEW` or `IN_REVIEW`."

    Design: Difficulty/compensating_invariant/review_slot_conservation_queue_then_withdraw
    """
    ctx = _setup_five_slot_window(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.withdraw_submission(ctx.submission_id, ctx.release_manager))
    second_id = _second_build(api, ctx)

    get_success_data(api.queue_submission(second_id, ctx.release_manager))
    assert _counters(api, ctx) == (1, 0, 4)

    claimed = validate_success(api.claim_submission(second_id, ctx.reviewer), 200)
    assert claimed["state"] == "IN_REVIEW"
    assert _counters(api, ctx) == (1, 0, 4)


def test_approval_consumes_the_slot_permanently_and_is_not_compensated(api):
    """"`slots_consumed` is the count whose `state` is `APPROVED`, `REJECTED`,
    `METADATA_REJECTED`, `APPEAL_PENDING`, `REJECTED_FINAL` or `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/review_slot_conservation_queue_then_withdraw
    """
    ctx = _setup_five_slot_window(api)
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    get_success_data(api.withdraw_submission(ctx.submission_id, ctx.release_manager))
    second_id = _second_build(api, ctx)
    get_success_data(api.queue_submission(second_id, ctx.release_manager))
    get_success_data(api.claim_submission(second_id, ctx.reviewer))

    approved = validate_success(
        api.decide_submission(second_id, {"outcome": "APPROVE"}, ctx.reviewer), 200
    )
    assert approved["state"] == "APPROVED"
    assert approved["review_window_id"] == ctx.window_id, (
        "a consumed slot keeps its window pointer"
    )
    assert _counters(api, ctx) == (0, 1, 4)


def test_slot_counters_sum_to_capacity_at_every_observation(api):
    """"The invariant is absolute: the three always sum to `capacity_slots`."

    Design: Difficulty/compensating_invariant/review_slot_conservation_queue_then_withdraw
    """
    ctx = _setup_five_slot_window(api)
    observations = [_counters(api, ctx)]
    get_success_data(api.queue_submission(ctx.submission_id, ctx.release_manager))
    observations.append(_counters(api, ctx))
    get_success_data(api.withdraw_submission(ctx.submission_id, ctx.release_manager))
    observations.append(_counters(api, ctx))
    second_id = _second_build(api, ctx)
    get_success_data(api.queue_submission(second_id, ctx.release_manager))
    observations.append(_counters(api, ctx))
    get_success_data(api.claim_submission(second_id, ctx.reviewer))
    observations.append(_counters(api, ctx))
    get_success_data(
        api.decide_submission(second_id, {"outcome": "APPROVE"}, ctx.reviewer)
    )
    observations.append(_counters(api, ctx))

    assert len(observations) == 6
    for reserved, consumed, available in observations:
        assert reserved + consumed + available == 5
    assert observations[0] == observations[2], (
        "withdrawal is the exact compensating action for a queue reservation"
    )
    assert observations[-1] == (0, 1, 4)


# ---------------------------------------------------------------------------
# expedite_credit_conservation_grant_consume_then_refund
# ---------------------------------------------------------------------------
def _expedite(api, ctx, submission_id=None, category="SECURITY_FIX", justification=None):
    payload = create_expedite_request_payload(
        submission_id or ctx.submission_id, justification_category=category
    )
    if justification is not None:
        payload["justification"] = justification
    return api.create_expedite_request(payload, ctx.release_manager)


def _grant(api, ctx, expedite_id, rationale="Confirmed regression in production."):
    return api.decide_expedite_request(
        expedite_id,
        {"outcome": "GRANT", "decision_rationale": rationale},
        ctx.appeal_board,
    )


def _setup_three_requests(api):
    """Three REQUESTED expedite rows against one PRE_REVIEW_PASSED build."""
    ctx = _setup_five_slot_window(api)
    first = get_success_data(_expedite(api, ctx, category="CRITICAL_BUG"))
    second = get_success_data(_expedite(api, ctx, category="SECURITY_FIX"))
    third = get_success_data(_expedite(api, ctx, category="TIME_SENSITIVE_EVENT"))
    return ctx, first["id"], second["id"], third["id"]


def test_filing_a_request_consumes_no_credit_at_all(api):
    """"Filing itself checks that the account's `standing_score_rolling_365` is at or above
    60.00, refusing below it with `ERR_STANDING_TOO_LOW`, but consumes no credit."

    Design: Difficulty/compensating_invariant/expedite_credit_conservation_grant_consume_then_refund
    """
    ctx = _setup_five_slot_window(api)

    filed = validate_success(_expedite(api, ctx, category="CRITICAL_BUG"), 201)
    assert filed["state"] == "REQUESTED"
    assert filed["granted_at"] is None
    assert filed["requested_at"] == DEFAULT_CLOCK
    assert filed["publisher_account_id"] == ctx.account_id

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 2
    assert standing["credits_used_in_window"] == 0
    assert_expedite_credit_conservation(standing, standing["credits_used_in_window"])


def test_two_grants_exhaust_the_window_and_the_third_is_refused(api):
    """"`expedite_credits_remaining` is 2 minus that count, so remaining plus used always
    equals 2 at every observable instant."

    Design: Difficulty/compensating_invariant/expedite_credit_conservation_grant_consume_then_refund
    """
    ctx, first_id, second_id, third_id = _setup_three_requests(api)

    granted = validate_success(_grant(api, ctx, first_id), 200)
    assert granted["state"] == "GRANTED"
    assert granted["granted_at"] == DEFAULT_CLOCK
    after_one = ctx.standing()
    assert after_one["expedite_credits_remaining"] == 1
    assert after_one["credits_used_in_window"] == 1
    assert_expedite_credit_conservation(after_one, after_one["credits_used_in_window"])

    validate_success(_grant(api, ctx, second_id), 200)
    after_two = ctx.standing()
    assert after_two["expedite_credits_remaining"] == 0
    assert after_two["credits_used_in_window"] == 2

    validate_error(
        _grant(api, ctx, third_id),
        ApiErrorId.ERR_EXPEDITE_QUOTA_EXHAUSTED,
        409,
    )
    third = get_success_data(api.get_expedite_request(third_id, ctx.release_manager))
    assert third["state"] == "REQUESTED"


def test_consumption_at_queue_entry_is_not_the_compensating_action(api):
    """"A granted request is `CONSUMED` at queue entry, and a `REQUESTED`, `GRANTED` or
    `CONSUMED` request becomes `REFUNDED` with `refunded_at` stamped when the cited submission
    is withdrawn, restoring the credit to its pre-grant value."

    Design: Difficulty/compensating_invariant/expedite_credit_conservation_grant_consume_then_refund
    """
    ctx, first_id, second_id, _third_id = _setup_three_requests(api)
    get_success_data(_grant(api, ctx, first_id))
    get_success_data(_grant(api, ctx, second_id))

    queued = validate_success(
        api.queue_submission(
            ctx.submission_id, ctx.release_manager, {"expedite_request_id": first_id}
        ),
        200,
    )
    assert queued["submission_channel"] == "EXPEDITED"
    assert queued["priority_band"] == "EXPEDITED"
    assert queued["effective_review_deadline_at"] == "2026-08-01T12:00:00Z"

    consumed = get_success_data(api.get_expedite_request(first_id, ctx.release_manager))
    assert consumed["state"] == "CONSUMED"
    assert consumed["consumed_at"] == DEFAULT_CLOCK

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 0
    assert standing["credits_used_in_window"] == 2


def test_withdrawal_refunds_consumed_and_granted_and_voids_the_requested_row(api):
    """"A grant followed by its refund must restore `expedite_credits_remaining` to the exact
    pre-grant integer, with no drift tolerated even when the clock moved between the two actions,
    and the third grant inside a rolling window is refused at zero credits."

    Design: Difficulty/compensating_invariant/expedite_credit_conservation_grant_consume_then_refund
    """
    ctx, first_id, second_id, third_id = _setup_three_requests(api)
    get_success_data(_grant(api, ctx, first_id))
    get_success_data(_grant(api, ctx, second_id))
    get_success_data(
        api.queue_submission(
            ctx.submission_id, ctx.release_manager, {"expedite_request_id": first_id}
        )
    )

    withdrawn = validate_success(
        api.withdraw_submission(ctx.submission_id, ctx.release_manager), 200
    )
    assert withdrawn["state"] == "DEVELOPER_WITHDRAWN"

    rows, _meta = validate_paginated(
        api.list_expedite_requests(
            ctx.release_manager, params={"submission_id": ctx.submission_id}
        )
    )
    assert len(rows) == 3
    assert [row["state"] for row in rows] == ["REFUNDED", "REFUNDED", "REFUNDED"]
    by_id = {row["id"]: row for row in rows}
    assert by_id[first_id]["refunded_at"] == DEFAULT_CLOCK
    assert by_id[third_id]["granted_at"] is None, (
        "the never-granted row was voided rather than refunded"
    )

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 2
    assert standing["credits_used_in_window"] == 0
    assert_expedite_credit_conservation(standing, standing["credits_used_in_window"])


def test_the_refunded_credit_makes_a_grant_legal_again_on_the_next_build(api):
    """"Credits used is the count of the account's expedite requests whose `state` is `GRANTED`
    or `CONSUMED` and whose `granted_at` falls at or after 365 days before the current instant,
    with the lower bound inclusive; `DENIED` and `REFUNDED` rows are out of scope, and a
    `REQUESTED` row has a null `granted_at` and therefore never counts."

    Design: Difficulty/compensating_invariant/expedite_credit_conservation_grant_consume_then_refund
    """
    ctx, first_id, second_id, _third_id = _setup_three_requests(api)
    get_success_data(_grant(api, ctx, first_id))
    get_success_data(_grant(api, ctx, second_id))
    get_success_data(
        api.queue_submission(
            ctx.submission_id, ctx.release_manager, {"expedite_request_id": first_id}
        )
    )
    get_success_data(api.withdraw_submission(ctx.submission_id, ctx.release_manager))

    rebuilt = add_submission(ctx, build_number=11, version_string="1.0.1")
    fourth = get_success_data(
        _expedite(api, ctx, submission_id=rebuilt["id"], category="SECURITY_FIX")
    )
    granted = validate_success(_grant(api, ctx, fourth["id"]), 200)
    assert granted["state"] == "GRANTED"
    assert granted["granted_at"] == DEFAULT_CLOCK

    standing = ctx.standing()
    assert standing["expedite_credits_remaining"] == 1
    assert standing["credits_used_in_window"] == 1
    assert_expedite_credit_conservation(standing, standing["credits_used_in_window"])


# ---------------------------------------------------------------------------
# audience_share_conservation_advance_pause_resume_then_rollback
# ---------------------------------------------------------------------------
def _shares(data):
    """The two share fields, checked for conservation at the point of reading."""
    released = num(data["released_share_pct"])
    held_back = num(data["held_back_share_pct"])
    assert round(released + held_back, 2) == 100.00, (
        f"shares must sum to exactly 100.00, got {released} + {held_back}"
    )
    return released, held_back


def _setup_phase_active_plan(api):
    """A started PHASED plan at phase 0, clock at its default."""
    set_clock(api, DEFAULT_CLOCK)
    return setup_released_ios(client=api, mode="PHASED")


def _advance(api, ctx, to_phase_index):
    return api.advance_rollout_plan(
        ctx.plan_id, {"to_phase_index": to_phase_index}, ctx.release_manager
    )


def test_started_plan_mirrors_the_first_phase_share_onto_the_app(api):
    """"The phase ladder is fixed at seven audience shares: 1.00, 2.00, 5.00, 10.00, 20.00,
    50.00 and 100.00 percent, at indices 0 through 6."

    Design: Difficulty/compensating_invariant/audience_share_conservation_advance_pause_resume_then_rollback
    """
    ctx = _setup_phase_active_plan(api)

    plan = ctx.plan()
    assert plan["state"] == "PHASE_ACTIVE"
    assert plan["phase_index"] == 0
    assert _shares(plan) == (1.00, 99.00)

    app = ctx.app()
    assert app["distribution_state"] == "PHASED_ROLLOUT"
    assert app["live_submission_id"] == ctx.submission_id
    assert _shares(app) == (1.00, 99.00)


def test_advance_exactly_at_the_dwell_edge_moves_both_copies_of_the_share(api):
    """"A successful advance sets `phase_index`, re-stamps `phase_entered_at`, sets
    `released_share_pct` to the share at the new index and `held_back_share_pct` to 100.00 minus
    it, and mirrors both onto the app record."

    Design: Difficulty/compensating_invariant/audience_share_conservation_advance_pause_resume_then_rollback
    """
    ctx = _setup_phase_active_plan(api)
    set_clock(api, "2026-08-02T00:00:00Z")

    advanced = validate_success(_advance(api, ctx, 1), 200)
    assert advanced["phase_index"] == 1
    assert advanced["phase_entered_at"] == "2026-08-02T00:00:00Z"
    assert _shares(advanced) == (2.00, 98.00)
    assert _shares(ctx.app()) == (2.00, 98.00)


def test_pause_freezes_the_shares_and_resume_restarts_the_dwell(api):
    """"`PAUSE` moves `PHASE_ACTIVE → PAUSED`, records the reason — the code
    `POSTURE_DEGRADED` is what the compliance cascades write here — freezes both share fields
    exactly as they stand, and drives the app to `PAUSED`."

    Design: Difficulty/compensating_invariant/audience_share_conservation_advance_pause_resume_then_rollback
    """
    ctx = _setup_phase_active_plan(api)
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(_advance(api, ctx, 1))

    paused = validate_success(
        api.hold_rollout_plan(
            ctx.plan_id,
            {"action": "PAUSE", "pause_reason_code": "CRASH_WATCH"},
            ctx.release_manager,
        ),
        200,
    )
    assert paused["state"] == "PAUSED"
    assert paused["pause_reason_code"] == "CRASH_WATCH"
    assert _shares(paused) == (2.00, 98.00)

    app_paused = ctx.app()
    assert app_paused["distribution_state"] == "PAUSED"
    assert _shares(app_paused) == (2.00, 98.00)

    resumed = validate_success(
        api.hold_rollout_plan(ctx.plan_id, {"action": "RESUME"}, ctx.release_manager),
        200,
    )
    assert resumed["state"] == "PHASE_ACTIVE"
    assert resumed["pause_reason_code"] is None
    assert resumed["phase_entered_at"] == "2026-08-02T00:00:00Z"
    assert _shares(resumed) == (2.00, 98.00)

    validate_error(
        _advance(api, ctx, 2), ApiErrorId.ERR_PHASE_DWELL_NOT_MET, 409
    )
    still = ctx.plan()
    assert still["phase_index"] == 1
    assert _shares(still) == (2.00, 98.00)


def test_rollback_returns_held_back_to_exactly_one_hundred_without_residue(api):
    """"`RESUME` moves `PAUSED → PHASE_ACTIVE`, requires the posture to be `OPEN` (otherwise
    `ERR_APP_COMPLIANCE_RESTRICTED`), clears `pause_reason_code`, and re-stamps
    `phase_entered_at` to the resume instant — which means the **full 24-hour dwell restarts
    from the resume**, so a pause does not bank time toward the next advance."

    Design: Difficulty/compensating_invariant/audience_share_conservation_advance_pause_resume_then_rollback
    """
    ctx = _setup_phase_active_plan(api)
    set_clock(api, "2026-08-02T00:00:00Z")
    get_success_data(_advance(api, ctx, 1))
    get_success_data(
        api.hold_rollout_plan(
            ctx.plan_id,
            {"action": "PAUSE", "pause_reason_code": "CRASH_WATCH"},
            ctx.release_manager,
        )
    )
    get_success_data(
        api.hold_rollout_plan(ctx.plan_id, {"action": "RESUME"}, ctx.release_manager)
    )
    set_clock(api, "2026-08-03T00:00:00Z")

    advanced = validate_success(_advance(api, ctx, 2), 200)
    assert advanced["phase_index"] == 2
    assert _shares(advanced) == (5.00, 95.00)
    assert _shares(ctx.app()) == (5.00, 95.00)

    rolled = validate_success(
        api.rollback_rollout_plan(
            ctx.plan_id,
            {"rollback_reason_code": "CRASH_SPIKE", "halt_distribution": True},
            ctx.release_manager,
        ),
        200,
    )
    assert rolled["state"] == "ROLLED_BACK"
    assert rolled["terminated_at"] == "2026-08-03T00:00:00Z"
    assert rolled["rollback_reason_code"] == "CRASH_SPIKE"
    assert rolled["phase_index"] == 2, "a rollback does not reset the phase index"
    assert _shares(rolled) == (0.00, 100.00)

    app = ctx.app()
    assert app["distribution_state"] == "ROLLED_BACK"
    assert app["live_submission_id"] is None
    assert app["rollback_count"] == 1
    assert _shares(app) == (0.00, 100.00)
