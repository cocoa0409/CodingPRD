"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database with the logical clock at its
initial reading. Helpers use the lenient `get_success_data()` validator so a broken
precondition reports as a setup failure rather than an obscure assertion error.

The helpers are layered: each stage calls the stage below it and forwards keyword
arguments, so a test can enter the pipeline at any depth and still control the
values it cares about. Every stage returns the same mutable ``world`` dict.

Typical keys in ``world``:
    term, student, student_headers, chair, chair_headers, member_1, member_2,
    room, thesis, committee, seats, defense_event, format_review, screening,
    embargo_request, deposit, students, faculty, rooms, theses
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_committee_member_payload,
    create_committee_payload,
    create_defense_event_payload,
    create_defense_room_payload,
    create_embargo_request_payload,
    create_faculty_member_payload,
    create_integrity_screening_payload,
    create_permission_record_payload,
    create_repository_deposit_payload,
    create_student_payload,
    create_term_payload,
    create_thesis_payload,
    format_review_decision_payload,
)
from .test_users import (
    ANALYST_ONE_USER_ID,
    ANALYST_TWO_USER_ID,
    DEAN_ONE_USER_ID,
    DEAN_TWO_USER_ID,
    INTEGRITY_OFFICER_ONE_USER_ID,
    TEST_USERS,
    make_analyst_headers,
    make_dean_headers,
    make_faculty_member_headers,
    make_integrity_officer_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]
ANALYST_TWO = TEST_USERS["analyst_two_headers"]


# --------------------------------------------------------------------------
# Primitive reference-data helpers
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; mutates no entity and fires no cascade."""
    return get_success_data(api_client.set_clock(to_iso8601, REGISTRAR))


def create_term(**overrides) -> dict:
    return get_success_data(
        api_client.create_term(create_term_payload(**overrides), REGISTRAR)
    )


def create_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), REGISTRAR)
    )


def create_faculty_member(**overrides) -> dict:
    return get_success_data(
        api_client.create_faculty_member(
            create_faculty_member_payload(**overrides), REGISTRAR
        )
    )


def create_defense_room(**overrides) -> dict:
    return get_success_data(
        api_client.create_defense_room(create_defense_room_payload(**overrides), REGISTRAR)
    )


def open_thesis(student: dict, term: dict, **overrides) -> dict:
    """Open a document record for the acting candidate."""
    return get_success_data(
        api_client.create_thesis(
            create_thesis_payload(student["id"], term["id"], **overrides),
            make_student_headers(student["id"]),
        )
    )


def read_thesis(thesis_id: str, headers: Optional[Dict[str, str]] = None) -> dict:
    return get_success_data(api_client.get_thesis(thesis_id, headers or REGISTRAR))


def thesis_version(thesis_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Read the current parent version for the stale-thesis guards."""
    return read_thesis(thesis_id, headers)["version"]


# --------------------------------------------------------------------------
# Extra actors added to an existing world
# --------------------------------------------------------------------------


def add_student(world: dict, **overrides) -> dict:
    student = create_student(**overrides)
    world.setdefault("students", []).append(student)
    return student


def add_faculty_member(world: dict, **overrides) -> dict:
    faculty = create_faculty_member(**overrides)
    world.setdefault("faculty", []).append(faculty)
    return faculty


def add_defense_room(world: dict, **overrides) -> dict:
    room = create_defense_room(**overrides)
    world.setdefault("rooms", []).append(room)
    return room


# --------------------------------------------------------------------------
# Tier 1 — reference data and a DRAFT document
# --------------------------------------------------------------------------


