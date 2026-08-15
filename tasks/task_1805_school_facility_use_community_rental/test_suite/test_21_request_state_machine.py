"""RentalRequest lifecycle corners: birth state, illegal approvals, terminal
lockdown, the revision-loop cap, and double-submit (PRD §3.4, §2.9)."""
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

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]

EVENT_START = "2026-12-01T01:00:00Z"
EVENT_END = "2026-12-01T03:00:00Z"


def _revision_cycle(api, env, request_id, new_headcount):
    """One UNDER_REVIEW -> REVISION_REQUESTED -> RESUBMITTED -> UNDER_REVIEW
    loop; returns the re-reviewed request row."""
    validate_success(api.request_revision(
        request_id, {"revision_note": "Please revise"}, COORDINATOR))
    org_id = env["org"]["id"]
    validate_success(api.resubmit_request(
        org_id, request_id, {"headcount_estimate": new_headcount},
        make_renter_headers(org_id)))
    return begin_review(request_id)


class TestRequestInitialState:
    def test_request_initial_state_is_draft(self, api):
        """PRD §3.4: "A new request is born in `DRAFT` with `revision_round` at 0
        and `submitted_at` still null."

        Design: Corner/state_machines/request_initial_state_is_draft
        """
        env = make_booking_env()
        req = make_draft_request(env, event_title="Draft Event", headcount_estimate=50,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        assert req["request_status"] == "DRAFT"
        assert req["revision_round"] == 0
        assert req["submitted_at"] is None


class TestInvalidTransitions:
    def test_approve_from_draft_returns_invalid_state(self, api):
        """PRD §2.9: "**Lifecycle state legality.** The target resource's current
        state must permit the operation — approval requires `UNDER_REVIEW`,
        permit cancellation requires `ISSUED`, terminal states reject all
        mutations — else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/approve_from_draft_returns_invalid_state
        """
        env = make_booking_env()
        req = make_draft_request(env, event_title="Draft Event", headcount_estimate=50,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        res = api.approve_request(
            req["id"], {"expected_request_version": req["version"]}, DIRECTOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        permits = validate_success(api.list_request_permits(req["id"], DIRECTOR))
        assert permits == [], "no Permit created by the rejected approval"

    def test_terminal_denied_request_rejects_all_mutations(self, api):
        """PRD §3.4: "Denial (`UNDER_REVIEW` → `DENIED`) requires the
        `FacilitiesDirector` to supply a `denial_reason_code` of `CAPACITY`,
        `CALENDAR_CONFLICT`, `INSURANCE`, `POLICY`, or `DISCRETIONARY`; the code
        is null on requests in every other status and `DENIED` is terminal."
        PRD §2.9: "**Lifecycle state legality.** The target resource's current
        state must permit the operation — approval requires `UNDER_REVIEW`,
        permit cancellation requires `ISSUED`, terminal states reject all
        mutations — else `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/terminal_denied_request_rejects_all_mutations
        """
        env = make_booking_env()
        req = make_draft_request(env, event_title="Doomed Event", headcount_estimate=50,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        submit_request(env, req["id"])
        reviewed = begin_review(req["id"])
        denied = validate_success(api.deny_request(
            req["id"], {"denial_reason_code": "DISCRETIONARY"}, DIRECTOR))
        assert denied["request_status"] == "DENIED"
        assert denied["denial_reason_code"] == "DISCRETIONARY"

        org_id = env["org"]["id"]
        current = validate_success(api.get_request(req["id"], DIRECTOR))
        attempts = [
            api.submit_request(org_id, req["id"], make_renter_headers(org_id)),
            api.begin_review(req["id"], COORDINATOR),
            api.approve_request(req["id"],
                                {"expected_request_version": current["version"]},
                                DIRECTOR),
            api.request_revision(req["id"], {"revision_note": "try again"},
                                 COORDINATOR),
            api.withdraw_request(org_id, req["id"], make_renter_headers(org_id)),
        ]
        for res in attempts:
            validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "DENIED", "DENIED is terminal"


class TestRevisionLoopCap:
    def test_revision_limit_exceeded_on_fourth_cycle(self, api):
        """PRD §3.4: "The cycle `UNDER_REVIEW` → `REVISION_REQUESTED` →
        `RESUBMITTED` → `UNDER_REVIEW` may repeat at most three times; a revision
        request when `revision_round` is already 3 is rejected with
        `ERR_REVISION_LIMIT_EXCEEDED`, and at that point the only remaining
        outcomes are approval or denial."

        Design: Corner/state_machines/revision_limit_exceeded_on_fourth_cycle
        """
        env = make_booking_env()
        req = make_draft_request(env, event_title="Looping Event",
                                 headcount_estimate=50,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        submit_request(env, req["id"])
        begin_review(req["id"])
        current = None
        for round_no, headcount in enumerate((49, 48, 47), start=1):
            current = _revision_cycle(api, env, req["id"], headcount)
            assert current["revision_round"] == round_no

        res = api.request_revision(req["id"], {"revision_note": "round 4 attempt"},
                                   COORDINATOR)
        validate_error(res, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED)
        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "UNDER_REVIEW"
        assert after["revision_round"] == 3


class TestDoubleSubmit:
    def test_idempotent_double_submit_rejected(self, api):
        """PRD §3.4: "The first successful submission stamps `submitted_at` from
        the logical clock, and that stamp is the canonical conflict-ordering key
        for the life of the request — later resubmissions never refresh it."
        PRD §3.4: "Submission (`DRAFT` → `SUBMITTED`) is the moment a draft
        becomes a claim on the calendar, and it is gated: the organization must
        be in `GOOD_STANDING` (else `ERR_RENTER_NOT_IN_GOOD_STANDING`); the
        `headcount_estimate` must not exceed the facility's `capacity` (else
        `ERR_CAPACITY_EXCEEDED`); the `starts_at` must lie strictly after the
        logical clock's current instant — no past-dated submissions; and the
        window must satisfy the temporal rules, `ends_at` strictly after
        `starts_at` and the total duration at most twelve hours (else
        `ERR_INVALID_TIME_WINDOW`)."

        Design: Corner/state_machines/idempotent_double_submit_rejected
        """
        env = make_booking_env()
        set_clock("2026-08-10T00:00:00Z")
        req = make_draft_request(env, event_title="Double Submit",
                                 headcount_estimate=50,
                                 starts_at=EVENT_START, ends_at=EVENT_END)
        submitted = submit_request(env, req["id"])
        assert submitted["submitted_at"].startswith("2026-08-10T00:00:00")

        res = api.submit_request(env["org"]["id"], req["id"],
                                 make_renter_headers(env["org"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_request(req["id"], DIRECTOR))
        assert after["request_status"] == "SUBMITTED"
        assert after["submitted_at"].startswith("2026-08-10T00:00:00"), (
            "the rejected second submit does not refresh submitted_at")
