"""Booking lifecycle: the re-quote self-loop, optimistic-concurrency on booking,
rescheduling, and invalid transitions out of terminal / wrong states."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, same_instant,
    create_config, create_draft_job, request_quote, read_job_version,
    create_booked_job, book_payload, reschedule_payload, complete_payload,
    make_customer_headers, ADMIN, DISPATCHER, api_client,
)

WEEKDAY_START = "2026-03-11T09:00:00Z"
WEEKDAY_END = "2026-03-11T12:00:00Z"


class TestReQuoteSelfLoop:
    """Design: Difficulty/non_linear_state_machine/job_requote_self_loop"""

    def test_requote_supersedes_prior_active_quote(self, api):
        """PRD §3.3: "Requesting a quote again while the job is `QUOTED` is a permitted
        self-loop: the job's current `ACTIVE` quote transitions `ACTIVE → SUPERSEDED`, a
        fresh `ACTIVE` quote is created, and `version` is incremented again."

        Design: Difficulty/non_linear_state_machine/job_requote_self_loop
        """
        rate_card, policy, customer = create_config(api)
        job = create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                               crew_size=2, estimated_hours=2.0,
                               window_start=WEEKDAY_START, window_end=WEEKDAY_END)
        q1 = request_quote(api, job["id"], customer["id"])
        q2 = request_quote(api, job["id"], customer["id"])
        q1_state = validate_success(api.get_quote(q1["id"], ADMIN))
        q2_state = validate_success(api.get_quote(q2["id"], ADMIN))
        assert q1_state["status"] == "SUPERSEDED"
        assert q2_state["status"] == "ACTIVE"

    def test_requote_keeps_job_quoted_and_increments_version(self, api):
        """PRD §3.3: "Requesting a quote again while the job is `QUOTED` is a permitted
        self-loop: the job's current `ACTIVE` quote transitions `ACTIVE → SUPERSEDED`, a
        fresh `ACTIVE` quote is created, and `version` is incremented again."

        The re-quote is a self-loop back to QUOTED; version advances by one per the mutation.

        Design: Difficulty/non_linear_state_machine/job_requote_self_loop
        """
        rate_card, policy, customer = create_config(api)
        job = create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                               crew_size=2, estimated_hours=2.0,
                               window_start=WEEKDAY_START, window_end=WEEKDAY_END)
        request_quote(api, job["id"], customer["id"])
        version_after_first = read_job_version(api, job["id"], customer["id"])
        request_quote(api, job["id"], customer["id"])
        after = validate_success(api.get_job(job["id"], make_customer_headers(customer["id"])))
        assert after["status"] == "QUOTED"
        assert after["version"] == version_after_first + 1


def test_book_with_stale_version_after_requote_rejected(api):
    """PRD §2.6: "If they do not match — for instance because another writer re-quoted the
    job after the client read it, which supersedes the previously `ACTIVE` quote and
    advances `version` — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/book_stale_job_version_conflict
    """
    rate_card, policy, customer = create_config(api)
    job = create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                           crew_size=1, estimated_hours=3.0,
                           window_start=WEEKDAY_START, window_end=WEEKDAY_END)
    request_quote(api, job["id"], customer["id"])
    stale_version = read_job_version(api, job["id"], customer["id"])
    q2 = request_quote(api, job["id"], customer["id"])  # supersedes q1, bumps version
    resp = api.book_job(job["id"], book_payload(q2["id"], stale_version),
                        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api.get_job(job["id"], make_customer_headers(customer["id"])))
    assert after["status"] == "QUOTED"


def test_reschedule_booked_job_updates_window_and_versions(api):
    """PRD §3.4: "On success the job's `window_start` and `window_end` are updated and its
    `version` is incremented by one."

    Design: Corner/state_machines/reschedule_updates_window
    """
    rate_card, policy, customer = create_config(api)
    booked, _quote = create_booked_job(api, rate_card["id"], policy["id"], customer["id"],
                                       crew_size=1, estimated_hours=3.0,
                                       window_start=WEEKDAY_START, window_end=WEEKDAY_END)
    resp = api.reschedule_job(
        booked["id"], reschedule_payload("2026-03-15T09:00:00Z", "2026-03-15T12:00:00Z"),
        make_customer_headers(customer["id"]),
    )
    updated = validate_success(resp)
    assert updated["status"] == "BOOKED"
    assert same_instant(updated["window_start"], "2026-03-15T09:00:00Z")
    assert same_instant(updated["window_end"], "2026-03-15T12:00:00Z")
    assert updated["version"] == booked["version"] + 1


def test_cancel_already_cancelled_job_rejected(api):
    """PRD §3.2 / §2.8: "For a state-transition operation, the target resource's current
    state is checked; an operation attempted from an ineligible state yields
    `ERR_INVALID_STATE` (409)."

    A second cancel on a CANCELLED (terminal) job is rejected and the job stays CANCELLED.

    Design: Corner/state_machines/cancel_a_cancelled_job_returns_invalid_state
    """
    rate_card, policy, customer = create_config(api)
    job = create_draft_job(api, rate_card["id"], policy["id"], customer["id"],
                           crew_size=1, estimated_hours=2.0,
                           window_start=WEEKDAY_START, window_end=WEEKDAY_END)
    request_quote(api, job["id"], customer["id"])
    validate_success(api.cancel_job(job["id"], make_customer_headers(customer["id"])))
    resp = api.cancel_job(job["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_job(job["id"], make_customer_headers(customer["id"])))
    assert after["status"] == "CANCELLED"


def test_complete_booked_job_without_start_rejected(api):
    """PRD §3.6: "When the work is done, the dispatcher completes the `IN_PROGRESS` job,
    transitioning it `IN_PROGRESS → COMPLETED`." PRD §2.8: "an operation attempted from an
    ineligible state yields `ERR_INVALID_STATE` (409)."

    Completing a BOOKED (never started) job is rejected.

    Design: Corner/state_machines/complete_without_start_returns_invalid_state
    """
    rate_card, policy, customer = create_config(api)
    booked, _quote = create_booked_job(api, rate_card["id"], policy["id"], customer["id"],
                                       crew_size=1, estimated_hours=2.0,
                                       window_start=WEEKDAY_START, window_end=WEEKDAY_END)
    resp = api.complete_job(booked["id"], complete_payload(2.0), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
