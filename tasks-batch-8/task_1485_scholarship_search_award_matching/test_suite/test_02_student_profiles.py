"""Student profile creation, computed aid figures, versioning, archival."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    MISSING_UUID,
    TEST_USERS,
    assert_instant_equal,
    assert_millisecond_timestamp,
    assert_student,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_student,
    get_success_data,
    is_valid_uuid,
    make_coordinator_headers,
    set_clock,
    setup_accepted_award,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestStudentCreation:
    def test_missing_required_gpa_rejected(self, api):
        """PRD §2.8: "**Request shape** — required fields are present, enum
        values are valid, and date ranges are ordered (the application close
        must be later than the application open; a cycle's `ends_on` must be
        later than its `starts_on`; a disbursement's `term_end_date` must be
        on or after its `term_start_date`); otherwise `ERR_VALIDATION` or
        `ERR_INVALID_DATE_RANGE`."
        PRD §3.1 lists the registration inputs (with only
        `verified_gpa_hundredths` and `tags` called out as optional): "A
        `ScholarshipCoordinator` registers each student with a `full_name`, a
        unique `email` (no two students may share an email address), a
        `grade_level` from 9 to 12, a self-reported `gpa_hundredths` between
        0 and 500, a two-letter `residency_state`, an `intended_major` drawn
        from `STEM`, `ARTS`, `BUSINESS`, `HEALTH`, `TRADES`, or `UNDECIDED`,
        the annual `household_income_cents`, the `efc_cents` expected family
        contribution, the `cost_of_attendance_cents` at the student's
        institution, and the `institution_name` itself."

        Design: Corner/entities/student_create_missing_required_gpa_rejected
        """
        payload = {
            "full_name": "No Gpa",
            "email": "nogpa@test.example",
            "grade_level": 12,
            "residency_state": "CA",
            "intended_major": "STEM",
            "household_income_cents": 5000000,
            "efc_cents": 0,
            "cost_of_attendance_cents": 3000000,
            "institution_name": "State U",
        }
        resp = api.create_student(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_defaults_applied_on_create(self, api):
        """PRD §3.1: "when omitted, `tags` starts empty. A new student begins
        with `status` `ACTIVE`."
        PRD §3.1: "The `aid_cap_cents` is the student's annual need cap: the
        `cost_of_attendance_cents` minus the `efc_cents`, computed at
        registration and recomputed whenever either input changes."

        Design: Corner/entities/student_defaults_applied_on_create
        """
        resp = api.create_student(
            {
                "full_name": "Def Ault",
                "email": "def@test.example",
                "grade_level": 11,
                "gpa_hundredths": 300,
                "residency_state": "OR",
                "intended_major": "ARTS",
                "household_income_cents": 4000000,
                "efc_cents": 1000000,
                "cost_of_attendance_cents": 2500000,
                "institution_name": "State U",
            },
            COORD,
        )
        student = validate_success(resp, expected_status=201)
        assert_student(student)
        assert student["tags"] == [], "omitted tags default to []"
        assert student["status"] == "ACTIVE"
        assert student["aid_cap_cents"] == 1500000, (
            "aid_cap = cost_of_attendance 2500000 - efc 1000000"
        )
        assert student["verified_gpa_hundredths"] is None

    def test_get_not_found_returns_404(self, api):
        """PRD §2.8: "**Existence** — path-referenced and body-referenced
        identifiers exist, validated left to right, so the first missing
        identifier in the path determines the `ERR_NOT_FOUND` rejection."

        Design: Corner/entities/student_get_not_found_returns_404
        """
        resp = api.get_student(MISSING_UUID, COORD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestVersionAndTimestamps:
    def test_version_increments_and_updated_at_refresh(self, api):
        """PRD §3.1: "Each update increments the student's `version` by one."
        PRD §2.4: "`updated_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording the resource's last modification; it is
        refreshed on any change to the resource."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/cross_cutting_layers/version_increments_and_updated_at_refresh
        """
        student = create_student(tags=[])
        v_1 = student["version"]
        created = student["created_at"]
        assert_millisecond_timestamp(created, "created_at")
        assert_millisecond_timestamp(student["updated_at"], "updated_at")
        assert_instant_equal(student["updated_at"], created, "updated_at at create")
        assert_instant_equal(created, CLOCK["STARTUP_DEFAULT"], "created_at")

        set_clock("2026-08-03T00:00:00Z")
        updated = validate_success(
            api.patch_student(student["id"], {"tags": ["VETERAN"]}, COORD)
        )
        assert updated["version"] == v_1 + 1, "update increments version by one"
        assert_instant_equal(updated["created_at"], created, "created_at immutable")
        assert_instant_equal(
            updated["updated_at"], "2026-08-03T00:00:00Z", "updated_at refreshed"
        )


class TestAidSummary:
    def test_aid_summary_computed_read(self, api):
        """PRD §3.1: "A dedicated aid-summary read exposes all four figures
        together with a per-award breakdown, and is available to the
        coordinator, the student, and the financial aid officer."
        PRD §3.1: "The `total_accepted_cents` sums `amount_cents` over the
        student's awards whose `offer_status` is `ACCEPTED`."
        PRD §3.1: "The `excess_cents` is the amount by which accepted aid
        exceeds the need cap — zero when `total_accepted_cents` is at or
        below `aid_cap_cents`, and the difference otherwise — and it is
        recomputed on every award amount or status change."

        Design: Corner/endpoints/aid_summary_computed_read
        """
        ctx = setup_accepted_award(
            amount_cents=800000,
            student_overrides={
                "household_income_cents": 2000000,
                "efc_cents": 1000000,
                "cost_of_attendance_cents": 3000000,
            },
            program_overrides={"program_type": "NEED", "award_amount_cents": 800000},
        )
        student_id = ctx["students"][0]["id"]
        summary = validate_success(api.get_aid_summary(student_id, COORD))
        assert summary["total_accepted_cents"] == 800000
        assert summary["total_disbursed_cents"] == 0
        assert summary["aid_cap_cents"] == 2000000
        assert summary["excess_cents"] == 0


class TestStudentArchiveGuard:
    def test_archive_guard_and_archived_application_gate(self, api):
        """PRD §3.1: "Archiving moves a student from `ACTIVE` to `ARCHIVED` as
        a soft delete — the record remains readable — and is refused with
        `ERR_INVALID_STATE` while the student has any application in `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, or `WAITLISTED`, or any award
        with `offer_status` `OFFERED` or `ACCEPTED`."
        PRD §3.3: "Two gates guard creation: the student's `status` must be
        `ACTIVE` (otherwise `ERR_INVALID_STATE`), and no other application
        may already exist for the same student-and-program pair in a
        non-terminal status — that is, in `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `SELECTED`, `WAITLISTED`, or `AWARDED` — otherwise
        the create is refused with `ERR_DUPLICATE_APPLICATION`."

        Design: Corner/state_machines/student_archive_guard_and_archived_application_gate
        """
        s_a = create_student()
        create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app_a = create_draft_application(s_a["id"], program["id"])

        # A DRAFT application blocks archival.
        resp = api.archive_student(s_a["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # After withdrawal the archive succeeds; the record stays readable.
        get_success_data(api.withdraw_application(app_a["id"], COORD))
        archived = validate_success(api.archive_student(s_a["id"], COORD))
        assert archived["status"] == "ARCHIVED"
        reread = validate_success(api.get_student(s_a["id"], COORD))
        assert reread["status"] == "ARCHIVED", "soft-deleted record remains readable"

        # An ARCHIVED student cannot open new applications.
        resp = api.create_application(
            {"student_id": s_a["id"], "program_id": program["id"]}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_archive_blocked_by_open_award(self, api):
        """PRD §3.1: "Archiving moves a student from `ACTIVE` to `ARCHIVED` as
        a soft delete — the record remains readable — and is refused with
        `ERR_INVALID_STATE` while the student has any application in `DRAFT`,
        `SUBMITTED`, `UNDER_REVIEW`, `SELECTED`, or `WAITLISTED`, or any award
        with `offer_status` `OFFERED` or `ACCEPTED`."

        Design: Corner/state_machines/student_archive_guard_and_archived_application_gate
        """
        ctx = setup_accepted_award()
        student_id = ctx["students"][0]["id"]
        resp = api.archive_student(student_id, make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        reread = validate_success(api.get_student(student_id, COORD))
        assert reread["status"] == "ACTIVE"
        assert is_valid_uuid(reread["id"])
