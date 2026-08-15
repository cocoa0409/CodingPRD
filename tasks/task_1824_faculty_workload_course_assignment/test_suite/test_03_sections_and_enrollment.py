"""Section scheduling, modality/time-range rules, enrollment sync, and section OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    create_section_payload,
    make_course,
    make_faculty,
    make_qualification,
    make_section,
    make_term,
    validate_error,
    validate_paginated,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_section_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_section_not_found_returns_404
    """
    resp = api.get_section(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_FOUND, 404)


def test_assignment_not_found_returns_404(api):
    """PRD §2.8: "The first missing reference surfaces the corresponding not-found
    error: `ERR_TERM_NOT_FOUND`, `ERR_FACULTY_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`,
    `ERR_QUALIFICATION_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_OVERLOAD_REQUEST_NOT_FOUND`, or
    `ERR_LOAD_SHEET_NOT_FOUND`."

    Design: Corner/entities/c_assignment_not_found_returns_404
    """
    resp = api.get_assignment(UNKNOWN_UUID, CHAIR)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND, 404)


def test_sections_list_pagination_and_filter(api):
    """PRD §2.3: "Endpoints that return lists of resources are paginated via query
    parameters. The `limit` parameter sets the maximum number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items to skip and defaults to 0."
    PRD §4 documents GET `/course-sections` with optional `term_id`, `course_id`,
    and `status` filters.

    Design: Corner/entities/c_sections_list_pagination_and_filter
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    s1 = make_section(term["id"], course["id"], section_number="01", meeting_day="MON")
    make_section(term["id"], course["id"], section_number="02", meeting_day="TUE", schedule=False)
    make_section(term["id"], course["id"], section_number="03", meeting_day="WED", schedule=False)

    rows, meta = validate_paginated(
        api.list_sections(CHAIR, params={"term_id": term["id"], "limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(
        api.list_sections(CHAIR, params={"term_id": term["id"], "status": "SCHEDULED"})
    )
    assert meta2["total_count"] == 1
    assert all(r["status"] == "SCHEDULED" for r in rows2)
    assert rows2[0]["id"] == s1["id"]


def test_duplicate_section_number_rejected(api):
    """PRD §3.3: "Creating a section takes the `term_id` and `course_id` it belongs
    to, a `section_number` (unique within its term-and-course pair, e.g. `01`; a
    collision is rejected with `ERR_DUPLICATE_SECTION`), ... ."

    Design: Corner/validations/c_duplicate_section_number_rejected
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    make_section(term["id"], course["id"], section_number="01", schedule=False)

    resp = api.create_section(
        create_section_payload(
            term["id"], course["id"], section_number="01", modality="ONLINE",
            meeting_day="TUE",
        ),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SECTION, 409)


def test_modality_not_allowed_rejected(api):
    """PRD §3.3: "... a `modality` that must be a member of the course's
    `allowed_modalities` (else `ERR_MODALITY_NOT_ALLOWED`), ... ."

    Design: Corner/validations/c_modality_not_allowed_rejected
    """
    term = make_term()
    course = make_course(
        course_code="CS-101L", title="Intro Lab", course_type="LAB", base_credits=2,
        default_enrollment_cap=24, allowed_modalities=["IN_PERSON"],
    )
    resp = api.create_section(
        create_section_payload(
            term["id"], course["id"], section_number="01", modality="ONLINE",
            meeting_day="MON",
        ),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_MODALITY_NOT_ALLOWED, 422)


def test_section_invalid_time_range_rejected(api):
    """PRD §3.3: "... a meeting window expressed as `start_minute` and `end_minute`,
    minutes since midnight in the range 0 through 1439, where the end must be
    strictly later than the start (violations surface as `ERR_INVALID_TIME_RANGE`)."

    Design: Corner/validations/c_section_invalid_time_range_rejected
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    resp = api.create_section(
        create_section_payload(
            term["id"], course["id"], section_number="01", modality="IN_PERSON",
            meeting_day="MON", start_minute=600, end_minute=600,
        ),
        CHAIR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 400)


def test_enrollment_exceeds_cap_rejected(api):
    """PRD §3.3: "The sync rejects an `enrolled_count` above the section's
    `enrollment_cap` with `ERR_ENROLLMENT_EXCEEDS_CAP` and a negative count with
    `ERR_VALIDATION`, and it increments the section's `version` on success."

    Design: Corner/validations/c_enrollment_exceeds_cap_rejected
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"],
                         default_enrollment_cap=30)
    section = make_section(term["id"], course["id"], schedule=False)
    assert section["enrollment_cap"] == 30, "cap must default from the course"

    resp = api.enrollment_sync(
        section["id"],
        {"enrolled_count": 31, "expected_section_version": section["version"]},
        REGISTRAR,
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_EXCEEDS_CAP, 422)

    after = validate_success(api.get_section(section["id"], CHAIR))
    assert after["enrolled_count"] == 0, "rejected sync must not move enrollment"
    assert after["version"] == section["version"], "rejected sync must not bump version"


