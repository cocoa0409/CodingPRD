"""Fair hearing overlap checks — closed-interval semantics with a
30-minute buffer applied to the new side only.

Exercises PRD §3.6 (hearing-overlap algorithm).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    file_appeal,
    iso_offset,
    iso_utc,
    parse_iso,
    schedule_hearing_payload,
    server_now_dt,
    setup_denied_application,
    validate_error,
    validate_success,
)


def _file_two_appeals():
    """Helper: returns (appeal_1, appeal_2) — two distinct INELIGIBLE
    determinations with appeals filed against them."""
    setup_a = setup_denied_application()
    setup_b = setup_denied_application()
    _, _hh_a, _, _app_a, det_a = setup_a
    _, _hh_b, _, _app_b, det_b = setup_b
    appeal_a = file_appeal(determination=det_a)
    appeal_b = file_appeal(determination=det_b)
    return appeal_a, appeal_b


class TestFairHearingOverlap:
    """PRD §3.6: "The new hearing's interval must not collide with
    another SCHEDULED FairHearing for the same officer_id."
    """

    def test_overlap_within_existing_window_rejected(self, api):
        """PRD §3.6: "The overlap check uses closed-interval semantics
        with a 30-minute buffer applied to the new hearing's interval
        on both sides."

        Claim: scheduling a second hearing whose unbuffered interval
        sits inside the first hearing's window for the same officer →
        ERR_HEARING_CONFLICT.
        """
        appeal_a, appeal_b = _file_two_appeals()
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        # First hearing: [now+1d, now+1d+1h].
        base = server_now_dt()
        s1 = iso_offset(days=1, base=base)
        e1 = iso_offset(days=1, hours=1, base=base)
        r1 = api.schedule_hearing(
            appeal_a["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s1, scheduled_end=e1,
            ),
            officer_headers,
        )
        validate_success(r1)
        # Second hearing on same officer: [now+1d+15min, now+1d+45min]
        # — strictly inside the first's window.
        s2 = iso_offset(days=1, minutes=15, base=base)
        e2 = iso_offset(days=1, minutes=45, base=base)
        r2 = api.schedule_hearing(
            appeal_b["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s2, scheduled_end=e2,
            ),
            officer_headers,
        )
        validate_error(r2, "ERR_HEARING_CONFLICT")

    def test_adjacent_hearing_with_buffer_rejected(self, api):
        """PRD §3.6: "Equivalently, the scheduling is rejected when
        both of the following hold: the new scheduled_start minus 30
        minutes is less than or equal to the existing scheduled_end,
        and the existing scheduled_start is less than or equal to the
        new scheduled_end plus 30 minutes."

        Claim: scheduling adjacent (new_start == existing_end) with a
        30-min buffer applied to the new side → ERR_HEARING_CONFLICT
        because new_start - 30min <= existing_end.

        # difficulty: resource_temporal_overlap/fair_hearing_closed_with_buffer_overlap
        """
        appeal_a, appeal_b = _file_two_appeals()
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        base = server_now_dt()
        # First: [now+1d, now+1d+1h].
        s1 = iso_offset(days=1, base=base)
        e1 = iso_offset(days=1, hours=1, base=base)
        api.schedule_hearing(
            appeal_a["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s1, scheduled_end=e1,
            ),
            officer_headers,
        )
        # Second: [now+1d+1h, now+1d+2h] — new_start == existing_end.
        # new_start - 30min = existing_end - 30min < existing_end →
        # buffered-new interval intersects existing.
        s2 = iso_offset(days=1, hours=1, base=base)
        e2 = iso_offset(days=1, hours=2, base=base)
        r2 = api.schedule_hearing(
            appeal_b["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s2, scheduled_end=e2,
            ),
            officer_headers,
        )
        validate_error(r2, "ERR_HEARING_CONFLICT")

    def test_well_separated_hearings_allowed(self, api):
        """PRD §3.6: the buffer is 30 minutes on the new side; a 31-
        minute gap clears the buffer.

        Claim: scheduling a second hearing 31 minutes after the first
        ends (so new_start - 30min > existing_end) → 200.

        # difficulty: resource_temporal_overlap/fair_hearing_closed_with_buffer_overlap
        """
        appeal_a, appeal_b = _file_two_appeals()
        officer_headers = TEST_USERS["appeals_officer_headers"]
        officer_id = officer_headers["X-User-ID"]
        base = server_now_dt()
        # First: [now+1d, now+1d+1h].
        s1 = iso_offset(days=1, base=base)
        e1 = iso_offset(days=1, hours=1, base=base)
        api.schedule_hearing(
            appeal_a["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s1, scheduled_end=e1,
            ),
            officer_headers,
        )
        # Second: [now+1d+1h+31m, now+1d+2h+31m] — 31 minutes after
        # first end, clears the buffer.
        s2 = iso_offset(days=1, hours=1, minutes=31, base=base)
        e2 = iso_offset(days=1, hours=2, minutes=31, base=base)
        r2 = api.schedule_hearing(
            appeal_b["id"],
            schedule_hearing_payload(
                officer_id=officer_id,
                scheduled_start=s2, scheduled_end=e2,
            ),
            officer_headers,
        )
        validate_success(r2)

    def test_different_officer_no_conflict(self, api):
        """PRD §3.6: "The new hearing's interval must not collide with
        another SCHEDULED FairHearing for the SAME officer_id."

        Claim: scheduling overlapping intervals for DIFFERENT officer
        ids does not conflict.

        Note: PRD §3.6 also requires AppealsOfficer X-User-ID to differ
        from the original deciding caseworker. We use the alt officer
        for the second appeal.
        """
        appeal_a, appeal_b = _file_two_appeals()
        officer_a_headers = TEST_USERS["appeals_officer_headers"]
        officer_b_headers = TEST_USERS["appeals_officer_headers_alt"]
        officer_a_id = officer_a_headers["X-User-ID"]
        officer_b_id = officer_b_headers["X-User-ID"]
        base = server_now_dt()
        s = iso_offset(days=1, base=base)
        e = iso_offset(days=1, hours=1, base=base)
        # Officer A.
        api.schedule_hearing(
            appeal_a["id"],
            schedule_hearing_payload(
                officer_id=officer_a_id,
                scheduled_start=s, scheduled_end=e,
            ),
            officer_a_headers,
        )
        # Officer B at the same time — must succeed.
        r2 = api.schedule_hearing(
            appeal_b["id"],
            schedule_hearing_payload(
                officer_id=officer_b_id,
                scheduled_start=s, scheduled_end=e,
            ),
            officer_b_headers,
        )
        validate_success(r2)
