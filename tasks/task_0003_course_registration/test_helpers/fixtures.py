"""Composite setup helpers for multi-step test prerequisites.

All ownership-gated setup calls thread the actual entity id through
make_student_headers / make_professor_headers so the implementation's
ownership check (PRD §2.1) sees a faithful X-User-ID.

A monotonically-increasing time base is used per fixture call so each
test gets a fresh non-overlapping Term window. The implementation's
clock is advanced forward only, so successive fixture calls must use
strictly increasing base instants.
"""
import uuid
from typing import Optional, List, Dict, Any
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_student_payload, create_department_payload, create_campus_payload,
    create_professor_payload, create_lab_equipment_payload, create_term_payload,
    create_course_payload, create_course_offering_payload,
    create_enrollment_request_payload, create_over_limit_application_payload,
    create_department_access_grant_payload, create_credit_equivalence_policy_payload,
    advance_clock_payload,
)
from .test_users import (
    TEST_USERS, make_student_headers, make_professor_headers,
)
from .constants import DEFAULTS


# ─── Time / clock helpers ──────────────────────────────────────────────
# Monotonic global counter so each fixture call uses a fresh future window.
# Start far enough in the future to avoid colliding with previous test runs
# that may have left the server clock advanced.
_TIME_BASE: List[int] = [2_000_000_000]  # ~2033
_STRIDE_SECONDS = 86_400 * 365 * 2       # 2-year stride per fixture call


def _next_time_base() -> int:
    base = _TIME_BASE[0]
    _TIME_BASE[0] += _STRIDE_SECONDS
    return base


def _unique_code(prefix: str) -> str:
    """Short unique code for test artifacts that need globally-unique names."""
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def advance_clock(target_unix_seconds: int) -> dict:
    """Advance the system clock to a target instant (Registrar capability)."""
    res = api_client.advance_clock(
        advance_clock_payload(target_unix_seconds), TEST_USERS["registrar_headers"]
    )
    return get_success_data(res)


def run_sweep() -> dict:
    res = api_client.run_sweep(TEST_USERS["registrar_headers"])
    return get_success_data(res)


# ─── Tier 1: primitive entity creators ─────────────────────────────────
def create_campus(commute_minutes_to: Optional[dict] = None,
                   code_prefix: str = "CAMPUS") -> dict:
    payload = create_campus_payload(
        code=_unique_code(code_prefix), name=f"{code_prefix} Campus",
        commute_minutes_to=commute_minutes_to or {},
    )
    return get_success_data(api_client.create_campus(payload, TEST_USERS["registrar_headers"]))


def create_department(campus_id: str, code_prefix: str = "DEPT") -> dict:
    payload = create_department_payload(
        code=_unique_code(code_prefix), name=f"{code_prefix} Department",
        campus_id=campus_id,
    )
    return get_success_data(api_client.create_department(payload, TEST_USERS["registrar_headers"]))


def create_professor(department_id: str, is_chair: bool = False,
                     rank: str = "ASSOCIATE",
                     max_minutes: int = DEFAULTS["DEFAULT_TEACHING_MINUTES_CAP"],
                     full_name: Optional[str] = None) -> dict:
    payload = create_professor_payload(
        department_id=department_id,
        full_name=full_name or ("Chair" if is_chair else "Professor"),
        rank=rank, is_chair=is_chair,
        max_concurrent_teaching_minutes_per_week=max_minutes,
    )
    return get_success_data(api_client.create_professor(payload, TEST_USERS["registrar_headers"]))


def create_student(program_department_id: str, home_campus_id: str,
                   year_in_program: int = 1, gpa: float = 3.5,
                   completed_course_ids: Optional[list] = None,
                   program_id: Optional[str] = None,
                   full_name: Optional[str] = None) -> dict:
    payload = create_student_payload(
        full_name=full_name or "Test Student",
        program_id=program_id or f"PROG-{program_department_id}",
        program_department_id=program_department_id,
        home_campus_id=home_campus_id,
        year_in_program=year_in_program, gpa=gpa,
        completed_course_ids=completed_course_ids or [],
    )
    return get_success_data(api_client.create_student(payload, TEST_USERS["registrar_headers"]))


