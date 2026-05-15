"""Program registration-window state machine driven by the test clock.

Covers PRD §2.10 (clock-advance sweeps, half-open registration interval),
§3.1 (window_status begins at SCHEDULED), §3.4 (submission requires
window_status == OPEN), and the application auto-withdraw on close.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BASE_CLOCK,
    advance_clock_iso,
    advance_clock_to,
    api_client,
    create_application,
    get_application,
    get_program,
    iso_utc,
    open_program_window,
    setup_district_with_school_and_program,
    setup_family_with_student,
    submit_application,
    validate_error,
    validate_success,
)


class TestWindowTransitions:

    def test_program_starts_scheduled_when_clock_before_open(self, api):
        """PRD §3.1: "its window_status begins at SCHEDULED".

        Claim: a program whose registration_open_at is in the future
        reports window_status == SCHEDULED.
        """
        district, school, program = setup_district_with_school_and_program()
        assert program["window_status"] == "SCHEDULED"

    def test_window_opens_at_exact_open_instant_inclusive(self, api):
        """PRD §3.5: SCHEDULED→OPEN is observed by the clock-advance
        sweep. The boundary is the registration_open_at instant —
        inclusive (left-inclusive half-open interval per scaffold §1.8
        rule 8 / PRD prose "Programs whose registration_open_at has
        been reached transition from SCHEDULED to OPEN").

        Claim: advancing the clock to exactly registration_open_at
        transitions the program to OPEN and submission becomes legal.
        """
        district, school, program = setup_district_with_school_and_program()
        # Advance to exact open instant.
        advance_clock_iso(program["registration_open_at"])
        prog = get_program(program["id"])
        assert prog["window_status"] == "OPEN", \
            "PRD §2.10: clock-advance sweep moves SCHEDULED→OPEN at registration_open_at"

    def test_submit_rejected_when_window_scheduled(self, api):
        """PRD §3.4: "Submission requires the program's window_status to
        be OPEN; outside of that window the request is rejected with
        ERR_REGISTRATION_WINDOW_CLOSED."

        Claim: submitting before the open instant yields
        ERR_REGISTRATION_WINDOW_CLOSED.
        """
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        from test_helpers import make_family_user_headers
        app = create_app(family, student, program, choice_rank=1)
        # Window is SCHEDULED — clock is at DEFAULT_BASE_CLOCK.
        res = api.submit_application(app["id"], make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED.value)

    def test_submit_rejected_when_window_closed(self, api):
        """PRD §3.4: "Submission requires the program's window_status
        to be OPEN; outside of that window the request is rejected with
        ERR_REGISTRATION_WINDOW_CLOSED."

        Claim: submitting after registration_close_at yields
        ERR_REGISTRATION_WINDOW_CLOSED.
        """
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        from test_helpers import make_family_user_headers
        app = create_app(family, student, program, choice_rank=1)
        # Advance past close.
        advance_clock_iso(program["registration_close_at"])
        prog = get_program(program["id"])
        assert prog["window_status"] == "CLOSED"
        res = api.submit_application(app["id"], make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED.value)

    def test_draft_auto_withdrawn_when_window_closes(self, api):
        """PRD §2.10: "any Application still in DRAFT under such a
        program is auto-transitioned to WITHDRAWN."

        Claim: a DRAFT application transitions to WITHDRAWN when the
        clock-advance sweep moves the program OPEN→CLOSED.
        """
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        from test_helpers import create_application as create_app
        app = create_app(family, student, program, choice_rank=1)
        assert app["status"] == "DRAFT"
        # Advance to after close — sweep should run.
        advance_clock_iso(program["registration_close_at"])
        app_after = get_application(app["id"])
        assert app_after["status"] == "WITHDRAWN", (
            "PRD §2.10: DRAFT applications auto-WITHDRAW when their "
            "program window closes"
        )