def setup_reference_data(
    *,
    clock: str = DEFAULT_CLOCK,
    term_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    room_overrides: Optional[Dict[str, Any]] = None,
    with_room: bool = True,
) -> dict:
    """Clock, one term, one candidate, three faculty members and one room.

    The three faculty members are a certified tenured chair, a certified
    tenure-track member and an uncertified adjunct member — the smallest roster
    that can legally fill a master's committee.
    """
    set_clock(clock)
    term = create_term(**(term_overrides or {}))
    student = create_student(**(student_overrides or {}))
    chair = create_faculty_member(
        full_name="Cara Cho",
        email="cho@u.edu",
        appointment_type="TENURED",
        graduate_faculty_certified=True,
    )
    member_1 = create_faculty_member(
        full_name="Dev Mehta",
        email="dev@u.edu",
        appointment_type="TENURE_TRACK",
        graduate_faculty_certified=True,
    )
    member_2 = get_success_data(
        api_client.create_faculty_member(
            {
                "full_name": "Eli Novak",
                "email": "eli@u.edu",
                "appointment_type": "ADJUNCT",
            },
            REGISTRAR,
        )
    )
    world: Dict[str, Any] = {
        "term": term,
        "student": student,
        "student_headers": make_student_headers(student["id"]),
        "chair": chair,
        "chair_headers": make_faculty_member_headers(chair["id"]),
        "member_1": member_1,
        "member_2": member_2,
        "students": [student],
        "faculty": [chair, member_1, member_2],
        "rooms": [],
        "theses": [],
    }
    if with_room:
        room = create_defense_room(**(room_overrides or {}))
        world["room"] = room
        world["rooms"].append(room)
    return world


def setup_draft_thesis(
    *, thesis_overrides: Optional[Dict[str, Any]] = None, **kwargs
) -> dict:
    """Reference data plus one DRAFT document owned by the candidate."""
    world = setup_reference_data(**kwargs)
    thesis = open_thesis(world["student"], world["term"], **(thesis_overrides or {}))
    world["thesis"] = thesis
    world["theses"].append(thesis)
    return world


# --------------------------------------------------------------------------
# Tier 2 — committee composition
# --------------------------------------------------------------------------