def create_lab_equipment(campus_id: str, setup_buffer_minutes: int = 0,
                         name_prefix: str = "EQUIPMENT") -> dict:
    payload = create_lab_equipment_payload(
        campus_id=campus_id, name=f"{name_prefix}-{_unique_code('L')}",
        setup_buffer_minutes=setup_buffer_minutes,
    )
    return get_success_data(api_client.create_lab_equipment(payload, TEST_USERS["registrar_headers"]))


def create_course(owning_department_id: str, credits: float = 3.0,
                  prerequisite_course_ids: Optional[list] = None,
                  equivalent_course_ids: Optional[list] = None,
                  code_prefix: str = "CRS") -> dict:
    payload = create_course_payload(
        code=_unique_code(code_prefix),
        title=f"{code_prefix} Course",
        credits=credits,
        owning_department_id=owning_department_id,
        prerequisite_course_ids=prerequisite_course_ids or [],
        equivalent_course_ids=equivalent_course_ids or [],
    )
    return get_success_data(api_client.create_course(payload, TEST_USERS["registrar_headers"]))


def create_term_in_planning(
    base_time: Optional[int] = None,
    registration_window_seconds: int = DEFAULTS["REGISTRATION_DURATION_SECONDS"],
    classes_window_seconds: int = DEFAULTS["CLASSES_DURATION_SECONDS"],
    exam_window_seconds: int = DEFAULTS["EXAM_WEEK_DURATION_SECONDS"],
) -> dict:
    """Create a Term in PLANNING with the given anchor schedule."""
    if base_time is None:
        base_time = _next_time_base()
    reg_close = base_time + registration_window_seconds
    classes_start = reg_close + 86_400  # 1 day buffer between reg-close and classes-start
    exam_start = classes_start + classes_window_seconds
    exam_end = exam_start + exam_window_seconds
    payload = create_term_payload(
        code=_unique_code("TERM"),
        registration_open_at=base_time,
        registration_close_at=reg_close,
        classes_start_at=classes_start,
        exam_window_start_at=exam_start,
        exam_window_end_at=exam_end,
    )
    return get_success_data(api_client.create_term(payload, TEST_USERS["registrar_headers"]))


def create_offering(term_id: str, course_id: str, campus_id: str,
                    instructor_id: str, base_capacity: int = 10,
                    scheduled_meetings: Optional[list] = None,
                    requires_lab_equipment_ids: Optional[list] = None) -> dict:
    payload = create_course_offering_payload(
        term_id=term_id, course_id=course_id, campus_id=campus_id,
        instructor_id=instructor_id, base_capacity=base_capacity,
        scheduled_meetings=scheduled_meetings,
        requires_lab_equipment_ids=requires_lab_equipment_ids or [],
    )
    return get_success_data(api_client.create_course_offering(payload, TEST_USERS["registrar_headers"]))


def open_offering(offering_id: str) -> dict:
    return get_success_data(api_client.open_course_offering(
        offering_id, TEST_USERS["registrar_headers"]
    ))


def close_offering(offering_id: str) -> dict:
    return get_success_data(api_client.close_course_offering(
        offering_id, TEST_USERS["registrar_headers"]
    ))


