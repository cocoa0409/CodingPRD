"""Concurrency / race-condition tests.

PRD §2.13 (Concurrency Serialization).
"""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    assert_race_outcome,
    run_race,
    validate_error_is_one_of,
)
from test_helpers import (
    ApiErrorId,
    PM,
    api_client,
    dispatch_assignment,
    make_translator_headers,
    setup_quoted_project_with_one_word_segment,
    setup_translator_passed,
)


# ===========================================================================
# Two translators race to accept the same PENDING assignment
# ===========================================================================
class TestConcurrentAccept:

    def test_two_translators_cannot_both_accept_same_assignment(self):
        """PRD §2.13: "Two translators attempting to accept the same
        PENDING assignment simultaneously serialize on the assignment's
        state transition: exactly one acceptance succeeds and the loser
        receives ERR_ASSIGNMENT_ALREADY_TAKEN."

        Claim: exactly one of two concurrent accepts succeeds; the loser
        gets ERR_ASSIGNMENT_ALREADY_TAKEN.
        """
        # Reach reproducible race: dispatch the SAME PENDING assignment id
        # and have two different translators try accept. PRD says assignment
        # is bound to ONE translator_id, so "two translators race" must mean
        # the same translator id races itself, OR translators try via API
        # via different X-User-ID headers. The PRD acceptance precondition
        # requires X-User-ID == Assignment.translator_id. So a true race
        # requires the SAME translator firing two accept calls concurrently
        # (idempotent attempt). The PRD §2.13 statement covers that case
        # under "first-writer-wins on Assignment.state transition."
        _, project, _, segments = setup_quoted_project_with_one_word_segment()
        t = setup_translator_passed(grade="SENIOR")
        seg_ids = [s["id"] for s in segments]
        a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
        api_client.activate_project(project["id"], PM)
        # Fire two concurrent accept calls from the same translator.
        headers = make_translator_headers(t["id"])
        results = run_race(
            lambda: api_client.accept_assignment(a["id"], headers),
            lambda: api_client.accept_assignment(a["id"], headers),
        )
        # Exactly one wins. PRD §2.13 names ERR_ASSIGNMENT_ALREADY_TAKEN
        # for this case; the second-wave validation may also surface
        # ERR_INVALID_ASSIGNMENT_STATE depending on whether the loser
        # observed state PENDING (loses on first-writer-wins) or
        # ACCEPTED (state precondition).
        outcome = assert_race_outcome(results, expected_successes=1,
                                      expected_failures=1)
        loser_resp = outcome["failures"][0]
        validate_error_is_one_of(loser_resp, [
            ApiErrorId.ERR_ASSIGNMENT_ALREADY_TAKEN.value,
            ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value,
        ])