def seat_member(
    world: dict,
    faculty: dict,
    role: str = "MEMBER",
    committee: Optional[dict] = None,
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    committee = committee or world["committee"]
    return get_success_data(
        api_client.create_committee_member(
            committee["id"],
            create_committee_member_payload(faculty["id"], role),
            headers or world["student_headers"],
        )
    )


def setup_committee_with_seats(
    *, seat_roles: Optional[List[str]] = None, **kwargs
) -> dict:
    """A DRAFT committee carrying three CONFIRMED seats: chair plus two members."""
    world = setup_draft_thesis(**kwargs)
    committee = get_success_data(
        api_client.create_committee(
            create_committee_payload(world["thesis"]["id"]),
            world["student_headers"],
        )
    )
    world["committee"] = committee
    roles = seat_roles or ["CHAIR", "MEMBER", "MEMBER"]
    faculty_order = [world["chair"], world["member_1"], world["member_2"]]
    seats: Dict[str, dict] = {}
    seat_rows: List[dict] = []
    for faculty, role in zip(faculty_order, roles):
        seat = seat_member(world, faculty, role, committee)
        seats[role if role not in seats else f"{role}_2"] = seat
        seat_rows.append(seat)
    world["seats"] = seats
    world["seat_rows"] = seat_rows
    return world


def setup_submitted_committee(**kwargs) -> dict:
    """The composition has been submitted for the dean's approval."""
    world = setup_committee_with_seats(**kwargs)
    world["committee"] = get_success_data(
        api_client.submit_committee(
            world["committee"]["id"], world["student_headers"]
        )
    )
    return world


def setup_approved_committee(*, dean_user_id: str = DEAN_ONE_USER_ID, **kwargs) -> dict:
    """The dean has approved the composition; the document is COMMITTEE_APPROVED."""
    world = setup_submitted_committee(**kwargs)
    world["committee"] = get_success_data(
        api_client.decide_committee(
            world["committee"]["id"],
            {"decision": "APPROVE"},
            make_dean_headers(dean_user_id),
        )
    )
    world["approving_dean_user_id"] = dean_user_id
    return world


# --------------------------------------------------------------------------
# Tier 3 — defense booking, announcement and outcome
# --------------------------------------------------------------------------


def schedule_defense(
    world: dict,
    *,
    thesis: Optional[dict] = None,
    room: Optional[dict] = None,
    scheduled_start: str = "2026-09-25T14:00:00Z",
    scheduled_end: str = "2026-09-25T16:00:00Z",
    headers: Optional[Dict[str, str]] = None,
) -> dict:
    thesis = thesis or world["thesis"]
    room = room or world["room"]
    return get_success_data(
        api_client.create_defense_event(
            create_defense_event_payload(
                thesis["id"],
                room["id"],
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
            ),
            headers or world["student_headers"],
        )
    )


def setup_scheduled_defense(
    *,
    scheduled_start: str = "2026-09-25T14:00:00Z",
    scheduled_end: str = "2026-09-25T16:00:00Z",
    schedule_clock: Optional[str] = None,
    **kwargs
) -> dict:
    """A DRAFT defense event occupies the room; the document is DEFENSE_SCHEDULED."""
    world = setup_approved_committee(**kwargs)
    if schedule_clock:
        set_clock(schedule_clock)
    world["defense_event"] = schedule_defense(
        world, scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    return world


def setup_announced_defense(**kwargs) -> dict:
    """The analyst has published the announcement; the document is DEFENSE_ANNOUNCED."""
    world = setup_scheduled_defense(**kwargs)
    world["defense_event"] = get_success_data(
        api_client.announce_defense_event(world["defense_event"]["id"], ANALYST_ONE)
    )
    return world


def setup_held_defense(
    *,
    outcome: str = "PASS",
    outcome_clock: str = "2026-09-25T16:30:00Z",
    outcome_note: Optional[str] = None,
    **kwargs
) -> dict:
    """The chair has recorded the defense outcome after the scheduled end."""
    world = setup_announced_defense(**kwargs)
    set_clock(outcome_clock)
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    world["defense_event"] = get_success_data(
        api_client.record_defense_outcome(
            world["defense_event"]["id"], payload, world["chair_headers"]
        )
    )
    return world


def setup_passed_defense(**kwargs) -> dict:
    """Shorthand for the PASS branch: the document is DEFENSE_PASSED."""
    return setup_held_defense(outcome="PASS", **kwargs)


# --------------------------------------------------------------------------
# Tier 4 — format review, permissions and screening
# --------------------------------------------------------------------------


def open_format_cycle(
    world: dict, *, thesis: Optional[dict] = None, clock: Optional[str] = None
) -> dict:
    thesis = thesis or world["thesis"]
    if clock:
        set_clock(clock)
    return get_success_data(
        api_client.create_format_submission(thesis["id"], world["student_headers"])
    )


def record_screening(
    world: dict,
    *,
    similarity_pct: float,
    excluded_quoted_pct: Optional[float] = None,
    thesis: Optional[dict] = None,
    analyst_user_id: str = ANALYST_ONE_USER_ID,
) -> dict:
    thesis = thesis or world["thesis"]
    payload = create_integrity_screening_payload(thesis["id"], similarity_pct)
    if excluded_quoted_pct is not None:
        payload["excluded_quoted_pct"] = excluded_quoted_pct
    return get_success_data(
        api_client.create_integrity_screening(
            payload, make_analyst_headers(analyst_user_id)
        )
    )


def act_on_screening(
    world: dict,
    screening: dict,
    action: str,
    *,
    resolution_note: Optional[str] = None,
    officer_user_id: str = INTEGRITY_OFFICER_ONE_USER_ID,
) -> dict:
    payload: Dict[str, Any] = {"action": action}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(
        api_client.act_on_integrity_screening(
            screening["id"], payload, make_integrity_officer_headers(officer_user_id)
        )
    )


def decide_format_review(
    world: dict,
    review: dict,
    *,
    decision: str = "ACCEPT",
    critical_defect_count: int = 0,
    major_defect_count: int = 0,
    minor_defect_count: int = 0,
    clock: Optional[str] = None,
    analyst_user_id: str = ANALYST_ONE_USER_ID,
    review_note: Optional[str] = None,
) -> dict:
    if clock:
        set_clock(clock)
    payload = format_review_decision_payload(
        decision, critical_defect_count, major_defect_count, minor_defect_count
    )
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(
        api_client.decide_format_review(
            review["id"], payload, make_analyst_headers(analyst_user_id)
        )
    )


def document_permission(
    world: dict,
    *,
    thesis: Optional[dict] = None,
    material_type: str = "FIGURE",
    rights_basis: str = "WRITTEN_PERMISSION",
    page_reference: str = "p. 42",
    **overrides
) -> dict:
    """Document one third-party item, re-reading the parent version first."""
    thesis = thesis or world["thesis"]
    payload = create_permission_record_payload(
        thesis["id"],
        thesis_version(thesis["id"], world["student_headers"]),
        material_type=material_type,
        rights_basis=rights_basis,
        page_reference=page_reference,
        **overrides,
    )
    return get_success_data(
        api_client.create_permission_record(payload, world["student_headers"])
    )


def review_permission(
    world: dict,
    record: dict,
    *,
    decision: str = "ACCEPT",
    review_note: Optional[str] = None,
    analyst_user_id: str = ANALYST_ONE_USER_ID,
) -> dict:
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(
        api_client.review_permission_record(
            record["id"], payload, make_analyst_headers(analyst_user_id)
        )
    )


def setup_open_format_cycle(
    *,
    cycle_clock: str = "2026-10-05T09:00:00Z",
    with_screening: bool = True,
    similarity_pct: float = 25.0,
    excluded_quoted_pct: Optional[float] = 7.5,
    **kwargs
) -> dict:
    """Cycle 1 is PENDING_REVIEW and, by default, a CLEARED screening exists."""
    world = setup_passed_defense(**kwargs)
    world["format_review"] = open_format_cycle(world, clock=cycle_clock)
    if with_screening:
        world["screening"] = record_screening(
            world,
            similarity_pct=similarity_pct,
            excluded_quoted_pct=excluded_quoted_pct,
        )
    return world


def setup_format_accepted_thesis(
    *,
    decision_clock: str = "2026-10-12T09:00:00Z",
    critical_defect_count: int = 0,
    major_defect_count: int = 0,
    minor_defect_count: int = 0,
    accepting_analyst_user_id: str = ANALYST_ONE_USER_ID,
    **kwargs
) -> dict:
    """The document is FORMAT_ACCEPTED, accepted by the named analyst."""
    world = setup_open_format_cycle(**kwargs)
    world["format_review"] = decide_format_review(
        world,
        world["format_review"],
        decision="ACCEPT",
        critical_defect_count=critical_defect_count,
        major_defect_count=major_defect_count,
        minor_defect_count=minor_defect_count,
        clock=decision_clock,
        analyst_user_id=accepting_analyst_user_id,
    )
    world["accepting_analyst_user_id"] = accepting_analyst_user_id
    return world


# --------------------------------------------------------------------------
# Tier 5 — embargo, deposit and the terminal runs
# --------------------------------------------------------------------------


def request_embargo(
    world: dict,
    *,
    thesis: Optional[dict] = None,
    reason_code: str = "PUBLISHER_AGREEMENT",
    requested_months: int = 6,
    justification: str = "Publisher requires a six-month hold.",
) -> dict:
    thesis = thesis or world["thesis"]
    payload = create_embargo_request_payload(
        thesis["id"],
        thesis_version(thesis["id"], world["student_headers"]),
        reason_code=reason_code,
        requested_months=requested_months,
        justification=justification,
    )
    return get_success_data(
        api_client.create_embargo_request(payload, world["student_headers"])
    )


def decide_embargo(
    world: dict,
    embargo: dict,
    *,
    decision: str = "APPROVE",
    approved_months: Optional[int] = None,
    decision_note: Optional[str] = None,
    dean_user_id: str = DEAN_TWO_USER_ID,
) -> dict:
    payload: Dict[str, Any] = {"decision": decision}
    if approved_months is not None:
        payload["approved_months"] = approved_months
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.decide_embargo_request(
            embargo["id"], payload, make_dean_headers(dean_user_id)
        )
    )


def supplement_embargo(world: dict, embargo: dict, justification: str) -> dict:
    return get_success_data(
        api_client.supplement_embargo_request(
            embargo["id"], {"justification": justification}, world["student_headers"]
        )
    )


def deposit_thesis(
    world: dict,
    *,
    thesis: Optional[dict] = None,
    abstract_word_count: int = 150,
    subject_keywords: Optional[List[str]] = None,
    late_fee_paid_cents: int = 0,
    advisor_name: Optional[str] = "Cara Cho",
    department_code: Optional[str] = "CS",
    depositor_user_id: str = ANALYST_TWO_USER_ID,
    **overrides
) -> dict:
    """Deposit through an analyst other than the one who accepted the review."""
    thesis = thesis or world["thesis"]
    payload = create_repository_deposit_payload(
        thesis["id"],
        abstract_word_count=abstract_word_count,
        subject_keywords=subject_keywords or ["format review", "deposit", "conferral"],
        late_fee_paid_cents=late_fee_paid_cents,
        **overrides,
    )
    if advisor_name is not None:
        payload["advisor_name"] = advisor_name
    if department_code is not None:
        payload["department_code"] = department_code
    return get_success_data(
        api_client.create_repository_deposit(
            payload, make_analyst_headers(depositor_user_id)
        )
    )


def setup_deposited_thesis(
    *,
    deposit_clock: str = "2026-11-02T10:00:00Z",
    deposit_overrides: Optional[Dict[str, Any]] = None,
    **kwargs
) -> dict:
    """The document has been deposited into the repository."""
    world = setup_format_accepted_thesis(**kwargs)
    set_clock(deposit_clock)
    world["deposit"] = deposit_thesis(world, **(deposit_overrides or {}))
    return world


def close_term_deposit(world: dict, *, term: Optional[dict] = None) -> dict:
    term = term or world["term"]
    return get_success_data(api_client.close_term_deposit(term["id"], REGISTRAR))


def confer_term_degrees(world: dict, *, term: Optional[dict] = None) -> dict:
    term = term or world["term"]
    return get_success_data(api_client.confer_term_degrees(term["id"], REGISTRAR))


# --------------------------------------------------------------------------
# Multi-candidate scenarios
# --------------------------------------------------------------------------


def add_second_candidate_pipeline(
    world: dict,
    *,
    full_name: str = "Ben Ruiz",
    email: str = "ben@u.edu",
    degree_level: str = "MASTERS",
    program_code: str = "CS",
    title: str = "Second Candidate",
    document_type: str = "THESIS",
    page_count: int = 101,
    third_party_item_count: int = 0,
    approve_committee: bool = True,
    dean_user_id: str = DEAN_ONE_USER_ID,
) -> dict:
    """Register a second candidate and walk them to an approved committee.

    Returns a sub-world dict with keys: student, student_headers, thesis,
    committee, seats.
    """
    student = add_student(
        world,
        full_name=full_name,
        email=email,
        degree_level=degree_level,
        program_code=program_code,
    )
    headers = make_student_headers(student["id"])
    thesis = get_success_data(
        api_client.create_thesis(
            create_thesis_payload(
                student["id"],
                world["term"]["id"],
                title=title,
                document_type=document_type,
                page_count=page_count,
                third_party_item_count=third_party_item_count,
            ),
            headers,
        )
    )
    committee = get_success_data(
        api_client.create_committee(create_committee_payload(thesis["id"]), headers)
    )
    seats = {}
    for faculty, role in (
        (world["chair"], "CHAIR"),
        (world["member_1"], "MEMBER"),
        (world["member_2"], "MEMBER"),
    ):
        seats[role if role not in seats else f"{role}_2"] = get_success_data(
            api_client.create_committee_member(
                committee["id"],
                create_committee_member_payload(faculty["id"], role),
                headers,
            )
        )
    committee = get_success_data(api_client.submit_committee(committee["id"], headers))
    if approve_committee:
        committee = get_success_data(
            api_client.decide_committee(
                committee["id"], {"decision": "APPROVE"}, make_dean_headers(dean_user_id)
            )
        )
    sub = {
        "student": student,
        "student_headers": headers,
        "thesis": thesis,
        "committee": committee,
        "seats": seats,
    }
    world.setdefault("candidates", []).append(sub)
    world["theses"].append(thesis)
    return sub