# ─── Tier 2: world primitives — basic infrastructure ───────────────────
def setup_basic_world(student_year: int = 1,
                       student_gpa: float = 3.5,
                       student_completed_course_ids: Optional[list] = None,
                       chair_rank: str = "FULL",
                       professor_rank: str = "ASSOCIATE",
                       instructor_max_minutes: int = 600,
                       term_base_time: Optional[int] = None) -> Dict[str, Any]:
    """Create a complete operating environment: campus + department +
    chair + non-chair professor + instructor + student + Term in
    REGISTRATION_OPEN. Returns a dict with all entities.

    The Term is created in PLANNING, then the clock is advanced to its
    registration_open_at so that the auto-transition fires and the term
    enters REGISTRATION_OPEN — the state most enrollment tests need.
    """
    campus = create_campus()
    department = create_department(campus["id"])
    chair = create_professor(department["id"], is_chair=True, rank=chair_rank,
                             full_name="Department Chair")
    professor = create_professor(department["id"], is_chair=False, rank=professor_rank,
                                 full_name="Designated Signer")
    instructor = create_professor(department["id"], is_chair=False, rank="ASSOCIATE",
                                  max_minutes=instructor_max_minutes,
                                  full_name="Default Instructor")
    student = create_student(
        program_department_id=department["id"], home_campus_id=campus["id"],
        year_in_program=student_year, gpa=student_gpa,
        completed_course_ids=student_completed_course_ids or [],
    )

    term = create_term_in_planning(base_time=term_base_time)
    # Advance the clock to registration_open_at so Term auto-transitions
    # PLANNING → REGISTRATION_OPEN (per PRD §2.13).
    advance_clock(term["registration_open_at"])
    term = get_success_data(api_client.get_term(term["id"], TEST_USERS["registrar_headers"]))

    return {
        "campus": campus,
        "department": department,
        "chair": chair,
        "professor": professor,
        "instructor": instructor,
        "student": student,
        "term": term,
    }


def setup_open_offering(world: Dict[str, Any],
                         credits: float = 3.0,
                         base_capacity: int = 10,
                         scheduled_meetings: Optional[list] = None,
                         course: Optional[dict] = None,
                         requires_lab_equipment_ids: Optional[list] = None,
                         instructor: Optional[dict] = None,
                         campus: Optional[dict] = None,
                         prerequisite_course_ids: Optional[list] = None,
                         equivalent_course_ids: Optional[list] = None) -> Dict[str, Any]:
    """In a world (term in REGISTRATION_OPEN), create a Course + CourseOffering and OPEN it."""
    if course is None:
        course = create_course(
            owning_department_id=world["department"]["id"],
            credits=credits,
            prerequisite_course_ids=prerequisite_course_ids,
            equivalent_course_ids=equivalent_course_ids,
        )
    offering = create_offering(
        term_id=world["term"]["id"],
        course_id=course["id"],
        campus_id=(campus or world["campus"])["id"],
        instructor_id=(instructor or world["instructor"])["id"],
        base_capacity=base_capacity,
        scheduled_meetings=scheduled_meetings,
        requires_lab_equipment_ids=requires_lab_equipment_ids,
    )
    offering = open_offering(offering["id"])
    return {"course": course, "offering": offering}


# ─── Tier 3: Enrollment helpers ────────────────────────────────────────
def submit_enrollment(student: dict, offering_id: str) -> Any:
    """Submit an EnrollmentRequest as the given student. Returns the raw response."""
    return api_client.create_enrollment_request(
        create_enrollment_request_payload(student_id=student["id"], offering_id=offering_id),
        make_student_headers(student["id"]),
    )


def submit_enrollment_success(student: dict, offering_id: str) -> dict:
    """Submit and get the resulting EnrollmentRequest (any 2xx outcome — APPROVED or WAITLISTED)."""
    res = submit_enrollment(student, offering_id)
    return get_success_data(res)


def cancel_enrollment(student: dict, request_id: str) -> dict:
    res = api_client.cancel_enrollment_request(request_id, make_student_headers(student["id"]))
    return get_success_data(res)


def settle_tuition(request_id: str) -> dict:
    res = api_client.settle_tuition(request_id, TEST_USERS["finance_headers"])
    return get_success_data(res)