def test_enrollment_sync_stale_version_412(api):
    """PRD §2.5: "A registrar enrollment sync on a course section must carry
    `expected_section_version`, likewise non-optional, whose value must equal the
    section's current `version`. A sync whose `expected_section_version` no longer
    matches — because a prior sync already advanced the section's version — is
    rejected with `ERR_STALE_VERSION` (HTTP 412): the registrar feed is acting on a
    stale view of the section."

    Design: Corner/cross_cutting_layers/c_enrollment_sync_stale_version_412
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    section = make_section(term["id"], course["id"], schedule=False)
    assert section["version"] == 1

    resp = api.enrollment_sync(
        section["id"], {"enrolled_count": 10, "expected_section_version": 1}, REGISTRAR
    )
    synced = validate_success(resp)
    assert synced["version"] == 2
    assert synced["enrolled_count"] == 10

    resp = api.enrollment_sync(
        section["id"], {"enrolled_count": 25, "expected_section_version": 1}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    after = validate_success(api.get_section(section["id"], CHAIR))
    assert after["enrolled_count"] == 10, "stale write must be rejected without effect"


def test_version_increments_on_mutation(api):
    """PRD §2.4: "`version` (integer): a system-managed integer that increments by
    exactly 1 on every mutation of the resource."
    PRD §2.4: "A transition call on an entity bumps that entity's `version` by 1 even
    when the transition carries no other field changes."

    Design: Corner/cross_cutting_layers/c_version_increments_on_mutation
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    resp = api.create_section(
        create_section_payload(term["id"], course["id"], section_number="01",
                               modality="IN_PERSON", meeting_day="MON"),
        CHAIR,
    )
    section = validate_success(resp, 201)
    assert section["version"] == 1

    resp = api.transition_section(section["id"], {"to_state": "SCHEDULED"}, CHAIR)
    scheduled = validate_success(resp)
    assert scheduled["version"] == 2

    resp = api.enrollment_sync(
        section["id"], {"enrolled_count": 5, "expected_section_version": 2}, REGISTRAR
    )
    synced = validate_success(resp)
    assert synced["version"] == 3


def test_section_cancelled_terminal(api):
    """PRD §3.6: "A chair may cancel a section from any of `PROPOSED`, `SCHEDULED`, or
    `STAFFED`; `CANCELLED` is terminal."
    PRD §3.3: "Direct transitions the state machine does not define — such as jumping
    a section straight from `PROPOSED` to `STAFFED`, or acting on a `CANCELLED`
    section — are rejected with `ERR_INVALID_SECTION_TRANSITION`."

    Design: Corner/state_machines/c_section_cancelled_terminal
    """
    term = make_term()
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    section = make_section(term["id"], course["id"], schedule=False)
    resp = api.transition_section(section["id"], {"to_state": "CANCELLED"}, CHAIR)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"

    resp = api.transition_section(section["id"], {"to_state": "SCHEDULED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_SECTION_TRANSITION, 409)

    after = validate_success(api.get_section(section["id"], CHAIR))
    assert after["status"] == "CANCELLED"


def test_section_schedule_depends_on_term_status__draft_allowed(api):
    """PRD §3.3: "The chair schedules a proposed section, moving it from `PROPOSED` to
    `SCHEDULED`; this transition is permitted only while the term is in `DRAFT` or
    `OPEN`, and otherwise fails with `ERR_INVALID_TERM_STATE`."

    Design: Difficulty/cross_entity_state_dependency/section_schedule_depends_on_term_status
    """
    term = make_term(open_it=False)
    assert term["status"] == "DRAFT"
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    section = make_section(term["id"], course["id"], schedule=False)

    resp = api.transition_section(section["id"], {"to_state": "SCHEDULED"}, CHAIR)
    scheduled = validate_success(resp)
    assert scheduled["status"] == "SCHEDULED", (
        "scheduling must be permitted while the term is DRAFT"
    )


def test_section_schedule_depends_on_term_status__locked_rejected(api):
    """PRD §3.3: "The chair schedules a proposed section, moving it from `PROPOSED` to
    `SCHEDULED`; this transition is permitted only while the term is in `DRAFT` or
    `OPEN`, and otherwise fails with `ERR_INVALID_TERM_STATE`."

    Design: Difficulty/cross_entity_state_dependency/section_schedule_depends_on_term_status
    """
    from test_helpers import transition_term
    term = make_term(open_it=False)
    course = make_course(course_code="CS-301", allowed_modalities=["IN_PERSON"])
    s1 = make_section(term["id"], course["id"], section_number="01", meeting_day="MON")
    assert s1["status"] == "SCHEDULED", "scheduling in DRAFT must succeed"

    transition_term(term["id"], "OPEN")
    s2 = make_section(term["id"], course["id"], section_number="02", meeting_day="TUE",
                      schedule=False)
    assert s2["status"] == "PROPOSED"
    transition_term(term["id"], "LOCKED")

    resp = api.transition_section(s2["id"], {"to_state": "SCHEDULED"}, CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_TERM_STATE, 409)


def test_credit_units_hybrid_no_online_premium(api):
    """PRD §3.4: "The online component is the term's `online_premium_credits` rounded
    half-up to 2 decimal places when the section's `modality` is `ONLINE`, and 0
    otherwise."

    Design: Corner/calculations/c_credit_units_hybrid_no_online_premium
    """
    from test_helpers import create_assignment_payload
    term = make_term()
    course = make_course(course_code="CS-301",
                         allowed_modalities=["IN_PERSON", "ONLINE", "HYBRID"])
    faculty = make_faculty()
    make_qualification(faculty["id"], course["id"])
    section = make_section(term["id"], course["id"], modality="HYBRID")

    resp = api.create_assignment(
        create_assignment_payload(section["id"], faculty["id"]), CHAIR
    )
    assignment = validate_success(resp, 201)
    assert assignment["credit_units"] == pytest.approx(3.0), (
        "HYBRID adds no online premium; enrollment below threshold adds no bonus"
    )
