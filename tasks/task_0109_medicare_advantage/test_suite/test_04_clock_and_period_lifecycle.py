"""Test clock and EnrollmentPeriod / Beneficiary auto-transitions.

Covers PRD §3.2: clock advance recomputes EnrollmentPeriod.status and
Beneficiary.lifecycle_status. Covers boundary inclusion at iep_end_date
(23:59:59 UTC), and the schedule-to-open / open-to-closed transitions.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_clock_advance,
    create_beneficiary,
    create_enrollment_period,
    get_iep_period,
    re_get_beneficiary,
    setup_clock_at,
    validate_error,
    validate_success,
)


class TestClockAdvance:
    """PRD §3.2 /_clock/advance."""

    def test_clock_advance_returns_transitions_list(self, api,
                                                   admin_headers):
        """PRD §3.2: "The advance returns the list of transitions
        actually applied, each carrying the entity type, entity id, and
        the from/to states; this output is the canonical mechanism for
        tests to confirm cascade fanout."

        Claim: POST /_clock/advance returns {now, transitions_applied:
        [...]}
        """
        resp = api.clock_advance(
            {"to": "2026-01-01T00:00:00.000Z"}, admin_headers,
        )
        data = validate_success(resp)
        assert_clock_advance(data)


class TestPreEligibleToIepOpen:
    """PRD §3.2: PRE_ELIGIBLE -> IEP_OPEN auto-transition."""

    def test_clock_crossing_iep_start_promotes_to_iep_open(
        self, api, admin_headers,
    ):
        """PRD §3.2: "A beneficiary in PRE_ELIGIBLE whose new clock
        value falls within their IEP window transitions to IEP_OPEN
        (and the corresponding EnrollmentPeriod SCHEDULED moves to
        OPEN)."

        Claim: starting from clock < iep_start_date in PRE_ELIGIBLE,
        advancing the clock into the IEP window flips lifecycle_status
        to IEP_OPEN and the IEP period status to OPEN.
        """
        # Place clock before IEP start.
        setup_clock_at(2025, 1, 1)
        b = create_beneficiary(date_of_birth="1961-04-15")
        b = re_get_beneficiary(b["id"])
        assert b["lifecycle_status"] == "PRE_ELIGIBLE"

        # Advance to inside IEP window (Jan-Jul 2026).
        advance_clock_to("2026-01-15T00:00:00.000Z")
        b_after = re_get_beneficiary(b["id"])
        assert b_after["lifecycle_status"] == "IEP_OPEN", (
            f"expected IEP_OPEN after clock crosses iep_start_date, "
            f"got {b_after['lifecycle_status']}"
        )
        iep = get_iep_period(b["id"])
        assert iep is not None
        assert iep["status"] == "OPEN"


class TestIepEndDateBoundary:
    """PRD §3.1 + §3.2: iep_end_date is the last second of the month,
    inclusive."""

    def test_clock_at_iep_end_inclusive_still_iep_open(self, api,
                                                      admin_headers):
        """PRD §3.1: "iep_end_date is the last second of the month
        that falls three months after medicare_eligibility_date —
        i.e., 23:59:59 UTC on the final day of that month, inclusive."

        Claim: at clock = iep_end_date (boundary inclusive), the
        beneficiary remains IEP_OPEN.
        """
        # For dob 1961-04-15: eligibility 2026-04-01, IEP ends
        # 2026-07-31T23:59:59Z (inclusive).
        setup_clock_at(2026, 1, 2)
        b = create_beneficiary(date_of_birth="1961-04-15")
        b = re_get_beneficiary(b["id"])
        assert b["lifecycle_status"] == "IEP_OPEN"
        # Advance precisely to iep_end_date (the last second).
        advance_clock_to("2026-07-31T23:59:59.000Z")
        b_after = re_get_beneficiary(b["id"])
        assert b_after["lifecycle_status"] == "IEP_OPEN", (
            f"at exact iep_end_date (23:59:59 inclusive) the "
            f"beneficiary must stay IEP_OPEN, got "
            f"{b_after['lifecycle_status']}"
        )

    def test_clock_one_second_past_iep_end_flips_to_iep_closed(
        self, api, admin_headers,
    ):
        """PRD §3.2: "A beneficiary in IEP_OPEN whose IEP has now ended
        without any ACTIVE Part A or Part B enrollment transitions to
        IEP_CLOSED (and the IEP period moves from OPEN to CLOSED)."
        Combined with PRD §3.1: iep_end_date is inclusive 23:59:59.

        Claim: at clock = iep_end_date + 1 second (2026-08-01T00:00:00),
        the beneficiary transitions to IEP_CLOSED.
        """
        setup_clock_at(2026, 1, 2)
        b = create_beneficiary(date_of_birth="1961-04-15")
        b = re_get_beneficiary(b["id"])
        assert b["lifecycle_status"] == "IEP_OPEN"
        advance_clock_to("2026-08-01T00:00:00.000Z")
        b_after = re_get_beneficiary(b["id"])
        assert b_after["lifecycle_status"] == "IEP_CLOSED", (
            f"one second past iep_end_date must transition to "
            f"IEP_CLOSED, got {b_after['lifecycle_status']}"
        )
        iep = get_iep_period(b["id"])
        assert iep["status"] == "CLOSED"


class TestNonIepPeriodCreation:
    """PRD §3.2: admin can open a non-IEP period."""

    def test_period_starts_scheduled_when_future(self, api,
                                                 admin_headers):
        """PRD §3.2: "The new period starts SCHEDULED if the current
        clock is before window_start, otherwise OPEN if the clock is
        inside the window."

        Claim: AEP with window_start in the future starts SCHEDULED.
        """
        setup_clock_at(2026, 1, 1)
        b = create_beneficiary(date_of_birth="1961-04-15")
        period = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2026-10-15T00:00:00.000Z",
            window_end="2026-12-07T23:59:59.000Z",
        )
        assert period["status"] == "SCHEDULED"

    def test_period_starts_open_when_window_covers_now(
        self, api, admin_headers,
    ):
        """PRD §3.2: "The new period starts SCHEDULED if the current
        clock is before window_start, otherwise OPEN if the clock is
        inside the window."

        Claim: AEP with window covering current clock starts OPEN.
        """
        setup_clock_at(2026, 11, 1)
        b = create_beneficiary(date_of_birth="1961-04-15")
        period = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2026-10-15T00:00:00.000Z",
            window_end="2026-12-07T23:59:59.000Z",
        )
        assert period["status"] == "OPEN"


class TestScheduledToOpenToClosedTransitions:
    """PRD §3.2: SCHEDULED->OPEN, OPEN->CLOSED via clock advance."""

    def test_period_scheduled_to_open(self, api, admin_headers):
        """PRD §3.2: "a period whose window straddles the new clock
        value (window_start <= now <= window_end) is OPEN".

        Claim: SCHEDULED period flips to OPEN when clock crosses
        window_start.
        """
        setup_clock_at(2026, 1, 1)
        b = create_beneficiary(date_of_birth="1961-04-15")
        period = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2026-10-15T00:00:00.000Z",
            window_end="2026-12-07T23:59:59.000Z",
        )
        assert period["status"] == "SCHEDULED"
        advance_clock_to("2026-10-20T00:00:00.000Z")
        # Read back via listing.
        from test_helpers import list_enrollment_periods
        rows = list_enrollment_periods(
            b["id"], admin_headers, params={"period_type": "AEP"},
        )
        aep_rows = [r for r in rows if r["period_type"] == "AEP"]
        assert aep_rows, "AEP period expected in list"
        assert aep_rows[0]["status"] == "OPEN"

    def test_period_open_to_closed_when_unconsumed(self, api,
                                                   admin_headers):
        """PRD §3.2: "a period whose window_end has passed and which
        was never consumed becomes CLOSED."

        Claim: OPEN AEP becomes CLOSED when clock advances past
        window_end (unconsumed).
        """
        setup_clock_at(2026, 10, 15)
        b = create_beneficiary(date_of_birth="1961-04-15")
        period = create_enrollment_period(
            beneficiary=b, period_type="AEP",
            window_start="2026-10-15T00:00:00.000Z",
            window_end="2026-12-07T23:59:59.000Z",
        )
        assert period["status"] == "OPEN"
        advance_clock_to("2026-12-08T00:00:00.000Z")
        from test_helpers import list_enrollment_periods
        rows = list_enrollment_periods(
            b["id"], admin_headers, params={"period_type": "AEP"},
        )
        aep_rows = [r for r in rows if r["period_type"] == "AEP"]
        assert aep_rows[0]["status"] == "CLOSED"
