"""Assignment creation: qualification gate, schedule overlap, union cap, one-open-per-section."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_assignment,
    assert_assignment,
    create_assignment_payload,
    get_load_sheet,
    make_course,
    make_faculty,
    make_qualification,
    make_section,
    make_term,
    setup_assignable,
    setup_faculty_with_load,
    validate_error,
    validate_success,
)

CHAIR = TEST_USERS["chair_headers"]


def test_assignment_create_with_credit_units_input_ignored(api):
    """PRD §3.4: "A successful create produces an assignment in `PROPOSED` status whose
    `term_id` is copied from the section's term. Two values are snapshotted at
    creation and never recomputed by later enrollment drift: `credit_units`, the
    provisional workload credits, and `matches_preference`, ... ."

    Design: Corner/entities/c_assignment_create_with_credit_units_input_ignored
    """
    term, course, faculty, _qual, section = setup_assignable()
    payload = create_assignment_payload(section["id"], faculty["id"])
    payload["credit_units"] = 99
    resp = api.create_assignment(payload, CHAIR)
    assignment = validate_success(resp, 201)
    assert assignment["credit_units"] == pytest.approx(3.0), (
        "server must compute the provisional credits (3.0 x lecture_multiplier 1.0); "
        "client-supplied credit_units is ignored"
    )


def test_loadsheet_auto_created_on_first_assignment(api):
    """PRD §3.4: "A load sheet exists per term-and-faculty pair and is auto-created by
    the first assignment — or the first release-time grant — for that pair; there is
    no direct create or update surface, only reads."
    PRD §3.4: "From these, `effective_obligation_credits` is the faculty member's
    `base_load_credits` minus `release_credits`, floored at 0; `overload_credits` is
    `teaching_credits` minus `effective_obligation_credits`, floored at 0; ... ."

    Design: Corner/entities/c_loadsheet_auto_created_on_first_assignment
    """
    term, course, faculty, _qual, section = setup_assignable()
    add_assignment(section["id"], faculty["id"])

    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["teaching_credits"] == pytest.approx(3.0)
    assert sheet["effective_obligation_credits"] == pytest.approx(12.0)
    assert sheet["overload_credits"] == pytest.approx(0.0)


def test_assignment_requires_active_qualification__qualified_succeeds(api):
    """PRD §3.4: "First, qualification: an `ACTIVE` qualification must exist pairing
    this `faculty_id` with the section's course; a qualification that is missing,
    `REVOKED`, or lazily `EXPIRED` fails the check and the create is rejected with
    `ERR_NOT_QUALIFIED_FOR_COURSE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_qualification
    """
    term, course, faculty, _qual, section = setup_assignable()
    assignment = add_assignment(section["id"], faculty["id"])
    assert_assignment(assignment)
    assert assignment["status"] == "PROPOSED"


def test_assignment_requires_active_qualification__missing_rejected(api):
    """PRD §3.4: "First, qualification: an `ACTIVE` qualification must exist pairing
    this `faculty_id` with the section's course; a qualification that is missing,
    `REVOKED`, or lazily `EXPIRED` fails the check and the create is rejected with
    `ERR_NOT_QUALIFIED_FOR_COURSE`."

    Design: Difficulty/cross_entity_state_dependency/assignment_requires_active_qualification
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    faculty = make_faculty()  # no qualification granted
    section = make_section(term["id"], course["id"])

    resp = api.create_assignment(
        create_assignment_payload(section["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_NOT_QUALIFIED_FOR_COURSE, 422)


def test_section_already_assigned_rejected(api):
    """PRD §3.4: "A section may carry at most one non-terminal assignment — one in
    `PROPOSED` or `CONFIRMED` — so proposing onto a section that already has a live
    assignment is rejected with `ERR_SECTION_ALREADY_ASSIGNED`."

    Design: Corner/validations/c_section_already_assigned_rejected
    """
    term = make_term()
    course = make_course(course_code="CS-301")
    anna = make_faculty(full_name="Anna Aho")
    ben = make_faculty(full_name="Ben Berg", rank="ASSISTANT_PROFESSOR",
                       base_salary_cents=8_000_000)
    make_qualification(anna["id"], course["id"])
    make_qualification(ben["id"], course["id"])
    section = make_section(term["id"], course["id"])
    add_assignment(section["id"], anna["id"])

    resp = api.create_assignment(
        create_assignment_payload(section["id"], ben["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_SECTION_ALREADY_ASSIGNED, 409)


def test_union_cap_exceeded_clean_rejected(api):
    """PRD §3.4: "The system projects the faculty member's teaching load as the current
    load sheet's `teaching_credits` plus the new assignment's provisional
    `credit_units`, computes the projected overload as the amount by which that
    projection exceeds the sheet's `effective_obligation_credits` (floored at 0), and
    rejects the create with `ERR_UNION_OVERLOAD_CAP_EXCEEDED` when the projected
    overload is strictly greater than the term's `union_max_overload_credits`."

    Design: Corner/validations/c_union_cap_exceeded_clean_rejected
    """
    # Five ONLINE sections at 3.5 each -> teaching 17.5, overload 5.5 (allowed).
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        5, modality="ONLINE"
    )
    # Sixth ONLINE section would project 21.0 - 12 = 9.0 overload > cap 6.
    s6 = make_section(
        term["id"], course["id"], section_number="06", modality="ONLINE",
        meeting_day="MON", start_minute=660, end_minute=720,
    )
    resp = api.create_assignment(
        create_assignment_payload(s6["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_UNION_OVERLOAD_CAP_EXCEEDED, 422)


def test_non_union_faculty_exceeds_cap_allowed(api):
    """PRD §3.4: "Third, the union overload cap, which applies only when the faculty
    member's `is_union_covered` is true — non-union faculty skip this check
    entirely."

    Design: Corner/validations/c_non_union_faculty_exceeds_cap_allowed
    """
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        5, modality="ONLINE",
        faculty_overrides={
            "full_name": "Cy Denn",
            "rank": "ADJUNCT",
            "base_salary_cents": 4_000_000,
            "is_union_covered": False,
        },
    )
    s6 = make_section(
        term["id"], course["id"], section_number="06", modality="ONLINE",
        meeting_day="MON", start_minute=660, end_minute=720,
    )
    assignment = add_assignment(s6["id"], faculty["id"])
    assert assignment["status"] == "PROPOSED", (
        "non-union faculty must skip the union overload cap entirely"
    )
    sheet = get_load_sheet(term["id"], faculty["id"])
    assert sheet["overload_credits"] == pytest.approx(9.0), (
        "overload is tracked (21.0 - 12) even though no cap blocks it"
    )


def test_half_open_meeting_overlap__adjacent_allowed(api):
    """PRD §3.4: "The overlap test uses half-open interval semantics — the candidate
    overlaps another section only when the candidate's `start_minute` is before the
    other's `end_minute` and the other's `start_minute` is before the candidate's
    `end_minute` — so back-to-back meetings, where one section's `start_minute`
    equals the other's `end_minute`, do **not** conflict."

    Design: Difficulty/resource_temporal_overlap/half_open_meeting_overlap_adjacency
    """
    term, course, faculty, _qual, s1 = setup_assignable(
        section_overrides={"meeting_day": "MON", "start_minute": 540, "end_minute": 600}
    )
    add_assignment(s1["id"], faculty["id"])
    # S2 starts exactly when S1 ends: 10:00 == 10:00 back-to-back.
    s2 = make_section(term["id"], course["id"], section_number="02", meeting_day="MON",
                      start_minute=600, end_minute=660)
    a2 = add_assignment(s2["id"], faculty["id"])
    assert a2["status"] == "PROPOSED", "half-open adjacency must be allowed"


def test_half_open_meeting_overlap__genuine_overlap_rejected(api):
    """PRD §3.4: "The overlap test uses half-open interval semantics — the candidate
    overlaps another section only when the candidate's `start_minute` is before the
    other's `end_minute` and the other's `start_minute` is before the candidate's
    `end_minute` — so back-to-back meetings, where one section's `start_minute`
    equals the other's `end_minute`, do **not** conflict."
    PRD §3.4: "Second, the schedule-overlap check: for the candidate section and every
    other section holding a non-terminal assignment (`PROPOSED` or `CONFIRMED`) for
    the same faculty member in the same term, if the two sections share a
    `meeting_day` and their meeting windows overlap, the create is rejected with
    `ERR_MEETING_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/half_open_meeting_overlap_adjacency
    """
    term, course, faculty, _qual, s1 = setup_assignable(
        section_overrides={"meeting_day": "MON", "start_minute": 540, "end_minute": 600}
    )
    add_assignment(s1["id"], faculty["id"])
    # S3 09:30-10:30 overlaps S1's 09:00-10:00 on the same day.
    s3 = make_section(term["id"], course["id"], section_number="03", meeting_day="MON",
                      start_minute=570, end_minute=630)
    resp = api.create_assignment(
        create_assignment_payload(s3["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_MEETING_TIME_CONFLICT, 409)


def test_state_precedes_temporal_on_assignment_create(api):
    """PRD §2.8: "Every write request passes through a fixed validation cascade, and
    the ordering matters because earlier failures mask later ones."
    PRD §2.8: "Temporal overlaps. Meeting-time conflicts on assignment creation
    surface as `ERR_MEETING_TIME_CONFLICT`; release-period overlaps on grant creation
    surface as `ERR_RELEASE_PERIOD_OVERLAP`." — temporal overlaps run two steps after
    the state preconditions in the fixed cascade.
    PRD §3.4: "The target section must be in `SCHEDULED` or `STAFFED` status, else the
    create is rejected with `ERR_SECTION_NOT_ASSIGNABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_temporal_on_assignment_create
    """
    term, course, faculty, _qual, s1 = setup_assignable(
        section_overrides={"meeting_day": "MON", "start_minute": 540, "end_minute": 600}
    )
    add_assignment(s1["id"], faculty["id"])
    # S2 would overlap S1, but S2 gets CANCELLED before the assignment attempt.
    s2 = make_section(term["id"], course["id"], section_number="02", meeting_day="MON",
                      start_minute=570, end_minute=630)
    resp = api.transition_section(s2["id"], {"to_state": "CANCELLED"}, CHAIR)
    validate_success(resp)

    resp = api.create_assignment(
        create_assignment_payload(s2["id"], faculty["id"]), CHAIR
    )
    err = validate_error(resp, ApiErrorId.ERR_SECTION_NOT_ASSIGNABLE, 409)
    assert err["error_id"] != "ERR_MEETING_TIME_CONFLICT", (
        "state precondition (priority 5) must mask the temporal overlap (priority 7)"
    )


def test_state_precedes_temporal_on_assignment_create__proposed_section(api):
    """PRD §2.8: "Every write request passes through a fixed validation cascade, and
    the ordering matters because earlier failures mask later ones."
    PRD §2.8: "Temporal overlaps. Meeting-time conflicts on assignment creation
    surface as `ERR_MEETING_TIME_CONFLICT`; release-period overlaps on grant creation
    surface as `ERR_RELEASE_PERIOD_OVERLAP`." — temporal overlaps run two steps after
    the state preconditions in the fixed cascade.
    PRD §3.4: "The target section must be in `SCHEDULED` or `STAFFED` status, else the
    create is rejected with `ERR_SECTION_NOT_ASSIGNABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_temporal_on_assignment_create
    """
    # The candidate section was never scheduled (still PROPOSED) AND overlaps an
    # existing assignment's meeting window: the state gate must answer first.
    term, course, faculty, _qual, s1 = setup_assignable(
        section_overrides={"meeting_day": "MON", "start_minute": 540, "end_minute": 600}
    )
    add_assignment(s1["id"], faculty["id"])
    s2 = make_section(term["id"], course["id"], section_number="02",
                      meeting_day="MON", start_minute=570, end_minute=630,
                      schedule=False)
    assert s2["status"] == "PROPOSED"

    resp = api.create_assignment(
        create_assignment_payload(s2["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_ASSIGNABLE, 409)


def test_referential_precedes_constraint_on_assignment_create(api):
    """PRD §2.8: "6. **Qualification.** On assignment creation only, the absence of an
    `ACTIVE` qualification for the faculty–course pair surfaces as
    `ERR_NOT_QUALIFIED_FOR_COURSE`." — the qualification check runs two steps before
    the uniqueness-and-constraint tier in the fixed cascade.
    PRD §2.8: "8. **Uniqueness and business constraints.** Duplicate and capacity
    failures surface as `ERR_DUPLICATE_TERM_CODE`, `ERR_DUPLICATE_FACULTY_EMAIL`,
    `ERR_DUPLICATE_SECTION`, `ERR_DUPLICATE_QUALIFICATION`,
    `ERR_MODALITY_NOT_ALLOWED`, `ERR_ENROLLMENT_EXCEEDS_CAP`,
    `ERR_UNION_OVERLOAD_CAP_EXCEEDED`, `ERR_SECTION_ALREADY_ASSIGNED`,
    `ERR_NO_OVERLOAD`, or `ERR_OVERLOAD_REQUEST_EXISTS`."

    Design: Difficulty/priority_pair_validation_conflict/referential_precedes_constraint_on_assignment_create
    """
    # Ben qualified for CS-301 ONLY; five ONLINE sections -> teaching 17.5, overload 5.5.
    term, course, ben, sections, assignments = setup_faculty_with_load(
        5, modality="ONLINE",
        faculty_overrides={"full_name": "Ben Berg", "rank": "ASSISTANT_PROFESSOR",
                           "base_salary_cents": 8_000_000},
    )
    # A second course Ben is NOT qualified for; the new section does not overlap.
    other = make_course(course_code="CS-401", title="Compilers")
    s6 = make_section(term["id"], other["id"], section_number="01", modality="ONLINE",
                      meeting_day="MON", start_minute=660, end_minute=720)
    resp = api.create_assignment(
        create_assignment_payload(s6["id"], ben["id"]), CHAIR
    )
    err = validate_error(resp, ApiErrorId.ERR_NOT_QUALIFIED_FOR_COURSE, 422)
    assert err["error_id"] != "ERR_UNION_OVERLOAD_CAP_EXCEEDED", (
        "qualification (priority 6) must mask the union-cap constraint (priority 8)"
    )


def test_referential_precedes_constraint_on_assignment_create__revoked_qualification(api):
    """PRD §2.8: "6. **Qualification.** On assignment creation only, the absence of an
    `ACTIVE` qualification for the faculty–course pair surfaces as
    `ERR_NOT_QUALIFIED_FOR_COURSE`." — the qualification check runs two steps before
    the uniqueness-and-constraint tier in the fixed cascade.
    PRD §3.4: "First, qualification: an `ACTIVE` qualification must exist pairing this
    `faculty_id` with the section's course; a qualification that is missing,
    `REVOKED`, or lazily `EXPIRED` fails the check and the create is rejected with
    `ERR_NOT_QUALIFIED_FOR_COURSE`."

    Design: Difficulty/priority_pair_validation_conflict/referential_precedes_constraint_on_assignment_create
    """
    # A faculty whose only qualification for the course was REVOKED, and whose
    # existing load already projects an overload above the union cap — the
    # referential qualification error must surface before the constraint error.
    term = make_term()
    course = make_course(course_code="CS-301")
    faculty = make_faculty(full_name="Dana Dorn", rank="LECTURER",
                           base_salary_cents=6_000_000)
    qual = make_qualification(faculty["id"], course["id"])
    # Build a 5.5-overload posture while the qualification is still ACTIVE.
    for i, day in enumerate(["MON", "TUE", "WED", "THU", "FRI"]):
        s = make_section(term["id"], course["id"], section_number=f"1{i}",
                         modality="ONLINE", meeting_day=day,
                         start_minute=780, end_minute=840)
        add_assignment(s["id"], faculty["id"])
    resp = api.patch_qualification(qual["id"], {"status": "REVOKED"}, CHAIR)
    validate_success(resp)
    # Target section would push teaching to 21.0 (overload 9.0 > cap 6) AND the
    # qualification is REVOKED: the referential error must win.
    s_target = make_section(term["id"], course["id"], section_number="99",
                            modality="ONLINE", meeting_day="MON",
                            start_minute=900, end_minute=960)
    resp = api.create_assignment(
        create_assignment_payload(s_target["id"], faculty["id"]), CHAIR
    )
    validate_error(resp, ApiErrorId.ERR_NOT_QUALIFIED_FOR_COURSE, 422)
