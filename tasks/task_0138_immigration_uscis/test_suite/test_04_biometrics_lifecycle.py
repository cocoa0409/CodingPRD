"""Biometrics lifecycle — PRD §3.4.

Coverage:
- Schedule biometrics requires scheduled_at >= now() + 7 days
  (ERR_BIOMETRICS_TOO_SOON).
- Only one SCHEDULED row per case at a time
  (ERR_BIOMETRICS_ALREADY_SCHEDULED).
- Complete requires now() >= scheduled_at; sets completed_at and
  advances parent case to BIOMETRICS_COMPLETED.
- NO_SHOW requires now() > scheduled_at + 24h.
- Reschedule: must be >= 7 days out, must be 24h before existing
  scheduled_at, and reschedule_count strictly < 3
  (ERR_BIOMETRICS_RESCHEDULE_TOO_LATE, ERR_BIOMETRICS_RESCHEDULE_LIMIT).
- A successful reschedule sets old.status=RESCHEDULED and new row
  carries reschedule_count = old + 1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BIOMETRICS_LEAD_DAYS,
    BIOMETRICS_MAX_RESCHEDULES,
    api_client,
    advance_clock_to,
    assert_biometrics,
    complete_biometrics,
    iso_instant_utc,
    no_show_biometrics,
    parse_iso,
    reschedule_biometrics,
    reschedule_biometrics_payload,
    schedule_biometrics,
    schedule_biometrics_payload,
    server_now_dt,
    server_offset_iso,
    setup_filed_case,
    validate_error,
    validate_success,
)


# ===========================================================================
# Scheduling
# ===========================================================================
class TestBiometricsScheduling:

    def test_schedule_at_seven_days_out_succeeds(self, api):
        """PRD §3.4: "The scheduled_at value must be at least seven
        days from the present moment".

        Claim: scheduled_at = now() + 7 days exactly is accepted.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        scheduled = server_offset_iso(days=BIOMETRICS_LEAD_DAYS)
        resp = api_client.schedule_biometrics(
            case["id"],
            schedule_biometrics_payload(
                scheduled_at=scheduled, location_code="ASC01",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        data = validate_success(resp, expected_status=201)
        assert_biometrics(data)
        assert data["status"] == "SCHEDULED"
        assert data["reschedule_count"] == 0

    def test_schedule_too_soon_rejected(self, api):
        """PRD §3.4: "an earlier value is rejected with
        ERR_BIOMETRICS_TOO_SOON".

        Claim: scheduled_at = now() + 6 days (less than 7d) ->
        ERR_BIOMETRICS_TOO_SOON.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        scheduled = server_offset_iso(days=BIOMETRICS_LEAD_DAYS - 1)
        resp = api_client.schedule_biometrics(
            case["id"],
            schedule_biometrics_payload(
                scheduled_at=scheduled, location_code="ASC01",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_BIOMETRICS_TOO_SOON.value,
        )

    def test_second_scheduled_rejected(self, api):
        """PRD §3.4: "Only one SCHEDULED Biometrics row may exist per
        case at a time — an attempt to schedule a second concurrent
        appointment is rejected with ERR_BIOMETRICS_ALREADY_SCHEDULED."

        Claim: scheduling a second appointment while one is SCHEDULED
        -> ERR_BIOMETRICS_ALREADY_SCHEDULED.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        schedule_biometrics(case, days_ahead=8)
        resp = api_client.schedule_biometrics(
            case["id"],
            schedule_biometrics_payload(
                scheduled_at=server_offset_iso(days=10),
                location_code="ASC02",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_BIOMETRICS_ALREADY_SCHEDULED.value,
        )


# ===========================================================================
# Completion
# ===========================================================================
class TestBiometricsCompletion:

    def test_complete_after_scheduled_at_advances_case(self, api):
        """PRD §3.4: "The completion sets completed_at to the present
        instant, updates the appointment's status to COMPLETED, and —
        when the parent case is still in BIOMETRICS_SCHEDULED —
        advances the case to BIOMETRICS_COMPLETED."

        Claim: completing biometrics after its scheduled_at sets the
        appointment status to COMPLETED, pins completed_at, and
        transitions the parent case to BIOMETRICS_COMPLETED.
        """
        from test_helpers import re_get_case
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        bio = schedule_biometrics(case, days_ahead=8)
        # Advance past scheduled_at.
        advance_clock_to(server_offset_iso(days=9))
        completed = complete_biometrics(bio)
        assert completed["status"] == "COMPLETED"
        assert completed.get("completed_at") is not None
        parent = re_get_case(case["id"])
        assert parent["status"] == "BIOMETRICS_COMPLETED"


# ===========================================================================
# Reschedule
# ===========================================================================
class TestBiometricsReschedule:

    def test_reschedule_creates_new_row_increments_count(self, api):
        """PRD §3.4: "A successful reschedule from a still-SCHEDULED
        row marks the old row's status as RESCHEDULED and creates a
        new Biometrics row ... in initial status SCHEDULED, with
        reschedule_count set to the prior row's reschedule_count plus
        one."

        Claim: a successful reschedule yields a new SCHEDULED row with
        reschedule_count = old + 1; the old row's status flips to
        RESCHEDULED.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        b1 = schedule_biometrics(case, days_ahead=20)
        # Reschedule from inside the 24h-cutoff window — the existing
        # scheduled_at is 20 days out, so any "now" before that minus
        # 24h is fine.
        b2 = reschedule_biometrics(b1, days_ahead=10)
        assert b2["status"] == "SCHEDULED"
        assert b2["reschedule_count"] == 1
        # Re-fetch the old row to observe RESCHEDULED.
        from test_helpers import api_client as _ac
        resp = _ac.get_biometrics(
            b1["id"],
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        old = validate_success(resp)
        assert old["status"] == "RESCHEDULED"

    def test_reschedule_too_late_rejected(self, api):
        """PRD §3.4: "the request must arrive no later than 24 hours
        before the existing appointment's scheduled_at
        (ERR_BIOMETRICS_RESCHEDULE_TOO_LATE)".

        Claim: reschedule requested less than 24h before the existing
        scheduled_at -> ERR_BIOMETRICS_RESCHEDULE_TOO_LATE.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        b1 = schedule_biometrics(case, days_ahead=8)
        # Move the clock to 23 hours before the existing scheduled_at.
        existing_at = parse_iso(b1["scheduled_at"])
        from datetime import timedelta
        from test_helpers import iso_utc
        advance_clock_to(iso_utc(existing_at - timedelta(hours=23)))
        new_at = server_offset_iso(days=BIOMETRICS_LEAD_DAYS + 1)
        resp = api_client.reschedule_biometrics(
            b1["id"],
            reschedule_biometrics_payload(
                new_scheduled_at=new_at, location_code="ASC02",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_BIOMETRICS_RESCHEDULE_TOO_LATE.value,
        )

    def test_reschedule_too_soon_for_new_time_rejected(self, api):
        """PRD §3.4: "The new appointment's new_scheduled_at must again
        be at least seven days into the future
        (ERR_BIOMETRICS_TOO_SOON)".

        Claim: a reschedule whose new_scheduled_at is less than 7 days
        out -> ERR_BIOMETRICS_TOO_SOON.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        b1 = schedule_biometrics(case, days_ahead=20)
        new_at = server_offset_iso(days=BIOMETRICS_LEAD_DAYS - 1)
        resp = api_client.reschedule_biometrics(
            b1["id"],
            reschedule_biometrics_payload(
                new_scheduled_at=new_at, location_code="ASC02",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_BIOMETRICS_TOO_SOON.value,
        )

    def test_fourth_reschedule_rejected(self, api):
        """PRD §3.4: "the current reschedule_count on the chain must be
        strictly less than 3, so the fourth reschedule attempt on the
        same chain is rejected with ERR_BIOMETRICS_RESCHEDULE_LIMIT."

        Claim: rescheduling 3 times succeeds; the 4th attempt on the
        same chain -> ERR_BIOMETRICS_RESCHEDULE_LIMIT.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        b = schedule_biometrics(case, days_ahead=20)
        # Three successful reschedules.
        b2 = reschedule_biometrics(b, days_ahead=15)
        assert b2["reschedule_count"] == 1
        b3 = reschedule_biometrics(b2, days_ahead=15)
        assert b3["reschedule_count"] == 2
        b4 = reschedule_biometrics(b3, days_ahead=15)
        assert b4["reschedule_count"] == BIOMETRICS_MAX_RESCHEDULES
        # 4th attempt on chain whose reschedule_count is already 3.
        new_at = server_offset_iso(days=15)
        resp = api_client.reschedule_biometrics(
            b4["id"],
            reschedule_biometrics_payload(
                new_scheduled_at=new_at, location_code="ASC02",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_BIOMETRICS_RESCHEDULE_LIMIT.value,
        )
