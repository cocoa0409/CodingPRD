"""Cascading side effects (PRD §2.9, §3.2, §3.7).

Includes the difficulty-design instances
`restrict_pauses_plans_blocks_future_sweep` and `close_cancels_plans`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    CADENCE_MONTHLY_DAYS,
    TEST_USERS,
    advance_clock_to,
    assert_version_incremented_by_one,
    create_recurring_plan,
    create_state_rule,
    ensure_state_rule,
    get_success_data,
    make_donor_headers,
    setup_donor_beneficiary_account,
    validate_success,
)


# ===========================================================================
# Restrict → pause cascade — PRD §2.9, §3.2
# ===========================================================================
class TestRestrictPausesPlansCascade:

    def test_restrict_pauses_active_plans_and_sweep_skips(self, api):
        """PRD §3.2: "Restriction has a cascade: every recurring plan
        attached to the account whose status is ACTIVE transitions to
        PAUSED."
        PRD §3.8: "An admin-only sweep capability iterates every
        ACTIVE recurring plan whose next_run_at is at or before the
        current now()."

        Claim: after /restrict, every ACTIVE recurring plan on that
        account is in PAUSED; a subsequent sweep that crosses their
        original next_run_at returns an empty contributions list.

        # difficulty: transitive_cascade/restrict_pauses_plans_blocks_future_sweep
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        p1 = create_recurring_plan(account=account, donor=donor)
        p2 = create_recurring_plan(account=account, donor=donor)
        # Sanity: both are ACTIVE.
        assert p1["status"] == "ACTIVE" and p2["status"] == "ACTIVE"
        # Restrict the account.
        api.restrict_account(account["id"], TEST_USERS["admin_headers"])
        # Re-read both plans.
        p1_after = get_success_data(
            api._request(
                "GET",
                f"/recurring-plans/{p1['id']}",
                headers=make_donor_headers(donor["id"]),
            ),
        ) if False else None
        # The PRD has no GET /recurring-plans/{id} endpoint, so we
        # observe the cascade through the sweep instead.
        # Advance the clock past both plans' next_run_at.
        next_run = datetime.fromisoformat(
            p1["next_run_at"].replace("Z", "+00:00"),
        )
        advance_to = (next_run + timedelta(days=1)).astimezone(
            timezone.utc,
        )
        advance_iso = advance_to.strftime("%Y-%m-%dT%H:%M:%S.") + (
            f"{advance_to.microsecond // 1000:03d}Z"
        )
        advance_clock_to(advance_iso)
        # Sweep: PRD §3.8 only materializes ACTIVE plans → empty list.
        sweep_resp = api.run_recurring_sweep(TEST_USERS["admin_headers"])
        batch = validate_success(sweep_resp, 200)
        assert isinstance(batch, list)
        assert len(batch) == 0


# ===========================================================================
# Close → cancel cascade — PRD §2.9, §3.2
# ===========================================================================
class TestCloseCancelsPlansCascade:

    def test_close_cancels_plans(self, api):
        """PRD §3.2: "Closing cascades every recurring plan on the
        account in status ACTIVE or PAUSED to CANCELLED. Each cascade
        refreshes updated_at and increments version on the affected
        rows."

        Claim: after close, the next sweep would observe NO ACTIVE
        plans on this account (all CANCELLED). Because the PRD has no
        GET /recurring-plans/{id}, we observe the cascade by attempting
        a forbidden-from-CANCELLED transition.

        # difficulty: transitive_cascade/close_cancels_plans
        """
        donor, _ben, account = setup_donor_beneficiary_account()
        p1 = create_recurring_plan(account=account, donor=donor)
        p2 = create_recurring_plan(account=account, donor=donor)
        # Pause p2 so we exercise both ACTIVE→CANCELLED and PAUSED→CANCELLED.
        api.pause_recurring_plan(
            p2["id"], make_donor_headers(donor["id"]),
        )
        # Close the account.
        close_resp = api.close_account(
            account["id"], make_donor_headers(donor["id"]),
        )
        validate_success(close_resp, 200)
        # PRD §3.4: "A plan that is already CANCELLED cannot be
        # transitioned again (ERR_INVALID_STATE)."
        # Attempting to cancel either plan now must fail with
        # ERR_INVALID_STATE, evidencing that the cascade already
        # CANCELLED them.
        res1 = api.cancel_recurring_plan(
            p1["id"], make_donor_headers(donor["id"]),
        )
        from test_helpers import validate_error
        validate_error(res1, "ERR_INVALID_STATE")
        res2 = api.cancel_recurring_plan(
            p2["id"], make_donor_headers(donor["id"]),
        )
        validate_error(res2, "ERR_INVALID_STATE")
