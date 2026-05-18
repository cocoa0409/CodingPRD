"""Court calendar: event creation, attorney buffered overlap, courtroom
no-buffer overlap, judgment cascade.

PRD §3.7.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    api_client,
    assert_court_event,
    complete_court_event_with_judgment,
    create_court_event,
    create_court_event_payload,
    get_case,
    iso_utc,
    parse_iso_date,
    server_now_dt,
    setup_case_with_fee,
    setup_negotiating,
    setup_ready_for_demand,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestCourtEventCreation:

    def test_create_event_returns_scheduled(self, api):
        """PRD §3.7: "New events start in SCHEDULED."

        Claim: New court event has status==SCHEDULED.
        """
        _, case, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        ev = create_court_event(
            case["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(now_dt + timedelta(days=20)),
            duration_minutes=60,
        )
        assert_court_event(ev)
        assert ev["status"] == "SCHEDULED"

    def test_scheduled_at_before_incident_date_rejected(
        self, api, attorney_headers,
    ):
        """PRD §3.7: "The scheduled time must be strictly after the
        case's incident_date and strictly before the case's
        sol_deadline plus five years (a sanity bound on stale
        calendaring); violations are rejected with
        ERR_COURT_EVENT_TIME_INVALID."

        Claim: scheduled_at before incident_date →
        ERR_COURT_EVENT_TIME_INVALID.
        """
        _, case, _, _, _, _, _ = setup_negotiating()
        # scheduled_at = incident_date - 1 day, in UTC noon.
        inc = parse_iso_date(case["incident_date"])
        bad_iso = (
            f"{(inc - timedelta(days=1)).isoformat()}T12:00:00.000Z"
        )
        resp = api.create_court_event(
            case["id"],
            create_court_event_payload(
                "MOTION_HEARING", bad_iso, 60,
            ),
            attorney_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_COURT_EVENT_TIME_INVALID.value,
        )

    def test_duration_below_15_rejected(self, api, attorney_headers):
        """PRD §3.7: "duration_minutes (an integer between 15 and 480
        inclusive, used for calendar-conflict math)".

        Claim: duration_minutes=14 → 4xx.
        """
        _, case, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        bad = create_court_event_payload(
            "MOTION_HEARING", iso_utc(now_dt + timedelta(days=20)), 14,
        )
        resp = api.create_court_event(case["id"], bad, attorney_headers)
        assert resp.status_code >= 400

    def test_duration_above_480_rejected(self, api, attorney_headers):
        """PRD §3.7: "duration_minutes (an integer between 15 and 480
        inclusive, used for calendar-conflict math)".

        Claim: duration_minutes=481 → 4xx.
        """
        _, case, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        bad = create_court_event_payload(
            "MOTION_HEARING", iso_utc(now_dt + timedelta(days=20)), 481,
        )
        resp = api.create_court_event(case["id"], bad, attorney_headers)
        assert resp.status_code >= 400


class TestAttorneyCalendarBufferedOverlap:

    def test_buffered_overlap_rejected_within_29_minutes(
        self, api, attorney_headers,
    ):
        """PRD §3.7: "Each event's time window is treated as a
        half-open interval beginning at scheduled_at and ending
        duration_minutes later, with a 15-minute travel buffer added
        to each side. Two events conflict if and only if the later of
        the two buffered start times is strictly less than the earlier
        of the two buffered end times".

        Claim: Two events on the same attorney 29 minutes apart →
        ERR_ATTORNEY_CALENDAR_CONFLICT.
        """
        # Cases must share the same assigned_attorney_id (default in
        # fixtures is ATTORNEY_ID).
        _, case_a, _, _, _, _, _ = setup_negotiating()
        _, case_b, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        # event A: 10:00-11:00 in 30 days → buffered [09:45, 11:15)
        start_a = now_dt + timedelta(days=30)
        start_a = start_a.replace(hour=10, minute=0, second=0, microsecond=0)
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60,
        )
        # event B on case_b: 11:29 same day → buffered [11:14, 12:44)
        # → overlaps event_a's buffered tail (11:15 > 11:14).
        start_b = start_a.replace(hour=11, minute=29)
        resp = api.create_court_event(
            case_b["id"],
            create_court_event_payload(
                "MOTION_HEARING", iso_utc(start_b), 60,
            ),
            attorney_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_ATTORNEY_CALENDAR_CONFLICT.value,
        )

    def test_buffered_adjacency_exactly_30_minutes_allowed(self, api):
        """PRD §3.7: "Adjacency exactly at the buffered edge (the
        back-to-back case where one event's buffered end equals the
        next event's buffered start, producing a 30-minute clearance
        between the unbuffered windows) does not conflict and is
        allowed."

        Claim: Two events 30 minutes apart on the same attorney are
        BOTH accepted.
        """
        _, case_a, _, _, _, _, _ = setup_negotiating()
        _, case_b, _, _, _, _, _ = setup_negotiating()
        now_dt = server_now_dt()
        start_a = (
            now_dt + timedelta(days=30)
        ).replace(hour=10, minute=0, second=0, microsecond=0)
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60,
        )
        # event B: 11:30 — buffered start = 11:15 == buffered end of
        # event A (11:00 + 15min). Allowed.
        start_b = start_a.replace(hour=11, minute=30)
        ev_b = create_court_event(
            case_b["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_b),
            duration_minutes=60,
        )
        assert ev_b["status"] == "SCHEDULED"


class TestCourtroomNoBufferOverlap:

    def test_courtroom_overlap_rejected_when_unbuffered_overlap(
        self, api, attorney_headers,
    ):
        """PRD §3.7: "The courtroom check is narrower: any two events
        that share the same non-null courtroom string conflict if and
        only if their unbuffered half-open intervals (scheduled_at
        through scheduled_at plus duration_minutes) overlap, with no
        buffer".

        Claim: Two events with same courtroom that overlap at minute
        14:59 (1 minute before exact adjacency) → ERR_COURTROOM_DOUBLE_BOOKED.

        To prevent the attorney-overlap rule from also firing, the two
        cases use DIFFERENT assigned_attorney_id values.
        """
        # Two cases with different attorneys.
        from test_helpers import (
            create_case, create_client, create_contingency_fee,
            ATTORNEY_ID, ATTORNEY_ID_ALT,
        )
        client_a = create_client()
        case_a = create_case(
            client_a["id"], assigned_attorney_id=ATTORNEY_ID,
        )
        create_contingency_fee(case_a["id"])
        client_b = create_client()
        case_b = create_case(
            client_b["id"], assigned_attorney_id=ATTORNEY_ID_ALT,
        )
        create_contingency_fee(case_b["id"])
        now_dt = server_now_dt()
        room = "Room-3"
        start_a = (
            now_dt + timedelta(days=30)
        ).replace(hour=14, minute=0, second=0, microsecond=0)
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60, courtroom=room,
        )
        # Event B: 14:59 → overlaps [14:00, 15:00) at minute 14:59.
        start_b = start_a.replace(hour=14, minute=59)
        resp = api.create_court_event(
            case_b["id"],
            create_court_event_payload(
                "MOTION_HEARING", iso_utc(start_b), 60,
                courtroom=room,
            ),
            attorney_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED.value,
        )

    def test_courtroom_exact_adjacency_allowed(self, api):
        """PRD §3.7: "touching boundaries (one event's end equal to
        the next event's start) do not conflict".

        Claim: Two same-courtroom events back-to-back (15:00 == 15:00)
        both accepted.
        """
        from test_helpers import (
            create_case, create_client, create_contingency_fee,
            ATTORNEY_ID, ATTORNEY_ID_ALT,
        )
        client_a = create_client()
        case_a = create_case(
            client_a["id"], assigned_attorney_id=ATTORNEY_ID,
        )
        create_contingency_fee(case_a["id"])
        client_b = create_client()
        case_b = create_case(
            client_b["id"], assigned_attorney_id=ATTORNEY_ID_ALT,
        )
        create_contingency_fee(case_b["id"])
        now_dt = server_now_dt()
        room = "Room-7"
        start_a = (
            now_dt + timedelta(days=30)
        ).replace(hour=14, minute=0, second=0, microsecond=0)
        create_court_event(
            case_a["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_a),
            duration_minutes=60, courtroom=room,
        )
        start_b = start_a.replace(hour=15)
        ev_b = create_court_event(
            case_b["id"], "MOTION_HEARING",
            scheduled_at=iso_utc(start_b),
            duration_minutes=60, courtroom=room,
        )
        assert ev_b["status"] == "SCHEDULED"


class TestJudgmentCascade:

    def test_judgment_completed_with_positive_award_promotes_case(
        self, api,
    ):
        """PRD §3.7: "If the completed event's event_type is JUDGMENT
        and the patch body supplies an award_amount_cents strictly
        greater than zero, the case advances from LITIGATION to
        TRIAL_AWARDED, Case.gross_settlement_cents is set equal to
        award_amount_cents, and the contingency tier used by
        attorney-fee calculation becomes the trial tier."

        Claim: After judgment COMPLETED with award>0, Case in
        TRIAL_AWARDED with gross_settlement_cents==award_amount_cents.
        """
        from test_helpers import setup_trial_awarded
        result = setup_trial_awarded(award_amount_cents=12_345_000)
        refreshed = get_case(result["case"]["id"])
        assert refreshed["status"] == "TRIAL_AWARDED"
        assert refreshed["gross_settlement_cents"] == 12_345_000
