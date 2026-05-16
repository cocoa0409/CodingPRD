"""SEPEvent state machine, effective_date arithmetic, window
computation, appeal cycle.

PRD §3.4.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    advance_clock_to_date,
    appeal_sep_event,
    assert_sep_event,
    create_sep_event,
    iso_date,
    iso_utc,
    make_applicant_headers,
    parse_iso,
    reject_sep_event,
    setup_approved_application,
    setup_submitted_application,
    validate_error,
    validate_success,
    verify_sep_event,
)


# ===========================================================================
# SEPEvent create
# ===========================================================================
class TestSepEventCreate:
    """PRD §3.4: "Outside the Open Enrollment Period, an applicant may
    file a Special Enrollment Period claim under the application by
    submitting an event_type from the enumerated set ... together with
    the calendar event_date on which the qualifying event occurred."""

    def test_create_sep_event_returns_submitted(self, api):
        """PRD §3.4: "The SEPEvent is created in SUBMITTED state with
        reported_at stamped to the current logical-clock time."
        """
        submitted, _primary = setup_submitted_application()
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date=iso_date(date.today()),
        )
        assert_sep_event(sep)
        assert sep["status"] == "SUBMITTED"
        assert sep["event_type"] == "MARRIAGE"


# ===========================================================================
# SEPEvent SUBMITTED → VERIFIED (60-day window)
# ===========================================================================
class TestSepEventVerify:
    """PRD §3.4: "Verification requires that the event_date lie within
    60 calendar days of the logical-clock present"."""

    def test_sep_window_60_day_exact_boundary_verifies(self, api):
        """# difficulty: boundary_precision_check/
        sep_window_60_day_exact_boundary

        PRD §3.4: "Verification requires that the event_date lie within
        60 calendar days of the logical-clock present; an event whose
        event_date is more than 60 days in the past is rejected with
        ERR_SEP_WINDOW_EXPIRED at the verify step".

        Claim: event_date exactly 60 days before /_clock.now() →
        VERIFIED succeeds (boundary inclusive at 60 days).
        """
        # Set the clock to a known point, then file SEP with event_date
        # exactly 60 days earlier.
        now_dt = datetime(2026, 3, 2, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date=iso_date(date(2026, 1, 1)),
        )
        advance_clock_to(iso_utc(now_dt))  # ensure clock at boundary
        verified = verify_sep_event(
            application=submitted, sep_event=sep,
        )
        assert verified["status"] == "VERIFIED"

    def test_sep_window_61_days_past_rejected(self, api):
        """# difficulty: boundary_precision_check/
        sep_window_60_day_exact_boundary

        PRD §3.4: "an event whose event_date is more than 60 days in
        the past is rejected with ERR_SEP_WINDOW_EXPIRED at the verify
        step".

        Claim: event_date 61 days before /_clock.now() →
        ERR_SEP_WINDOW_EXPIRED.
        """
        now_dt = datetime(2026, 3, 2, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date=iso_date(date(2025, 12, 31)),
        )
        advance_clock_to(iso_utc(now_dt))
        res = api.verify_sep_event(
            submitted["id"], sep["id"], TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_SEP_WINDOW_EXPIRED")


# ===========================================================================
# SEP effective-date arithmetic (PRD §3.4)
# ===========================================================================
class TestSepEffectiveDate:
    """PRD §3.4: "When a SEPEvent is verified, the server computes three
    derived dates: window_opens_on, window_closes_on, and
    effective_date. The arithmetic varies by event_type."""

    def test_marriage_effective_date_is_event_date(self, api):
        """PRD §3.4: "For BIRTH_ADOPTION and MARRIAGE, the effective
        date is retroactive to the qualifying event itself:
        window_opens_on equals event_date and effective_date equals
        event_date."

        Claim: MARRIAGE with event_date 2026-04-01, clock 2026-04-05 →
        effective_date == '2026-04-01' and window_opens_on ==
        '2026-04-01'.
        """
        now_dt = datetime(2026, 4, 5, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date="2026-04-01",
        )
        verified = verify_sep_event(
            application=submitted, sep_event=sep,
        )
        assert verified["window_opens_on"] == "2026-04-01"
        assert verified["effective_date"] == "2026-04-01"

    def test_loss_of_coverage_effective_date_first_of_next_month(
        self, api,
    ):
        """PRD §3.4: "For LOSS_OF_COVERAGE and MEDICAID_LOSS, the
        effective date is forward-looking: window_opens_on equals
        event_date, and effective_date equals the first day of the
        calendar month after the month containing reported_at."

        Claim: LOSS_OF_COVERAGE event_date 2026-03-10, reported_at
        (i.e., logical clock) 2026-03-15 → effective_date '2026-04-01',
        window_opens_on '2026-03-10'.
        """
        now_dt = datetime(2026, 3, 15, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="LOSS_OF_COVERAGE",
            event_date="2026-03-10",
        )
        verified = verify_sep_event(
            application=submitted, sep_event=sep,
        )
        assert verified["window_opens_on"] == "2026-03-10"
        assert verified["effective_date"] == "2026-04-01"

    def test_window_closes_on_60_days_after_window_opens_on(self, api):
        """PRD §3.4: "In every case, window_closes_on is exactly 60
        calendar days after window_opens_on."

        Claim: MARRIAGE event_date 2026-04-01 → window_opens_on
        '2026-04-01' and window_closes_on '2026-05-31' (60 days
        later).
        """
        now_dt = datetime(2026, 4, 5, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date="2026-04-01",
        )
        verified = verify_sep_event(
            application=submitted, sep_event=sep,
        )
        open_d = date.fromisoformat(verified["window_opens_on"])
        close_d = date.fromisoformat(verified["window_closes_on"])
        assert (close_d - open_d).days == 60


# ===========================================================================
# SEP reject + appeal cycle (PRD §3.4)
# ===========================================================================
class TestSepRejectAppealCycle:
    """# difficulty: non_linear_state_machine/sep_event_reject_appeal_cycle

    PRD §3.4: "if the applicant believes the rejection was in error, a
    customer-service operator may appeal the rejected event back to
    SUBMITTED, provided the appeal is filed within 30 calendar days of
    the rejection."
    """

    def test_reject_then_appeal_returns_to_submitted(self, api):
        """# difficulty: non_linear_state_machine/sep_event_reject_appeal_cycle

        PRD §3.4: "a customer-service operator may appeal the rejected
        event back to SUBMITTED".

        Claim: after /reject the SEP is REJECTED; after /appeal it
        returns to SUBMITTED.
        """
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date=iso_date(date.today()),
        )
        rejected = reject_sep_event(
            application=submitted, sep_event=sep,
            reason="insufficient docs",
        )
        assert rejected["status"] == "REJECTED"
        appealed = appeal_sep_event(
            application=submitted, sep_event=sep,
        )
        assert appealed["status"] == "SUBMITTED"

    def test_full_reject_appeal_verify_cycle(self, api):
        """# difficulty: non_linear_state_machine/sep_event_reject_appeal_cycle

        PRD §3.4 covers the full cycle: SUBMITTED → REJECTED →
        SUBMITTED (via appeal) → VERIFIED (via verify with valid
        event_date).
        """
        now_dt = datetime(2026, 4, 5, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date="2026-04-01",
        )
        reject_sep_event(application=submitted, sep_event=sep)
        appealed = appeal_sep_event(
            application=submitted, sep_event=sep,
        )
        assert appealed["status"] == "SUBMITTED"
        verified = verify_sep_event(
            application=submitted, sep_event=sep,
        )
        assert verified["status"] == "VERIFIED"


# ===========================================================================
# Application.enrollment_window side effect of verify (PRD §3.4)
# ===========================================================================
class TestSepVerifySideEffectsEnrollmentWindow:
    """PRD §3.4: "Verification has two further side effects. It sets the
    parent application's enrollment_window to SEP."
    """

    def test_verify_sets_enrollment_window_to_sep(self, api):
        """PRD §3.4: "It sets the parent application's enrollment_window
        to SEP."
        """
        now_dt = datetime(2026, 4, 5, tzinfo=timezone.utc)
        advance_clock_to(iso_utc(now_dt))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
        )
        sep = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date="2026-04-01",
        )
        verify_sep_event(application=submitted, sep_event=sep)
        from test_helpers import re_get_application
        app = re_get_application(application_id=submitted["id"])
        assert app["enrollment_window"] == "SEP"
