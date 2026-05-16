"""Session lifecycle: DRAFT, OPEN, CLOSED, CANCELLED.

Tests cover PRD §3.3 (session create + open + cancel + close) and the
side effects of each transition. The Session.OPEN→CLOSED transition is
gated on the clock and tested in test_10_cascades_and_clock.py.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_session,
    create_session,
    create_session_payload,
    iso_date,
    iso_offset,
    iso_utc,
    next_monday,
    open_session,
    parse_iso,
    setup_open_session,
    validate_error,
    validate_success,
)
from datetime import timedelta


# ===========================================================================
# Session creation + DRAFT state
# ===========================================================================
class TestSessionCreation:
    def test_create_session_starts_in_draft(self, api):
        """PRD §3.3: "A ProgramAdmin creates a session in DRAFT state."
        PRD §3.3: "The new session starts at status DRAFT."

        Claim: POST /camp/sessions returns 201 + Session with
        status=="DRAFT".
        """
        payload = create_session_payload()
        res = api.create_session(payload, TEST_USERS["admin_headers"])
        session = validate_success(res, 201)
        assert_session(session)
        assert session["status"] == "DRAFT"

    def test_age_min_above_age_max_rejected(self, api):
        """PRD §3.3: "both values lie between 3 and 17 and age_min is
        at most age_max" (intake constraint, ERR_VALIDATION per §2.9).

        Claim: a session payload with age_min > age_max is rejected.
        """
        payload = create_session_payload(age_min=12, age_max=5)
        res = api.create_session(payload, TEST_USERS["admin_headers"])
        assert res.status_code >= 400

    def test_rainy_day_pool_above_capacity_rejected(self, api):
        """PRD §3.3: "a rainy_day_pool_per_week of indoor backup
        seats reserved for weather reroutes that must lie between 0
        and weekly_capacity inclusive."

        Claim: rainy_day_pool_per_week > weekly_capacity is rejected.
        """
        payload = create_session_payload(
            weekly_capacity=5, rainy_day_pool_per_week=10,
        )
        res = api.create_session(payload, TEST_USERS["admin_headers"])
        assert res.status_code >= 400


# ===========================================================================
# DRAFT → OPEN transition + SessionDay materialization
# ===========================================================================
class TestSessionOpen:
    def test_open_session_transitions_to_open(self, api):
        """PRD §3.3: "The admin opens it via a session-open action
        that transitions DRAFT → OPEN."
        PRD §3.3: "The session's status is set to OPEN."

        Claim: POST /camp/sessions/{id}/open returns 200 + Session
        with status=="OPEN".
        """
        session = create_session()
        res = api.open_session(session["id"], TEST_USERS["admin_headers"])
        opened = validate_success(res, 200)
        assert opened["status"] == "OPEN"

    def test_open_already_open_session_rejected(self, api):
        """PRD §2.12 + PRD §3.3 state machine: opening an already-OPEN
        session is not legal.

        PRD §2.9: "After the safety checks, state-machine legality
        (ERR_INVALID_STATE) is evaluated before domain constraints."

        Claim: a second open call on an OPEN session returns
        ERR_INVALID_STATE.
        """
        session = setup_open_session()
        res = api.open_session(session["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Cancellation from DRAFT and OPEN
# ===========================================================================
class TestSessionCancel:
    def test_cancel_draft_session_succeeds_no_preconditions(self, api):
        """PRD §3.3: "A ProgramAdmin can also cancel a session. From
        DRAFT, cancellation has no preconditions and simply sets
        status to CANCELLED."

        Claim: POST /camp/sessions/{id}/cancel on a DRAFT session
        returns 200 + status==CANCELLED.
        """
        session = create_session()
        res = api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_open_session_succeeds(self, api):
        """PRD §3.3: "From OPEN, cancellation requires that the
        session currently be OPEN and cascades."

        Claim: POST /camp/sessions/{id}/cancel on an OPEN session
        returns 200 + status==CANCELLED.
        """
        session = setup_open_session()
        res = api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_cancelled_session_rejected(self, api):
        """PRD §3.3: "Cancellation from any state other than DRAFT or
        OPEN is rejected as ERR_INVALID_STATE."

        Claim: a second cancel on an already-CANCELLED session returns
        ERR_INVALID_STATE.
        """
        session = create_session()
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        res = api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Terminal-state lockdown
# ===========================================================================
class TestSessionTerminalLockdown:
    def test_open_cancelled_session_rejected(self, api):
        """PRD §3.3: "Both CLOSED and CANCELLED are terminal for a
        session — no further state change is permitted, and any
        attempt yields ERR_INVALID_STATE."

        Claim: opening a CANCELLED session returns ERR_INVALID_STATE.
        """
        session = create_session()
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        res = api.open_session(session["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_INVALID_STATE")

    def test_cancel_cancelled_returns_invalid_state(self, api):
        """PRD §3.3: "Both CLOSED and CANCELLED are terminal for a
        session — no further state change is permitted, and any
        attempt yields ERR_INVALID_STATE."

        Claim: re-cancelling a CANCELLED session returns
        ERR_INVALID_STATE.
        """
        session = create_session()
        api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        res = api.cancel_session(session["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Session close gated by clock — preconditions
# ===========================================================================
class TestSessionClose:
    def test_close_before_weeks_elapsed_rejected(self, api):
        """PRD §3.3: "The single precondition is that every week of
        the session has reached week_start plus seven calendar days
        on the logical clock — i.e., every enrollable week has fully
        elapsed."

        Claim: closing an OPEN session whose week_start is still in
        the future returns ERR_INVALID_STATE.
        """
        # week_start defaults to next Monday — clearly not yet elapsed.
        session = setup_open_session()
        res = api.close_session(session["id"], TEST_USERS["admin_headers"])
        validate_error(res, "ERR_INVALID_STATE")
