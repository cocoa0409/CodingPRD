"""Depth tests for non-linear (cyclic / revert) state-machine edges and the renewal
window temporal boundary.

Queue A (Difficulty) translations for: non_linear_state_machine and the
renewal-window instance of boundary_precision_check.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    setup_active_policy_no_split,
    setup_renewal_task_offered,
    open_trust_account_with_balance,
    set_clock,
)

MANAGER = lambda: TEST_USERS["account_manager_headers"]


# ===========================================================================
# Rule: non_linear_state_machine / renewal_task_cyclic_offered_to_review
# ===========================================================================
class TestRenewalTaskCyclicRequote:
    def test_requote_returns_offered_task_to_review(self, api):
        """PRD §3.8: "From the `OFFERED` stage the task can cycle back: a **re-quote** moves
        it `OFFERED → REVIEW` to model a renegotiation round, incrementing the task's
        `requote_count` each time it does so (the count starts at 0 and rises by one on
        every such cycle)."

        Design: Difficulty/non_linear_state_machine/renewal_task_cyclic_offered_to_review
        """
        set_clock("2026-01-01T00:00:00Z")
        s = setup_renewal_task_offered(
            active_setup=setup_active_policy_no_split(
                policy_overrides={
                    "effective_date": "2026-01-01T00:00:00Z",
                    "expiration_date": "2027-01-01T00:00:00Z",
                }
            )
        )
        task = s["task"]
        resp = api.requote_renewal_task(
            task["id"], {"expected_renewaltask_version": task["version"]}, MANAGER()
        )
        data = validate_success(resp, 200)
        assert data["stage"] == "REVIEW", data

    def test_requote_increments_requote_count(self, api):
        """PRD §3.8: "From the `OFFERED` stage the task can cycle back: a **re-quote** moves
        it `OFFERED → REVIEW` to model a renegotiation round, incrementing the task's
        `requote_count` each time it does so (the count starts at 0 and rises by one on
        every such cycle)."

        Design: Difficulty/non_linear_state_machine/renewal_task_cyclic_offered_to_review
        """
        set_clock("2026-01-01T00:00:00Z")
        s = setup_renewal_task_offered(
            active_setup=setup_active_policy_no_split(
                policy_overrides={
                    "effective_date": "2026-01-01T00:00:00Z",
                    "expiration_date": "2027-01-01T00:00:00Z",
                }
            )
        )
        task = s["task"]
        assert task["requote_count"] == 0, task
        resp = api.requote_renewal_task(
            task["id"], {"expected_renewaltask_version": task["version"]}, MANAGER()
        )
        data = validate_success(resp, 200)
        assert data["requote_count"] == 1, data


# ===========================================================================
# Rule: non_linear_state_machine / policy_cyclic_cancelled_to_reinstated
# ===========================================================================
class TestPolicyCyclicReinstate:
    def _cancelled_policy(self):
        set_clock("2026-06-01T00:00:00Z")
        open_trust_account_with_balance(5_000_000, state_code="CA")
        s = setup_active_policy_no_split(
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            }
        )
        policy = s["policy"]
        cancelled = get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-06-01T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        return cancelled

    def test_cancelled_policy_reinstates_to_reinstated(self, api):
        """PRD §3.7: "A `CANCELLED` policy may be **reinstated** by an `AccountManager`,
        transitioning `CANCELLED → REINSTATED`, provided the cancellation can be undone".

        Design: Difficulty/non_linear_state_machine/policy_cyclic_cancelled_to_reinstated
        """
        cancelled = self._cancelled_policy()
        resp = api.reinstate_policy(
            cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
        )
        data = validate_success(resp, 200)
        assert data["status"] == "REINSTATED", data

    def test_reinstate_resets_return_and_earned_premium(self, api):
        """PRD §3.7: "The policy's `return_premium_cents` and `earned_premium_cents` are both
        reset to 0."

        Design: Difficulty/non_linear_state_machine/policy_cyclic_cancelled_to_reinstated
        """
        cancelled = self._cancelled_policy()
        resp = api.reinstate_policy(
            cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
        )
        data = validate_success(resp, 200)
        assert data["return_premium_cents"] == 0, data
        assert data["earned_premium_cents"] == 0, data


# ===========================================================================
# Rule: boundary_precision_check / renewal_window_boundary_at_exactly_60_days
# ===========================================================================
class TestRenewalWindowBoundary:
    def _active_policy_then_clock(self, clock_iso):
        set_clock("2026-01-01T00:00:00Z")
        s = setup_active_policy_no_split(
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            }
        )
        set_clock(clock_iso)
        return s["policy"]

    def test_one_second_before_window_is_rejected(self, api):
        """PRD §3.8: "A renewal may be opened only inside the **renewal window**, which opens
        sixty days before expiration: the current moment must be at or after the policy's
        `expiration_date` minus sixty days. ... Opening a renewal task before the window
        opens is rejected with `ERR_RENEWAL_WINDOW_CLOSED` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/renewal_window_boundary_at_exactly_60_days
        """
        # expiration 2027-01-01 minus 60 days == 2026-11-02T00:00:00Z; one second earlier is closed.
        policy = self._active_policy_then_clock("2026-11-01T23:59:59Z")
        resp = api.create_renewal_task(
            {"policy_id": policy["id"], "target_effective_date": "2027-01-01T00:00:00Z"},
            MANAGER(),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED.value)
        # Policy unchanged.
        refreshed = get_success_data(api_client.get_policy(policy["id"], MANAGER()))
        assert refreshed["status"] == "ACTIVE", refreshed

    def test_exactly_at_window_open_succeeds(self, api):
        """PRD §3.8: "A renewal may be opened only inside the **renewal window**, which opens
        sixty days before expiration: the current moment must be at or after the policy's
        `expiration_date` minus sixty days."

        Design: Difficulty/boundary_precision_check/renewal_window_boundary_at_exactly_60_days
        """
        # expiration 2027-01-01 minus 60 days == 2026-11-02T00:00:00Z exactly opens the window.
        policy = self._active_policy_then_clock("2026-11-02T00:00:00Z")
        resp = api.create_renewal_task(
            {"policy_id": policy["id"], "target_effective_date": "2027-01-01T00:00:00Z"},
            MANAGER(),
        )
        data = validate_success(resp, 201)
        assert data["stage"] == "IDENTIFIED", data
        refreshed = get_success_data(api_client.get_policy(policy["id"], MANAGER()))
        assert refreshed["status"] == "PENDING_RENEWAL", refreshed
