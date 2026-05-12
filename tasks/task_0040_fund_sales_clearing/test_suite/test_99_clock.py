"""PRD §2.12: The authoritative server clock -- monotonic advancement."""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_payload,
    advance_clock_to,
    assert_clock,
    get_current_clock,
    parse_iso,
    validate_error,
    validate_success,
)


class TestClockMonotonic:
    def test_advance_to_strictly_later_succeeds(self, api):
        """PRD §2.12: "the system exposes an admin-only test-driving
        capability that advances the authoritative server clock to a
        supplied `now` ISO 8601 timestamp; the clock is monotonic."

        Claim: advancing to a strictly later timestamp succeeds and the
        Clock.now field reflects the new value.
        """
        first = "2030-01-01T00:00:00.000Z"
        res = api.advance_clock(
            advance_clock_payload(first),
            TEST_USERS["platform_admin_headers"],
        )
        clock = validate_success(res)
        assert_clock(clock)
        assert clock["now"] == first

        second = "2030-01-02T00:00:00.000Z"
        res2 = api.advance_clock(
            advance_clock_payload(second),
            TEST_USERS["platform_admin_headers"],
        )
        clock2 = validate_success(res2)
        assert clock2["now"] == second

    def test_advance_to_earlier_rejected(self, api):
        """PRD §2.12: "An advance call with a `now` value at or before the
        current clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`
        (HTTP 422)."

        Claim: advancing to a timestamp strictly earlier than current
        Clock.now is rejected with ERR_CLOCK_NOT_MONOTONIC.
        """
        advance_clock_to("2030-06-01T12:00:00.000Z")
        res = api.advance_clock(
            advance_clock_payload("2030-05-31T00:00:00.000Z"),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_CLOCK_NOT_MONOTONIC")

    def test_advance_to_equal_rejected(self, api):
        """PRD §2.12: "An advance call with a `now` value at or before the
        current clock value is rejected with `ERR_CLOCK_NOT_MONOTONIC`
        (HTTP 422)."

        Claim: an advance call equal to current Clock.now (the boundary
        case) is rejected.
        """
        advance_clock_to("2031-01-01T00:00:00.000Z")
        cur = get_current_clock()
        res = api.advance_clock(
            advance_clock_payload(cur),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, "ERR_CLOCK_NOT_MONOTONIC")

    def test_get_clock_returns_singleton(self, api):
        """PRD §2.4: "The `Clock` resource has the fixed `id` `"clock"` and
        the single field `now`."

        Claim: GET /_clock returns a body whose id is exactly "clock" and
        whose now is an ISO 8601 timestamp.
        """
        res = api.get_clock(TEST_USERS["platform_admin_headers"])
        clock = validate_success(res)
        assert_clock(clock)
        assert clock["id"] == "clock"