# ─── Tier 4: full-offering / waitlist setup ────────────────────────────
def setup_offering_with_seat_taken(world: Dict[str, Any],
                                    occupant_year: int = 1,
                                    credits: float = 3.0,
                                    scheduled_meetings: Optional[list] = None,
                                    base_capacity: int = 1) -> Dict[str, Any]:
    """Open an offering and pre-fill a seat with a different student so
    a follow-up submission by `world['student']` will be WAITLISTED (when
    base_capacity matches occupants count).
    """
    co = setup_open_offering(world, credits=credits, base_capacity=base_capacity,
                              scheduled_meetings=scheduled_meetings)
    # Create a separate occupant student in the same department/campus so
    # the cross-department check passes.
    occupant = create_student(
        program_department_id=world["department"]["id"],
        home_campus_id=world["campus"]["id"],
        year_in_program=occupant_year, full_name="Seat Occupant",
    )
    occupant_request = submit_enrollment_success(occupant, co["offering"]["id"])
    assert occupant_request["academic_status"] == "APPROVED", (
        f"Occupant setup failed: expected APPROVED, got {occupant_request['academic_status']!r}"
    )
    return {**co, "occupant": occupant, "occupant_request": occupant_request}


def get_offering(offering_id: str) -> dict:
    return get_success_data(api_client.get_course_offering(
        offering_id, TEST_USERS["registrar_headers"]
    ))


def get_enrollment_request(request_id: str) -> dict:
    return get_success_data(api_client.get_enrollment_request(
        request_id, TEST_USERS["registrar_headers"]
    ))


def list_waitlist(offering_id: str) -> list:
    res = api_client.get_course_offering_waitlist(
        offering_id, TEST_USERS["registrar_headers"]
    )
    data, _meta = validate_paginated(res)
    return data


def list_student_sync_events(student_id: str) -> list:
    res = api_client.get_student_sync_events(
        student_id, TEST_USERS["registrar_headers"]
    )
    data, _meta = validate_paginated(res)
    return data


# ─── Tier 5: OverLimitApplication helpers ──────────────────────────────
def create_over_limit_application(student: dict, term_id: str,
                                   primary_signer: dict, secondary_signer: dict,
                                   requested_extension_credits: float = 6.0,
                                   justification: str = "Need extra credits") -> dict:
    payload = create_over_limit_application_payload(
        student_id=student["id"], term_id=term_id,
        requested_extension_credits=requested_extension_credits,
        justification=justification,
        primary_signer_id=primary_signer["id"],
        secondary_signer_id=secondary_signer["id"],
    )
    return get_success_data(api_client.create_over_limit_application(
        payload, make_student_headers(student["id"])
    ))


def submit_application(student: dict, application_id: str) -> dict:
    return get_success_data(api_client.submit_over_limit_application(
        application_id, make_student_headers(student["id"])
    ))


def sign_application(professor: dict, application_id: str,
                     version: Optional[int] = None) -> dict:
    body = {} if version is None else {"version": version}
    return get_success_data(api_client.sign_over_limit_application(
        application_id, body, make_professor_headers(professor["id"])
    ))


def reject_application(professor: dict, application_id: str,
                       version: Optional[int] = None) -> dict:
    body = {} if version is None else {"version": version}
    return get_success_data(api_client.reject_over_limit_application(
        application_id, body, make_professor_headers(professor["id"])
    ))


def revise_application(student: dict, application_id: str) -> dict:
    return get_success_data(api_client.revise_over_limit_application(
        application_id, make_student_headers(student["id"])
    ))


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_over_limit_application(
        application_id, TEST_USERS["registrar_headers"]
    ))


# ─── Tier 6: cross-department / cross-program scaffolding ──────────────
def setup_cross_department_world() -> Dict[str, Any]:
    """Create two departments on a shared campus, with a student in D1.
    Useful for cross-department access tests.
    """
    campus = create_campus()
    department_home = create_department(campus["id"], code_prefix="DHOME")
    department_other = create_department(campus["id"], code_prefix="DOTHER")
    chair = create_professor(department_home["id"], is_chair=True, rank="FULL",
                             full_name="Home Chair")
    professor = create_professor(department_home["id"], is_chair=False, rank="ASSOCIATE",
                                 full_name="Home Signer")
    instructor_other = create_professor(department_other["id"], is_chair=False, rank="ASSOCIATE",
                                         full_name="Other Instructor", max_minutes=600)
    student = create_student(
        program_department_id=department_home["id"],
        home_campus_id=campus["id"], year_in_program=2,
    )
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])
    term = get_success_data(api_client.get_term(term["id"], TEST_USERS["registrar_headers"]))
    return {
        "campus": campus,
        "department_home": department_home,
        "department_other": department_other,
        "chair": chair,
        "professor": professor,
        "instructor_other": instructor_other,
        "student": student,
        "term": term,
    }


