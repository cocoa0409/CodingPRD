"""Programs, students, and terms: creation defaults, uniqueness, shape rules."""
import pytest

from test_helpers import (
    AID_OFFICER, NON_EXISTENT_UUID, REGISTRAR, api_client, create_program,
    create_student, create_term, is_valid_uuid, program_payload,
    student_payload, term_payload, validate_error, validate_paginated,
    validate_success,
)


def test_program_create_applies_policy_defaults(api):
    """PRD section 3.1: "The qualitative standard `min_gpa` defaults to 2.0 and is
    compared against the student's cumulative GPA at three-decimal precision. The
    quantitative standard `min_pace_pct` defaults to 67.0 and is compared against the
    student's pace percentage at two-decimal precision."
    PRD section 3.1: "When a suspension is evaluated, `appeal_window_days` (default 14)
    fixes how many days the student has to submit an appeal, with the deadline day itself
    still open. Finally, `reminder_offset_days` (default the two-entry list 7 and 13)
    fixes the days after a suspension evaluation at which appeal-deadline reminders are
    scheduled to reach the student."

    Design: Corner/entities/program_create_applies_policy_defaults
    """
    res = api.create_program(
        program_payload(code="BS-DEF", name="Defaults", required_credits=120), REGISTRAR)
    program = validate_success(res, 201)
    assert program["min_gpa"] == pytest.approx(2.0)
    assert program["min_pace_pct"] == pytest.approx(67.0)
    assert program["appeal_window_days"] == 14
    assert program["reminder_offset_days"] == [7, 13]


def test_program_duplicate_code_returns_conflict(api):
    """PRD section 3.1: "A duplicate `code` is rejected with
    `ERR_PROGRAM_CODE_CONFLICT`, and the creation is recorded with a `PROGRAM_CREATED`
    audit event."

    Design: Corner/entities/program_duplicate_code_returns_conflict
    """
    first = validate_success(api.create_program(
        program_payload(code="BS-DUP", name="First", required_credits=120), REGISTRAR), 201)
    res = api.create_program(
        program_payload(code="BS-DUP", name="Second", required_credits=90), REGISTRAR)
    validate_error(res, "ERR_PROGRAM_CODE_CONFLICT")

    reread = validate_success(api.get_program(first["id"], REGISTRAR), 200)
    assert reread["name"] == "First"
    assert reread["required_credits"] == 120


def test_student_create_initial_state(api):
    """PRD section 3.2: "The new record starts in `GOOD_STANDING` with zeroed cumulative
    counters and `max_tf_exceeded` false, and any computed or system-managed fields
    supplied in the creation body are ignored."
    PRD section 3.3: "The pace metric `pace_pct` is one hundred times the summed earned
    credits divided by the summed attempted credits, rounded half up to two decimal
    places; it is null when no attempted credits exist at all."
    PRD section 2.5: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/student_create_initial_state
    """
    program = create_program(code="BS-INIT", name="Init", required_credits=120)
    res = api.create_student(
        student_payload(program["id"], student_number="S-0001", full_name="Init Student"),
        REGISTRAR)
    student = validate_success(res, 201)
    assert student["sap_status"] == "GOOD_STANDING"
    assert student["cumulative_attempted_credits"] == 0
    assert student["cumulative_earned_credits"] == 0
    assert student["cumulative_gpa"] is None, "no GPA hours -> null cumulative GPA"
    assert student["pace_pct"] is None, "no attempted credits -> null pace"
    assert student["max_tf_exceeded"] is False
    assert is_valid_uuid(student["id"]), "id must be a server-minted UUID"
    assert isinstance(student["version"], int)


def test_student_duplicate_number_returns_conflict(api):
    """PRD section 3.2: "Before any enrollment exists, a `Registrar` registers the
    student with a unique `student_number` — duplicates are rejected with
    `ERR_STUDENT_NUMBER_CONFLICT` — along with the `full_name` and the `program_id` of
    the program of enrollment."

    Design: Corner/entities/student_duplicate_number_returns_conflict
    """
    program_a = create_program(code="BS-A", name="A", required_credits=120)
    program_b = create_program(code="BS-B", name="B", required_credits=90)
    validate_success(api.create_student(
        student_payload(program_a["id"], student_number="S-0002", full_name="First"),
        REGISTRAR), 201)
    res = api.create_student(
        student_payload(program_b["id"], student_number="S-0002", full_name="Second"),
        REGISTRAR)
    validate_error(res, "ERR_STUDENT_NUMBER_CONFLICT")


