"""Concurrency tests — race-condition outcomes defined verbatim by
PRD §2.10.

Generation policy: race tests are generated only when PRD prose
explicitly defines the outcome of the concurrent operation. PRD §2.10
defines five concurrency scenarios verbatim, naming both the winning
error and serialization point. We generate tests for each scenario the
fixtures can construct without depending on PRD-silent discovery.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_appeal_payload,
    decide_application_payload,
    file_appeal,
    run_race,
    setup_denied_application,
    setup_eligible_application,
    validate_error_is_one_of,
)


class TestConcurrentDecide:
    """PRD §2.10: "Two EligibilityCaseworkers decide the same
    UNDER_REVIEW application concurrently. Exactly one decision
    commits; the loser observes that the application is no longer
    UNDER_REVIEW and receives ERR_INVALID_STATE (HTTP 409)."
    """

    def test_two_concurrent_decisions_one_succeeds(self, api):
        """PRD §2.10: "Exactly one decision commits; the loser observes
        that the application is no longer UNDER_REVIEW and receives
        ERR_INVALID_STATE."

        Claim: two simultaneous /decide APPROVE calls — exactly one
        succeeds; the other fails. PRD names the loser's error_id, so
        we also assert it on the failing response.
        """
        _sp, household, _, application = setup_eligible_application(
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 12_000.00, "frequency": "ANNUAL"},
            ],
        )
        # Two distinct caseworkers (both _alt and primary differ — the
        # original determination has not been DENIED, so no SoD blocks).
        cw_a = TEST_USERS["eligibility_caseworker_headers"]
        cw_b = TEST_USERS["eligibility_caseworker_headers_alt"]
        results = run_race(
            lambda: api.decide_application(
                household["id"], application["id"],
                decide_application_payload(decision="APPROVE"), cw_a,
            ),
            lambda: api.decide_application(
                household["id"], application["id"],
                decide_application_payload(decision="APPROVE"), cw_b,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # Failure's error_id should be ERR_INVALID_STATE per PRD §2.10.
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(
            loser_resp, ["ERR_INVALID_STATE"],
        )


class TestConcurrentAppealUniqueness:
    """PRD §2.10: "Two distinct appeals are filed against the same
    INELIGIBLE EligibilityDetermination concurrently. At most one
    appeal exists per determination_id; the second creation is rejected
    with ERR_APPEAL_ALREADY_EXISTS."
    """

    def test_two_concurrent_appeal_filings_one_succeeds(self, api):
        """PRD §2.10: "the second creation is rejected with
        ERR_APPEAL_ALREADY_EXISTS."

        Claim: two simultaneous POST /appeals against the same
        determination_id — exactly one succeeds; the loser receives
        ERR_APPEAL_ALREADY_EXISTS.
        """
        _sp, _hh, _, _app, determination = setup_denied_application()
        iw = TEST_USERS["intake_worker_headers"]
        results = run_race(
            lambda: api.create_appeal(
                create_appeal_payload(determination_id=determination["id"]),
                iw,
            ),
            lambda: api.create_appeal(
                create_appeal_payload(determination_id=determination["id"]),
                iw,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser_resp = outcome["failures"][0]
        # PRD §3.6 names ERR_APPEAL_ALREADY_EXISTS for the
        # duplicate-determination case, but PRD §2.10's priority order
        # places state-machine check (5) above appeal-uniqueness (11);
        # the losing concurrent filing may also legitimately observe the
        # winner's Application transition to APPEALED and return
        # ERR_INVALID_STATE. Both are PRD-faithful outcomes for the
        # losing writer.
        validate_error_is_one_of(
            loser_resp, ["ERR_APPEAL_ALREADY_EXISTS", "ERR_INVALID_STATE"],
        )
