"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared endpoints;
each test runs against a freshly restarted server with an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_term_payload,
    create_faculty_payload,
    create_course_payload,
    create_qualification_payload,
    create_section_payload,
    create_assignment_payload,
    create_grant_payload,
    create_overload_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_chair_headers,
    make_faculty_headers,
    make_dean_headers,
)

CHAIR = TEST_USERS["chair_headers"]
DEAN = TEST_USERS["dean_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["admin_headers"]

MEETING_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def make_term(open_it: bool = True, **overrides) -> dict:
    """Create a term; when open_it, transition DRAFT -> OPEN. Returns the term."""
    resp = api_client.create_term(create_term_payload(**overrides), CHAIR)
    term = get_success_data(resp, 201)
    if open_it:
        resp = api_client.transition_term(term["id"], {"to_state": "OPEN"}, CHAIR)
        term = get_success_data(resp)
    return term


def make_faculty(**overrides) -> dict:
    """Create a faculty member (born ACTIVE)."""
    resp = api_client.create_faculty(create_faculty_payload(**overrides), CHAIR)
    return get_success_data(resp, 201)


def make_course(**overrides) -> dict:
    """Create a course."""
    resp = api_client.create_course(create_course_payload(**overrides), CHAIR)
    return get_success_data(resp, 201)


def make_qualification(faculty_id: str, course_id: str, **overrides) -> dict:
    """Grant an ACTIVE qualification."""
    resp = api_client.create_qualification(
        create_qualification_payload(faculty_id, course_id, **overrides), CHAIR
    )
    return get_success_data(resp, 201)


def make_section(term_id: str, course_id: str, schedule: bool = True, **overrides) -> dict:
    """Create a section (born PROPOSED); when schedule, move it to SCHEDULED."""
    resp = api_client.create_section(create_section_payload(term_id, course_id, **overrides), CHAIR)
    section = get_success_data(resp, 201)
    if schedule:
        resp = api_client.transition_section(section["id"], {"to_state": "SCHEDULED"}, CHAIR)
        section = get_success_data(resp)
    return section


def transition_term(term_id: str, to_state: str, headers=None) -> dict:
    resp = api_client.transition_term(term_id, {"to_state": to_state}, headers or CHAIR)
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> None:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_assignable(
    open_term: bool = True,
    with_section: bool = True,
    faculty_overrides=None,
    course_overrides=None,
    section_overrides=None,
    term_overrides=None,
):
    """Open term + course + faculty + ACTIVE qualification (+ one SCHEDULED section).

    Returns (term, course, faculty, qualification, section_or_None).
    """
    term = make_term(open_it=open_term, **(term_overrides or {}))
    course = make_course(**(course_overrides or {}))
    faculty = make_faculty(**(faculty_overrides or {}))
    qual = make_qualification(faculty["id"], course["id"])
    section = None
    if with_section:
        section = make_section(term["id"], course["id"], **(section_overrides or {}))
    return term, course, faculty, qual, section


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def add_assignment(section_id: str, faculty_id: str) -> dict:
    """Chair proposes an assignment (born PROPOSED)."""
    resp = api_client.create_assignment(
        create_assignment_payload(section_id, faculty_id), CHAIR
    )
    return get_success_data(resp, 201)


def confirm_assignment(assignment_id: str, faculty_id: str) -> dict:
    """The named faculty member confirms their own assignment (ownership-gated)."""
    resp = api_client.transition_assignment(
        assignment_id, {"to_state": "CONFIRMED"}, make_faculty_headers(faculty_id)
    )
    return get_success_data(resp)


def add_confirmed_assignment(section_id: str, faculty_id: str) -> dict:
    """Propose + faculty confirm. Returns the CONFIRMED assignment."""
    assignment = add_assignment(section_id, faculty_id)
    return confirm_assignment(assignment["id"], faculty_id)


def get_load_sheet(term_id: str, faculty_id: str) -> dict:
    """Fetch the single load sheet for (term, faculty)."""
    resp = api_client.list_load_sheets(CHAIR, params={"term_id": term_id, "faculty_id": faculty_id})
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly 1 load sheet for ({term_id}, {faculty_id}), got {data}"
    )
    return data[0]


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_faculty_with_load(
    n_sections: int,
    modality: str = "IN_PERSON",
    confirm: bool = False,
    faculty_overrides=None,
    term_overrides=None,
    course_overrides=None,
    base_minute: int = 540,
):
    """Open term + course + qualified faculty + N SCHEDULED sections (distinct
    meeting days MON..FRI), each carrying one assignment for the faculty.

    With the default policy an IN_PERSON section is worth 3.0 credits and an
    ONLINE section 3.5.

    Returns (term, course, faculty, sections, assignments).
    """
    assert n_sections <= len(MEETING_DAYS), "at most five distinct meeting days"
    term = make_term(**(term_overrides or {}))
    course = make_course(**(course_overrides or {}))
    faculty = make_faculty(**(faculty_overrides or {}))
    make_qualification(faculty["id"], course["id"])
    sections, assignments = [], []
    for i in range(n_sections):
        section = make_section(
            term["id"],
            course["id"],
            section_number=f"{i + 1:02d}",
            modality=modality,
            meeting_day=MEETING_DAYS[i],
            start_minute=base_minute,
            end_minute=base_minute + 60,
        )
        sections.append(section)
        if confirm:
            assignments.append(add_confirmed_assignment(section["id"], faculty["id"]))
        else:
            assignments.append(add_assignment(section["id"], faculty["id"]))
    return term, course, faculty, sections, assignments


