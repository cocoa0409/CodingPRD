"""Concurrency: race conditions where PRD explicitly defines an
expected outcome.

Per the SKILL silence-pattern rules, race tests are generated ONLY for
scenarios where PRD names the outcome. The PRD §3.2 / §3.10 / §3.11
race clauses (loser error_id named) qualify; other races (e.g.,
issue_result_notice vs sweep on the loser's specific error_id) are
generated only when the SKILL's two-reader test passes.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    close_dispute_verified,
    create_dispute_payload,
    file_regulatory_complaint,
    make_consumer_headers,
    place_credit_freeze,
    run_race,
    setup_consumer_furnisher_report_tradeline,
    setup_dispute_in_state,
    validate_error_is_one_of,
)


# ===========================================================================
# Duplicate dispute race — PRD §3.2
# ===========================================================================
class TestDuplicateDisputeRace:

    def test_two_simultaneous_disputes_one_loses_with_duplicate_active(self, api):
        """PRD §3.2: 'When two consumers race two submissions for the
        same tradeline simultaneously, this same rule serializes them:
        the first writer wins on (consumer_id, tradeline_item_id) when
        the existing dispute is in a non-terminal status and the loser
        receives ERR_DUPLICATE_ACTIVE_DISPUTE.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        payload_a = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
        )
        payload_b = create_dispute_payload(
            credit_report_id=r["id"], tradeline_item_id=t["id"],
        )
        results = run_race(
            lambda: api.create_dispute(
                c["id"], payload_a, make_consumer_headers(c["id"]),
            ),
            lambda: api.create_dispute(
                c["id"], payload_b, make_consumer_headers(c["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names the loser's error_id explicitly.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE.value],
        )


# ===========================================================================
# Duplicate freeze race — PRD §3.11
# ===========================================================================
class TestDuplicateFreezeRace:

    def test_two_simultaneous_freezes_one_loses_with_already_active(self, api):
        """PRD §3.11: 'a second placement is rejected with
        ERR_FREEZE_ALREADY_ACTIVE, which is also the loser's error
        when two placements race in parallel.'"""
        from test_helpers import create_consumer
        c = create_consumer()
        results = run_race(
            lambda: api.create_credit_freeze(
                c["id"], {"bureau": "EQUIFAX"},
                make_consumer_headers(c["id"]),
            ),
            lambda: api.create_credit_freeze(
                c["id"], {"bureau": "EQUIFAX"},
                make_consumer_headers(c["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_FREEZE_ALREADY_ACTIVE.value],
        )


# ===========================================================================
# Duplicate regulatory complaint race — PRD §3.10
# ===========================================================================
class TestDuplicateComplaintRace:

    def test_two_simultaneous_complaints_one_loses_with_already_open(self, api):
        """PRD §3.10: 'A second open complaint is rejected with
        ERR_COMPLAINT_ALREADY_OPEN, which is also the loser's error
        when two consumers race two complaint creations against the
        same dispute.'

        However, PRD §3.13 boundary case states that when a dispute is
        both non-CLOSED_* and already has an open complaint, the
        precedence is ERR_NOT_ESCALATABLE (priority 16) over
        ERR_COMPLAINT_ALREADY_OPEN (priority 17). The race loser
        observes exactly this condition by the time its row check
        commits (the winner has already flipped the dispute to
        ESCALATED). Both readings are PRD-supported; we accept either."""
        from test_helpers import create_regulatory_complaint_payload
        c, f, r, t, d = setup_dispute_in_state(state="CLOSED_VERIFIED")
        payload_a = create_regulatory_complaint_payload(
            dispute_id=d["id"], narrative="A",
        )
        payload_b = create_regulatory_complaint_payload(
            dispute_id=d["id"], narrative="B",
        )
        results = run_race(
            lambda: api.create_regulatory_complaint(
                c["id"], payload_a, make_consumer_headers(c["id"]),
            ),
            lambda: api.create_regulatory_complaint(
                c["id"], payload_b, make_consumer_headers(c["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser,
            [
                ApiErrorId.ERR_COMPLAINT_ALREADY_OPEN.value,
                ApiErrorId.ERR_NOT_ESCALATABLE.value,
            ],
        )


# ===========================================================================
# OCC version check — PRD §2.6
# ===========================================================================
class TestOptimisticConcurrency:

    def test_stale_version_on_freeze_lift_rejected_with_invalid_state(self, api):
        """PRD §2.6: 'When the client includes version, the server
        compares it to the resource's current version; if the two do
        not match, the request is rejected with
        ERR_INVALID_STATE_TRANSITION because the resource has moved
        on since the client last read it.'

        Concrete vehicle: freeze placement returns version=1. Cause a
        version bump via a different mutation, then submit a lift with
        the stale version -> ERR_INVALID_STATE_TRANSITION."""
        from test_helpers import (
            create_consumer,
            get_consumer,
            lift_credit_freeze_payload,
        )
        c = create_consumer()
        # Place freeze; capture initial version.
        freeze_resp = api.create_credit_freeze(
            c["id"], {"bureau": "EQUIFAX"},
            make_consumer_headers(c["id"]),
        )
        freeze = freeze_resp.json()["data"]
        stale_version = freeze["version"]
        # Get current PIN.
        c_after = get_consumer(c["id"], headers=make_consumer_headers(c["id"]))
        pin = c_after["freeze_pin"]
        # Submit lift with deliberately stale version (one less than current).
        lift_body = {**lift_credit_freeze_payload(pin=pin),
                     "version": stale_version - 1}
        res = api.lift_credit_freeze(
            c["id"], freeze["id"], lift_body,
            make_consumer_headers(c["id"]),
        )
        # PRD §2.6 explicitly states ERR_INVALID_STATE_TRANSITION.
        from test_helpers import validate_error
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
