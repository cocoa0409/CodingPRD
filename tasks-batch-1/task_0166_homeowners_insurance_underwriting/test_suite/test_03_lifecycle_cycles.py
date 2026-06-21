"""Cyclic state machines: the application review cycle (SUBMITTED <-> UNDER_REVIEW)
and the policy lapse/reinstate cycle. Queue A — rule non_linear_state_machine.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_underwriter_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestApplicationReviewCycle:
    def _under_review(self, api):
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property()
        app = fx.create_application(prop["id"], 300000)
        app = fx.submit_application(app["id"])
        app = fx.take_review(app["id"], uw["id"])
        return uw, app

    def test_return_to_queue_clears_assignment(self, api):
        """PRD §3.6: "The assigned underwriter may release it back to the queue,
        returning it from `UNDER_REVIEW` to `SUBMITTED` and clearing
        `assigned_underwriter_id` to null."

        Design: Difficulty/non_linear_state_machine/application_review_cycle_under_review_to_submitted
        """
        uw, app = self._under_review(api)
        returned = validate_success(
            api.return_to_queue_application(app["id"], make_underwriter_headers(uw["id"]))
        )
        assert returned["status"] == "SUBMITTED"
        assert returned["assigned_underwriter_id"] is None

    def test_retake_review_resets_assignment_and_bumps_version(self, api):
        """PRD §3.6: "An underwriter takes a submitted application under review,
        which is permitted only from `SUBMITTED` ... taking it sets the application's
        `assigned_underwriter_id` to the acting underwriter and moves it from
        `SUBMITTED` to `UNDER_REVIEW`."
        PRD §2.4: "a `version`, an integer that begins at its initial value and
        increments by one on each mutation of the resource."

        Design: Difficulty/non_linear_state_machine/application_review_cycle_under_review_to_submitted
        """
        uw, app = self._under_review(api)
        v_before = app["version"]
        validate_success(
            api.return_to_queue_application(app["id"], make_underwriter_headers(uw["id"]))
        )
        retaken = validate_success(
            api.take_review_application(app["id"], make_underwriter_headers(uw["id"]))
        )
        assert retaken["status"] == "UNDER_REVIEW"
        assert retaken["assigned_underwriter_id"] == uw["id"]
        assert retaken["version"] == v_before + 2, (
            f"Two mutations (return-to-queue + take-review) bump version by 2; "
            f"got {retaken['version']} from {v_before}"
        )


class TestPolicyLapseReinstateCycle:
    def test_active_to_lapsed_increments_lapse_count(self, api):
        """PRD §3.7: "A lapse moves the policy to `LAPSED`, increases its `lapse_count`
        by one, increments the policy's `version` by one, and posts a CREDIT to the
        ledger for the entire current `premium_balance` as a lapse write-off, so that
        `premium_balance` returns to 0."

        Design: Difficulty/non_linear_state_machine/policy_lapse_reinstate_cycle
        """
        ctx = fx.setup_active_policy(binding_amount=997.50)
        policy, uw = ctx["policy"], ctx["underwriter"]
        lapsed = validate_success(
            api.lapse_policy(policy["id"], {"expected_policy_version": policy["version"]},
                             make_underwriter_headers(uw["id"]))
        )
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_count"] == 1

    def test_lapsed_to_reinstated_via_payment_returns_to_non_terminal(self, api):
        """PRD §3.7: "A lapsed policy can be reinstated by the agent through a
        reinstatement payment, which moves the policy from `LAPSED` to `REINSTATED`."

        Design: Difficulty/non_linear_state_machine/policy_lapse_reinstate_cycle
        """
        ctx = fx.setup_active_policy(binding_amount=997.50)
        policy, uw = ctx["policy"], ctx["underwriter"]
        lapsed = fx.lapse_policy(policy["id"], policy["version"], uw["id"])
        assert lapsed["status"] == "LAPSED" and lapsed["lapse_count"] == 1
        # annual_premium 997.50 + REINSTATEMENT_FEE 250 = 1247.50
        reinstated = validate_success(
            api.create_payment(
                f.create_payment_payload(policy["id"], "REINSTATEMENT", 1247.50), AGENT
            ),
            201,
        )
        pol_after = fx.get_policy(policy["id"])
        assert pol_after["status"] == "REINSTATED", "Policy returns to a non-terminal state via the cycle"
        assert pol_after["lapse_count"] == 1
