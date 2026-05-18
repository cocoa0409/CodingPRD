"""PRD §3.3 (furnisher reverification + sweep), §2.9 (reage).

Covers:
- furnisher_response transitions UNDER_INVESTIGATION -> RESULTS_PENDING.
- Boundary at reverification_deadline_day: inclusive operator success at
  day == deadline; ERR_FURNISHER_LATE at day == deadline + 1.
- Reage prohibition at furnisher_response with new_dofd_day > current
  reported_dofd_day -> ERR_REAGE_PROHIBITED.
- Sweep flips PENDING -> NO_RESPONSE when deadline strictly passed.
- ERR_DISPUTE_DEADLINE_PASSED when clock.day past dispute deadline.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FURNISHER_REVERIFY_WINDOW_DAYS,
    TEST_USERS,
    advance_clock,
    furnisher_response_payload,
    get_dispute,
    make_consumer_headers,
    read_clock_day,
    record_furnisher_response,
    run_sweep,
    setup_dispute_in_state,
    submit_additional_info,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy path — PRD §3.3
# ===========================================================================
class TestFurnisherResponseHappyPath:

    def test_verified_response_transitions_to_results_pending(self, api):
        """PRD §3.3: 'On acceptance, the system records the supplied
        response on the inquiry, stamps response_day with the current
        clock day, stores the response_payload, and advances the
        dispute from UNDER_INVESTIGATION to RESULTS_PENDING.'"""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        d2 = record_furnisher_response(
            consumer_id=c["id"], dispute_id=d["id"],
            response="VERIFIED", response_payload={},
        )
        assert d2["status"] == "RESULTS_PENDING"


# ===========================================================================
# Boundary at reverification_deadline_day — PRD §3.3
# ===========================================================================
class TestFurnisherDeadlineBoundary:

    def test_response_on_deadline_day_inclusive_succeeds(self, api):
        """PRD §3.3: 'if the operator request reaches the server when
        clock.day is still less than or equal to
        reverification_deadline_day, the operator wins and the inquiry
        records the real response'.

        Boundary at clock.day == forwarded_day + 25. The operator
        response on day 25 must succeed."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        forwarded_day = d["submitted_day"]
        delta = (forwarded_day + FURNISHER_REVERIFY_WINDOW_DAYS) - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(response="VERIFIED", response_payload={}),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_success(res, 200)

    def test_response_after_deadline_day_rejected(self, api):
        """PRD §3.3: 'otherwise the sweep's NO_RESPONSE stands and
        the late operator request is rejected with ERR_FURNISHER_LATE.'

        And PRD §3.3 (precondition): 'if the current clock day is
        strictly greater than the inquiry's reverification_deadline_day
        (ERR_FURNISHER_LATE — the deadline is inclusive of the
        operator response on the deadline day itself)'.

        Boundary +1: clock.day == forwarded_day + 26. The operator
        response must fail with ERR_FURNISHER_LATE."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        forwarded_day = d["submitted_day"]
        # Advance to forwarded_day + 26 (one past boundary).
        target = forwarded_day + FURNISHER_REVERIFY_WINDOW_DAYS + 1
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(response="VERIFIED", response_payload={}),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FURNISHER_LATE)


# ===========================================================================
# Reage prohibition at furnisher_response — PRD §2.9, §3.3
# ===========================================================================
class TestReageAtFurnisherResponse:

    def test_new_dofd_later_than_current_reported_rejected(self, api):
        """PRD §3.3: 'The reage prohibition also fires here: if the
        furnisher's response_payload carries a new_dofd_day strictly
        greater than the tradeline's current reported_dofd_day, the
        request is rejected with ERR_REAGE_PROHIBITED.'

        Tradeline's original_dofd_day=100 -> reported_dofd_day=100.
        A furnisher_response with new_dofd_day=200 must be rejected."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        assert t["reported_dofd_day"] == 100
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(
                response="UPDATED",
                response_payload={"new_dofd_day": 200},
            ),
            TEST_USERS["bureau_operator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_REAGE_PROHIBITED)


# ===========================================================================
# Sweep semantics — PRD §3.3, §2.11
# ===========================================================================
class TestSweepSemantics:

    def test_sweep_flips_pending_to_no_response_when_deadline_strictly_passed(
        self, api,
    ):
        """PRD §2.11: 'walks every FurnisherInquiry whose response is
        still PENDING and whose reverification_deadline_day is strictly
        less than the current clock day; for each such inquiry, the
        response is set to NO_RESPONSE and the parent Dispute advances
        to RESULTS_PENDING along the system-driven arm of its state
        machine.'

        At clock.day = reverification_deadline_day + 1 (strictly less
        than not satisfied by deadline itself — must be strictly less
        than clock.day), sweep flips PENDING -> NO_RESPONSE and
        Dispute -> RESULTS_PENDING."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        forwarded_day = d["submitted_day"]
        # Advance past the strictly-less-than threshold.
        target = forwarded_day + FURNISHER_REVERIFY_WINDOW_DAYS + 1
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        run_sweep()
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        assert d_after["status"] == "RESULTS_PENDING"

    def test_clock_advance_alone_does_not_run_sweep(self, api):
        """PRD §2.11: 'The clock-advance capability never runs the
        sweep implicitly — clock advancement and sweep execution are
        two distinct test-driving operations.'

        Advancing past the deadline without invoking sweep must
        leave the dispute UNDER_INVESTIGATION (no system arm fires)."""
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        forwarded_day = d["submitted_day"]
        target = forwarded_day + FURNISHER_REVERIFY_WINDOW_DAYS + 5
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        d_after = get_dispute(consumer_id=c["id"], dispute_id=d["id"])
        # PRD §2.11: clock-advance does not fire deadlines.
        assert d_after["status"] == "UNDER_INVESTIGATION"


# ===========================================================================
# Dispute deadline gate on furnisher_response — PRD §3.3
# ===========================================================================
class TestDisputeDeadlineAtFurnisherResponse:

    def test_furnisher_response_after_dispute_deadline_rejected(self, api):
        """PRD §3.3: 'if the current clock day is past the dispute's
        deadline_day (ERR_DISPUTE_DEADLINE_PASSED)'.

        Note: PRD §3.13 lists ERR_DISPUTE_DEADLINE_PASSED at priority
        9 and ERR_FURNISHER_LATE at priority 10 — so when both fire,
        dispute-deadline should win. We isolate by extending the
        dispute deadline to 45 days but keeping the furnisher window
        at 25; we then advance past day 45 but past 25 as well, so
        only the dispute-deadline gate is what the test asserts."""
        # Use a fresh dispute we extend to deadline_day = submitted_day + 45.
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        # Extend to +45.
        d2 = submit_additional_info(consumer=c, dispute_id=d["id"])
        assert d2["deadline_day"] == d["submitted_day"] + 45
        # Advance to deadline_day + 1.
        target = d2["deadline_day"] + 1
        delta = target - read_clock_day()
        if delta > 0:
            advance_clock(delta)
        res = api.record_furnisher_response(
            c["id"], d["id"],
            furnisher_response_payload(response="VERIFIED", response_payload={}),
            TEST_USERS["bureau_operator_headers"],
        )
        # Both ERR_DISPUTE_DEADLINE_PASSED (priority 9) and
        # ERR_FURNISHER_LATE (priority 10) match; per PRD §3.13 the
        # higher-priority check wins.
        validate_error(res, ApiErrorId.ERR_DISPUTE_DEADLINE_PASSED)
