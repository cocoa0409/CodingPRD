"""Program creation, derived-field initialization, and RecruitingCalendar
window-shape validation.

PRD §3.1 (program founding, calendar windows), §3.7
(compliance_status initial value), §2.4 (common fields shape).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_program,
    assert_recruiting_calendar,
    create_program,
    create_program_payload,
    create_recruiting_calendar_payload,
    declare_calendar_window,
    iso_offset,
    iso_utc,
    parse_iso,
    utcnow,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Program founding
# ===========================================================================
class TestProgramCreation:
    """PRD §3.1: a ComplianceOfficer founds a Program with the listed
    fields; derived fields are initialized to zero / GREEN."""

    def test_create_program_initializes_derived_fields_to_zero(
        self, api, officer_headers,
    ):
        """PRD §3.1: "On creation, the system initializes the program's
        total_equivalencies_used to zero, active_roster_count to zero,
        penalty_points_total to zero, and compliance_status to GREEN."

        Claim: a freshly created program has those four derived fields
        set to zero / GREEN.
        """
        res = api.create_program(
            create_program_payload(
                sport="FOOTBALL",
                scholarship_cap_equivalencies=85.0,
                roster_cap_count=85,
            ),
            officer_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_program(data)
        assert data["total_equivalencies_used"] == 0
        assert data["active_roster_count"] == 0
        assert data["penalty_points_total"] == 0
        assert data["compliance_status"] == "GREEN"

    def test_create_program_returns_201(self, api, officer_headers):
        """PRD §4 endpoint table: "Operations that create a new,
        stand-alone resource ... return 201 Created."

        Claim: POST /programs returns 201.
        """
        res = api.create_program(
            create_program_payload(), officer_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.1 RecruitingCalendar window-shape validation
# ===========================================================================
class TestCalendarWindowShape:
    """PRD §3.1: "The window must be at least one day long and
    start_date must be strictly before end_date; either failure raises
    ERR_CALENDAR_WINDOW_INVALID with HTTP 400." """

    def test_start_date_after_end_date_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.1: "start_date must be strictly before end_date;
        either failure raises ERR_CALENDAR_WINDOW_INVALID with HTTP
        400."

        Claim: start_date > end_date -> ERR_CALENDAR_WINDOW_INVALID.
        """
        program = create_program()
        res = api.create_recruiting_calendar(
            create_recruiting_calendar_payload(
                program_id=program["id"],
                period_type="CONTACT",
                start_date="2026-05-10T00:00:00.000Z",
                end_date="2026-05-05T00:00:00.000Z",
            ),
            officer_headers,
        )
        validate_error(res, "ERR_CALENDAR_WINDOW_INVALID")

    def test_start_date_equals_end_date_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.1: "start_date must be strictly before end_date".

        Claim: start_date == end_date -> ERR_CALENDAR_WINDOW_INVALID.
        """
        program = create_program()
        res = api.create_recruiting_calendar(
            create_recruiting_calendar_payload(
                program_id=program["id"],
                period_type="CONTACT",
                start_date="2026-05-10T00:00:00.000Z",
                end_date="2026-05-10T00:00:00.000Z",
            ),
            officer_headers,
        )
        validate_error(res, "ERR_CALENDAR_WINDOW_INVALID")

    def test_window_shorter_than_one_day_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.1: "The window must be at least one day long ...
        either failure raises ERR_CALENDAR_WINDOW_INVALID with HTTP
        400."

        Claim: a window strictly shorter than one day ->
        ERR_CALENDAR_WINDOW_INVALID.
        """
        program = create_program()
        res = api.create_recruiting_calendar(
            create_recruiting_calendar_payload(
                program_id=program["id"],
                period_type="CONTACT",
                start_date="2026-05-10T00:00:00.000Z",
                end_date="2026-05-10T12:00:00.000Z",
            ),
            officer_headers,
        )
        validate_error(res, "ERR_CALENDAR_WINDOW_INVALID")

    def test_valid_window_accepted(self, api, officer_headers):
        """PRD §3.1: a window at least one day long with start_date
        strictly before end_date is created.

        Claim: a 10-day window is accepted, returns 201 with the
        declared period_type pinned.
        """
        program = create_program()
        res = api.create_recruiting_calendar(
            create_recruiting_calendar_payload(
                program_id=program["id"],
                period_type="CONTACT",
                start_date="2026-05-01T00:00:00.000Z",
                end_date="2026-05-11T00:00:00.000Z",
            ),
            officer_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_recruiting_calendar(data)
        assert data["period_type"] == "CONTACT"


# ===========================================================================
# §2.4 RecruitingCalendar append-only shape
# ===========================================================================
class TestCalendarAppendOnly:
    """PRD §2.4: "Two entity types are append-only logs and therefore
    carry only id and created_at; neither updated_at nor version is
    present on them: the RecruitingCalendar (an immutable window
    declaration) and the RecruitingContact (an immutable contact event
    log)." """

    def test_calendar_response_does_not_carry_version(
        self, api, officer_headers,
    ):
        """PRD §2.4: "Append-only resources do not bear updated_at or
        version."

        Claim: a RecruitingCalendar response has either no version key,
        or a null version (PRD §2.4 says it is not present on these
        entities).
        """
        program = create_program()
        cal = declare_calendar_window(
            program["id"],
            period_type="CONTACT",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-15T00:00:00.000Z",
        )
        assert cal.get("version") in (None, ""), (
            f"RecruitingCalendar must not carry version per PRD §2.4, "
            f"got {cal.get('version')!r}"
        )
