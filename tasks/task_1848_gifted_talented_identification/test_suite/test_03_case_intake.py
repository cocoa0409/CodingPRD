"""Case intake: pathways, windows, uniqueness, and grade-band fit."""
from test_helpers import (
    CLOCK_TODAY,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_gifted_case,
    create_case,
    create_case_payload,
    create_cycle,
    create_site,
    create_student,
    create_transfer_honor_case_payload,
    get_case,
    get_student,
    make_parent_guardian_headers,
    make_referring_educator_headers,
    set_clock,
    setup_cycle_in_state,
    setup_cycle_with_published_profile,
    validate_error,
    validate_paginated,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestTransferHonor:
    def test_case_transfer_honor_auto_identifies(self, api):
        """PRD §3.3: "`decided_on` is set to today and the student's
        `gifted_status` flips to `IDENTIFIED` in the same atomic create."
        PRD §3.3: "the district honors an identification already made
        elsewhere."

        Design: Corner/entities/case_transfer_honor_auto_identifies
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3,
                                 primary_guardian_user_id="guard-1")
        resp = api.create_case(
            create_transfer_honor_case_payload(
                student_id=student["id"], cycle_id=cycle["id"],
                external_district_name="ExtDist",
                external_identified_on="2026-03-01"),
            GC)
        case = validate_success(resp, 201)
        assert_gifted_case(case)
        assert case["status"] == "IDENTIFIED"
        assert case["decided_on"] == "2026-08-20"
        assert case["composite_score"] is None
        assert get_student(student["id"])["gifted_status"] == "IDENTIFIED"

    def test_transfer_window_lapsed_rejected(self, api):
        """PRD §3.3: "the student record must be at most 45 days old — filing
        later fails with `ERR_TRANSFER_WINDOW_LAPSED`".

        Design: Corner/validations/transfer_window_lapsed_rejected
        """
        # Student record created under the startup clock (2026-08-01); the
        # clock then advances 50 days to 2026-09-20 before the transfer filing.
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        cycle, _ = setup_cycle_in_state("OPEN")
        set_clock("2026-09-20T00:00:00Z")
        resp = api.create_case(
            create_transfer_honor_case_payload(
                student_id=student["id"], cycle_id=cycle["id"],
                external_district_name="ExtDist",
                external_identified_on="2026-03-01"),
            GC)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_LAPSED.value)

    def test_external_identification_too_old_rejected(self, api):
        """PRD §3.3: "the external identification must be no more than 730
        days old, else `ERR_EXTERNAL_ID_TOO_OLD`".

        Design: Corner/validations/external_identification_too_old_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        # 2024-08-19 is 731 days before 2026-08-20 (2025 and 2026 spans of
        # 365 days each, plus one).
        resp = api.create_case(
            create_transfer_honor_case_payload(
                student_id=student["id"], cycle_id=cycle["id"],
                external_district_name="ExtDist",
                external_identified_on="2024-08-19"),
            GC)
        validate_error(resp, ApiErrorId.ERR_EXTERNAL_ID_TOO_OLD.value)


class TestCaseIntakeGates:
    def test_case_intake_requires_open_cycle(self, api):
        """PRD §3.3: "Case intake requires the cycle to be `OPEN`; attempting
        it in any other cycle state fails with `ERR_CYCLE_NOT_OPEN`."

        Design: Corner/validations/case_intake_requires_open_cycle
        """
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        cycle = create_cycle()  # DRAFT, never advanced
        resp = api.create_case(
            create_case_payload(student_id=student["id"], cycle_id=cycle["id"],
                                pathway="UNIVERSAL_SCREEN"),
            GC)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value)

    def test_duplicate_case_same_cycle_rejected(self, api):
        """PRD §3.3: "At most one `GiftedCase` may exist per (`student_id`,
        `cycle_id`) pair — a duplicate create is rejected with
        `ERR_DUPLICATE_CASE`".

        Design: Corner/validations/duplicate_case_same_cycle_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        cycle, _ = setup_cycle_in_state("OPEN")
        create_case(student["id"], cycle["id"], pathway="UNIVERSAL_SCREEN")
        resp = api.create_case(
            create_case_payload(student_id=student["id"], cycle_id=cycle["id"],
                                pathway="UNIVERSAL_SCREEN"),
            GC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE.value)

    def test_grade_band_mismatch_rejected(self, api):
        """PRD §3.3: "the student's `grade_level` must fall inside the cycle's
        `grade_band` (else `ERR_GRADE_BAND_MISMATCH`)".
        PRD §3.2: "a `grade_band` of `ELEMENTARY` (grades 0–5), `MIDDLE`
        (6–8), or `HIGH` (9–12)".

        Design: Corner/validations/grade_band_mismatch_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=7)
        cycle, _ = setup_cycle_in_state("OPEN")  # ELEMENTARY
        resp = api.create_case(
            create_case_payload(student_id=student["id"], cycle_id=cycle["id"],
                                pathway="UNIVERSAL_SCREEN"),
            GC)
        validate_error(resp, ApiErrorId.ERR_GRADE_BAND_MISMATCH.value)

    def test_referral_after_close_rejected(self, api):
        """PRD §3.3: "A referral filed after the cycle's `referral_close_on`
        is rejected with `ERR_REFERRAL_WINDOW_CLOSED`."

        Design: Corner/validations/referral_after_close_rejected
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=3)
        cycle, _ = setup_cycle_in_state("OPEN")
        # referral_close_on is 2026-09-30; file the referral the day after.
        set_clock("2026-10-01T00:00:00Z")
        resp = api.create_case(
            create_case_payload(student_id=student["id"], cycle_id=cycle["id"],
                                pathway="REFERRAL", referral_source="TEACHER"),
            make_referring_educator_headers("edu-1"))
        validate_error(resp, ApiErrorId.ERR_REFERRAL_WINDOW_CLOSED.value)


class TestCaseListing:
    def test_cases_list_filter_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
        100; `offset` defaults to 0. The `meta` envelope of every list
        response carries `limit`, `offset`, `total_count`, and `has_more`."
        PRD §4: "GET /gifted/cases — List cases; filterable by `student_id`,
        `cycle_id`, `status`, `pathway`".

        Design: Corner/endpoints/cases_list_filter_pagination_envelope
        """
        set_clock(CLOCK_TODAY)
        site = create_site()
        cycle, _ = setup_cycle_in_state("OPEN")
        for i in (1, 2, 3):
            stu = create_student(site["id"], student_number=f"ST-{i}",
                                 legal_name=f"Stu {i}", grade_level=3,
                                 primary_guardian_user_id=f"guard-{i}")
            create_case(stu["id"], cycle["id"], pathway="UNIVERSAL_SCREEN")

        page1_resp = api.list_cases(GC, params={"cycle_id": cycle["id"],
                                                "limit": 2})
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert isinstance(meta1["limit"], int) and meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2_resp = api.list_cases(GC, params={"cycle_id": cycle["id"],
                                                "limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
