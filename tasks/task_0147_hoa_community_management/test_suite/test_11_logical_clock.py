"""Logical clock — PRD §3.10 and §2.4.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    clock_advance_payload,
    current_clock,
    iso_utc,
    parse_iso,
    TEST_USERS,
    utcnow,
    validate_error,
    validate_success,
)


class TestClockAdvance:

    def test_president_advances_clock_returns_new_now(self, api):
        """PRD §3.10: "On a successful advance, the server returns the
        new clock value".

        Claim: POST /hoa/_clock/advance by PresidentRole with a target
        in the future succeeds.
        """
        target = utcnow() + timedelta(days=1)
        resp = api.advance_clock(
            clock_advance_payload(iso_utc(target)),
            TEST_USERS["president_role_headers"],
        )
        validate_success(resp, expected_status=200)

    def test_backward_clock_move_returns_time_travel(self, api):
        """PRD §3.10: "the timestamp MUST be strictly greater than or
        equal to the current clock; a backward move is rejected with
        ERR_TIME_TRAVEL."

        Claim: a target_timestamp clearly in the past returns
        ERR_TIME_TRAVEL.
        """
        # First, push the clock forward so we have known wiggle room.
        forward = utcnow() + timedelta(days=10)
        api.advance_clock(
            clock_advance_payload(iso_utc(forward)),
            TEST_USERS["president_role_headers"],
        )
        # Now try to step backward.
        backward = utcnow() - timedelta(days=365)
        resp = api.advance_clock(
            clock_advance_payload(iso_utc(backward)),
            TEST_USERS["president_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TIME_TRAVEL.value)
