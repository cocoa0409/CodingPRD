"""Shift scheduling and voiding.

Covers PRD §3.2 — Scheduling, Punching, and Closing a Shift (the
scheduling and void parts; punches are in test_04).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_shift,
    clock_set,
    create_employee,
    create_shift,
    create_shift_payload,
    make_employee_headers,
    post_punch,
    setup_open_shift,
    TEST_DEFAULTS,
    validate_error,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Schedule a shift — PRD §3.2
# ===========================================================================
class TestSchedule:

    def test_create_shift_in_scheduled_state(self, api, supervisor_headers):
        """PRD §3.2: "A newly scheduled shift enters initial state
        `SCHEDULED`".
        """
        emp = create_employee()
        resp = api.create_shift(
            create_shift_payload(emp["id"]), supervisor_headers,
        )
        shift = validate_success(resp, expected_status=201)
        assert_shift(shift)
        assert shift["state"] == "SCHEDULED"
        assert shift["actual_start"] is None
        assert shift["actual_end"] is None

    def test_create_shift_for_exempt_employee_rejected(
        self, api, supervisor_headers,
    ):
        """PRD §3.2: "A shift created for an employee whose
        `classification` is `EXEMPT` is rejected with
        `ERR_EXEMPT_NOT_ELIGIBLE` and HTTP status 422".
        """
        emp = create_employee(classification="EXEMPT")
        resp = api.create_shift(
            create_shift_payload(emp["id"]), supervisor_headers,
        )
        validate_error(resp, "ERR_EXEMPT_NOT_ELIGIBLE")


# ===========================================================================
# Void a shift — PRD §3.2
# ===========================================================================
class TestVoid:

    def test_void_scheduled_shift_with_no_punches(
        self, api, supervisor_headers,
    ):
        """PRD §3.2: "A supervisor or payroll administrator may void a
        shift while it is still in `SCHEDULED` and no punch has yet
        been recorded against it, transitioning it to terminal state
        `VOIDED`".
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        resp = api.delete_shift(shift["id"], supervisor_headers)
        assert resp.status_code == 204, (
            f"PRD §4: DELETE /timekeeping/shifts/{{id}} returns 204; "
            f"got {resp.status_code}"
        )
        # Confirm the shift is now VOIDED.
        get_resp = api.get_shift(shift["id"],
                                 supervisor_headers)
        voided = validate_success(get_resp, expected_status=200)
        assert voided["state"] == "VOIDED"

    def test_void_shift_with_existing_punch_rejected(
        self, api, supervisor_headers,
    ):
        """PRD §3.2: "an attempt to void a shift in any other state, or
        one against which punches already exist, is rejected with
        `ERR_SHIFT_INVALID_STATE`."
        """
        emp, shift, in_punch = setup_open_shift()
        resp = api.delete_shift(shift["id"], supervisor_headers)
        validate_error(resp, "ERR_SHIFT_INVALID_STATE")

    def test_void_already_voided_shift_rejected(
        self, api, supervisor_headers,
    ):
        """PRD §3.2: "an attempt to void a shift in any other state ...
        is rejected with `ERR_SHIFT_INVALID_STATE`."

        Claim: re-voiding a VOIDED shift → ERR_SHIFT_INVALID_STATE.
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        # First void.
        first = api.delete_shift(shift["id"], supervisor_headers)
        assert first.status_code == 204
        # Second void.
        resp = api.delete_shift(shift["id"], supervisor_headers)
        validate_error(resp, "ERR_SHIFT_INVALID_STATE")


# ===========================================================================
# Read / list — PRD §3.2
# ===========================================================================
class TestRead:

    def test_get_shift_returns_computed_fields(
        self, api, payroll_admin_headers,
    ):
        """PRD §3.2: "The shift carries computed columns that the system
        fills as punches arrive: `actual_start` is stamped when the
        first `IN` punch lands ... `requires_meal_break` is derived
        true when the expected worked hours exceed 5.0 ...
        `meal_break_premium_owed_cents` carries the premium owed ...
        `detention_minutes` carries the minutes the actual end ran
        past the scheduled end".
        """
        emp = create_employee()
        shift = create_shift(emp["id"])
        resp = api.get_shift(shift["id"], payroll_admin_headers)
        retrieved = validate_success(resp, expected_status=200)
        # All computed fields must be present on a Shift response, even
        # on a SCHEDULED shift (their values may be defaults).
        assert "requires_meal_break" in retrieved
        assert "meal_break_premium_owed_cents" in retrieved
        assert "detention_minutes" in retrieved
        assert "state" in retrieved
