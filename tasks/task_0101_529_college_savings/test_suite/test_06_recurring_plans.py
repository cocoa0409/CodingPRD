"""RecurringPlan creation, state-machine cycle, OCC patch, sweep
(PRD §3.3, §3.4, §3.8).

Includes the difficulty-design `recurring_plan_active_paused_cycle`
instance and the `recurring_plan_next_run_overlap_with_sweep_window`
instance.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CADENCE_MONTHLY_DAYS,
    SECONDS_PER_DAY,
    TEST_USERS,
    assert_recurring_plan,
    assert_version_incremented_by_one,
    create_recurring_plan,
    create_recurring_plan_payload,
    iso_offset,
    is_iso8601_timestamp,
    make_donor_headers,
    patch_recurring_plan_payload,
    server_now_iso,
    advance_clock_to,
    setup_donor_beneficiary_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Create RecurringPlan — PRD §3.3
# ===========================================================================
class TestCreateRecurringPlan:

    def test_create_recurring_plan_initializes_next_run_at(self, api):
        """PRD §3.3: "the plan's next_run_at is initialized to the
        current server clock plus cadence_days × 86400 seconds."

        Claim: a new RecurringPlan has next_run_at as a valid ISO 8601
        UTC timestamp and is initialized in status ACTIVE.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        res = api.create_recurring_plan(
            account["id"],
            create_recurring_plan_payload(
                donor_id=donor["id"], amount_cents=50_000,
                cadence_days=CADENCE_MONTHLY_DAYS,
            ),
            make_donor_headers(donor["id"]),
        )
        plan = validate_success(res, 201)
        assert_recurring_plan(plan)
        assert plan["status"] == "ACTIVE"
        assert plan["cadence_days"] == CADENCE_MONTHLY_DAYS
        assert is_iso8601_timestamp(plan["next_run_at"])

    @pytest.mark.parametrize("bad_cadence", [0, 1, 5, 10, 31, 100])
    def test_create_recurring_plan_invalid_cadence_rejected(
        self, api, bad_cadence,
    ):
        """PRD §3.3: "cadence_days (one of 7, 14, 30, 90, or 365)."

        Claim: cadence_days outside {7,14,30,90,365} →
        ERR_VALIDATION_FAILED.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        res = api.create_recurring_plan(
            account["id"],
            create_recurring_plan_payload(
                donor_id=donor["id"], amount_cents=50_000,
                cadence_days=bad_cadence,
            ),
            make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_VALIDATION_FAILED")


# ===========================================================================
# State machine — PRD §3.4
# ===========================================================================
class TestRecurringPlanStateMachine:

    def test_active_paused_active_paused_cancelled_cycle(self, api):
        """PRD §3.4: "A Donor may pause an ACTIVE plan, transitioning
        its status from ACTIVE to PAUSED ... A Donor may resume a
        PAUSED plan, transitioning its status from PAUSED to ACTIVE,
        provided the account is OPEN ... A Donor may cancel a plan in
        either ACTIVE or PAUSED."

        Claim: a full cycle ACTIVE → PAUSED → ACTIVE → PAUSED →
        CANCELLED transitions correctly at each step.

        # difficulty: non_linear_state_machine/recurring_plan_active_paused_cycle
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(
            account=account, donor=donor, cadence_days=CADENCE_MONTHLY_DAYS,
        )
        # Pause #1
        paused = validate_success(
            api.pause_recurring_plan(
                plan["id"], make_donor_headers(donor["id"]),
            ), 200,
        )
        assert paused["status"] == "PAUSED"
        # Resume → ACTIVE; next_run_at reset
        resumed = validate_success(
            api.resume_recurring_plan(
                plan["id"], make_donor_headers(donor["id"]),
            ), 200,
        )
        assert resumed["status"] == "ACTIVE"
        # Pause #2
        paused2 = validate_success(
            api.pause_recurring_plan(
                plan["id"], make_donor_headers(donor["id"]),
            ), 200,
        )
        assert paused2["status"] == "PAUSED"
        # Cancel from PAUSED → terminal
        cancelled = validate_success(
            api.cancel_recurring_plan(
                plan["id"], make_donor_headers(donor["id"]),
            ), 200,
        )
        assert cancelled["status"] == "CANCELLED"

    def test_pause_already_paused_rejected(self, api):
        """PRD §3.4 + §2.7: pause requires source state ACTIVE; PRD
        §2.7 makes wrong from-state return ERR_INVALID_STATE.

        Claim: a second pause on a PAUSED plan → ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        api.pause_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        res = api.pause_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_resume_requires_account_open(self, api, admin_headers):
        """PRD §3.4: "A Donor may resume a PAUSED plan, transitioning
        its status from PAUSED to ACTIVE, provided the account is
        OPEN."

        Claim: when the account is RESTRICTED, resuming a PAUSED plan
        → ERR_ACCOUNT_RESTRICTED.
        """
        from test_helpers import restrict_account
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        api.pause_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        restrict_account(account["id"])
        res = api.resume_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_ACCOUNT_RESTRICTED")

    def test_cancel_terminal_rejected(self, api):
        """PRD §3.4: "A plan that is already CANCELLED cannot be
        transitioned again (ERR_INVALID_STATE)."

        Claim: a second cancel on a CANCELLED plan → ERR_INVALID_STATE.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        api.cancel_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        res = api.cancel_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# OCC PATCH — PRD §2.5
