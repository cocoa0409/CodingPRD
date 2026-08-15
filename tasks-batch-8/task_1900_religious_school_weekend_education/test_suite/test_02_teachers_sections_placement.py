"""Teacher vetting/hiring pipeline, section scheduling, placement rules."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_year, setup_open_year, setup_open_year_with_section,
    create_teacher_payload, create_section_payload,
    create_hired_teacher, create_staffed_section,
    create_family, create_student, enroll_student_fresh,
    get_section,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTeacherPipeline:
    def test_hire_from_applied_rejected(self):
        """PRD §3.2: "Hiring moves `VETTED` → `HIRED`" — no `APPLIED` → `HIRED`
        transition exists, and per §2.8 step 7 "The requested transition's from-state
        holds (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/teacher_hire_from_applied_rejected
        """
        teacher = get_success_data(
            api_client.create_teacher(create_teacher_payload(), ADMIN), 201
        )
        assert teacher["status"] == "APPLIED"
        resp = api_client.hire_teacher(teacher["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        teacher_now = get_success_data(api_client.get_teacher(teacher["id"], ADMIN))
        assert teacher_now["status"] == "APPLIED"

    def test_vet_requires_background_check(self):
        """PRD §3.2: "vetting a teacher whose `background_check_cleared` is still
        false fails with `ERR_BACKGROUND_CHECK_REQUIRED`." PRD §3.2: "an optional
        `background_check_cleared` flag that defaults to false".

        Design: Corner/validations/vet_requires_background_check
        """
        payload = create_teacher_payload()
        del payload["background_check_cleared"]
        teacher = get_success_data(api_client.create_teacher(payload, ADMIN), 201)
        assert teacher["background_check_cleared"] is False
        resp = api_client.vet_teacher(teacher["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_BACKGROUND_CHECK_REQUIRED)
        teacher_now = get_success_data(api_client.get_teacher(teacher["id"], ADMIN))
        assert teacher_now["status"] == "APPLIED"

    def test_unvetted_teacher_assignment_rejected(self):
        """PRD §3.2: "only `HIRED` teachers may be assigned to sections: an attempt
        to assign a teacher in `APPLIED`, `VETTED`, or `SEPARATED` status fails with
        `ERR_TEACHER_NOT_HIRED`."

        Design: Corner/validations/unvetted_teacher_assignment_rejected
        """
        year = create_year()
        teacher = get_success_data(
            api_client.create_teacher(create_teacher_payload(), ADMIN), 201
        )
        payload = create_section_payload()
        payload["teacher_id"] = teacher["id"]
        resp = api_client.create_section(year["id"], payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_TEACHER_NOT_HIRED)


class TestRoomTimeConflict:
    def test_halfopen_overlap_back_to_back_and_different_room(self):
        """PRD §2.9: "Section meeting times, by contrast, are **half-open**: a
        section occupies its room from `start_time` up to but not including
        `end_time`, so two sections in the same room on the same day may be
        back-to-back — one ending at exactly the minute the other begins — without
        conflict." PRD §3.2: "a new section whose half-open time block intersects an
        existing section's block in the same `room` on the same `day_of_week` of the
        same year is rejected with `ERR_ROOM_TIME_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/section_room_halfopen_time_overlap
        """
        year = create_year()
        # Existing: R1 SUN 10:00-11:30 (unstaffed sections are creatable).
        s1 = get_success_data(
            api_client.create_section(
                year["id"],
                create_section_payload(room="R1", day_of_week="SUN",
                                       start_time="10:00", end_time="11:30",
                                       grade="G3"),
                ADMIN,
            ),
            201,
        )
        # Back-to-back at 11:30 -> accepted under half-open semantics.
        s2 = api_client.create_section(
            year["id"],
            create_section_payload(room="R1", day_of_week="SUN",
                                   start_time="11:30", end_time="12:30",
                                   grade="G4"),
            ADMIN,
        )
        validate_success(s2, 201)
        # 11:00-12:00 intersects [10:00, 11:30) -> conflict.
        conflict = api_client.create_section(
            year["id"],
            create_section_payload(room="R1", day_of_week="SUN",
                                   start_time="11:00", end_time="12:00",
                                   grade="G5"),
            ADMIN,
        )
        validate_error(conflict, ApiErrorId.ERR_ROOM_TIME_CONFLICT)
        # Same window, different room -> no conflict.
        other_room = api_client.create_section(
            year["id"],
            create_section_payload(room="R2", day_of_week="SUN",
                                   start_time="10:30", end_time="11:00",
                                   grade="G5"),
            ADMIN,
        )
        validate_success(other_room, 201)

    def test_overlapping_same_room_same_window_rejected(self):
        """PRD §3.2: "Room double-booking is impossible: a new section whose
        half-open time block intersects an existing section's block in the same
        `room` on the same `day_of_week` of the same year is rejected with
        `ERR_ROOM_TIME_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/section_room_halfopen_time_overlap
        """
        year = create_year()
        get_success_data(
            api_client.create_section(
                year["id"],
                create_section_payload(room="R9", day_of_week="MON",
                                       start_time="09:00", end_time="10:30",
                                       grade="G1"),
                ADMIN,
            ),
            201,
        )
        resp = api_client.create_section(
            year["id"],
            create_section_payload(room="R9", day_of_week="MON",
                                   start_time="10:00", end_time="11:00",
                                   grade="G2"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_TIME_CONFLICT)


class TestSectionValidation:
    def test_section_time_range_invalid(self):
        """PRD §2.8 step 5: "Required fields are present, types and enum
        memberships are valid, and ranges hold — `capacity` at least 1,
        `amount_cents` greater than 0, `hours` greater than 0, a section's
        `start_time` strictly earlier than its `end_time`, a closure's `start_date`
        on or before its `end_date`, and the conditional award fields on a decide
        payload; otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_input_shapes_return_invalid_request
        """
        year = create_year()
        resp = api_client.create_section(
            year["id"],
            create_section_payload(start_time="11:30", end_time="10:00"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_student_grade_enum_invalid(self):
        """PRD §3.3: "each with a `full_name`, a `grade` of `K`, `G1`, `G2`, `G3`,
        `G4`, `G5`, `G6`, or `G7`, and a `hebrew_level` of `BEGINNER`,
        `INTERMEDIATE`, or `ADVANCED`" and §2.8 step 5: "types and enum memberships
        are valid... otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_input_shapes_return_invalid_request
        """
        family = create_family()
        resp = api_client.create_student(
            family["id"],
            {"full_name": "Kid", "grade": "G9", "hebrew_level": "BEGINNER"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_capacity_patch_below_enrolled_rejected(self):
        """PRD §3.2: "or to change its `capacity`, which may not be lowered below
        the current `enrolled_count` (`ERR_CAPACITY_BELOW_ENROLLED`)."

        Design: Corner/validations/capacity_patch_below_enrolled_rejected
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        family = create_family()
        s1 = create_student(family["id"])
        s2 = create_student(family["id"])
        enroll_student_fresh(section["id"], s1["id"])
        enroll_student_fresh(section["id"], s2["id"])
        resp = api_client.patch_section(section["id"], {"capacity": 1}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_ENROLLED)


class TestPlacement:
    def test_placement_mismatch_grade_and_level(self):
        """PRD §3.3: "the student's `grade` must exactly equal the section's `grade`
        and the student's `hebrew_level` must exactly equal the section's
        `hebrew_level`, or the enrollment is rejected with
        `ERR_PLACEMENT_MISMATCH`".

        Design: Corner/validations/placement_mismatch_rejected
        """
        ctx = setup_open_year_with_section(grade="G3", hebrew_level="BEGINNER")
        section = ctx["section"]
        family = create_family()
        wrong_grade = create_student(family["id"], grade="G4", hebrew_level="BEGINNER")
        wrong_level = create_student(family["id"], grade="G3", hebrew_level="ADVANCED")
        resp_g = api_client.create_enrollment(
            section["id"],
            {"student_id": wrong_grade["id"],
             "expected_section_version": section["version"]},
            ADMIN,
        )
        validate_error(resp_g, ApiErrorId.ERR_PLACEMENT_MISMATCH)
        resp_l = api_client.create_enrollment(
            section["id"],
            {"student_id": wrong_level["id"],
             "expected_section_version": section["version"]},
            ADMIN,
        )
        validate_error(resp_l, ApiErrorId.ERR_PLACEMENT_MISMATCH)
        section_now = get_section(section["id"])
        assert section_now["enrolled_count"] == 0

    def test_duplicate_enrollment_rejected(self):
        """PRD §3.3: "the student must not already hold an enrollment in the same
        year in `REGISTERED` or `ACTIVE` status, which fails with
        `ERR_DUPLICATE_ENROLLMENT`."

        Design: Corner/validations/duplicate_enrollment_rejected
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        family = create_family()
        student = create_student(family["id"])
        enroll_student_fresh(section["id"], student["id"])
        fresh = get_section(section["id"])
        resp = api_client.create_enrollment(
            section["id"],
            {"student_id": student["id"],
             "expected_section_version": fresh["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)