def grant_cross_department_access(source_department_id: str, target_department_id: str,
                                    categories: list, bidirectional: bool = False) -> dict:
    payload = create_department_access_grant_payload(
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        course_categories_allowed=categories,
        bidirectional=bidirectional,
    )
    return get_success_data(api_client.create_department_access_grant(
        payload, TEST_USERS["registrar_headers"]
    ))


def setup_two_program_world_with_completed_source_course() -> Dict[str, Any]:
    """For transferable_credits tests:
    - Two programs (SRC_PRG rooted in D_SRC; TGT_PRG rooted in D_TGT).
    - One source course owned by D_SRC.
    - Two target courses owned by D_TGT.
    - One student in TGT_PRG/D_TGT with the source course in completed_course_ids.
    """
    campus = create_campus()
    d_src = create_department(campus["id"], code_prefix="DSRC")
    d_tgt = create_department(campus["id"], code_prefix="DTGT")
    src_program_id = f"SRCPROG-{d_src['id'][:8]}"
    tgt_program_id = f"TGTPROG-{d_tgt['id'][:8]}"

    c_src = create_course(owning_department_id=d_src["id"], credits=1.0, code_prefix="CSRC")
    c_tgt = create_course(owning_department_id=d_tgt["id"], credits=1.0, code_prefix="CTGT")
    c_tgt2 = create_course(owning_department_id=d_tgt["id"], credits=1.0, code_prefix="CTGT2")

    student = create_student(
        program_department_id=d_tgt["id"],
        home_campus_id=campus["id"],
        year_in_program=2,
        program_id=tgt_program_id,
        completed_course_ids=[c_src["id"]],
        full_name="Cross-Program Student",
    )
    return {
        "campus": campus,
        "d_src": d_src, "d_tgt": d_tgt,
        "src_program_id": src_program_id, "tgt_program_id": tgt_program_id,
        "c_src": c_src, "c_tgt": c_tgt, "c_tgt2": c_tgt2,
        "student": student,
    }


def create_credit_equivalence_policy(source_program_id: str, target_program_id: str,
                                      source_course_id: str, target_course_id: str,
                                      transfer_factor: float = 1.0) -> dict:
    payload = create_credit_equivalence_policy_payload(
        source_program_id=source_program_id,
        target_program_id=target_program_id,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
        transfer_factor=transfer_factor,
    )
    return get_success_data(api_client.create_credit_equivalence_policy(
        payload, TEST_USERS["registrar_headers"]
    ))


def get_degree_plan(student_id: str, headers: Optional[dict] = None) -> dict:
    if headers is None:
        headers = TEST_USERS["registrar_headers"]
    return get_success_data(api_client.get_student_degree_plan(student_id, headers))


# ─── Tier 7: load student credits / fraud helpers ──────────────────────
def load_student_credits_via_approved(world: Dict[str, Any],
                                        target_credits: float,
                                        per_course_credits: float = 4.0,
                                        scheduled_meeting_day: int = 0,
                                        meeting_start: int = 540,
                                        meeting_end: int = 600,
                                        ) -> List[Dict[str, Any]]:
    """Build N independent OPEN offerings and submit-and-approve the world's
    student into each so that total APPROVED Course.credits == target_credits.

    Each offering has its own course owned by the home department (so no
    cross-department check fires) and its own meeting day to avoid
    time-conflict collisions across additions.
    """
    results: List[Dict[str, Any]] = []
    accumulated = 0.0
    day_cycle = scheduled_meeting_day
    while accumulated + per_course_credits <= target_credits + 1e-9:
        co = setup_open_offering(
            world,
            credits=per_course_credits,
            base_capacity=5,
            scheduled_meetings=[{
                "day_of_week": day_cycle % 7,
                "start_minute_of_day": meeting_start,
                "end_minute_of_day": meeting_end,
            }],
        )
        er = submit_enrollment_success(world["student"], co["offering"]["id"])
        assert er["academic_status"] == "APPROVED", (
            f"Setup failed loading credits: expected APPROVED, got {er['academic_status']!r}"
        )
        results.append({"course": co["course"], "offering": co["offering"], "request": er})
        accumulated += per_course_credits
        day_cycle += 1
    return results


