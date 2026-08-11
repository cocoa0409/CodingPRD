"""Subscription lifecycle: single-subscription rule, plan-change OCC, terminal
cancel, pause/resume cycle and cadence shifts, half-open pause-window
adjacency, the 60-day pause allowance, ops-run auto-resume, and the cadence
gate on box creation."""

from test_helpers import (
    ADMIN,
    OPS,
    ApiErrorId,
    assert_same_date,
    assert_same_instant,
    assert_version_incremented,
    create_box_create_payload,
    create_next_box,
    create_pause_payload,
    create_plan_change_payload,
    create_plan_payload,
    create_subscription_payload,
    list_subscription_boxes,
    make_member_headers,
    pause_subscription,
    read_subscription,
    register_member,
    resume_subscription,
    set_clock,
    setup_closed_box,
    setup_member_with_subscription,
    subscribe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOneSubscriptionPerMember:
    def test_second_active_subscription_rejected_then_allowed_after_cancel(self, api):
        """PRD §3.3: "Each member may carry at most one non-`CANCELLED`
        subscription; a second attempt is rejected with
        `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (HTTP 409)."
        PRD §3.3: "The subscription starts `ACTIVE` with an initially empty
        `pause_windows` list, and its cadence anchor `next_cycle_due_at` is
        initialized to the subscription's `created_at`, so the first box is
        immediately due."

        Design: Corner/validations/second_active_subscription_rejected
        """
        ctx = setup_member_with_subscription(member_email="m.sub2@x.com",
                                             with_child=False)
        member, plan = ctx["member"], ctx["plan"]
        headers = make_member_headers(member["id"])

        resp = api.create_subscription(member["id"],
                                       create_subscription_payload(plan["id"]), headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_ACTIVE_EXISTS.value, 409)

        validate_success(api.cancel_subscription(
            ctx["subscription"]["id"], {}, headers))
        resp2 = api.create_subscription(member["id"],
                                        create_subscription_payload(plan["id"]), headers)
        sub2 = validate_success(resp2, 201)
        assert sub2["status"] == "ACTIVE"
        assert_same_instant(sub2["next_cycle_due_at"], sub2["created_at"],
                            "next_cycle_due_at")


class TestCancelTerminal:
    def test_cancel_already_cancelled_subscription_returns_invalid_state(self, api):
        """PRD §3.3: "Cancelling is terminal and is permitted from either
        `ACTIVE` or `PAUSED` — any other state yields `ERR_INVALID_STATE`."
        PRD §3.3: "An optional `reason` is captured into `cancel_reason`."

        Design: Corner/state_machines/cancel_already_cancelled_subscription_returns_invalid_state
        """
        ctx = setup_member_with_subscription(member_email="m.term@x.com",
                                             with_child=False)
        member = ctx["member"]
        headers = make_member_headers(member["id"])
        validate_success(api.cancel_subscription(
            ctx["subscription"]["id"], {"reason": "first"}, headers))

        resp = api.cancel_subscription(
            ctx["subscription"]["id"], {"reason": "second"}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

        sub = validate_success(api.get_subscription(ctx["subscription"]["id"], headers))
        assert sub["status"] == "CANCELLED"
        assert sub["cancel_reason"] == "first"


class TestPlanChangeOcc:
    def test_plan_change_stale_version_rejected_after_successful_change(self, api):
        """PRD §2.8: "Changing a subscription's plan (`PATCH
        /toy-rental/subscriptions/{id}/plan`) requires
        `expected_subscription_version`. If it does not equal the
        subscription's current `version` — because box creation, a pause or
        resume, or an earlier plan change has advanced the subscription since
        the caller last read it — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), since the caller's view of the plan
        terms is stale."

        Design: Corner/complexity_layers/occ_plan_change_stale_version
        """
        plan_std = validate_success(api.create_plan(create_plan_payload(name="STD"),
                                                    ADMIN), 201)
        plan_plus = validate_success(api.create_plan(
            create_plan_payload(name="PLUS", monthly_fee_cents=8000, toys_per_box=4,
                                swap_allowance_per_cycle=3, max_holds=4,
                                rotation_cadence_days=21, rental_period_days=21,
                                buyout_discount_pct=0.15), ADMIN), 201)
        member = register_member(email="m.occ1@x.com")
        headers = make_member_headers(member["id"])
        sub = subscribe(member, plan_std["id"])
        observed_version = sub["version"]

        ok = validate_success(api.change_plan(
            sub["id"],
            create_plan_change_payload(plan_plus["id"], observed_version),
            headers))
        assert_version_incremented(ok["version"], observed_version)
        assert ok["plan_id"] == plan_plus["id"]

        # Replaying the pre-mutation version is stale.
        resp = api.change_plan(
            sub["id"],
            create_plan_change_payload(plan_std["id"], observed_version),
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

        sub_now = validate_success(api.get_subscription(sub["id"], headers))
        assert sub_now["plan_id"] == plan_plus["id"]


class TestPauseResumeCycle:
    def test_resume_shifts_cadence_anchor_by_consumed_days(self, api):
        """PRD §3.3: "Either way the window is stamped `closed` with
        `consumed_days` set to the whole days between its start date and the
        earlier of the resume date and the window's end date; `current_pause_end`
        clears to null; `paused_days_used_365d` is recomputed; the cadence
        clock, frozen during the pause, is shifted forward — `next_cycle_due_at`
        moves later by exactly the closed window's `consumed_days` days; and
        the subscription's `version` increments by one."
        PRD §3.3: "its cadence anchor `next_cycle_due_at` is initialized to the
        subscription's `created_at`, so the first box is immediately due."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        ctx = setup_member_with_subscription(member_email="m.pause@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        assert_same_instant(sub["next_cycle_due_at"], sub["created_at"],
                            "initial next_cycle_due_at")

        paused = pause_subscription(sub["id"], member, "2026-05-01", 14)
        assert paused["status"] == "PAUSED"

        set_clock("2026-05-10T00:00:00Z")
        resumed = resume_subscription(sub["id"], member)
        assert resumed["status"] == "ACTIVE"
        # Consumed: min(2026-05-10, window end 2026-05-15) - 2026-05-01 = 9 days.
        assert resumed["paused_days_used_365d"] == 9
        # Cadence anchor: 2026-05-01 (created_at) + 9 consumed days.
        assert_same_instant(resumed["next_cycle_due_at"], "2026-05-10T00:00:00Z",
                            "next_cycle_due_at after resume")
        assert resumed["current_pause_end"] is None
        assert_version_incremented(resumed["version"], paused["version"])

    def test_pause_resume_pause_cycle_loops_legally(self, api):
        """PRD §3.3: "When `start_date` is on or before the logical clock date,
        the pause is immediate: the subscription moves `ACTIVE` → `PAUSED`,
        `current_pause_end` is set to the window's end date"
        PRD §3.3: "the new window must not overlap any existing window, with
        pure adjacency — a start date equal to a prior window's end date —
        explicitly allowed; violations are rejected with
        `ERR_PAUSE_WINDOW_OVERLAP` (HTTP 409)."

        The second pause starts exactly at the first window's recorded end date
        (pure adjacency), so the ACTIVE -> PAUSED -> ACTIVE -> PAUSED loop is
        legal on a strict half-open reading of the recorded windows.

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        ctx = setup_member_with_subscription(member_email="m.pause@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]

        pause_subscription(sub["id"], member, "2026-05-01", 14)
        set_clock("2026-05-10T00:00:00Z")
        resumed = resume_subscription(sub["id"], member)
        assert resumed["status"] == "ACTIVE"

        # First window was recorded as [2026-05-01, 2026-05-15); a new window
        # starting 2026-05-15 is purely adjacent to it.
        set_clock("2026-05-15T00:00:00Z")
        paused_again = pause_subscription(sub["id"], member, "2026-05-15", 5)
        assert paused_again["status"] == "PAUSED"
        assert_same_instant(paused_again["current_pause_end"], "2026-05-20T00:00:00Z",
                            "current_pause_end")
        assert_version_incremented(paused_again["version"], resumed["version"])


class TestPauseWindowOverlap:
    def test_adjacent_pause_window_accepted(self, api):
        """PRD §3.3: "the new window must not overlap any existing window, with
        pure adjacency — a start date equal to a prior window's end date —
        explicitly allowed; violations are rejected with
        `ERR_PAUSE_WINDOW_OVERLAP` (HTTP 409)."
        PRD §3.3: "When `start_date` lies in the future, the request is a
        scheduled pause: the window is appended, the subscription remains
        `ACTIVE` (a self-transition that still increments the subscription's
        `version` by one)"

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        ctx = setup_member_with_subscription(member_email="m.ovl@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        headers = make_member_headers(member["id"])

        # Scheduled window [2026-05-10, 2026-05-17) — future start, stays ACTIVE.
        first = validate_success(api.pause_subscription(
            sub["id"], create_pause_payload("2026-05-10", 7), headers))
        assert first["status"] == "ACTIVE"

        # Adjacent window: start 2026-05-17 == the prior window's end date.
        second = validate_success(api.pause_subscription(
            sub["id"], create_pause_payload("2026-05-17", 7), headers))
        assert second["status"] == "ACTIVE"
        assert_version_incremented(second["version"], first["version"])

        sub_now = read_subscription(sub["id"], member)
        windows = sub_now["pause_windows"]
        assert len(windows) == 2
        assert_same_date(windows[0]["start_date"], "2026-05-10", "window 1 start")
        assert_same_date(windows[0]["end_date"], "2026-05-17", "window 1 end")
        assert_same_date(windows[1]["start_date"], "2026-05-17", "window 2 start")
        assert_same_date(windows[1]["end_date"], "2026-05-24", "window 2 end")

    def test_overlapping_pause_window_rejected(self, api):
        """PRD §3.3: "Pausing records a half-open date window — start date
        inclusive, end date exclusive — described by a `start_date` and a
        `duration_days` length"
        PRD §3.3: "the new window must not overlap any existing window, with
        pure adjacency — a start date equal to a prior window's end date —
        explicitly allowed; violations are rejected with
        `ERR_PAUSE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        ctx = setup_member_with_subscription(member_email="m.ovl@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        headers = make_member_headers(member["id"])

        pause_subscription(sub["id"], member, "2026-05-10", 7)
        pause_subscription(sub["id"], member, "2026-05-17", 7)

        # [2026-05-18, 2026-05-25) genuinely overlaps [2026-05-17, 2026-05-24).
        resp = api.pause_subscription(
            sub["id"], create_pause_payload("2026-05-18", 7), headers)
        validate_error(resp, ApiErrorId.ERR_PAUSE_WINDOW_OVERLAP.value, 409)

        sub_now = read_subscription(sub["id"], member)
        assert len(sub_now["pause_windows"]) == 2
        assert sub_now["status"] == "ACTIVE"


class TestPauseAllowanceBoundary:
    def test_sixty_days_used_then_sixty_first_rejected(self, api):
        """PRD §3.3: "the requested duration plus `paused_days_used_365d` — the
        sum of consumed pause days across windows whose start date falls within
        the trailing 365 days of the logical clock, where the currently open
        window contributes the days elapsed so far and scheduled not-yet-active
        windows contribute their full duration — must not exceed 60 days;
        exactly 60 is legal and 61 is rejected with
        `ERR_PAUSE_ALLOWANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/pause_allowance_boundary_60_days
        """
        ctx = setup_member_with_subscription(member_email="m.pa60@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        headers = make_member_headers(member["id"])

        # Window 1: [2026-05-01, 2026-05-31), resumed at its end -> 30 days.
        pause_subscription(sub["id"], member, "2026-05-01", 30)
        set_clock("2026-05-31T00:00:00Z")
        resume_subscription(sub["id"], member)

        # Window 2: adjacent start 2026-05-31, resumed at its end -> 30 days.
        pause_subscription(sub["id"], member, "2026-05-31", 30)
        set_clock("2026-06-30T00:00:00Z")
        resumed = resume_subscription(sub["id"], member)
        assert resumed["paused_days_used_365d"] == 60

        # The 61st day exceeds the allowance.
        resp = api.pause_subscription(
            sub["id"], create_pause_payload("2026-07-01", 1), headers)
        validate_error(resp, ApiErrorId.ERR_PAUSE_ALLOWANCE_EXCEEDED.value, 422)

        sub_now = read_subscription(sub["id"], member)
        assert sub_now["paused_days_used_365d"] == 60
        assert sub_now["status"] == "ACTIVE"


class TestOpsRunAutoResume:
    def test_ops_run_auto_resumes_at_pause_end(self, api):
        """PRD §3.3: "A member may resume early, and the operations checkpoint
        auto-resumes a pause once the logical clock reaches `current_pause_end`."
        PRD §3.9: "And it auto-resumes pauses whose `current_pause_end` the
        clock has reached or passed, closing the windows and shifting each
        subscription's cadence anchor by the consumed days."
        PRD §3.9: "The run reports `promoted_count`, `expired_count`, and
        `resumed_count`, plus the `promoted_entry_ids` of the entries it
        promoted."

        Design: Corner/state_machines/ops_run_auto_resume_at_pause_end
        """
        ctx = setup_member_with_subscription(member_email="m.auto@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]

        paused = pause_subscription(sub["id"], member, "2026-05-01", 14)
        assert paused["status"] == "PAUSED"
        assert_same_instant(paused["current_pause_end"], "2026-05-15T00:00:00Z",
                            "current_pause_end")

        set_clock("2026-05-15T00:00:00Z")
        run = validate_success(api.run_allocation(OPS))
        assert run["resumed_count"] == 1

        sub_now = read_subscription(sub["id"], member)
        assert sub_now["status"] == "ACTIVE"
        # Full window consumed: min(2026-05-15, 2026-05-15) - 2026-05-01 = 14.
        assert sub_now["paused_days_used_365d"] == 14
        assert_same_instant(sub_now["next_cycle_due_at"], "2026-05-15T00:00:00Z",
                            "next_cycle_due_at after auto-resume")
        assert sub_now["current_pause_end"] is None


class TestCadenceGate:
    def test_box_create_before_cycle_due_then_exactly_at_due(self, api):
        """PRD §3.5: "the logical clock must have reached the subscription's
        `next_cycle_due_at` — an early attempt is rejected with
        `ERR_BOX_CYCLE_NOT_DUE` (HTTP 422)"
        PRD §3.8: "Closure resets the subscription's `next_cycle_due_at` to the
        current clock plus the plan's `rotation_cadence_days`"
        PRD §3.5: "A legal create stamps the new box `PLANNED` with the next
        1-based `cycle_number` in creation order"

        Design: Corner/validations/box_create_before_cycle_due_rejected
        """
        ctx = setup_closed_box(member_email="m.cad@x.com",
                               close_clock="2026-05-10T00:00:00Z")
        member, sub = ctx["member"], ctx["subscription"]
        headers = make_member_headers(member["id"])

        # Box 1 closed at clock 2026-05-10 -> next cycle due 2026-06-07.
        sub_now = read_subscription(sub["id"], member)
        assert_same_instant(sub_now["next_cycle_due_at"], "2026-06-07T00:00:00Z",
                            "next_cycle_due_at after close")

        set_clock("2026-06-06T00:00:00Z")
        resp = api.create_rotation_box(
            sub["id"], create_box_create_payload(sub_now["version"]), headers)
        validate_error(resp, ApiErrorId.ERR_BOX_CYCLE_NOT_DUE.value, 422)
        assert len(list_subscription_boxes(sub["id"], member)) == 1

        # Exactly at the due instant the create is legal (>=, not >).
        set_clock("2026-06-07T00:00:00Z")
        resp2 = api.create_rotation_box(
            sub["id"], create_box_create_payload(sub_now["version"]), headers)
        box2 = validate_success(resp2, 201)
        assert box2["cycle_number"] == 2
        assert box2["status"] == "PLANNED"

    def test_next_box_blocked_while_previous_open(self, api):
        """PRD §3.5: "no sibling box of the same subscription may sit in
        `PLANNED`, `SHIPPED`, `DELIVERED`, `RETURNING`, `RECEIVED`, or
        `INSPECTED` (`ERR_PREVIOUS_BOX_OPEN`, HTTP 409)."

        Design: Corner/endpoints/next_box_blocked_while_previous_open
        """
        ctx = setup_member_with_subscription(member_email="m.pbo@x.com",
                                             with_child=False)
        member, sub = ctx["member"], ctx["subscription"]
        headers = make_member_headers(member["id"])
        create_next_box(member, sub["id"])  # first box sits PLANNED

        sub_now = read_subscription(sub["id"], member)
        resp = api.create_rotation_box(
            sub["id"], create_box_create_payload(sub_now["version"]), headers)
        validate_error(resp, ApiErrorId.ERR_PREVIOUS_BOX_OPEN.value, 409)

        data, meta = validate_paginated(api.list_rotation_boxes(sub["id"], headers))
        assert meta["total_count"] == 1
        assert len(data) == 1
