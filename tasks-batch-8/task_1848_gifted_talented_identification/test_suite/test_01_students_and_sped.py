"""Students, enrollment, and special-education coordination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_sped_plan,
    assert_student,
    create_site,
    create_sped_plan,
    create_sped_plan_payload,
    create_student,
    create_student_payload,
    get_student,
    validate_error,
    validate_paginated,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]
SE = TEST_USERS["special_ed_coordinator_headers"]


class TestStudentCreation:
    def test_student_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "plus the `primary_guardian_user_id` of the guardian
        authorized to act for the child, and an optional `is_ell` flag
        defaulting to false. The student's `gifted_status` starts at
        `NOT_IDENTIFIED`".
        PRD §2.4: "Resources with full lifecycle tracking additionally carry
        `created_at` and `updated_at` as ISO 8601 UTC timestamps with three
        fractional digits, and a `version` integer that starts at its initial
        value on creation and increments by one on every mutation of that
        resource."

        Design: Corner/entities/student_creation_defaults_and_system_fields
        """
        site = create_site()
        resp = api.create_student(
            create_student_payload(
                student_number="ST-1", legal_name="Stu One", grade_level=3,
                school_site_id=site["id"], demographic_group="ASIAN",
                primary_guardian_user_id="guard-1"),
            GC)
        data = validate_success(resp, 201)
        assert_student(data)
        assert data["is_ell"] is False, "is_ell must default to false when omitted"
        assert data["gifted_status"] == "NOT_IDENTIFIED"
        assert data["has_active_sped_plan"] is False

    def test_student_missing_required_returns_invalid_request(self, api):
        """PRD §3.1: "Each `Student` is enrolled with a district-unique
        `student_number`, a `legal_name`, a `grade_level` from 0 (kindergarten)
        through 12 inclusive, the `school_site_id` of the enrollment site, a
        `demographic_group` drawn from `AMERICAN_INDIAN`, `ASIAN`, `BLACK`,
        `HISPANIC`, `WHITE`, `MULTIRACIAL`, or `PACIFIC_ISLER` — spelled
        exactly `PACIFIC_ISLANDER`".
        PRD §2.5: "Request shape — required fields, types, enum membership,
        numeric ranges, date ordering, weight sums, cut-band sanity,
        pathway-conditional fields, future dates (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/student_missing_required_returns_invalid_request
        """
        site = create_site()
        payload = create_student_payload(
            student_number="ST-1", legal_name="Stu One", grade_level=3,
            school_site_id=site["id"], primary_guardian_user_id="guard-1")
        payload.pop("demographic_group")
        resp = api.create_student(payload, GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_student_get_not_found_returns_not_found(self, api):
        """PRD §2.5: "4. Path-parameter existence, validated left-to-right
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/student_get_not_found_returns_not_found
        """
        resp = api.get_student(NON_EXISTENT_UUID, GC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestSpedPlan:
    def test_sped_plan_creation_marks_twice_exceptional(self, api):
        """PRD §3.1: "Registering the plan sets the student's
        `has_active_sped_plan` flag to true".

        Design: Corner/entities/sped_plan_creation_marks_twice_exceptional
        """
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=5)
        resp = api.create_sped_plan(
            student["id"],
            create_sped_plan_payload(plan_type="IEP", started_on="2026-01-15"),
            SE)
        plan = validate_success(resp, 201)
        assert_sped_plan(plan)
        assert plan["plan_type"] == "IEP"
        assert plan["student_id"] == student["id"]
        after = get_student(student["id"])
        assert after["has_active_sped_plan"] is True, (
            "has_active_sped_plan must flip to true after plan registration")

    def test_duplicate_sped_plan_rejected(self, api):
        """PRD §3.1: "At most one plan may exist per student — a second
        registration is refused with `ERR_DUPLICATE_SPED_PLAN`".

        Design: Corner/entities/duplicate_sped_plan_rejected
        """
        site = create_site()
        student = create_student(site["id"], student_number="ST-1",
                                 legal_name="Stu One", grade_level=5)
        create_sped_plan(student["id"], plan_type="IEP",
                         started_on="2026-01-15")
        resp = api.create_sped_plan(
            student["id"],
            create_sped_plan_payload(plan_type="PLAN_504",
                                     started_on="2026-06-01"),
            SE)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SPED_PLAN.value)


class TestBulkEnroll:
    def test_bulk_enroll_creates_roster(self, api):
        """PRD §3.1: "a coordinator may instead bulk-enroll `count` students
        sharing one `school_site_id`, `grade_level`, and `demographic_group`;
        the server mints their `student_number` values, leaves
        `primary_guardian_user_id` null on the bulk rows, and returns
        `created_count` alongside the minted `student_ids`."

        Design: Corner/endpoints/bulk_enroll_creates_roster
        """
        site = create_site()
        resp = api.bulk_enroll_students(
            {"school_site_id": site["id"], "grade_level": 4,
             "demographic_group": "ASIAN", "count": 15},
            GC)
        data = validate_success(resp, 201)
        assert data["created_count"] == 15
        ids = data["student_ids"]
        assert isinstance(ids, list) and len(ids) == 15
        assert len(set(ids)) == 15, "student_ids must be distinct"

        lst_resp = api.list_site_students(
            site["id"], GC, params={"demographic_group": "ASIAN", "limit": 100})
        students, meta = validate_paginated(lst_resp)
        assert meta["total_count"] == 15
        assert len(students) == 15