def raise_student_fraud_score(world: Dict[str, Any],
                                target_score: int) -> Dict[str, Any]:
    """Raise the student's fraud_score to exactly `target_score` using the
    rapid-resubmission signal (PRD §2.11: each over-limit attempt adds +5).

    Strategy: open many tiny-credit offerings (each on a distinct day to
    avoid time conflicts and each with capacity >> 1 to absorb successful
    submissions). Submit RAPID_SUBMIT_LIMIT successful enrollments, then
    issue (target_score / 5) additional submissions which all trip the
    rate limit and add +5 each. Finally, advance the clock past the
    60-second window so the rate-limit counter resets and follow-up
    submissions in the test are not interfered with.
    """
    from .constants import FRAUD
    assert target_score % FRAUD["RAPID_SUBMIT_PENALTY"] == 0, (
        "raise_student_fraud_score requires target_score to be a multiple of "
        f"RAPID_SUBMIT_PENALTY={FRAUD['RAPID_SUBMIT_PENALTY']}"
    )
    n_penalty = target_score // FRAUD["RAPID_SUBMIT_PENALTY"]
    n_successful = FRAUD["RAPID_SUBMIT_LIMIT"] + 1   # crosses the strict-greater-than threshold

    # Build the successful-pad offerings (low credits, distinct days).
    pad_offerings: List[Dict[str, Any]] = []
    for i in range(n_successful):
        co = setup_open_offering(
            world, credits=0.01, base_capacity=5,
            scheduled_meetings=[{
                "day_of_week": i % 7,
                "start_minute_of_day": (i // 7) * 30 + 60,
                "end_minute_of_day": (i // 7) * 30 + 90,
            }],
        )
        er = submit_enrollment_success(world["student"], co["offering"]["id"])
        assert er["academic_status"] == "APPROVED", (
            f"Setup pad submission failed: status={er['academic_status']!r}"
        )
        pad_offerings.append(co)

    # Build a SINGLE rate-limit absorber offering (the rate-limited submissions
    # don't consume seats — they're rejected before any state change).
    rl_offering = setup_open_offering(
        world, credits=0.01, base_capacity=5,
        scheduled_meetings=[{
            "day_of_week": (n_successful + 1) % 7,
            "start_minute_of_day": 800,
            "end_minute_of_day": 830,
        }],
    )
    for _ in range(n_penalty):
        # We expect rate-limited rejections; do not assert success.
        api_client.create_enrollment_request(
            create_enrollment_request_payload(
                student_id=world["student"]["id"],
                offering_id=rl_offering["offering"]["id"],
            ),
            make_student_headers(world["student"]["id"]),
        )

    # Push the clock past the 60-second rate-limit window so subsequent
    # submissions in the actual test are not throttled. The current term's
    # registration_open_at is in the past; we advance by FRAUD window + 1.
    current_term = get_success_data(api_client.get_term(
        world["term"]["id"], TEST_USERS["registrar_headers"]
    ))
    # Use a large enough advance to clear the 60s window plus some slack;
    # but keep us inside the term's registration window.
    advance_target = max(current_term["registration_open_at"], 0) + FRAUD["RAPID_SUBMIT_WINDOW_SECONDS"] + 5
    # advance_clock is forward-only; if the current target is already greater,
    # the implementation may either no-op or error. Use the larger value safely.
    try:
        advance_clock(advance_target)
    except Exception:
        pass
    return {"pad_offerings": pad_offerings, "rate_limit_offering": rl_offering}


# Reload student to read the updated fraud_score
def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, TEST_USERS["registrar_headers"]))
