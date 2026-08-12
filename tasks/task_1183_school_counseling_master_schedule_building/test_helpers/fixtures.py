"""Composite setup helpers.

Multi-step setup sequences so tests focus on assertions. All helpers build
their preconditions from scratch using only PRD-declared endpoints, and use
get_success_data() internally so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_term_payload, create_course_payload, create_counselor_payload,
    create_teacher_payload, create_room_payload, create_student_payload,
)
from .test_users import TEST_USERS, make_counselor_headers, make_student_headers

ADMIN = TEST_USERS["admin_headers"]

# ---------------------------------------------------------------------------
# Tier 1 / 2: basic people + term building blocks
# ---------------------------------------------------------------------------


def setup_counselor(max_caseload=100, full_name=None):
    """Create one counselor. Returns the counselor dict."""
    payload = create_counselor_payload(max_caseload=max_caseload)
    if full_name:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_counselor(payload, ADMIN), )


def setup_term(code, periods_per_day=8, max_students_per_section=32,
               class_size_target=25, **extra):
    """Create a term in COLLECTING. Returns the term dict."""
    payload = create_term_payload(
        code=code,
        periods_per_day=periods_per_day,
        max_students_per_section=max_students_per_section,
        class_size_target=class_size_target,
        **extra,
    )
    return get_success_data(api_client.create_term(payload, ADMIN))


def setup_course(code, credits=1.0, subject_area="ELECTIVE", **extra):
    """Create one catalog course. Returns the course dict."""
    payload = create_course_payload(
        course_code=code, credits=credits, subject_area=subject_area, **extra,
    )
    return get_success_data(api_client.create_course(payload, ADMIN))


def setup_student(counselor_id, external_ref, grade_level=9, special_program="NONE",
                  earned_credits=None, full_name=None):
    """Create one student on the given counselor's caseload."""
    payload = create_student_payload(
        external_ref=external_ref, grade_level=grade_level,
        special_program=special_program, counselor_id=counselor_id,
    )
    if earned_credits is not None:
        payload["earned_credits"] = earned_credits
    if full_name:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_student(payload, ADMIN))


def setup_teacher(max_sections=10, full_name=None):
    payload = create_teacher_payload(max_sections=max_sections)
    if full_name:
        payload["full_name"] = full_name
    return get_success_data(api_client.create_teacher(payload, ADMIN))


def setup_room(room_number, capacity=32, room_type="STANDARD"):
    payload = create_room_payload(
        room_number=room_number, capacity=capacity, room_type=room_type,
    )
    return get_success_data(api_client.create_room(payload, ADMIN))


def qualify_teacher(teacher_id, course_id, qualified_at="2026-01-01T00:00:00Z"):
    return get_success_data(api_client.create_qualification(
        teacher_id, {"course_id": course_id, "qualified_at": qualified_at}, ADMIN,
    ))


# ---------------------------------------------------------------------------
# Course-request helpers
# ---------------------------------------------------------------------------


def make_course_request(student_id, course_id, term_id, priority_rank=1, is_alternate=False):
    """Create a DRAFT request as the owning student."""
    payload = {
        "student_id": student_id,
        "course_id": course_id,
        "term_id": term_id,
        "priority_rank": priority_rank,
    }
    if is_alternate:
        payload["is_alternate"] = True
    return get_success_data(api_client.create_course_request(
        payload, make_student_headers(student_id),
    ))


def make_and_submit_request(student_id, course_id, term_id, priority_rank=1,
                            is_alternate=False):
    """Create + submit a request as the owning student. Returns the request dict."""
    req = make_course_request(student_id, course_id, term_id, priority_rank, is_alternate)
    return get_success_data(api_client.submit_course_request(
        req["id"], make_student_headers(student_id),
    ))


def setup_students_with_submitted_requests(counselor_id, term_id, course_id, count,
                                           ref_prefix, grade_level=9,
                                           special_program="NONE", credits_earned=None):
    """Create `count` students, each holding one SUBMITTED primary request for
    the course. Returns the list of student dicts."""
    students = []
    for i in range(1, count + 1):
        stu = setup_student(
            counselor_id, f"{ref_prefix}{i:03d}", grade_level=grade_level,
            special_program=special_program, earned_credits=credits_earned,
        )
        make_and_submit_request(stu["id"], course_id, term_id, priority_rank=1)
        students.append(stu)
    return students


def setup_students_with_draft_requests(counselor_id, term_id, course_id, count,
                                       ref_prefix, grade_level=9):
    """Create `count` students, each holding one DRAFT primary request."""
    students = []
    for i in range(1, count + 1):
        stu = setup_student(counselor_id, f"{ref_prefix}{i:03d}", grade_level=grade_level)
        make_course_request(stu["id"], course_id, term_id, priority_rank=1)
        students.append(stu)
    return students


