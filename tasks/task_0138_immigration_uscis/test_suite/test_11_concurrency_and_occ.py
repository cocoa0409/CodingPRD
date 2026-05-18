"""Concurrency and racing decisions — PRD §2.6.

Coverage targets PRD-stated outcomes only:
- Two concurrent RFE issues on the same case: at most one wins; the
  loser receives ERR_RFE_ALREADY_OUTSTANDING. PRD §3.5: "when two
  officers attempt to issue an RFE on the same case at the same
  instant the first writer wins and the second receives
  ERR_RFE_ALREADY_OUTSTANDING".
- Withdraw vs approve on READY_FOR_DECISION: exactly one wins; loser
  observes the case in its new terminal state and is rejected with
  ERR_INVALID_STATE. PRD §3.7 / §2.6.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    decide_case_payload,
    issue_rfe_payload,
    make_petitioner_headers,
    run_race,
    setup_biometrics_completed,
    setup_ready_for_decision_i130,
    validate_error_is_one_of,
)


class TestConcurrentRFE:

    def test_two_officers_issue_rfe_race(self, api):
        """PRD §3.5: "when two officers attempt to issue an RFE on the
        same case at the same instant the first writer wins and the
        second receives ERR_RFE_ALREADY_OUTSTANDING referencing the
        existing RFE's id."

        Claim: two concurrent /rfe attempts on the same case — exactly
        one succeeds, the other receives ERR_RFE_ALREADY_OUTSTANDING.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case_id = bundle["case"]["id"]
        h1 = {"X-User-ID": "officer-a", "X-User-Role": "Officer",
              "Content-Type": "application/json"}
        h2 = {"X-User-ID": "officer-b", "X-User-Role": "Officer",
              "Content-Type": "application/json"}
        results = run_race(
            lambda: api_client.issue_rfe(
                case_id, issue_rfe_payload(reason_code="MISSING_DOC"), h1,
            ),
            lambda: api_client.issue_rfe(
                case_id,
                issue_rfe_payload(reason_code="IDENTITY_DOC"), h2,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser must carry ERR_RFE_ALREADY_OUTSTANDING per PRD.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_RFE_ALREADY_OUTSTANDING.value],
        )


class TestConcurrentTerminalDecisions:

    def test_withdraw_vs_approve_race(self, api):
        """PRD §3.7: "Two terminal-state races on the same case — for
        instance, a petitioner withdrawing while an officer approves a
        READY_FOR_DECISION case — are resolved first-writer-wins on
        Case.status; the loser is rejected with ERR_INVALID_STATE and
        observes the case already in its new terminal state."

        Claim: simultaneous withdraw + decide on a READY_FOR_DECISION
        case — exactly one terminal transition wins; the loser gets
        ERR_INVALID_STATE.
        """
        bundle = setup_ready_for_decision_i130()
        case_id = bundle["case"]["id"]
        petitioner = bundle["petitioner"]
        officer_h = {"X-User-ID": "officer-x", "X-User-Role": "Officer",
                     "Content-Type": "application/json"}
        results = run_race(
            lambda: api_client.decide_case(
                case_id, decide_case_payload(decision="APPROVE"),
                officer_h,
            ),
            lambda: api_client.withdraw_case(
                case_id, make_petitioner_headers(petitioner["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD pins the loser-error to ERR_INVALID_STATE.
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )
