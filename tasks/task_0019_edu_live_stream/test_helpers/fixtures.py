"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures inside individual tests.

**Identity threading is mandatory** (PRD §2.1). Whenever a fixture creates an
entity-backed role's backing record (Instructor, Student), any ownership-gated
call made on behalf of that role MUST use make_<role>_headers(<actual-id>),
NEVER the shared TEST_USERS fallback. The shared fallbacks carry an X-User-ID
that does not match any real entity id, so every ownership check would reject
the call.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    assign_enrollment_payload,
    checkin_payload,
    create_announcement_payload,
    create_assignment_payload,
    create_chapter_payload,
    create_class_group_payload,
    create_course_payload,
    create_enrollment_payload,
    create_instructor_payload,
    create_leave_request_payload,
    create_live_class_payload,
    create_refund_request_payload,
    create_student_payload,
    create_submission_payload,
    create_watch_session_payload,
    grade_submission_payload,
    request_revision_payload,
    update_submission_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_instructor_headers,
    make_student_headers,
    make_ta_headers,
)


# ──────────────────────────────────────────────────────────
# Clock helpers (PRD §2.10, §3.9)
# ──────────────────────────────────────────────────────────

def advance_clock(seconds: int) -> Dict[str, Any]:
    """POST /_clock/advance — advance now_ts by `seconds` (PRD §3.9)."""
    return get_success_data(api_client.advance_clock(seconds, TEST_USERS["admin_headers"]))


def sweep_at_risk() -> Dict[str, Any]:
    """POST /_sweep/at-risk — force at-risk evaluation across all enrolments (PRD §3.9)."""
    return get_success_data(api_client.sweep_at_risk(TEST_USERS["admin_headers"]))


def advance_clock_days(days: int) -> Dict[str, Any]:
    """Convenience wrapper: advance clock by `days` whole days (86400s each)."""
    return advance_clock(days * 86400)


# ──────────────────────────────────────────────────────────
# Tier 0: Atomic-actor creators (Instructor, Student)
# ──────────────────────────────────────────────────────────

def create_instructor(**overrides: Any) -> Dict[str, Any]:
    """POST /instructors — registered by AcademicAdmin (PRD §3.2)."""
    admin = TEST_USERS["admin_headers"]
    payload = create_instructor_payload(**overrides)
    return get_success_data(api_client.create_instructor(payload, admin))


def create_student(**overrides: Any) -> Dict[str, Any]:
    """POST /students — registered by AcademicAdmin or self (PRD §3.2)."""
    admin = TEST_USERS["admin_headers"]
    payload = create_student_payload(**overrides)
    return get_success_data(api_client.create_student(payload, admin))


# ──────────────────────────────────────────────────────────
# Tier 1: Course state progression
# ──────────────────────────────────────────────────────────

def create_draft_course(
    *,
    instructor: Optional[Dict[str, Any]] = None,
    list_price_cents: int = 100000,
    discount_percent: int = 0,
    **course_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create an Instructor and a DRAFT Course owned by them. Returns (course, instructor)."""
    if instructor is None:
        instructor = create_instructor()
    instr_headers = make_instructor_headers(instructor["id"])
    course = get_success_data(api_client.create_course(
        create_course_payload(
            instructor["id"],
            list_price_cents=list_price_cents,
            discount_percent=discount_percent,
            **course_overrides,
        ),
        instr_headers,
    ))
    return course, instructor


def add_chapter(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    ordinal: int = 1,
    video_duration_seconds: int = 1000,
    required_for_completion: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/chapters using the course owner's identity."""
    instr_headers = make_instructor_headers(instructor["id"])
    return get_success_data(api_client.create_chapter(
        course["id"],
        create_chapter_payload(
            ordinal=ordinal,
            video_duration_seconds=video_duration_seconds,
            required_for_completion=required_for_completion,
            **overrides,
        ),
        instr_headers,
    ))


def submit_course_for_review(course: Dict[str, Any], instructor: Dict[str, Any]) -> Dict[str, Any]:
    """DRAFT → UNDER_REVIEW (PRD §3.1). Owner-only."""
    return get_success_data(api_client.submit_course_for_review(
        course["id"], make_instructor_headers(instructor["id"])
    ))


def approve_course(course: Dict[str, Any]) -> Dict[str, Any]:
    """UNDER_REVIEW → PUBLISHED. AcademicAdmin only (PRD §3.1)."""
    return get_success_data(api_client.approve_course(course["id"], TEST_USERS["admin_headers"]))


def reject_course(course: Dict[str, Any]) -> Dict[str, Any]:
    """UNDER_REVIEW → REJECTED. AcademicAdmin only (PRD §3.1)."""
    return get_success_data(api_client.reject_course(course["id"], TEST_USERS["admin_headers"]))


def return_course_to_draft(course: Dict[str, Any], instructor: Dict[str, Any]) -> Dict[str, Any]:
    """REJECTED → DRAFT. Owner-only (PRD §3.1)."""
    return get_success_data(api_client.return_course_to_draft(
        course["id"], make_instructor_headers(instructor["id"])
    ))


def delist_course(course: Dict[str, Any]) -> Dict[str, Any]:
    """PUBLISHED → DELISTED with depth-3 cascade. AcademicAdmin only (PRD §3.1)."""
    return get_success_data(api_client.delist_course(course["id"], TEST_USERS["admin_headers"]))


def create_published_course(
    *,
    instructor: Optional[Dict[str, Any]] = None,
    list_price_cents: int = 100000,
    discount_percent: int = 0,
    num_required_chapters: int = 1,
    chapter_video_seconds: int = 1000,
    **course_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create an Instructor + Course, add required chapters, walk through
    DRAFT → UNDER_REVIEW → PUBLISHED. Returns (course, instructor, chapters).

    Used by every test that needs a PUBLISHED course (enrollments, live
    classes, refunds, etc.). Chapter durations default to chapter_video_seconds
    each; pass num_required_chapters>1 to build multi-chapter syllabi for
    progress-percentage tests.
    """
    course, instructor = create_draft_course(
        instructor=instructor,
        list_price_cents=list_price_cents,
        discount_percent=discount_percent,
        **course_overrides,
    )
    chapters: List[Dict[str, Any]] = []
    for i in range(num_required_chapters):
        ch = add_chapter(
            course,
            instructor,
            ordinal=i + 1,
            video_duration_seconds=chapter_video_seconds,
            required_for_completion=True,
        )
        chapters.append(ch)
    submit_course_for_review(course, instructor)
    course = approve_course(course)
    return course, instructor, chapters


# ──────────────────────────────────────────────────────────
# Tier 2: Enrollment + class group
# ──────────────────────────────────────────────────────────

def enroll_student(
    course: Dict[str, Any],
    *,
    student: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Student (if not supplied) and enroll them in `course`. Returns (enrollment, student).

    The enrollment call uses the student's own headers (PRD §2.1: Student is
    entity-backed; X-User-ID == Student.id). This is required because the
    POST /courses/{id}/enrollments endpoint is restricted to the Student role
    and the body's student_id must equal the X-User-ID of the caller.
    """
    if student is None:
        student = create_student()
    student_headers = make_student_headers(student["id"])
    enrollment = get_success_data(api_client.create_enrollment(
        course["id"],
        create_enrollment_payload(student["id"]),
        student_headers,
    ))
    return enrollment, student


def create_class_group(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    capacity: int = 50,
    ta: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/class-groups (PRD §3.2). Owned by the course's instructor."""
    payload_kwargs = dict(capacity=capacity)
    if ta is not None:
        payload_kwargs["ta_instructor_id"] = ta["id"]
    payload_kwargs.update(overrides)
    return get_success_data(api_client.create_class_group(
        course["id"],
        create_class_group_payload(**payload_kwargs),
        make_instructor_headers(instructor["id"]),
    ))


def assign_enrollment_to_group(
    class_group: Dict[str, Any],
    enrollment: Dict[str, Any],
    instructor: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /class-groups/{id}/assign-enrollment (PRD §3.2). Owner-or-admin."""
    return get_success_data(api_client.assign_enrollment_to_group(
        class_group["id"],
        assign_enrollment_payload(enrollment["id"]),
        make_instructor_headers(instructor["id"]),
    ))


# ──────────────────────────────────────────────────────────
# Tier 3: Live class lifecycle
# ──────────────────────────────────────────────────────────

def schedule_live_class(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    room_id: Optional[str] = None,
    start_ts: int = 5_000_000,
    end_ts: int = 5_003_600,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/live-classes (PRD §3.3). Owner-only; default room_id is unique per call.

    The instructor's availability windows from create_instructor() span
    [0, 10_000_000_000], so any reasonable timestamp passes the closed-interval
    instructor-availability check (PRD §3.3) by default.
    """
    if room_id is None:
        # Unique-per-call to avoid accidental overlap across tests in the same session.
        import uuid
        room_id = f"ROOM-{uuid.uuid4().hex[:8]}"
    return get_success_data(api_client.create_live_class(
        course["id"],
        create_live_class_payload(
            instructor_id=instructor["id"],
            room_id=room_id,
            start_ts=start_ts,
            end_ts=end_ts,
            **overrides,
        ),
        make_instructor_headers(instructor["id"]),
    ))


def start_live_class(
    live_class: Dict[str, Any], instructor: Dict[str, Any]
) -> Dict[str, Any]:
    """SCHEDULED → LIVE (PRD §3.3). Owner-only."""
    return get_success_data(api_client.start_live_class(
        live_class["id"], make_instructor_headers(instructor["id"])
    ))


def end_live_class(
    live_class: Dict[str, Any], instructor: Dict[str, Any]
) -> Dict[str, Any]:
    """LIVE → ENDED (PRD §3.3). Owner-only."""
    return get_success_data(api_client.end_live_class(
        live_class["id"], make_instructor_headers(instructor["id"])
    ))


def setup_live_session_in_progress(
    *,
    instructor: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
    start_ts: int = 5_000_000,
    end_ts: int = 5_003_600,
    course_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a LIVE LiveClass with one enrolled Student.

    Returns (course, instructor, student, enrollment, live_class) where
    live_class.status == "LIVE".

    Composes: create_published_course → enroll_student → schedule_live_class →
    advance clock to within +10min lead window → start_live_class.
    """
    course, instructor, _ = create_published_course(
        instructor=instructor, **(course_kwargs or {})
    )
    enrollment, student = enroll_student(course, student=student)
    live_class = schedule_live_class(course, instructor, start_ts=start_ts, end_ts=end_ts)
    # Advance clock to start_ts so 'start' passes the now_ts >= start_ts - 600 gate.
    advance_clock(start_ts)
    live_class = start_live_class(live_class, instructor)
    return course, instructor, student, enrollment, live_class


# ──────────────────────────────────────────────────────────
# Tier 4: Watch sessions and progress accumulation
# ──────────────────────────────────────────────────────────

def log_watch_session(
    enrollment: Dict[str, Any],
    student: Dict[str, Any],
    chapter_id: str,
    seconds_watched: int,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/watch-sessions (PRD §3.4). Student-owned."""
    return get_success_data(api_client.create_watch_session(
        enrollment["id"],
        create_watch_session_payload(chapter_id=chapter_id, seconds_watched=seconds_watched),
        make_student_headers(student["id"]),
    ))


def setup_enrollment_with_progress(
    *,
    target_progress_percent: float = 0.0,
    list_price_cents: int = 100000,
    discount_percent: int = 0,
    num_required_chapters: int = 2,
    chapter_video_seconds: int = 1000,
    instructor: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build a published course + enrollment whose progress_percent equals
    `target_progress_percent` (approximately, via watch_duration_percent).

    Returns (course, instructor, student, enrollment, chapters).

    Strategy: total video seconds across required chapters is
    num_required_chapters * chapter_video_seconds. To reach a watch_duration of
    P%, the student must watch exactly (P/100) * total seconds, distributed so
    no single chapter exceeds its video_duration_seconds (the per-chapter cap).
    The math is exact when target_progress_percent rounds to 1 decimal cleanly.
    """
    course, instructor, chapters = create_published_course(
        instructor=instructor,
        list_price_cents=list_price_cents,
        discount_percent=discount_percent,
        num_required_chapters=num_required_chapters,
        chapter_video_seconds=chapter_video_seconds,
    )
    enrollment, student = enroll_student(course, student=student)
    if target_progress_percent <= 0:
        return course, instructor, student, enrollment, chapters

    total_seconds = num_required_chapters * chapter_video_seconds
    seconds_to_watch = int(round(total_seconds * (target_progress_percent / 100.0)))
    # Spread across chapters without exceeding any per-chapter cap.
    remaining = seconds_to_watch
    for ch in chapters:
        if remaining <= 0:
            break
        chunk = min(remaining, ch["video_duration_seconds"])
        if chunk > 0:
            log_watch_session(enrollment, student, ch["id"], chunk)
            remaining -= chunk
    return course, instructor, student, enrollment, chapters


# ──────────────────────────────────────────────────────────
# Tier 4b: Refund-targeted setups
# ──────────────────────────────────────────────────────────

def setup_enrollment_for_refund(
    *,
    list_price_cents: int = 100000,
    discount_percent: int = 0,
    days_after_enroll: int = 0,
    target_progress_percent: float = 0.0,
    num_required_chapters: int = 2,
    chapter_video_seconds: int = 1000,
    instructor: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build an enrollment positioned at (days_after_enroll, target_progress_percent)
    for refund-tier boundary tests.

    Returns (course, instructor, student, enrollment, chapters). Enrollment is
    PAID/ACTIVE; clock has been advanced by `days_after_enroll` whole days
    (86400s each) since enrolled_at.
    """
    course, instructor, student, enrollment, chapters = setup_enrollment_with_progress(
        target_progress_percent=target_progress_percent,
        list_price_cents=list_price_cents,
        discount_percent=discount_percent,
        num_required_chapters=num_required_chapters,
        chapter_video_seconds=chapter_video_seconds,
        instructor=instructor,
        student=student,
    )
    if days_after_enroll > 0:
        advance_clock_days(days_after_enroll)
    return course, instructor, student, enrollment, chapters


def file_refund_request(
    enrollment: Dict[str, Any],
    student: Dict[str, Any],
    *,
    materials_kit_count: int = 0,
) -> Dict[str, Any]:
    """POST /enrollments/{id}/refund-requests (PRD §3.7). Student-owned."""
    return get_success_data(api_client.create_refund_request(
        enrollment["id"],
        create_refund_request_payload(materials_kit_count=materials_kit_count),
        make_student_headers(student["id"]),
    ))


def approve_refund_request(refund: Dict[str, Any]) -> Dict[str, Any]:
    """POST /refund-requests/{id}/approve (PRD §3.7). AcademicAdmin only."""
    return get_success_data(api_client.approve_refund_request(
        refund["id"], TEST_USERS["admin_headers"]
    ))


def reject_refund_request(refund: Dict[str, Any], reason: str = "Not eligible per policy.") -> Dict[str, Any]:
    """POST /refund-requests/{id}/reject (PRD §3.7). AcademicAdmin only."""
    from .factories import reject_refund_request_payload
    return get_success_data(api_client.reject_refund_request(
        refund["id"], reject_refund_request_payload(reason=reason),
        TEST_USERS["admin_headers"],
    ))


# ──────────────────────────────────────────────────────────
# Tier 5: Assignment + submission cyclic loop
# ──────────────────────────────────────────────────────────

def publish_assignment(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    fmt: str = "TEXT",
    due_ts: int = 99_999_999_999,
    max_score: int = 100,
    title: str = "Test Assignment",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /courses/{id}/assignments (PRD §3.8). Owner-only."""
    return get_success_data(api_client.create_assignment(
        course["id"],
        create_assignment_payload(
            title=title, fmt=fmt, due_ts=due_ts, max_score=max_score, **overrides
        ),
        make_instructor_headers(instructor["id"]),
    ))


def submit_assignment(
    assignment: Dict[str, Any],
    enrollment: Dict[str, Any],
    student: Dict[str, Any],
    *,
    fmt: str = "TEXT",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /assignments/{id}/submissions (PRD §3.8). Student-owned."""
    return get_success_data(api_client.create_submission(
        assignment["id"],
        create_submission_payload(enrollment["id"], fmt=fmt, **overrides),
        make_student_headers(student["id"]),
    ))


def start_review(submission: Dict[str, Any], instructor: Dict[str, Any]) -> Dict[str, Any]:
    """SUBMITTED → UNDER_REVIEW (PRD §3.8). Course owner OR class group's TA."""
    return get_success_data(api_client.start_submission_review(
        submission["id"], make_instructor_headers(instructor["id"])
    ))


def request_revision(
    submission: Dict[str, Any], instructor: Dict[str, Any], feedback: str = "Please revise."
) -> Dict[str, Any]:
    """UNDER_REVIEW → REVISION_REQUESTED (PRD §3.8). Course owner OR class group's TA."""
    return get_success_data(api_client.request_submission_revision(
        submission["id"],
        request_revision_payload(feedback=feedback),
        make_instructor_headers(instructor["id"]),
    ))


def resubmit(
    submission: Dict[str, Any], student: Dict[str, Any], *, fmt: str = "TEXT", **overrides: Any
) -> Dict[str, Any]:
    """REVISION_REQUESTED → SUBMITTED (PRD §3.8). Student-owned."""
    return get_success_data(api_client.update_submission_payload(
        submission["id"],
        update_submission_payload(fmt=fmt, **overrides),
        make_student_headers(student["id"]),
    ))


def grade_submission(
    submission: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    score: int = 80,
    feedback: str = "Good work.",
    override_plagiarism: Optional[bool] = None,
) -> Dict[str, Any]:
    """UNDER_REVIEW → GRADED (PRD §3.8). Course owner only."""
    payload_kwargs: Dict[str, Any] = {"score": score, "feedback": feedback}
    if override_plagiarism is not None:
        payload_kwargs["override_plagiarism"] = override_plagiarism
    return get_success_data(api_client.grade_submission(
        submission["id"],
        grade_submission_payload(**payload_kwargs),
        make_instructor_headers(instructor["id"]),
    ))


def setup_submission_under_review(
    *,
    fmt: str = "TEXT",
    instructor: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
    max_score: int = 100,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build (course, instructor, student, enrollment, assignment, submission)
    where submission is in UNDER_REVIEW.
    """
    course, instructor, _ = create_published_course(instructor=instructor)
    enrollment, student = enroll_student(course, student=student)
    assignment = publish_assignment(course, instructor, fmt=fmt, max_score=max_score)
    submission = submit_assignment(assignment, enrollment, student, fmt=fmt)
    submission = start_review(submission, instructor)
    return course, instructor, student, enrollment, assignment, submission


# ──────────────────────────────────────────────────────────
# Tier 6: Leave request lifecycle
# ──────────────────────────────────────────────────────────

def file_leave_request(
    enrollment: Dict[str, Any],
    live_class: Dict[str, Any],
    student: Dict[str, Any],
    *,
    reason: str = "Medical appointment.",
) -> Dict[str, Any]:
    """POST /leave-requests (PRD §3.3). Student-owned."""
    return get_success_data(api_client.create_leave_request(
        create_leave_request_payload(enrollment["id"], live_class["id"], reason=reason),
        make_student_headers(student["id"]),
    ))


def setup_pending_leave_with_ta(
    *,
    instructor: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
    start_ts: int = 5_000_000,
    end_ts: int = 5_003_600,
) -> Tuple[
    Dict[str, Any],  # course
    Dict[str, Any],  # instructor
    Dict[str, Any],  # ta_instructor (the TA's backing Instructor row)
    Dict[str, Any],  # student
    Dict[str, Any],  # enrollment
    Dict[str, Any],  # class_group (with ta_instructor_id == ta_instructor.id)
    Dict[str, Any],  # live_class (SCHEDULED)
    Dict[str, Any],  # leave_request (PENDING)
]:
    """Build the full PENDING-leave fixture used by leave-approve/reject tests.

    Builds course + instructor + a separate TA-Instructor + student + enrollment +
    class_group (TA assigned) + assigned enrollment + live_class (SCHEDULED) +
    leave_request (PENDING).

    Returns the 8-tuple above. The TA's headers are constructed via
    make_ta_headers(ta_instructor["id"]).
    """
    course, instructor, _ = create_published_course(instructor=instructor)
    ta_instructor = create_instructor()  # Stored as Instructor row per PRD §2.1
    enrollment, student = enroll_student(course, student=student)
    class_group = create_class_group(course, instructor, ta=ta_instructor)
    assign_enrollment_to_group(class_group, enrollment, instructor)
    live_class = schedule_live_class(course, instructor, start_ts=start_ts, end_ts=end_ts)
    leave_request = file_leave_request(enrollment, live_class, student)
    return course, instructor, ta_instructor, student, enrollment, class_group, live_class, leave_request


# ──────────────────────────────────────────────────────────
# Tier 7: Difficulty-design composite fixtures
# ──────────────────────────────────────────────────────────

def setup_course_delist_cascade(
    *,
    list_price_cents: int = 100000,
    chapter_video_seconds: int = 1000,
    instructor: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any],          # course (PUBLISHED)
    Dict[str, Any],          # instructor
    List[Dict[str, Any]],    # students [s_a, s_b]
    List[Dict[str, Any]],    # enrollments [e_a, e_b]
    Dict[str, Any],          # live_class (SCHEDULED)
    Dict[str, Any],          # refund_request (PENDING for enrollment_a)
]:
    """Pre-cascade fixture for difficulty rule 4 (course_delist_depth_3_cascade).

    PRD §3.1: "Every LiveClass belonging to this course that is currently in
    SCHEDULED is moved to CANCELLED... for every enrollment whose
    learning_status was ACTIVE and whose attendance window overlaps a now-
    cancelled live class, learning_status flips to AT_RISK ... every
    enrollment that flipped to AT_RISK in step two has any associated PENDING
    RefundRequest re-priced."
    """
    course, instructor, chapters = create_published_course(
        instructor=instructor,
        list_price_cents=list_price_cents,
        chapter_video_seconds=chapter_video_seconds,
    )
    student_a = create_student()
    student_b = create_student()
    enrollment_a, _ = enroll_student(course, student=student_a)
    enrollment_b, _ = enroll_student(course, student=student_b)
    # Schedule a live class within reach of the enrollment attendance windows.
    live_class = schedule_live_class(
        course, instructor, start_ts=10_000, end_ts=13_600
    )
    # File refund (PENDING) for enrollment_a.
    refund_request = file_refund_request(enrollment_a, student_a)
    return course, instructor, [student_a, student_b], [enrollment_a, enrollment_b], live_class, refund_request


def setup_room_with_existing_session(
    *,
    room_id: str = "ROOM-OVERLAP",
    instructor: Optional[Dict[str, Any]] = None,
    existing_start_ts: int = 1000,
    existing_end_ts: int = 2000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pre-existing live class for room-overlap tests (difficulty rule 8).

    Returns (course, instructor, existing_live_class). The existing class is
    SCHEDULED on `room_id` over [existing_start_ts, existing_end_ts).
    """
    course, instructor, _ = create_published_course(instructor=instructor)
    existing = schedule_live_class(
        course, instructor, room_id=room_id,
        start_ts=existing_start_ts, end_ts=existing_end_ts,
    )
    return course, instructor, existing


def setup_instructor_with_window(
    *,
    window_start: int = 1000,
    window_end: int = 5000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pre-built course + instructor whose availability_windows is a single
    closed interval [window_start, window_end] for difficulty rule 8
    (instructor_availability boundary)."""
    instructor = create_instructor(
        availability_windows=[{"start_ts": window_start, "end_ts": window_end}]
    )
    course, _, _ = create_published_course(instructor=instructor)
    return course, instructor, instructor


def reach_revision_count(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    enrollment: Dict[str, Any],
    student: Dict[str, Any],
    target_count: int,
    *,
    fmt: str = "TEXT",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a Submission through the cyclic loop until revision_count == target_count.

    Returns (assignment, submission). Submission ends in SUBMITTED (after the
    student resubmits) — caller can then start-review and request another
    revision to test the cap, or grade it.

    PRD §3.8 cycle: SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED.
    revision_count increments on the REVISION_REQUESTED → SUBMITTED leg.
    """
    assignment = publish_assignment(course, instructor, fmt=fmt)
    submission = submit_assignment(assignment, enrollment, student, fmt=fmt)
    for _ in range(target_count):
        submission = start_review(submission, instructor)
        submission = request_revision(submission, instructor, feedback="please redo")
        submission = resubmit(submission, student, fmt=fmt)
    return assignment, submission
