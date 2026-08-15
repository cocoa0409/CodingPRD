"""Program onboarding, standards library, listing envelope, and the program clock."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_assessment_program,
    assert_content_standard,
    create_program_payload,
    create_standard_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PD_H, create_program


class TestProgramCreation:
    def test_program_create_with_required_fields_returns_201(self, api):
        """PRD: "A `ProgramDirector` brings a new assessment program into
        existence by supplying a `program_code` that uniquely identifies it, a
        `subject` of `MATH`, `ELA`, `SCIENCE`, or `SOCIAL_STUDIES`, a
        `grade_level` between grade 3 and grade 12 inclusive, and the
        `admin_year` of the administration."
        PRD: "The new program begins with `status` set to `ACTIVE`"
        PRD: "The clock is initialized to exactly `2026-08-01T00:00:00Z` when
        the program is created and never moves on its own."

        Design: Corner/entities/program_create_with_required_fields_returns_201
        """
        resp = api.create_assessment_program(
            create_program_payload(program_code="ELA-G3", subject="ELA",
                                   grade_level=3, admin_year=2026),
            PD_H,
        )
        program = validate_success(resp, 201)
        assert_assessment_program(program)
        assert is_valid_uuid(program["id"])
        assert program["current_period_utc"] == "2026-08-01T00:00:00Z", (
            "clock initializes to the fixed logical default"
        )
        assert program["status"] == "ACTIVE"
        assert is_iso8601_timestamp(program["created_at"])

    def test_program_create_missing_required_field_returns_400(self, api):
        """PRD: "Requests with a missing required field, a type mismatch, or an
        unrecognized enum value are structurally invalid and fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/program_create_missing_required_field_returns_400
        """
        payload = {"program_code": "MISSING-SUBJ", "grade_level": 5,
                   "admin_year": 2026}
        resp = api.create_assessment_program(payload, PD_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_program_retrieve_by_id_returns_stored_data(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." (and GET returns the stored resource per the endpoint table)

        Design: Corner/entities/program_retrieve_by_id_returns_stored_data
        """
        program = create_program(program_code="SCI-G7", subject="SCIENCE",
                                 grade_level=7)
        fetched = validate_success(api.get_assessment_program(program["id"], PD_H))
        assert fetched["id"] == program["id"]
        assert fetched["program_code"] == "SCI-G7"
        assert fetched["grade_level"] == 7
        assert fetched["subject"] == "SCIENCE"

    def test_program_retrieve_nonexistent_returns_404(self, api):
        """PRD: "Each identifier in the path must resolve to an existing
        resource before the next identifier is examined, and the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
        does not resolve."

        Design: Corner/entities/program_retrieve_nonexistent_returns_404
        """
        resp = api.get_assessment_program(NON_EXISTENT_UUID, PD_H)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_program_list_pagination_default(self, api):
        """PRD: "The `limit` parameter caps the number of resources returned in
        one response; it defaults to 10 when omitted, and any supplied value
        must be at least 1 and no more than 100. The `offset` parameter skips a
        number of resources from the front of the result set and defaults to 0."
        PRD: "The `meta` object of every list response carries four pagination
        fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/program_list_pagination_default
        """
        create_program(program_code="P-1")
        create_program(program_code="P-2")
        data, meta = validate_paginated(api.list_assessment_programs(PD_H))
        assert len(data) == 2
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_pagination_limit_offset_consistent(self, api):
        """PRD: "The `limit` parameter caps the number of resources returned in
        one response; it defaults to 10 when omitted, and any supplied value
        must be at least 1 and no more than 100. The `offset` parameter skips a
        number of resources from the front of the result set and defaults to 0."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_consistent
        """
        for code in ("P-P1", "P-P2", "P-P3"):
            create_program(program_code=code)
        data, meta = validate_paginated(
            api.list_assessment_programs(PD_H, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_assessment_programs(PD_H, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False


class TestStandards:
    def test_standard_create_read_list(self, api):
        """PRD: "Within a program, the `ProgramDirector` registers the
        ContentStandards against which items will be aligned. Each standard
        carries the owning `program_id`, a `standard_code` such as
        `CCSS.MATH.8.EE.B.5`, the top-level `strand` it belongs to, the full
        `description` text, and a `depth_of_knowledge` rating from 1 through 4
        inclusive."
        PRD: "The standards collection may be listed with `program_id` and
        `strand` filters."

        Design: Corner/endpoints/standard_create_read_list
        """
        program = create_program()
        resp = api.create_content_standard(
            create_standard_payload(program["id"], standard_code="CCSS.3.NBT",
                                    strand="NBT",
                                    description="Number and operations",
                                    depth_of_knowledge=1),
            PD_H,
        )
        standard = validate_success(resp, 201)
        assert_content_standard(standard)
        assert standard["status"] == "ACTIVE"

        fetched = validate_success(api.get_content_standard(standard["id"], PD_H))
        assert fetched["id"] == standard["id"]
        assert fetched["standard_code"] == "CCSS.3.NBT"

        data, meta = validate_paginated(
            api.list_content_standards(PD_H, params={"program_id": program["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == standard["id"]


class TestProgramClock:
    def test_clock_advance_action_endpoint(self, api):
        """PRD: "The clock is initialized to exactly `2026-08-01T00:00:00Z`
        when the program is created and never moves on its own. A
        `ProgramDirector` advances it through a clock-advance capability that
        takes a `by_seconds` argument and adds that many seconds to
        `current_period_utc`."

        Design: Corner/endpoints/clock_advance_action_endpoint
        """
        program = create_program(program_code="P-CLK")
        assert program["current_period_utc"] == "2026-08-01T00:00:00Z"
        updated = validate_success(api.advance_clock(program["id"], 3600, PD_H))
        assert updated["current_period_utc"] == "2026-08-01T01:00:00Z", (
            "3600 seconds added to the logical clock"
        )

    def test_read_after_write_returns_updated_data(self, api):
        """PRD: "A `ProgramDirector` advances it through a clock-advance
        capability that takes a `by_seconds` argument and adds that many
        seconds to `current_period_utc`."

        Design: Corner/consistency_model/read_after_write_returns_updated_data
        """
        program = create_program(program_code="P-IMM")
        get_success_data(api.advance_clock(program["id"], 7200, PD_H))
        fetched = validate_success(api.get_assessment_program(program["id"], PD_H))
        assert fetched["current_period_utc"] == "2026-08-01T02:00:00Z", (
            "the read reflects the write immediately"
        )
