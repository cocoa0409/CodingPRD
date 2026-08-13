"""Student registration, retrieval, listing, and academic record snapshots."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_student,
    assert_student_record,
    create_student_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_student_headers,
    publish_record,
    reset_clock,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    create_student,
)


class TestStudentCrud:
    def test_student_creation_returns_201_with_system_fields(self, api, admin_headers):
        """PRD §2.4: "Most entities additionally carry `created_at` (ISO 8601 UTC
        with three fractional digits), `updated_at` (refreshed on every mutation),
        and `version` (an integer starting at 1, incremented by exactly 1 on every
        mutation)."
        PRD §3.1: "`ferpa_restricted` defaults to false" and
        "`archived_record_flag` defaults to false" and "`status` defaults to `ACTIVE`".

        Design: Corner/entities/student_creation_returns_201_with_system_fields
        """
        reset_clock()
        resp = api.create_student(
            {
                "student_number": "SB000001",
                "full_name": "Sam B",
                "date_of_birth": "2000-01-01",
                "email": "sam@example.edu",
            },
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_student(data)
        assert data["version"] == 1, f"version must start at 1, got {data['version']}"
        assert data["ferpa_restricted"] is False
        assert data["archived_record_flag"] is False
        assert data["status"] == "ACTIVE"

    def test_student_get_by_id_returns_stored(self, api, admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/student_get_by_id_returns_stored
        """
        reset_clock()
        created = create_student(
            student_number="SB000002",
            full_name="Sam C",
            date_of_birth="2001-02-02",
            email="samc@example.edu",
        )
        resp = api.get_student(created["id"], admin_headers)
        data = validate_success(resp, expected_status=200)
        assert_student(data)
        assert data["student_number"] == "SB000002"
        assert data["full_name"] == "Sam C"

    def test_student_list_pagination_fields_present(self, api, admin_headers):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` block."

        Design: Corner/entities/student_list_pagination_fields_present
        """
        reset_clock()
        create_student(
            student_number="SB000101", full_name="A",
            date_of_birth="2000-01-01", email="a@x.edu",
        )
        create_student(
            student_number="SB000102", full_name="B",
            date_of_birth="2000-01-01", email="b@x.edu",
        )
        create_student(
            student_number="SB000103", full_name="C",
            date_of_birth="2000-01-01", email="c@x.edu",
        )
        resp = api.list_students(admin_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    def test_student_get_not_found_returns_404(self, api, admin_headers):
        """PRD §2.5: "followed by left-to-right existence resolution of every
        path-templated resource (`ERR_NOT_FOUND`, 404)".

        Design: Corner/entities/student_get_not_found_returns_404
        """
        reset_clock()
        resp = api.get_student(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_student_missing_required_field_returns_400(self, api, admin_headers):
        """PRD §2.5: "and finally generic shape validation (`ERR_INVALID_REQUEST`,
        400)".
        PRD §3.1: "A `RegistrarAdmin` registers a student by supplying
        `student_number` (unique across the tenant, six to twelve alphanumeric
        characters), `full_name` (the legal name on record), `date_of_birth` (an
        ISO 8601 date consumed by identity verification), and `email`."

        Design: Corner/entities/student_missing_required_field_returns_400
        """
        reset_clock()
        resp = api.create_student(
            {"full_name": "NoNum", "date_of_birth": "2000-01-01", "email": "n@x.edu"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStudentRecords:
    def test_student_record_gpa_computed_ignores_input(self, api, admin_headers):
        """PRD §3.1: "The server computes `gpa_cents` from that course list: it
        sums, over every course, the product of that course's `grade_points` and
        `credits`; it separately sums the `credits` across the same list; if the
        credit total is greater than zero the GPA in cents is one hundred times
        the point total divided by the credit total, rounded half-up to the
        nearest integer; if the credit total is zero the GPA in cents is 0."

        Design: Corner/entities/student_record_gpa_computed_ignores_input
        """
        reset_clock()
        student = create_student(
            student_number="SB000201", full_name="GPA T",
            date_of_birth="2000-01-01", email="gpa@x.edu",
        )
        # (4.0*3 + 3.0*3) / 6 = 21/6 = 3.5 -> 350 cents
        resp = api.publish_student_record(
            student["id"],
            {
                "effective_term": "2026-SPR",
                "earned_credits": 6,
                "courses": [
                    {"grade_points": 4.0, "credits": 3},
                    {"grade_points": 3.0, "credits": 3},
                ],
            },
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_student_record(data)
        assert data["gpa_cents"] == 350, f"expected gpa_cents 350, got {data['gpa_cents']}"
        assert data["record_version"] == 1

    def test_gpa_weighted_average_correct_result(self, api, admin_headers):
        """PRD §3.1: "if the credit total is greater than zero the GPA in cents is
        one hundred times the point total divided by the credit total, rounded
        half-up to the nearest integer".

        Design: Corner/calculations/gpa_weighted_average_correct_result
        """
        reset_clock()
        student = create_student(
            student_number="SC001001", full_name="G Calc",
            date_of_birth="2000-01-01", email="g@x.edu",
        )
        # (4.0*3 + 2.0*1) / 4 = 14/4 = 3.5 -> 350 cents
        resp = api.publish_student_record(
            student["id"],
            {
                "effective_term": "2026-SPR",
                "earned_credits": 4,
                "courses": [
                    {"grade_points": 4.0, "credits": 3},
                    {"grade_points": 2.0, "credits": 1},
                ],
            },
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["gpa_cents"] == 350, f"expected gpa_cents 350, got {data['gpa_cents']}"

    def test_derived_field_reconciliation_is_current_on_record_publish(self, api, admin_headers):
        """PRD §3.1: "Each snapshot carries a monotonically increasing
        `record_version` starting at 1, and exactly one snapshot per student has
        `is_current` set to true — the act of publishing flips every prior
        snapshot for that student to `is_current` false and increments the owning
        student's `version` by 1."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_is_current_on_record_publish
        """
        reset_clock()
        student = create_student(
            student_number="SC006301", full_name="DR T",
            date_of_birth="2000-01-01", email="dr@x.edu",
        )
        rec1 = publish_record(
            student["id"],
            effective_term="2025-FALL",
            earned_credits=3,
            courses=[{"grade_points": 3.0, "credits": 3}],
        )
        assert rec1["record_version"] == 1
        assert rec1["is_current"] is True

        rec2 = publish_record(
            student["id"],
            effective_term="2026-SPR",
            earned_credits=6,
            courses=[{"grade_points": 4.0, "credits": 3}],
        )
        assert rec2["record_version"] == 2
        assert rec2["is_current"] is True

        resp = api.list_student_records(student["id"], admin_headers)
        data, _meta = validate_paginated(resp)
        by_id = {r["id"]: r for r in data}
        assert by_id[rec1["id"]]["is_current"] is False
        assert by_id[rec2["id"]]["is_current"] is True
