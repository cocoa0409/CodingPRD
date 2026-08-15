"""Optimistic concurrency on capacity-sensitive writes (PRD §2.7) and list
pagination envelope (PRD §2.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_enrollment,
    create_ceremony,
    create_general_volunteer,
    create_legal_volunteer,
    create_program,
    create_screened_applicant,
    create_section,
    create_workshop,
    enroll,
    get_section,
    get_workshop,
    register_applicant,
    reserve_seat,
    setup_section_with_enrollees,
    setup_two_oath_ready_cases,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


class TestOptimisticConcurrency:
    def test_occ_enrollment_create_stale_section_version(self, api):
        """PRD §2.7: "Creating an enrollment requires `expected_section_version` to
        match the class section's current `version`, since the seat ledger the caller
        relied on may have shifted."
        PRD §2.7: "If the supplied value does not match the parent's current `version`
        — because another writer has legitimately advanced it since the caller last
        read the parent — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_enrollment_create_stale_section_version
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=3, total_sessions=10)
        stale_version = section["version"]
        applicant_a, _ = create_screened_applicant()
        applicant_b, _ = create_screened_applicant()

        # A legitimate write advances the section version after the caller's read.
        enroll(applicant_a["id"], section["id"])

        stale = api.create_enrollment(
            {"applicant_id": applicant_b["id"], "class_section_id": section["id"],
             "expected_section_version": stale_version},
            COORD,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_section(section["id"])["version"]
        retried = validate_success(
            api.create_enrollment(
                {"applicant_id": applicant_b["id"], "class_section_id": section["id"],
                 "expected_section_version": fresh_version},
                COORD,
            ),
            201,
        )
        assert_enrollment(retried)
        assert retried["status"] == "ENROLLED"
        assert get_section(section["id"])["enrolled_count"] == 2, (
            "exactly one enrollment landed from the stale-attempt pair"
        )

    def test_occ_workshop_seat_reserve_stale_version(self, api):
        """PRD §2.7: "Reserving a workshop seat requires `expected_workshop_version`
        to match the workshop's current `version`, since the caller's view of
        remaining capacity may be stale."
        PRD §2.7: "If the supplied value does not match the parent's current `version`
        — because another writer has legitimately advanced it since the caller last
        read the parent — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_workshop_seat_reserve_stale_version
        """
        create_program()
        applicant_a, _ = create_screened_applicant()
        applicant_b, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-20T10:00:00Z",
                                   duration_hours=2, capacity=5)
        stale_version = workshop["version"]

        # The first reservation legitimately advances the workshop version.
        reserve_seat(workshop["id"], applicant_a["id"])

        stale = api.reserve_workshop_seat(
            workshop["id"],
            {"applicant_id": applicant_b["id"],
             "expected_workshop_version": stale_version},
            COORD,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert get_workshop(workshop["id"])["reserved_count"] == 1, (
            "the stale reserve must land nothing even though capacity remains"
        )

    def test_occ_screening_supersede_stale_applicant_version(self, api):
        """PRD §2.7: "Creating a screening requires `expected_applicant_version` to
        match the applicant's current `version`, because screening creation supersedes
        the applicant's prior active screening and repoints their active-screening
        reference."
        PRD §2.7: "If the supplied value does not match the parent's current `version`
        — because another writer has legitimately advanced it since the caller last
        read the parent — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_screening_supersede_stale_applicant_version
        """
        create_program()
        applicant = register_applicant()
        stale_version = applicant["version"]

        # The first screening legitimately advances the applicant version.
        first = validate_success(
            api.create_screening(
                applicant["id"],
                {"expected_applicant_version": stale_version,
                 "marital_to_citizen": False, "lpr_months": 80,
                 "continuous_residence_months": 61, "physical_presence_days": 1000,
                 "age_years": 36, "english_level": 2, "civics_practice_pct": 50,
                 "has_legal_flag": False},
                COORD,
            ),
            201,
        )

        stale = api.create_screening(
            applicant["id"],
            {"expected_applicant_version": stale_version,
             "marital_to_citizen": True, "lpr_months": 40,
             "continuous_residence_months": 37, "physical_presence_days": 600,
             "age_years": 36, "english_level": 1, "civics_practice_pct": 10,
             "has_legal_flag": False},
            COORD,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        rows, meta = validate_paginated(api.list_screenings(applicant["id"], COORD))
        assert meta["total_count"] == 1, "the stale write must supersede nothing"
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "ACTIVE"

    def test_occ_oath_assign_stale_ceremony_version(self, api):
        """PRD §2.7: "Assigning a case to an oath ceremony requires
        `expected_ceremony_version` to match the ceremony's current `version`, since
        the caller's view of ceremony capacity may be stale."
        PRD §2.7: "If the supplied value does not match the parent's current `version`
        — because another writer has legitimately advanced it since the caller last
        read the parent — the write is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_oath_assign_stale_ceremony_version
        """
        bundle = setup_two_oath_ready_cases()
        case_a, case_b = bundle["cases"]
        ceremony = create_ceremony(capacity=5)
        stale_version = ceremony["version"]

        # The first assignment legitimately advances the ceremony version.
        first = validate_success(
            api.assign_oath_ceremony(
                ceremony["id"],
                {"case_id": case_a["id"],
                 "expected_ceremony_version": stale_version},
                ADMIN,
            ),
            200,
        )
        assert first["stage"] == "OATH_SCHEDULED"

        stale = api.assign_oath_ceremony(
            ceremony["id"],
            {"case_id": case_b["id"],
             "expected_ceremony_version": stale_version},
            ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        case_b_after = api.get_case(case_b["id"], ADMIN).json()["data"]
        assert case_b_after["stage"] == "APPROVED_PENDING_OATH"
        ceremony_after = api.get_oath_ceremony(ceremony["id"], ADMIN).json()["data"]
        assert ceremony_after["assigned_count"] == 1


class TestPagination:
    def test_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it defaults
        to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of
        items skipped and defaults to 0. Unless otherwise specified, every list
        endpoint returns resources sorted by `created_at` in ascending order. List
        responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta`
        object of the response envelope."

        Design: Corner/cross_cutting_layers/pagination_limit_offset_has_more
        """
        scenario = setup_section_with_enrollees(
            capacity=1, num_applicants=4, total_sessions=10,
            weekday="MON", start_minute=600, end_minute=660, room_id="R1",
        )
        section = scenario["section"]
        statuses = [e["status"] for e in scenario["enrollments"]]
        assert statuses == ["ENROLLED", "WAITLISTED", "WAITLISTED", "WAITLISTED"]

        page_one, meta_one = validate_paginated(
            api.list_enrollments(
                COORD,
                params={"class_section_id": section["id"], "status": "WAITLISTED",
                        "limit": 2, "offset": 0},
            )
        )
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert len(page_one) == 2
        assert all(row["status"] == "WAITLISTED" for row in page_one)

        page_two, meta_two = validate_paginated(
            api.list_enrollments(
                COORD,
                params={"class_section_id": section["id"], "status": "WAITLISTED",
                        "limit": 2, "offset": 2},
            )
        )
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert len(page_two) == 1

        # The ENROLLED enrollment never leaks into the WAITLISTED-filtered pages.
        paged_ids = {row["id"] for row in page_one + page_two}
        assert scenario["enrollments"][0]["id"] not in paged_ids
        assert paged_ids == {e["id"] for e in scenario["enrollments"][1:]}
