"""Program lifecycle, calendar spine, and facility-date overlap (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    archive_program,
    close_day,
    close_registration,
    create_day,
    create_program,
    open_day_with_clock,
    open_registration,
    start_session,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

_DIRECTOR = TEST_USERS["program_director_headers"]


class TestProgramCreation:
    def test_missing_start_date_rejected(self, api, program_director_headers):
        """PRD §2.9 (priority 0): "the body parses; all required fields are
        present" — failures report `ERR_INVALID_REQUEST` (HTTP 400). PRD §3.1
        creates a program "with its `name`, `program_year`, inclusive
        `start_date` and `end_date`, the registration window
        `registration_opens_at` and `registration_closes_at` (both inclusive
        instants, with close strictly after open), and the
        `supply_budget_cents` that caps curriculum-kit spending (zero or more
        cents)".

        Design: Corner/entities/program_create_missing_required_start_date
        """
        payload = {
            "name": "VBS Alpha",
            "program_year": 2026,
            "end_date": "2026-08-21",
            "registration_opens_at": "2026-07-15T00:00:00Z",
            "registration_closes_at": "2026-08-15T23:59:59Z",
            "supply_budget_cents": 100000,
        }
        resp = api.create_program(payload, program_director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestProgramDateOverlap:
    def test_touching_inclusive_end_date_rejected(self, api):
        """PRD §3.1: "A new program's inclusive date range must not intersect
        any other non-`ARCHIVED` program's inclusive range — overlapping ranges
        are rejected with `ERR_PROGRAM_DATE_OVERLAP`." PRD §2.4: "`start_date`
        and `end_date` are inclusive bounds wherever a range is tested" — so a
        start on the existing program's last day still shares that date.

        Design: Difficulty/resource_temporal_overlap/program_date_overlap_inclusive_intervals
        """
        create_program(name="VBS Alpha")
        resp = api.create_program(
            {
                "name": "VBS Beta",
                "program_year": 2026,
                "start_date": "2026-08-21",
                "end_date": "2026-08-25",
                "registration_opens_at": "2026-07-15T00:00:00Z",
                "registration_closes_at": "2026-08-15T23:59:59Z",
                "supply_budget_cents": 50000,
            },
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_DATE_OVERLAP, 409)
        data, meta = validate_paginated(api.list_programs(_DIRECTOR))
        assert meta["total_count"] == 1, "the rejected create persisted nothing"
        assert data[0]["name"] == "VBS Alpha"

    def test_start_day_after_inclusive_end_accepted(self, api):
        """PRD §3.1: "A new program's inclusive date range must not intersect
        any other non-`ARCHIVED` program's inclusive range — overlapping ranges
        are rejected with `ERR_PROGRAM_DATE_OVERLAP`." Starting one day after
        the existing inclusive end date shares no date, so creation succeeds.

        Design: Difficulty/resource_temporal_overlap/program_date_overlap_inclusive_intervals
        """
        create_program(name="VBS Alpha")
        resp = api.create_program(
            {
                "name": "VBS Gamma",
                "program_year": 2026,
                "start_date": "2026-08-22",
                "end_date": "2026-08-26",
                "registration_opens_at": "2026-07-15T00:00:00Z",
                "registration_closes_at": "2026-08-15T23:59:59Z",
                "supply_budget_cents": 50000,
            },
            _DIRECTOR,
        )
        data = validate_success(resp, 201)
        assert data["name"] == "VBS Gamma"
        assert data["status"] == "DRAFT"


class TestProgramDaySpine:
    def test_gap_day_rejected_and_indexes_stay_sequential(self, api):
        """PRD §3.1: "The first day must equal the program's `start_date`;
        every later day must be exactly one calendar day after the previously
        appended day, with violations reported as `ERR_DAY_NOT_SEQUENTIAL`",
        and each creation "receives the next 1-based `day_index` in append
        order".

        Design: Difficulty/resource_temporal_overlap/program_day_append_strict_adjacency
        """
        program = create_program()
        day1 = create_day(program["id"], "2026-08-17")
        assert day1["day_index"] == 1

        resp_gap = api.create_program_day(
            {"program_id": program["id"], "date": "2026-08-19"}, _DIRECTOR
        )
        validate_error(resp_gap, ApiErrorId.ERR_DAY_NOT_SEQUENTIAL, 409)

        day2 = create_day(program["id"], "2026-08-18")
        assert day2["day_index"] == 2

    def test_reoccupying_existing_date_rejected(self, api):
        """PRD §3.1: "every later day must be exactly one calendar day after
        the previously appended day, with violations reported as
        `ERR_DAY_NOT_SEQUENTIAL`" — re-using an earlier date is not the day
        after the previously appended one.

        Design: Difficulty/resource_temporal_overlap/program_day_append_strict_adjacency
        """
        program = create_program()
        create_day(program["id"], "2026-08-17")
        create_day(program["id"], "2026-08-18")
        resp_dup = api.create_program_day(
            {"program_id": program["id"], "date": "2026-08-17"}, _DIRECTOR
        )
        validate_error(resp_dup, ApiErrorId.ERR_DAY_NOT_SEQUENTIAL, 409)

    def test_first_day_out_of_range_reports_out_of_range(self, api):
        """PRD §3.1: "every day must lie within the program's inclusive range,
        with violations reported as `ERR_DAY_OUT_OF_RANGE` — and the
        out-of-range error outranks the adjacency error when a date breaks
        both."

        Design: Corner/validations/first_day_out_of_range_reports_out_of_range
        """
        program = create_program()
        resp = api.create_program_day(
            {"program_id": program["id"], "date": "2026-08-22"}, _DIRECTOR
        )
        validate_error(resp, ApiErrorId.ERR_DAY_OUT_OF_RANGE, 409)


class TestProgramLifecycleGates:
    def test_start_session_without_days_rejected(self, api):
        """PRD §3.1: "Starting the session requires at least one program day —
        otherwise `ERR_NO_PROGRAM_DAYS`".

        Design: Corner/validations/start_session_without_days_returns_no_program_days
        """
        program = create_program()
        open_registration(program["id"])
        close_registration(program["id"])
        resp = api.start_session(program["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NO_PROGRAM_DAYS, 409)
        from test_helpers import get_program
        assert get_program(program["id"])["status"] == "REGISTRATION_CLOSED"

    def test_complete_with_open_day_rejected(self, api):
        """PRD §3.1: "Completing requires every day `CLOSED` — otherwise
        `ERR_DAYS_STILL_OPEN`".

        Design: Corner/validations/complete_with_open_day_returns_days_still_open
        """
        from test_helpers import get_program
        program = create_program()
        day = create_day(program["id"], "2026-08-17")
        open_registration(program["id"])
        close_registration(program["id"])
        start_session(program["id"])
        open_day_with_clock(day)
        resp = api.complete_program(program["id"], _DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DAYS_STILL_OPEN, 409)
        assert get_program(program["id"])["status"] == "IN_SESSION"

    def test_archive_terminal_lockdown(self, api):
        """PRD §3.1: "Archiving moves `COMPLETED` → `ARCHIVED`, after which the
        program is read-only: every write targeting it or its children returns
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/program_archive_terminal_lockdown
        """
        program = create_program()
        day = create_day(program["id"], "2026-08-17")
        open_registration(program["id"])
        close_registration(program["id"])
        start_session(program["id"])
        open_day_with_clock(day)
        close_day(day["id"])
        resp_complete = api.complete_program(program["id"], _DIRECTOR)
        validate_success(resp_complete)
        archived = archive_program(program["id"])
        assert archived["status"] == "ARCHIVED"

        resp_reopen = api.open_registration(program["id"], _DIRECTOR)
        validate_error(resp_reopen, ApiErrorId.ERR_INVALID_STATE, 409)

        resp_day = api.create_program_day(
            {"program_id": program["id"], "date": "2026-08-18"}, _DIRECTOR
        )
        validate_error(resp_day, ApiErrorId.ERR_INVALID_STATE, 409)
