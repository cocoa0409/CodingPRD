"""Load summary aggregation, RBAC role gates, ownership, auth context, FK ordering."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    add_assignment,
    create_course_payload,
    create_grant_payload,
    make_admin_headers,
    make_chair_headers,
    make_course,
    make_dean_headers,
    make_faculty,
    make_faculty_headers,
    make_qualification,
    make_registrar_headers,
    make_section,
    make_term,
    setup_assignable,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role` value is
    not one of these five declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/c_missing_auth_header_returns_400
    """
    resp = api.list_terms(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_get_endpoints_allow_all_roles(api):
    """PRD §2.1: "The system recognizes exactly five roles, spelled precisely as
    follows: `DepartmentChair`, `FacultyMember`, `DeanOffice`, `Registrar`, and
    `SystemAdmin`."
    PRD §2.1: "When `X-User-Role` is `DepartmentChair`, `DeanOffice`, `Registrar`, or
    `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any
    persisted entity. The server may record it — most notably as
    `endorsed_by_user_id` on an `OverloadRequest` when a chair endorses — but it does
    not compare it to any entity's `id`, except for the segregation-of-duties
    comparison described next."
    PRD §4 lists every GET endpoint's authorized roles as Any.

    Design: Corner/rbac/c_get_endpoints_allow_all_roles
    """
    term = make_term()
    for headers in (
        make_faculty_headers("any-faculty-id"),
        make_registrar_headers(),
        make_dean_headers(),
        make_admin_headers(),
        make_chair_headers(),
    ):
        resp = api.get_term(term["id"], headers)
        data = validate_success(resp)
        assert data["id"] == term["id"]


def test_faculty_cannot_create_course(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint — including per-`to_state` role gates on the shared transition endpoints
    — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 restricts POST `/courses` to the DepartmentChair role.

    Design: Corner/rbac/c_faculty_cannot_create_course
    """
    faculty = make_faculty()
    resp = api.create_course(
        create_course_payload(course_code="CS-301"),
        make_faculty_headers(faculty["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_registrar_cannot_transition_assignment(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint — including per-`to_state` role gates on the shared transition endpoints
    — is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 restricts POST `/assignments/{assignmentId}/transition` to the
    DepartmentChair and FacultyMember roles.

    Design: Corner/rbac/c_registrar_cannot_transition_assignment
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])

    resp = api.transition_assignment(
        assignment["id"], {"to_state": "CONFIRMED"}, make_registrar_headers("registrar-1")
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_faculty_cannot_confirm_others_assignment(api):
    """PRD §2.1: "a `FacultyMember` caller may confirm or decline an assignment only
    when the assignment's `faculty_id` equals the caller's `X-User-ID`, and any
    mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`."

    Design: Corner/rbac/c_faculty_cannot_confirm_others_assignment
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    anna = make_faculty(full_name="Anna Aho")
    ben = make_faculty(full_name="Ben Berg", rank="ASSISTANT_PROFESSOR",
                       base_salary_cents=8_000_000)
    make_qualification(anna["id"], course["id"])
    make_qualification(ben["id"], course["id"])
    section = make_section(term["id"], course["id"])
    assignment = add_assignment(section["id"], anna["id"])

    resp = api.transition_assignment(
        assignment["id"], {"to_state": "CONFIRMED"}, make_faculty_headers(ben["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP, 403)

    after = validate_success(api.get_assignment(assignment["id"], CHAIR))
    assert after["status"] == "PROPOSED"


def test_body_fk_existence_left_to_right(api):
    """PRD §2.8: "Path identifiers are resolved left to right ... then body foreign
    keys in their declared input order (`term_id` before `section_id`, `faculty_id`
    before `course_id`, and so on). The first missing reference surfaces the
    corresponding not-found error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, ...
    ."

    Design: Corner/entities/c_body_fk_existence_left_to_right
    """
    term = make_term()
    # Bogus term_id masks bogus faculty_id: term is validated first.
    resp = api.create_grant(
        create_grant_payload(UNKNOWN_UUID, UNKNOWN_UUID,
                             grant_type="SABBATICAL", credits_released=1),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_FOUND, 404)

    # With a valid term the bogus faculty_id surfaces next.
    resp = api.create_grant(
        create_grant_payload(term["id"], UNKNOWN_UUID,
                             grant_type="SABBATICAL", credits_released=1),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_FACULTY_NOT_FOUND, 404)


def test_load_summary_aggregation(api):
    """PRD §3.10: "The summary aggregates over every load sheet of the term whose
    faculty member is not `SEPARATED`: `total_teaching_credits` is the sum of the
    sheets' `teaching_credits`; `overloaded_faculty_count` counts sheets whose
    `overload_credits` exceeds 0; `underloaded_faculty_count` counts sheets whose
    `underload_credits` exceeds 0; and `fairness_spread_credits` is the difference
    between the largest and smallest `teaching_credits` across those sheets, or 0
    when the term has no qualifying sheets at all. ... Preference satisfaction is
    tallied across the term's assignments in `PROPOSED` or `CONFIRMED` status:
    `preference_satisfied_count` counts those whose `matches_preference` is true, and
    `preference_unsatisfied_count` counts the rest."

    Design: Corner/calculations/c_load_summary_aggregation
    """
    # Anna prefers the course and carries 4 ONLINE proposals (14.0, overload 2.0).
    term = make_term()
    course = make_course(course_code="CS-301")
    anna = make_faculty(full_name="Anna Aho")
    make_qualification(anna["id"], course["id"])
    anna = validate_success(api.patch_faculty(
        anna["id"], {"preferred_course_ids": [course["id"]]}, CHAIR
    ))
    for i, day in enumerate(["MON", "TUE", "WED", "THU"]):
        s = make_section(term["id"], course["id"], section_number=f"{i + 1:02d}",
                         modality="ONLINE", meeting_day=day)
        add_assignment(s["id"], anna["id"])

    # Ben states no preference and carries 2 IN_PERSON proposals (6.0, underload 6.0).
    ben = make_faculty(full_name="Ben Berg", rank="ASSISTANT_PROFESSOR",
                       base_salary_cents=8_000_000)
    make_qualification(ben["id"], course["id"])
    s5 = make_section(term["id"], course["id"], section_number="05",
                      modality="IN_PERSON", meeting_day="FRI",
                      start_minute=540, end_minute=600)
    add_assignment(s5["id"], ben["id"])
    s6 = make_section(term["id"], course["id"], section_number="06",
                      modality="IN_PERSON", meeting_day="FRI",
                      start_minute=660, end_minute=720)
    add_assignment(s6["id"], ben["id"])

    summary = validate_success(api.get_load_summary(term["id"], CHAIR))
    assert summary["total_teaching_credits"] == pytest.approx(20.0), "14.0 + 6.0"
    assert summary["fairness_spread_credits"] == pytest.approx(8.0), "14.0 - 6.0"
    assert summary["overloaded_faculty_count"] == 1, "Anna 2.0 over"
    assert summary["underloaded_faculty_count"] == 1, "Ben 6.0 under"
    assert summary["preference_satisfied_count"] == 4, "Anna preferred the course"
    assert summary["preference_unsatisfied_count"] == 2, "Ben stated none"
    assert summary["comp_budget_spent_cents"] == 0
    assert summary["comp_budget_remaining_cents"] == 2_000_000
