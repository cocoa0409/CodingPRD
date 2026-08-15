"""Access-control and advising-note claims: header authentication, role
authorization and its priority over existence, ownership gates, CONFIDENTIAL
authorship restriction and server-side visibility filtering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    author_note,
    create_advisor,
    create_advisor_payload,
    create_appointment_payload,
    create_note_payload,
    create_student,
    make_advisor_headers,
    make_ghost_headers,
    place_hold,
    setup_student_with_two_advisors,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Difficulty: priority_pair_validation_conflict / confidential_note_on_inactive

def test_confidential_note_on_inactive_reports_state_error(api, director_headers):
    """PRD §2.10 step 6: "and two student-state gates apply: note creation requires the student not be `INACTIVE` (`ERR_STUDENT_INACTIVE`), and assignment creation requires the student be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`). All are HTTP 409."
    PRD §2.10: "A failure at any step stops evaluation and produces that step's error, so when several problems coexist, the earliest step's error is the one reported:"

    Design: Difficulty/priority_pair_validation_conflict/confidential_note_on_inactive_student_state_beats_safety
    """
    student, advisor_a, advisor_b = setup_student_with_two_advisors()
    api.update_student(student["id"], {"care_status": "INACTIVE"}, director_headers)
    # Advisor B is both unassigned (safety violation, step 7) and the student is
    # INACTIVE (state violation, step 6): the earlier state error must win.
    res = api.create_note(
        student["id"],
        create_note_payload(visibility="CONFIDENTIAL", body="sensitive"),
        make_advisor_headers(advisor_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_INACTIVE)


def test_director_note_on_inactive_also_blocked(api, director_headers):
    """PRD §3.9: "The student must not be `INACTIVE` — attempts against an inactive student are rejected with `ERR_STUDENT_INACTIVE`, while `ON_LEAVE` students may still receive notes."
    PRD §2.10 step 6: "and two student-state gates apply: note creation requires the student not be `INACTIVE` (`ERR_STUDENT_INACTIVE`), and assignment creation requires the student be `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`). All are HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/confidential_note_on_inactive_student_state_beats_safety
    """
    student, advisor_a, advisor_b = setup_student_with_two_advisors()
    api.update_student(student["id"], {"care_status": "INACTIVE"}, director_headers)
    # The director is exempt from the confidentiality restriction but not from
    # the state gate: the state error still fires.
    res = api.create_note(
        student["id"],
        create_note_payload(visibility="CONFIDENTIAL", body="director note"),
        director_headers,
    )
    validate_error(res, ApiErrorId.ERR_STUDENT_INACTIVE)


# ─── Corner: validations / confidential_note_create_by_unassigned_rejected ────

def test_confidential_note_create_by_unassigned_rejected(api):
    """PRD §3.9: "A `CONFIDENTIAL` note may be authored only by the student's assigned advisor or by the director; any other `Advisor`-role caller attempting one is rejected with `ERR_NOTE_CONFIDENTIALITY_RESTRICTED`."

    Design: Corner/validations/confidential_note_create_by_unassigned_rejected
    """
    student, advisor_a, advisor_b = setup_student_with_two_advisors()
    # Student stays ENROLLED: the sole failure is the confidentiality gate.
    res = api.create_note(
        student["id"],
        create_note_payload(visibility="CONFIDENTIAL", body="private"),
        make_advisor_headers(advisor_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOTE_CONFIDENTIALITY_RESTRICTED)


# ─── Corner: rbac / confidential_note_visibility_filter_by_role ───────────────

def test_confidential_note_visibility_filter_by_role(api, director_headers):
    """PRD §3.9: "The note list — available to an `Advisor` or the director, with an optional `visibility` filter — is filtered server-side: `CONFIDENTIAL` notes are visible only to their author and to `AdvisingDirector` callers, while `SHARED` notes are visible to both roles."

    Design: Corner/rbac/confidential_note_visibility_filter_by_role
    """
    student, advisor_a, advisor_b = setup_student_with_two_advisors()
    author_note(
        student["id"], "CONFIDENTIAL", "secret", make_advisor_headers(advisor_a["id"])
    )
    author_note(
        student["id"], "SHARED", "public", make_advisor_headers(advisor_a["id"])
    )

    other_advisor_list, other_meta = validate_paginated(
        api.list_notes(student["id"], make_advisor_headers(advisor_b["id"]))
    )
    assert other_meta["total_count"] == 1, (
        "the unassigned advisor sees only the SHARED note"
    )
    assert other_advisor_list[0]["visibility"] == "SHARED"

    director_list, director_meta = validate_paginated(
        api.list_notes(student["id"], director_headers)
    )
    assert director_meta["total_count"] == 2, (
        "the director's override sees both notes"
    )


# ─── Corner: validations / unknown_role_header_unauthenticated ────────────────

def test_unknown_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role value outside these four, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/unknown_role_header_unauthenticated
    """
    res = api.list_students(make_ghost_headers())
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