# ---------------------------------------------------------------------------
# Tier 3: term lifecycle chains
# ---------------------------------------------------------------------------


def get_term_version(term_id):
    return get_success_data(api_client.get_term(term_id, ADMIN))["version"]


def list_term_sections(term_id):
    return get_success_data(api_client.list_sections(ADMIN, params={"term_id": term_id}))


def schedule_section(section_id, teacher_id, room_id, period, capacity, term_id):
    """PATCH a DRAFT section to SCHEDULED, re-reading the term version for OCC."""
    version = get_term_version(term_id)
    return get_success_data(api_client.patch_section(section_id, {
        "teacher_id": teacher_id,
        "room_id": room_id,
        "period": period,
        "capacity": capacity,
        "expected_term_version": version,
    }, ADMIN))


def drive_term_to_building(term_id):
    """COLLECTING -> TALLYING -> BUILDING. Returns the refreshed term dict."""
    get_success_data(api_client.close_collection(term_id, ADMIN))
    return get_success_data(api_client.generate_sections(term_id, ADMIN))


def drive_term_to_published(term_id, section_specs, teacher_id, room_ids):
    """Schedule every DRAFT section of the term, then publish.

    section_specs: dict mapping course_id -> list of {"period": int,
    "capacity": int, "room_id": str} (room_id may be omitted to cycle room_ids).
    Sections within a course are scheduled in ascending created_at order (list
    order), so spec idx lines up with creation order. Returns the refreshed
    term dict.
    """
    sections = list_term_sections(term_id)
    for course_id, specs in section_specs.items():
        course_sections = [s for s in sections if s["course_id"] == course_id]
        course_sections.sort(key=lambda s: s["created_at"])
        for idx, spec in enumerate(specs):
            room_id = spec.get("room_id") or room_ids[idx % len(room_ids)]
            schedule_section(
                course_sections[idx]["id"], teacher_id, room_id,
                spec["period"], spec["capacity"], term_id,
            )
    return get_success_data(api_client.publish_term(term_id, ADMIN))


def drive_term_to_change_window(term_id):
    get_success_data(api_client.open_change_window(term_id, ADMIN))
    return get_success_data(api_client.get_term(term_id, ADMIN))


def drive_term_to_locked(term_id):
    get_success_data(api_client.close_change_window(term_id, ADMIN))
    return get_success_data(api_client.get_term(term_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: change-request workflow helpers
# ---------------------------------------------------------------------------


def make_change_request(student_id, term_id, kind, drop_entry_id=None,
                        add_section_id=None, reason="Schedule adjustment needed"):
    """File a change request as the owning student. Returns the request dict."""
    payload = {"student_id": student_id, "term_id": term_id, "kind": kind, "reason": reason}
    if drop_entry_id is not None:
        payload["drop_entry_id"] = drop_entry_id
    if add_section_id is not None:
        payload["add_section_id"] = add_section_id
    return get_success_data(api_client.create_change_request(
        payload, make_student_headers(student_id),
    ))


def claim_change_request(request_id, counselor_id):
    return get_success_data(api_client.claim_change_request(
        request_id, make_counselor_headers(counselor_id),
    ))


def approve_change_request(request_id, term_id):
    """Decide APPROVE as an opaque administrator, re-reading the term version."""
    version = get_term_version(term_id)
    return get_success_data(api_client.decide_change_request(request_id, {
        "decision": "APPROVE", "expected_term_version": version,
    }, TEST_USERS["admin_headers"]))


def setup_approved_change_request(student_id, counselor_id, term_id, kind,
                                  drop_entry_id=None, add_section_id=None,
                                  reason="Schedule adjustment needed"):
    """File -> claim -> approve. Returns the APPROVED change request dict."""
    req = make_change_request(student_id, term_id, kind, drop_entry_id, add_section_id, reason)
    claim_change_request(req["id"], counselor_id)
    return approve_change_request(req["id"], term_id)


def get_enrolled_entries(student_id, term_id=None):
    params = {"state": "ENROLLED"}
    if term_id:
        params["term_id"] = term_id
    return get_success_data(api_client.get_student_schedule(student_id, ADMIN, params=params))


# ---------------------------------------------------------------------------
# Appointment helpers
# ---------------------------------------------------------------------------


def set_clock(to_iso8601):
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN))