def setup_overload_request(
    n_sections: int = 5,
    modality: str = "IN_PERSON",
    endorse: bool = False,
    endorser_user_id: str = "chair-1",
    confirm: bool = False,
    faculty_overrides=None,
    term_overrides=None,
):
    """Faculty with overload > 0 plus a SUBMITTED overload request; optionally
    endorsed by the given chair user id.

    Default (5 x IN_PERSON 3.0 = 15.0 teaching vs obligation 12) yields overload 3.0.

    Returns (term, course, faculty, sections, assignments, overload_request).
    """
    term, course, faculty, sections, assignments = setup_faculty_with_load(
        n_sections,
        modality=modality,
        confirm=confirm,
        faculty_overrides=faculty_overrides,
        term_overrides=term_overrides,
    )
    resp = api_client.create_overload_request(
        create_overload_request_payload(term["id"], faculty["id"]), CHAIR
    )
    overload_request = get_success_data(resp, 201)
    if endorse:
        resp = api_client.transition_overload_request(
            overload_request["id"],
            {"to_state": "CHAIR_ENDORSED"},
            make_chair_headers(endorser_user_id),
        )
        overload_request = get_success_data(resp)
    return term, course, faculty, sections, assignments, overload_request


def approve_overload_request(request_id: str, dean_user_id: str = "dean-1") -> dict:
    resp = api_client.transition_overload_request(
        request_id, {"to_state": "DEAN_APPROVED"}, make_dean_headers(dean_user_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: publish / terminal-state setups
# ---------------------------------------------------------------------------

def publish_term(term_id: str) -> dict:
    """Drive a term OPEN -> LOCKED -> PUBLISHED (preconditions must already hold)."""
    transition_term(term_id, "LOCKED")
    return transition_term(term_id, "PUBLISHED")


def setup_grant(term_id: str, faculty_id: str, approve: bool = False, **overrides) -> dict:
    """Create a REQUESTED release-time grant; optionally approve it as DeanOffice."""
    resp = api_client.create_grant(create_grant_payload(term_id, faculty_id, **overrides), CHAIR)
    grant = get_success_data(resp, 201)
    if approve:
        resp = api_client.transition_grant(grant["id"], {"to_state": "APPROVED"}, DEAN)
        grant = get_success_data(resp)
    return grant