# ─── Corner: validations / wrong_role_beats_not_found_priority ────────────────

def test_wrong_role_beats_not_found_priority(api, faculty_headers):
    """PRD §2.10: "Every request is evaluated against a fixed pipeline of checks. A failure at any step stops evaluation and produces that step's error, so when several problems coexist, the earliest step's error is the one reported:"
    PRD §2.10 step 3: "The caller's role must appear in the endpoint's authorized role list, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.10 step 4: "Path identifiers are validated left to right, then body-referenced identifiers such as `student_id`, `advisor_id`, and `referral_id`."

    Design: Corner/validations/wrong_role_beats_not_found_priority
    """
    # FacultyReferrer is not in GET /advising/students/{id}'s role list (§4);
    # the id does not exist either. Role authorization (step 3) beats existence
    # (step 4): ERR_UNAUTHORIZED_ROLE, not ERR_STUDENT_NOT_FOUND.
    res = api.get_student(NON_EXISTENT_UUID, faculty_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ─── Corner: rbac / faculty_cannot_book_appointment ───────────────────────────

def test_faculty_cannot_book_appointment(api, faculty_headers):
    """PRD §2.1: "A request whose role is valid but not in the target endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    The §4 endpoint table limits POST /advising/appointments to FrontDeskStaff, Advisor and AdvisingDirector; FacultyReferrer is not listed.

    Design: Corner/rbac/faculty_cannot_book_appointment
    """
    student = create_student(full_name="RB1", email="rb1@x.edu")
    advisor = create_advisor(full_name="Advisor RB1", email="rb1a@x.edu")
    res = api.create_appointment(
        create_appointment_payload(student["id"], advisor["id"]),
        faculty_headers,
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ─── Corner: rbac / unassigned_advisor_cannot_release_hold ────────────────────

def test_unassigned_advisor_cannot_release_hold(api, director_headers):
    """PRD §3.8: "It may be performed by the student's assigned advisor or by the director; any other `Advisor`-role caller is rejected with `ERR_NOT_ASSIGNED_ADVISOR`."
    PRD §2.10 step 7: "On ownership-gated operations, an `Advisor`-role caller must be the student's assigned advisor — meaning an `ACTIVE` assignment whose `advisor_id` equals `X-User-ID` — else `ERR_NOT_ASSIGNED_ADVISOR` (HTTP 403); `CONFIDENTIAL` note authorship carries its own restriction, else `ERR_NOTE_CONFIDENTIALITY_RESTRICTED` (HTTP 403)."

    Design: Corner/rbac/unassigned_advisor_cannot_release_hold
    """
    student, advisor_a, advisor_b = setup_student_with_two_advisors()
    hold = place_hold(student["id"], hold_type="ADVISING")
    denied = api.release_hold(
        student["id"], hold["id"], make_advisor_headers(advisor_b["id"])
    )
    validate_error(denied, ApiErrorId.ERR_NOT_ASSIGNED_ADVISOR)
    allowed = api.release_hold(
        student["id"], hold["id"], make_advisor_headers(advisor_a["id"])
    )
    released = validate_success(allowed, 200)
    assert released["status"] == "RELEASED", "the assigned advisor succeeds"


# ─── Corner: rbac / advisor_cannot_create_advisor ─────────────────────────────

def test_advisor_cannot_create_advisor(api):
    """PRD §2.1: "A request whose role is valid but not in the target endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    The §4 endpoint table limits POST /advising/advisors to AdvisingDirector alone.

    Design: Corner/rbac/advisor_cannot_create_advisor
    """
    caller = create_advisor(full_name="Advisor RB4", email="rb4@x.edu")
    res = api.create_advisor(
        create_advisor_payload(
            full_name="Sneaky", email="sn@x.edu", major_codes=["CS"], max_caseload=5
        ),
        make_advisor_headers(caller["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