def make_appointment(counselor_id, student_id, start_at, end_at):
    """Book an appointment as the attending counselor."""
    return get_success_data(api_client.create_appointment({
        "counselor_id": counselor_id, "student_id": student_id,
        "start_at": start_at, "end_at": end_at,
    }, make_counselor_headers(counselor_id)))


def make_no_show_appointment(counselor_id, student_id, start_at, end_at):
    """Book + mark-no-show. Returns the resolved appointment dict."""
    appt = make_appointment(counselor_id, student_id, start_at, end_at)
    return get_success_data(api_client.mark_no_show_appointment(
        appt["id"], make_counselor_headers(counselor_id),
    ))


# ---------------------------------------------------------------------------
# Tier 5: full change-window / locked scenarios
# ---------------------------------------------------------------------------


def setup_change_window_scenario(courses, students, section_specs,
                                 periods_per_day=8, max_students_per_section=32,
                                 class_size_target=25, term_code="CW-TERM",
                                 counselor_name="C Scenario", counselor_max=500,
                                 open_window=True, **term_extra):
    """Build a term through COLLECTING -> ... -> CHANGE_WINDOW (or PUBLISHED when
    open_window is False).

    courses: list of kwargs-dicts for setup_course (must include course_code).
    students: list of dicts:
        {ref, grade_level=9, special_program="NONE", earned_credits=None,
         requests: [(course_index, priority_rank)]}   (all submitted primaries)
    section_specs: {course_index: [{"period": p, "capacity": c}, ...]}; each spec
    is applied to the course's DRAFT sections in ascending created_at order.

    Every section gets its own (teacher, room) pair so no grid conflict can
    arise; each teacher is qualified for the course it teaches.

    Returns dict(term, counselor, courses, students, sections) with sections
    keyed by course index, in spec order, refreshed after publish.
    """
    counselor = setup_counselor(max_caseload=counselor_max, full_name=counselor_name)
    term = setup_term(term_code, periods_per_day=periods_per_day,
                      max_students_per_section=max_students_per_section,
                      class_size_target=class_size_target, **term_extra)
    course_objs = [
        setup_course(**{("code" if k == "course_code" else k): v
                        for k, v in c.items()})
        for c in courses
    ]
    student_objs = []
    for spec in students:
        stu = setup_student(
            counselor["id"], spec["ref"],
            grade_level=spec.get("grade_level", 9),
            special_program=spec.get("special_program", "NONE"),
            earned_credits=spec.get("earned_credits"),
        )
        for course_idx, rank in spec["requests"]:
            make_and_submit_request(stu["id"], course_objs[course_idx]["id"], term["id"], rank)
        student_objs.append(stu)

    drive_term_to_building(term["id"])
    all_sections = list_term_sections(term["id"])

    teacher_pool = {}
    room_pool = {}
    n_slots = [0] * (periods_per_day + 2)
    scheduled = {}
    seq = 0
    for course_idx, specs in section_specs.items():
        course_sections = sorted(
            [s for s in all_sections if s["course_id"] == course_objs[course_idx]["id"]],
            key=lambda s: s["created_at"],
        )
        scheduled[course_idx] = []
        for idx, spec in enumerate(specs):
            section = course_sections[idx]
            period = spec["period"]
            n_slots[period] += 1
            key = (period, n_slots[period])
            if key not in teacher_pool:
                seq += 1
                teacher_pool[key] = setup_teacher(max_sections=20,
                                                  full_name=f"T-{term_code}-{seq}")
                room_pool[key] = setup_room(f"{term_code}-R{seq}", capacity=64)
            teacher = teacher_pool[key]
            room = room_pool[key]
            qualify_teacher(teacher["id"], course_objs[course_idx]["id"])
            scheduled[course_idx].append(schedule_section(
                section["id"], teacher["id"], room["id"], period,
                spec["capacity"], term["id"],
            ))

    get_success_data(api_client.publish_term(term["id"], ADMIN))
    if open_window:
        drive_term_to_change_window(term["id"])
    # Refresh section state after publish
    refreshed = {}
    for course_idx, secs in scheduled.items():
        refreshed[course_idx] = [
            get_success_data(api_client.get_section(s["id"], ADMIN)) for s in secs
        ]
    return {
        "term": get_success_data(api_client.get_term(term["id"], ADMIN)),
        "counselor": counselor,
        "courses": course_objs,
        "students": student_objs,
        "sections": refreshed,
    }


def entry_for(api, student_id, section_id):
    """Find the student's ENROLLED entry on a section, or None."""
    entries = get_success_data(api.get_student_schedule(student_id, ADMIN))
    for entry in entries:
        if entry["section_id"] == section_id and entry["state"] == "ENROLLED":
            return entry
    return None
