"""Faculty roster, course catalog, and qualification claims."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_faculty_member,
    create_faculty_payload,
    create_qualification_payload,
    make_course,
    make_faculty,
    make_qualification,
    make_term,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]


def test_faculty_create_with_id_input_ignored(api):
    """PRD §2.4: "`id` (string): a server-minted unique identifier, formatted as a
    UUID with no type prefix."
    PRD §3.2: "Two policy-flavored fields default when omitted: `is_union_covered`
    (default true) marks whether the union overload cap applies to this person, and
    `base_load_credits` (default 12) is the contractual per-term teaching load. ... A
    faculty member is born `ACTIVE`."

    Design: Corner/entities/c_faculty_create_with_id_input_ignored
    """
    payload = create_faculty_payload(
        full_name="Anna Aho", rank="LECTURER", base_salary_cents=7_000_000
    )
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    resp = api.create_faculty(payload, CHAIR)
    data = validate_success(resp, 201)
    assert_faculty_member(data)
    assert data["id"] != "11111111-1111-1111-1111-111111111111", (
        "client-supplied id must be ignored; the server mints its own"
    )
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"
    assert data["is_union_covered"] is True


def test_faculty_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_faculty_not_found_returns_404
    """
    resp = api.get_faculty(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_FACULTY_NOT_FOUND, 404)


def test_course_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_course_not_found_returns_404
    """
    resp = api.get_course(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_FOUND, 404)


def test_qualification_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_qualification_not_found_returns_404
    """
    resp = api.get_qualification(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_QUALIFICATION_NOT_FOUND, 404)


def test_grant_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_grant_not_found_returns_404
    """
    resp = api.get_grant(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_FOUND, 404)


def test_overload_request_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_overload_request_not_found_returns_404
    """
    resp = api.get_overload_request(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_OVERLOAD_REQUEST_NOT_FOUND, 404)


def test_load_sheet_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_load_sheet_not_found_returns_404
    """
    resp = api.get_load_sheet(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_LOAD_SHEET_NOT_FOUND, 404)


def test_duplicate_term_code_rejected(api):
    """PRD §3.1: "A duplicate `term_code` anywhere in the system is rejected with
    `ERR_DUPLICATE_TERM_CODE`."

    Design: Corner/validations/c_duplicate_term_code_rejected
    """
    from test_helpers import create_term_payload
    resp = api.create_term(create_term_payload(term_code="2026-FA"), CHAIR)
    validate_success(resp, 201)

    resp = api.create_term({
        "term_code": "2026-FA",
        "title": "Fall Again",
        "start_date": "2026-08-24",
        "census_date": "2026-09-07",
        "comp_budget_cents": 100_000,
    }, CHAIR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TERM_CODE, 409)


def test_duplicate_faculty_email_rejected(api):
    """PRD §3.2: "Creating a faculty member takes a `full_name`, an `email` that must
    be unique across all faculty (duplicates are rejected with
    `ERR_DUPLICATE_FACULTY_EMAIL`), ... ."

    Design: Corner/validations/c_duplicate_faculty_email_rejected
    """
    resp = api.create_faculty(
        create_faculty_payload(full_name="Anna Aho", email="anna-dup@x.edu",
                               rank="LECTURER", base_salary_cents=7_000_000),
        CHAIR,
    )
    validate_success(resp, 201)

    resp = api.create_faculty(
        create_faculty_payload(full_name="Anna Clone", email="anna-dup@x.edu",
                               rank="ADJUNCT", base_salary_cents=5_000_000),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FACULTY_EMAIL, 409)


def test_duplicate_active_qualification_rejected(api):
    """PRD §3.2: "At most one qualification per faculty-and-course pair may be
    `ACTIVE` at a time — a second grant for the same pair is rejected with
    `ERR_DUPLICATE_QUALIFICATION`."

    Design: Corner/validations/c_duplicate_active_qualification_rejected
    """
    course = make_course(course_code="CS-301")
    faculty = make_faculty()
    make_qualification(faculty["id"], course["id"], expires_on="2027-01-15")

    resp = api.create_qualification(
        create_qualification_payload(faculty["id"], course["id"], expires_on="2027-06-30"),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUALIFICATION, 409)


def test_faculty_separated_terminal(api):
    """PRD §3.2: "A chair may also move a faculty member to the terminal `SEPARATED`
    state from either `ACTIVE` or `ON_LEAVE`. A status edit to a state not reachable
    from the current state is rejected with `ERR_INVALID_FACULTY_STATE`."

    Design: Corner/state_machines/c_faculty_separated_terminal
    """
    faculty = make_faculty(full_name="Anna Aho", rank="LECTURER", base_salary_cents=7_000_000)
    resp = api.patch_faculty(faculty["id"], {"status": "SEPARATED"}, CHAIR)
    separated = validate_success(resp)
    assert separated["status"] == "SEPARATED"

    resp = api.patch_faculty(faculty["id"], {"status": "ACTIVE"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_FACULTY_STATE, 409)


def test_qualification_revoked_terminal(api):
    """PRD §3.2: "A chair may revoke a qualification by setting its status to
    `REVOKED`; attempting any other status value, or patching a qualification that is
    already terminal, is rejected with `ERR_INVALID_QUALIFICATION_TRANSITION`."

    Design: Corner/state_machines/c_qualification_revoked_terminal
    """
    course = make_course(course_code="CS-301")
    faculty = make_faculty()
    qual = make_qualification(faculty["id"], course["id"])
    resp = api.patch_qualification(qual["id"], {"status": "REVOKED"}, CHAIR)
    revoked = validate_success(resp)
    assert revoked["status"] == "REVOKED"

    resp = api.patch_qualification(qual["id"], {"status": "REVOKED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_QUALIFICATION_TRANSITION, 409)


def test_qualification_expired_blocks_assignment(api):
    """PRD §3.2: "Expiry is lazy and clock-driven: whenever a qualification is read or
    consulted during validation while the logical clock's date is strictly later than
    its `expires_on`, the system treats and reports it as `EXPIRED`."
    PRD §3.4: "First, qualification: an `ACTIVE` qualification must exist pairing this
    `faculty_id` with the section's course; a qualification that is missing,
    `REVOKED`, or lazily `EXPIRED` fails the check and the create is rejected with
    `ERR_NOT_QUALIFIED_FOR_COURSE`."

    Design: Corner/validations/c_qualification_expired_blocks_assignment
    """
    from test_helpers import (
        create_assignment_payload,
        make_section,
        set_clock,
    )
    term = make_term()
    course = make_course(course_code="CS-301")
    faculty = make_faculty()
    qual = make_qualification(faculty["id"], course["id"], expires_on="2026-08-10")
    section = make_section(term["id"], course["id"])
    set_clock("2026-08-11T00:00:00Z")

    got = validate_success(api.get_qualification(qual["id"], CHAIR))
    assert got["status"] == "EXPIRED", (
        "lazy expiry must report EXPIRED once the clock passes expires_on"
    )

    resp = api.create_assignment(
        create_assignment_payload(section["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_NOT_QUALIFIED_FOR_COURSE, 422)
