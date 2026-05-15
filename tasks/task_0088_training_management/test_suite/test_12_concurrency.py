"""Concurrency / race tests — only for races whose outcome the PRD
explicitly names (PRD §2.5, §2.11, §3.1, §3.3, §3.4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    cancel_session_payload,
    create_credit_adjustment_payload,
    create_credit_pool,
    create_enrollment_payload,
    create_trainee,
    make_trainee_headers,
    run_race,
    setup_open_session,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


SESSION_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
ENROLL_DEADLINE = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


# ===========================================================================
# Two enrollments race for the last seat (PRD §3.4)
# ===========================================================================
class TestLastSeatRace:

    def test_two_enrollments_for_last_seat_serialize(
        self, api, training_admin_headers,
    ):
        """PRD §3.4: "When two enrollments race for the last open seat
        in a session, the system serializes the increment on
        enrolled_count using a compare-and-set against session.version:
        exactly one enrollment becomes CONFIRMED, and the loser is
        placed on the waitlist when waitlist capacity permits."

        Claim: with capacity=1 and waitlist_capacity=5, concurrent
        enrollments by two distinct trainees both return 2xx but only
        one is CONFIRMED; the other is WAITLISTED.
        """
        env = setup_open_session(
            capacity=1, waitlist_capacity=5, is_charged=False,
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        t1 = create_trainee(job_level=5)
        t2 = create_trainee(job_level=5)

        def enroll(t):
            return api.create_enrollment(
                create_enrollment_payload(
                    session_id=env["session"]["id"],
                    trainee_id=t["id"], mode="SELF",
                ),
                make_trainee_headers(t["id"]),
            )

        results = run_race(lambda: enroll(t1), lambda: enroll(t2))
        outcome = assert_race_outcome(results, expected_successes=2,
                                      expected_failures=0)
        # Read enrollments via list and assert one CONFIRMED, one WAITLISTED.
        list_resp = api.list_enrollments(
            training_admin_headers,
            params={"session_id": env["session"]["id"]},
        )
        rows, _ = validate_paginated(list_resp)
        statuses = sorted(r["status"] for r in rows
                          if r["trainee_id"] in (t1["id"], t2["id"]))
        assert statuses == ["CONFIRMED", "WAITLISTED"], (
            f"PRD §3.4 demands exactly one CONFIRMED and one WAITLISTED; "
            f"got {statuses}"
        )


# ===========================================================================
# Cancel vs Complete on the same session (PRD §3.3)
# ===========================================================================
class TestCancelCompleteRace:

    def test_cancel_and_complete_serialize(self, api, training_admin_headers):
        """PRD §3.3: "Cancellation racing with a completion attempt is
        serialized at the level of session.status: exactly one of the
        two operations succeeds, and the loser receives
        ERR_INVALID_SESSION_STATE."

        Claim: concurrent /cancel and /complete on the same session —
        exactly one succeeds; the other receives
        ERR_INVALID_SESSION_STATE.
        """
        env = setup_open_session(
            capacity=10, waitlist_capacity=0, is_charged=False,
            start_at=SESSION_START, end_at=SESSION_END,
            enrollment_deadline=ENROLL_DEADLINE,
        )
        # Drive to IN_PROGRESS so /complete is otherwise legal.
        advance_clock_to(SESSION_END + timedelta(minutes=1))
        # Don't run sweep + complete eagerly — keep both verbs racing.
        from test_helpers import run_sweep
        run_sweep()

        def cancel():
            return api.cancel_session(
                env["session"]["id"],
                cancel_session_payload(reason="race"),
                training_admin_headers,
            )

        def complete():
            return api.complete_session(env["session"]["id"],
                                        training_admin_headers)

        results = run_race(cancel, complete)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp, [ApiErrorId.ERR_INVALID_SESSION_STATE.value],
        )


# ===========================================================================
# Credit-pool race (PRD §2.5)
# ===========================================================================
class TestCreditPoolRace:

    def test_two_concurrent_adjustments_accumulate_or_one_retries(
        self, api, training_admin_headers,
    ):
        """PRD §2.5: "the loser of the compare-and-set on
        credit_pool.version receives this error and must retry,
        while the eventually accumulated balance reflects the exact
        arithmetic sum of every applied delta."

        Claim: two concurrent CreditAdjustments either (a) both
        succeed via serialization with accumulated_credits ==
        delta1+delta2, or (b) one fails with ERR_VERSION_CONFLICT
        and the other succeeds with accumulated_credits == its delta.

        The PRD explicitly admits both outcomes ("the loser ... must
        retry"), so we accept both endings as PRD-conformant.
        """
        trainee = create_trainee(job_level=5)
        pool = create_credit_pool(trainee_id=trainee["id"],
                                  required_credits=100.0)

        def adjust(delta, reason):
            return api.create_credit_adjustment(
                create_credit_adjustment_payload(
                    credit_pool_id=pool["id"], delta=delta, reason=reason,
                ),
                training_admin_headers,
            )

        results = run_race(
            lambda: adjust(3.0, "grant-a"),
            lambda: adjust(2.0, "grant-b"),
        )
        # Either both succeed (well-serialized) or exactly one
        # succeeds with ERR_VERSION_CONFLICT on the loser.
        succ = [r for r in results if 200 <= r.status_code < 300]
        fail = [r for r in results if r.status_code >= 400]
        assert succ, "PRD §2.5 demands at least one CreditAdjustment succeeds"
        for f in fail:
            validate_error_is_one_of(
                f, [ApiErrorId.ERR_VERSION_CONFLICT.value],
            )
        # Final pool balance must reflect applied deltas exactly.
        refreshed = validate_success(
            api.get_credit_pool(pool["id"], training_admin_headers),
            expected_status=200,
        )
        expected_balance = 0.0
        if len(succ) == 2:
            expected_balance = 5.0
        else:
            # Determine which delta won by looking at audit rows.
            from test_helpers import validate_paginated as vp
            audit_resp = api.list_audit_logs(
                training_admin_headers,
                params={"subject_kind": "CREDIT_POOL", "subject_id": pool["id"]},
            )
            audit_rows, _ = vp(audit_resp)
            # Heuristic: balance equals the delta of the surviving row.
            # We do not pin which one — accept either 3.0 or 2.0.
            assert float(refreshed["accumulated_credits"]) in (
                pytest.approx(3.0, abs=0.01), pytest.approx(2.0, abs=0.01),
            ), (
                f"PRD §2.5: surviving accumulated_credits must be one of "
                f"{{3.0, 2.0}} when one writer wins; got "
                f"{refreshed['accumulated_credits']}"
            )
            return
        assert float(refreshed["accumulated_credits"]) == pytest.approx(
            expected_balance, abs=0.01,
        ), (
            f"PRD §2.5: when both succeed, accumulated_credits == "
            f"{expected_balance}; got {refreshed['accumulated_credits']}"
        )