# ===========================================================================
class TestRecurringPlanPatchOcc:

    def test_patch_without_version_succeeds(self, api):
        """PRD §2.5: "When version is omitted, the server skips the
        check and applies the write unconditionally."
        PRD §3.4: "A Donor may update an existing plan's amount_cents
        or cadence_days."

        Claim: PATCH /recurring-plans/{id} without `version` accepts
        the change and increments version.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        old_version = plan["version"]
        res = api.patch_recurring_plan(
            plan["id"],
            patch_recurring_plan_payload(amount_cents=99_999),
            make_donor_headers(donor["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["amount_cents"] == 99_999
        assert_version_incremented_by_one(updated, old_version)

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: "When version is supplied, the server compares it
        to the row's current version; if the values differ, the write
        is rejected with ERR_VERSION_CONFLICT."

        Claim: PATCH with a stale version → ERR_VERSION_CONFLICT.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        stale_version = plan["version"]
        # First PATCH succeeds and increments version.
        api.patch_recurring_plan(
            plan["id"],
            patch_recurring_plan_payload(amount_cents=55_000),
            make_donor_headers(donor["id"]),
        )
        # Second PATCH supplies the stale version → conflict.
        res = api.patch_recurring_plan(
            plan["id"],
            patch_recurring_plan_payload(
                amount_cents=44_000, version=stale_version,
            ),
            make_donor_headers(donor["id"]),
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_with_current_version_succeeds(self, api):
        """PRD §2.5: "A successful PATCH increments version by 1 and
        refreshes updated_at."

        Claim: PATCH with the current version is accepted and version
        increments.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(account=account, donor=donor)
        res = api.patch_recurring_plan(
            plan["id"],
            patch_recurring_plan_payload(
                amount_cents=66_000, version=plan["version"],
            ),
            make_donor_headers(donor["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["amount_cents"] == 66_000
        assert_version_incremented_by_one(updated, plan["version"])


# ===========================================================================
# Sweep — PRD §3.8 + difficulty-design recurring_plan_next_run_overlap
# ===========================================================================
class TestRecurringPlanSweep:

    def test_sweep_materializes_one_contribution_per_due_plan(self, api):
        """PRD §3.8: "An admin-only sweep capability iterates every
        ACTIVE recurring plan whose next_run_at is at or before the
        current now(), materializes one PENDING contribution per
        qualifying plan (stamped with contribution_kind of RECURRING
        and the originating recurring_plan_id), and advances each
        swept plan's next_run_at by cadence_days × 86400 seconds. The
        output of the sweep is the list of newly created contributions."

        Claim: after advancing the clock past the plan's first
        next_run_at, the sweep returns one PENDING contribution stamped
        RECURRING and bound to the plan.

        # difficulty: resource_temporal_overlap/recurring_plan_next_run_overlap_with_sweep_window
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(
            account=account, donor=donor,
            cadence_days=CADENCE_MONTHLY_DAYS,
        )
        # Advance the clock to one second past next_run_at to make the
        # plan strictly due.
        from datetime import datetime, timedelta, timezone
        next_run = datetime.fromisoformat(
            plan["next_run_at"].replace("Z", "+00:00"),
        )
        advance_to = (next_run + timedelta(seconds=1)).astimezone(
            timezone.utc,
        )
        advance_clock_to(
            advance_to.strftime("%Y-%m-%dT%H:%M:%S.") + (
                f"{advance_to.microsecond // 1000:03d}Z"
            ),
        )
        # First sweep.
        res = api.run_recurring_sweep(TEST_USERS["admin_headers"])
        first_batch = validate_success(res, 200)
        # PRD §3.8: "The output of the sweep is the list of newly
        # created contributions."
        assert isinstance(first_batch, list)
        assert len(first_batch) == 1
        c = first_batch[0]
        assert c["contribution_kind"] == "RECURRING"
        assert c["recurring_plan_id"] == plan["id"]
        assert c["status"] == "PENDING"
        # Second sweep (no clock advance) → no new contributions because
        # next_run_at has been pushed by cadence_days.
        second = validate_success(
            api.run_recurring_sweep(TEST_USERS["admin_headers"]), 200,
        )
        assert isinstance(second, list)
        assert len(second) == 0

    def test_sweep_skips_paused_plans(self, api):
        """PRD §3.8: "An admin-only sweep capability iterates every
        ACTIVE recurring plan."

        Claim: a PAUSED plan whose next_run_at has been reached is NOT
        materialized by the sweep.
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        plan = create_recurring_plan(
            account=account, donor=donor, cadence_days=CADENCE_MONTHLY_DAYS,
        )
        # Pause the plan.
        api.pause_recurring_plan(
            plan["id"], make_donor_headers(donor["id"]),
        )
        # Advance clock past next_run_at.
        from datetime import datetime, timedelta, timezone
        next_run = datetime.fromisoformat(
            plan["next_run_at"].replace("Z", "+00:00"),
        )
        advance_to = (next_run + timedelta(seconds=1)).astimezone(
            timezone.utc,
        )
        advance_clock_to(
            advance_to.strftime("%Y-%m-%dT%H:%M:%S.") + (
                f"{advance_to.microsecond // 1000:03d}Z"
            ),
        )
        # Sweep → empty list because the plan is PAUSED.
        res = api.run_recurring_sweep(TEST_USERS["admin_headers"])
        batch = validate_success(res, 200)
        assert isinstance(batch, list)
        assert len(batch) == 0


# ===========================================================================
# Clock — PRD §3.8
# ===========================================================================
class TestClock:

    def test_clock_advance_backward_rejected(self, api):
        """PRD §3.8: "time only moves forward, and an attempt to advance
        to a moment less than or equal to current now() is rejected
        with ERR_CLOCK_NOT_MOVING_FORWARD."

        Claim: a clock-advance whose to_iso8601 is in the past →
        ERR_CLOCK_NOT_MOVING_FORWARD.
        """
        from datetime import datetime, timedelta, timezone
        # Read the server's current time, then attempt to advance back.
        now_iso = server_now_iso()
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        past = (now_dt - timedelta(hours=1)).astimezone(timezone.utc)
        past_iso = past.strftime("%Y-%m-%dT%H:%M:%S.") + (
            f"{past.microsecond // 1000:03d}Z"
        )
        res = api.clock_advance(
            {"to_iso8601": past_iso}, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_CLOCK_NOT_MOVING_FORWARD")
