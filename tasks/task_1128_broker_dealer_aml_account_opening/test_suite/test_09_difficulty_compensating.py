"""Difficulty queue: compensating invariants (exposure conservation, open workload)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_account,
    get_alert,
    post_security_txn,
    setup_open_account,
    setup_structuring_alert,
    validate_success,
    escalate_alert,
)


class TestPostThenReverseConservesExposure:
    def _setup_account_with_deposit(self):
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        post_security_txn(
            account_id, None, "DEPOSIT_DTC", "BLUE", 250, 40.00,
            headers=TEST_USERS["ops_headers"],
        )
        return ctx, account_id

    def test_post_adds_to_exposure(self, api):
        """PRD §3.5: "The `exposure_30d_amount` sums `amount` over all of the
        account's transactions not in `REVERSED` within the trailing thirty calendar
        days inclusive".
        The account starts at 10000.00 (DEPOSIT_DTC 250 @ 40.00, T1); posting a SELL
        of 1000 @ 4.50 = 4500.00 raises exposure to 14500.00.

        Design: Difficulty/compensating_invariant/post_then_reverse_conserves_exposure
        """
        _ctx, account_id = self._setup_account_with_deposit()
        before = get_account(account_id)
        assert before["exposure_30d_amount"] == pytest.approx(10000.00, abs=0.01)
        assert before["exposure_tier"] == "T1"

        post_security_txn(
            account_id, None, "SELL", "PNY", 1000, 4.50,
            headers=TEST_USERS["ops_headers"],
        )
        after = get_account(account_id)
        assert after["exposure_30d_amount"] == pytest.approx(14500.00, abs=0.01), (
            f"posting 4500.00 must raise exposure from 10000.00 to 14500.00, "
            f"got {after['exposure_30d_amount']}"
        )

    def test_reverse_restores_pre_post_exposure(self, api):
        """PRD §3.5: "Reversal is a compensating action: exposure and wire velocity are
        recomputed excluding the reversed transaction, so that posting followed by
        reversal leaves both aggregates equal to their pre-post values".
        Post 4500.00 then reverse it: exposure returns to 10000.00 and the tier to T1.

        Design: Difficulty/compensating_invariant/post_then_reverse_conserves_exposure
        """
        _ctx, account_id = self._setup_account_with_deposit()
        txn = post_security_txn(
            account_id, None, "SELL", "PNY", 1000, 4.50,
            headers=TEST_USERS["ops_headers"],
        )
        resp = api_client.reverse_transaction(
            txn["id"], {"reason": "erroneous trade"}, TEST_USERS["ops_headers"]
        )
        reversed_txn = validate_success(resp)
        assert reversed_txn["status"] == "REVERSED"

        after = get_account(account_id)
        assert after["exposure_30d_amount"] == pytest.approx(10000.00, abs=0.01), (
            f"post+reverse must conserve exposure at 10000.00, "
            f"got {after['exposure_30d_amount']}"
        )
        assert after["exposure_tier"] == "T1"


class TestEscalateThenDecideNoFileConservesOpenWorkload:
    def test_escalation_moves_workload_from_alert_to_case(self, api):
        """PRD §3.5: "the account's `open_alert_count` — the number of its alerts in
        `NEW` or `UNDER_REVIEW`" and PRD §3.6: "recomputes `open_case_count` — cases in
        `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, or `REOPENED`".
        Escalation moves the alert to ESCALATED_TO_CASE (leaving open_alert_count) and
        opens a case (entering open_case_count): 1 + 0 becomes 0 + 1.

        Design: Difficulty/compensating_invariant/escalate_then_decide_no_file_conserves_open_workload
        """
        ctx = setup_structuring_alert(under_review=True)
        account_id = ctx["account"]["id"]
        before = get_account(account_id)
        assert before["open_alert_count"] == 1
        assert before["open_case_count"] == 0

        escalate_alert(ctx["alert"]["id"])
        after = get_account(account_id)
        assert after["open_alert_count"] == 0, (
            f"escalated alert leaves open_alert_count, got {after['open_alert_count']}"
        )
        assert after["open_case_count"] == 1, (
            f"new case enters open_case_count, got {after['open_case_count']}"
        )

    def test_decide_no_file_returns_pre_escalation_workload(self, api):
        """PRD §3.6: "The decision compensates the escalation that brought the case in:
        the origin alert (if any) returns from `ESCALATED_TO_CASE` to `UNDER_REVIEW`,
        linked `ESCALATED` transactions become `CLEARED`, the account's open counts and
        posture are recomputed, and both the case's and the account's `version`
        increment — leaving the account's open workload as it was before the escalate
        and decide-no-file pair."

        Design: Difficulty/compensating_invariant/escalate_then_decide_no_file_conserves_open_workload
        """
        ctx = setup_structuring_alert(under_review=True)
        account_id = ctx["account"]["id"]
        case_id = escalate_alert(ctx["alert"]["id"])["case_id"]
        resp = api_client.begin_investigation(case_id, TEST_USERS["analyst_headers"])
        validate_success(resp)
        resp = api_client.decide_no_file(
            case_id,
            {"rationale": "legitimate client behavior"},
            TEST_USERS["sar_officer_headers"],
        )
        validate_success(resp)

        after = get_account(account_id)
        assert after["open_alert_count"] == 1, (
            f"alert returned for re-triage restores open_alert_count 1, "
            f"got {after['open_alert_count']}"
        )
        assert after["open_case_count"] == 0, (
            f"decided case leaves open_case_count, got {after['open_case_count']}"
        )
        alert = get_alert(ctx["alert"]["id"])
        assert alert["status"] == "UNDER_REVIEW", (
            f"origin alert returns to UNDER_REVIEW, got {alert['status']}"
        )