def test_student_create_computed_fields_input_ignored(api):
    """PRD section 3.2: "The new record starts in `GOOD_STANDING` with zeroed cumulative
    counters and `max_tf_exceeded` false, and any computed or system-managed fields
    supplied in the creation body are ignored."

    Design: Corner/entities/student_create_computed_fields_input_ignored
    """
    program = create_program(code="BS-IGN", name="Ignore", required_credits=120)
    payload = student_payload(program["id"], student_number="S-0003", full_name="Sneaky")
    payload["sap_status"] = "SUSPENSION"
    payload["cumulative_earned_credits"] = 999
    student = validate_success(api.create_student(payload, REGISTRAR), 201)
    assert student["sap_status"] == "GOOD_STANDING"
    assert student["cumulative_earned_credits"] == 0


def test_term_create_end_before_start_returns_invalid_request(api):
    """PRD section 3.2: "Creating a term takes a `code` such as `2026FA`, a
    monotonically increasing ordinal `seq` that later drives academic-plan coverage
    arithmetic, and a `start_date`/`end_date` pair interpreted as a closed interval —
    the start must fall on or before the end, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/term_create_end_before_start_returns_invalid_request
    """
    res = api.create_term(
        term_payload(1, "2026-05-08", "2026-01-12", code="TBAD"), REGISTRAR)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_enrollment_get_nonexistent_returns_not_found(api):
    """PRD section 2.9: "The request is rejected with `ERR_NOT_FOUND` for the first
    identifier that does not resolve, and no further validation runs."

    Design: Corner/entities/enrollment_get_nonexistent_returns_not_found
    """
    res = api.get_enrollment(NON_EXISTENT_UUID, AID_OFFICER)
    validate_error(res, "ERR_NOT_FOUND")


def test_students_list_pagination_and_envelope(api):
    """PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD section 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/students_list_pagination_and_envelope
    """
    program = create_program(code="BS-PAG", name="Paging", required_credits=120)
    for number in ("S-P01", "S-P02", "S-P03"):
        create_student(program["id"], student_number=number)

    resp = api.list_students(AID_OFFICER, params={"limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert isinstance(resp.json()["meta"].get("api_request_id"), str)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_students(AID_OFFICER, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


class TestTermDateOverlap:
    """Closed-interval date semantics on the term calendar."""

    def test_touching_term_intervals_rejected(self, api):
        """PRD section 3.2: "A new term may not intersect any existing term's interval
        under closed-interval semantics: both boundary days count as occupied, so two
        ranges that merely touch on a single calendar day still conflict and the create
        fails with `ERR_TERM_DATE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/term_date_intervals_touching_rejected
        """
        create_term(1, "2026-01-12", "2026-05-08", code="T1")
        res = api.create_term(
            term_payload(2, "2026-05-08", "2026-08-14", code="T2-TOUCH"), REGISTRAR)
        validate_error(res, "ERR_TERM_DATE_OVERLAP")

    def test_one_day_gap_term_accepted(self, api):
        """PRD section 3.2: "A new term may not intersect any existing term's interval
        under closed-interval semantics: both boundary days count as occupied, so two
        ranges that merely touch on a single calendar day still conflict and the create
        fails with `ERR_TERM_DATE_OVERLAP`."
        PRD section 3.2: "Terms open in `OPEN` status, and creation appends
        `TERM_CREATED`."

        Design: Difficulty/resource_temporal_overlap/term_date_intervals_touching_rejected
        """
        create_term(1, "2026-01-12", "2026-05-08", code="T1")
        res = api.create_term(
            term_payload(2, "2026-05-09", "2026-08-14", code="T2"), REGISTRAR)
        term = validate_success(res, 201)
        assert term["status"] == "OPEN"
        assert term["start_date"] == "2026-05-09"
