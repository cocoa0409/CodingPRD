"""Rental request revision cycle: loop counting and submission seniority
(PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_renter_headers,
    make_booking_env, make_draft_request, submit_request, begin_review,
    set_clock,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

COORDINATOR = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]

EVENT_START = "2026-11-14T01:00:00Z"
EVENT_END = "2026-11-14T05:00:00Z"


def _revision_cycle(api, env, request_id, new_headcount):
    """One UNDER_REVIEW -> REVISION_REQUESTED -> RESUBMITTED -> UNDER_REVIEW loop."""
    validate_success(api.request_revision(
        request_id, {"revision_note": "Reduce headcount or provide crowd plan"},
        COORDINATOR))
    org_id = env["org"]["id"]
    validate_success(api.resubmit_request(
        org_id, request_id, {"headcount_estimate": new_headcount},
        make_renter_headers(org_id)))
    return begin_review(request_id)


class TestRevisionCycleSeniorityPreserved:
    def _setup(self, api):
        env = make_booking_env()
        set_clock("2026-08-10T00:00:00Z")
        req = make_draft_request(
            env, event_title="Fall Carnival", headcount_estimate=200,
            starts_at=EVENT_START, ends_at=EVENT_END)
        submit_request(env, req["id"])
        begin_review(req["id"])
        return env, req

    def test_two_revision_cycles_preserve_seniority(self, api):
        """PRD §3.4: "The renter answers by resubmitting (`REVISION_REQUESTED` →
        `RESUBMITTED`) with any of `headcount_estimate`, `starts_at`, `ends_at`, or
        `event_title` revised — the revised headcount is re-checked against capacity
        — and resubmission increments `revision_round` by one while leaving
        `submitted_at` untouched, preserving the original seniority."

        Design: Difficulty/non_linear_state_machine/rental_request_revision_cycle_seniority_preserved
        """
        env, req = self._setup(api)
        _revision_cycle(api, env, req["id"], 150)
        current = _revision_cycle(api, env, req["id"], 120)

        current = validate_success(api.get_request(req["id"], DIRECTOR))
        assert current["request_status"] == "UNDER_REVIEW"
        # revision_round increments on resubmission only, not on request_revision
        assert current["revision_round"] == 2
        # submitted_at stamps the FIRST submit (clock was 2026-08-10T00:00:00Z)
        # and resubmissions never refresh it
        assert current["submitted_at"].startswith("2026-08-10T00:00:00")
        assert current["headcount_estimate"] == 120

    def test_third_cycle_legal_fourth_revision_rejected(self, api):
        """PRD §3.4: "The cycle `UNDER_REVIEW` → `REVISION_REQUESTED` →
        `RESUBMITTED` → `UNDER_REVIEW` may repeat at most three times; a revision
        request when `revision_round` is already 3 is rejected with
        `ERR_REVISION_LIMIT_EXCEEDED`, and at that point the only remaining
        outcomes are approval or denial."

        Design: Difficulty/non_linear_state_machine/rental_request_revision_cycle_seniority_preserved
        """
        env, req = self._setup(api)
        current = _revision_cycle(api, env, req["id"], 150)
        current = _revision_cycle(api, env, req["id"], 120)
        current = _revision_cycle(api, env, req["id"], 100)
        assert current["request_status"] == "UNDER_REVIEW"
        assert current["revision_round"] == 3

        res = api.request_revision(
            req["id"], {"revision_note": "round 4 attempt"}, COORDINATOR)
        validate_error(res, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED)

        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "UNDER_REVIEW"
        assert after["revision_round"] == 3
