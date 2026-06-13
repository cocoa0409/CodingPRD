"""Subscription lifecycle: pause/resume/cancel cycle, terminal guards, pause/cancel cascades,
and member deactivation gated by live subscriptions.

Translates queue A (Difficulty) non_linear_state_machine + cross_entity_state_dependency
+ transitive_cascade(deactivate), and queue B (Corner) subscription state-machine and
cascading_side_effects instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_plan, create_zone, register_member, create_subscription,
    create_box, setup_active_subscription, setup_paused_subscription,
    setup_referrer_referee_with_pending_referral,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: non_linear_state_machine / subscription_active_paused_cycle ──

def test_subscription_cycle_active_paused_active_increments_version(api):
    """PRD §3.3: "On success the subscription returns to `ACTIVE`, `scheduled_resume_date` is cleared to null, and `version` increments by one."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_cycle
    """
    ctx = setup_active_subscription(clock="2026-07-01T00:00:00.000Z")
    sub, member = ctx["subscription"], ctx["member"]
    assert sub["version"] == 1
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"},
        make_member_headers(member["id"])), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_subscription(
        sub["id"], make_member_headers(member["id"])), 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["version"] == 3
    assert resumed["scheduled_resume_date"] is None


def test_subscription_resume_clears_scheduled_resume_date(api):
    """PRD §3.3: "When the pause succeeds, the subscription moves to `PAUSED`; `scheduled_resume_date` is set to the supplied `resume_date"
    PRD §3.3: "On success the subscription returns to `ACTIVE`, `scheduled_resume_date` is cleared to null, and `version` increments by one."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_cycle
    """
    ctx = setup_active_subscription(clock="2026-07-01T00:00:00.000Z")
    sub, member = ctx["subscription"], ctx["member"]
    hdr = make_member_headers(member["id"])
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"}, hdr), 200)
    assert paused["scheduled_resume_date"] == "2026-08-01T00:00:00.000Z"
    resumed = validate_success(api.resume_subscription(sub["id"], hdr), 200)
    assert resumed["scheduled_resume_date"] is None


# ─── Difficulty: cross_entity_state_dependency / member_deactivate_blocked... ─

def test_member_deactivate_blocked_by_paused_subscription(api):
    """PRD §3.2: "it requires that the member hold no subscription that is either `ACTIVE` or `PAUSED`, otherwise it is rejected with `ERR_MEMBER_HAS_LIVE_SUBSCRIPTION`."

    Design: Difficulty/cross_entity_state_dependency/member_deactivate_blocked_by_live_subscription
    """
    ctx = setup_paused_subscription(clock="2026-07-01T00:00:00.000Z",
                                    resume_date="2026-08-01T00:00:00.000Z")
    member = ctx["member"]
    res = api.deactivate_member(member["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_MEMBER_HAS_LIVE_SUBSCRIPTION.value, expected_status=409)
    refetched = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert refetched["status"] == "ACTIVE"


def test_member_deactivate_blocked_by_active_subscription(api):
    """PRD §3.2: "it requires that the member hold no subscription that is either `ACTIVE` or `PAUSED`, otherwise it is rejected with `ERR_MEMBER_HAS_LIVE_SUBSCRIPTION`."

    Design: Difficulty/cross_entity_state_dependency/member_deactivate_blocked_by_live_subscription
    """
    ctx = setup_active_subscription(clock="2026-07-01T00:00:00.000Z")
    member = ctx["member"]
    res = api.deactivate_member(member["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_MEMBER_HAS_LIVE_SUBSCRIPTION.value, expected_status=409)
    refetched = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert refetched["status"] == "ACTIVE"


# ─── Difficulty: transitive_cascade / deactivate_member_voids_referee_referrals ──

def test_deactivate_referee_voids_pending_referral(api):
    """PRD §3.2: "When deactivation succeeds, the member's `status` becomes `DEACTIVATED`, and as a cascade, every still-`PENDING` referral in which this member is the referee is moved to `VOID`, with each such referral's `reward_cents` remaining 0."

    Design: Difficulty/transitive_cascade/deactivate_member_voids_referee_referrals_depth2
    """
    ctx = setup_referrer_referee_with_pending_referral(clock="2026-07-01T00:00:00.000Z")
    referee, referral = ctx["referee"], ctx["referral"]
    deactivated = validate_success(api.deactivate_member(referee["id"], ADMIN), 200)
    assert deactivated["status"] == "DEACTIVATED"
    settled = validate_success(api.get_referral(referral["id"], ADMIN), 200)
    assert settled["status"] == "VOID"
    assert settled["reward_cents"] == 0


def test_deactivate_referee_reaches_deactivated_status(api):
    """PRD §3.2: "A member can be moved from `ACTIVE` to `DEACTIVATED` by an administrator. Deactivation requires the member to currently be `ACTIVE`, otherwise it is rejected with `ERR_MEMBER_NOT_ACTIVE"

    Design: Difficulty/transitive_cascade/deactivate_member_voids_referee_referrals_depth2
    """
    ctx = setup_referrer_referee_with_pending_referral(clock="2026-07-01T00:00:00.000Z")
    referee = ctx["referee"]
    deactivated = validate_success(api.deactivate_member(referee["id"], ADMIN), 200)
    assert deactivated["status"] == "DEACTIVATED"


# ─── Corner: state_machines (invalid transitions) ───────────────────────────

def test_cancel_already_cancelled_subscription_rejected(api):
    """PRD §3.3: "Cancelling from `ACTIVE` requires the subscription to be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`), and cancelling from `PAUSED` requires it to be `PAUSED` (else `ERR_SUBSCRIPTION_NOT_PAUSED`)."

    Design: Corner/state_machines/cancel_already_cancelled_subscription_rejected
    """
    ctx = setup_active_subscription(clock="2026-07-01T00:00:00.000Z")
    sub, member = ctx["subscription"], ctx["member"]
    hdr = make_member_headers(member["id"])
    validate_success(api.cancel_subscription(sub["id"], hdr), 200)
    res = api.cancel_subscription(sub["id"], hdr)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, expected_status=409)


def test_resume_active_subscription_rejected(api):
    """PRD §3.3: "A member resumes a `PAUSED` subscription. It must be `PAUSED` (else `ERR_SUBSCRIPTION_NOT_PAUSED`)."

    Design: Corner/state_machines/resume_active_subscription_rejected
    """
    ctx = setup_active_subscription(clock="2026-07-01T00:00:00.000Z")
    sub, member = ctx["subscription"], ctx["member"]
    res = api.resume_subscription(sub["id"], make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_PAUSED.value, expected_status=409)


# ─── Corner: cascading_side_effects (pause / cancel) ────────────────────────

def test_pause_skips_in_window_boxes_and_leaves_post_resume_boxes_open(api):
    """PRD §3.3: "as a cascade, every owning weekly box that is still `OPEN` on its selection dimension, still `PENDING` on its fulfillment dimension, and scheduled to deliver on or before the `resume_date` is moved to `SKIPPED` on its selection dimension."

    Design: Corner/cross_cutting_complexity_layers/pause_skips_in_window_boxes_cascade
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box_in = create_box(member, sub, "2026-07-29T00:00:00.000Z")   # within pause window
    box_out = create_box(member, sub, "2026-08-12T00:00:00.000Z")  # after resume
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-01T00:00:00.000Z"},
        make_member_headers(member["id"])), 200)
    after_in = validate_success(api.get_weekly_box(box_in["id"], ADMIN), 200)
    after_out = validate_success(api.get_weekly_box(box_out["id"], ADMIN), 200)
    assert after_in["selection_status"] == "SKIPPED"
    assert after_out["selection_status"] == "OPEN"


def test_cancel_skips_pending_boxes_regardless_of_window(api):
    """PRD §3.3: "In both cases, as a cascade, every owning weekly box whose fulfillment dimension is still `PENDING` has its selection dimension set to `SKIPPED` while its `fulfillment_status` remains `PENDING` — only non-terminal boxes are touched."

    Design: Corner/cross_cutting_complexity_layers/cancel_skips_pending_boxes_cascade
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-09-15T00:00:00.000Z")
    cancelled = validate_success(api.cancel_subscription(
        sub["id"], make_member_headers(member["id"])), 200)
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_weekly_box(box["id"], ADMIN), 200)
    assert after["selection_status"] == "SKIPPED"


# ─── Corner: validations (invalid resume date) ──────────────────────────────

def test_invalid_resume_date_in_past_rejected(api):
    """PRD §3.3: "the `resume_date` must be strictly after the current clock date (else `ERR_INVALID_RESUME_DATE`)."

    Design: Corner/validations/invalid_resume_date_rejected
    """
    set_clock("2026-07-13T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    res = api.pause_subscription(sub["id"], {"resume_date": "2026-07-01T00:00:00.000Z"},
                                 make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_RESUME_DATE.value, expected_status=422)
