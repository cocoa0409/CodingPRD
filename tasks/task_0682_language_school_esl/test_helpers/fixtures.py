"""Composite setup helpers for the Language School ESL API.

Most interesting claims require the system in a specific multi-step state:
a student with a scored placement test matching a cohort's level/track, an
enrollment created and confirmed to ENROLLED, optionally an I-20 issued and
status activated, optionally attendance + a progress report + clock advance so
the enrollment can complete. These helpers encapsulate those chains.

Every helper builds its preconditions from scratch (the harness restarts the
server with an empty DB before every test) and uses get_success_data() so a
setup failure surfaces as a clear "Setup failed" rather than a confusing
assertion error.

Identity threading: when a fixture creates a Student and a downstream call is
ownership-gated (add-on create/cancel as the Student role), it uses
make_student_headers(student_id), never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_student_headers
from . import factories as f

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]
INSTR = TEST_USERS["instructor_headers"]

# raw_score -> band: 50 lands B1, 10 lands A1, 60 lands B2, etc. (PRD §3.2)
_LEVEL_TO_RAW = {"A1": 10, "A2": 30, "B1": 50, "B2": 65, "C1": 80, "C2": 95}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, REG))


# ---------------------------------------------------------------------------
# Tier 0 — single entity creators
# ---------------------------------------------------------------------------
def create_contract(contracted_seats=5, discount_tier="BRONZE", company_name="Test Co"):
    """Create an ACTIVE corporate contract. Returns the contract dict."""
    payload = f.create_corporate_contract_payload(
        company_name=company_name, contracted_seats=contracted_seats, discount_tier=discount_tier
    )
    return get_success_data(api_client.create_corporate_contract(payload, REG))


def create_student(is_international=False, corporate_contract_id=None, track="GENERAL", **overrides):
    """Register a bare student. Returns the student dict."""
    kwargs = dict(track=track, is_international=is_international)
    if corporate_contract_id is not None:
        kwargs["corporate_contract_id"] = corporate_contract_id
    kwargs.update(overrides)
    return get_success_data(api_client.create_student(f.create_student_payload(**kwargs), REG))


def create_cohort(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                  base_tuition_cents=100000, schedule_block="MORNING",
                  term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                  total_sessions=40, name="Cohort"):
    """Create an OPEN cohort. Returns the cohort dict (carries version)."""
    payload = f.create_cohort_payload(
        name=name, level=level, track=track, capacity=capacity, weekly_hours=weekly_hours,
        term_start=term_start, term_end=term_end, total_sessions=total_sessions,
        base_tuition_cents=base_tuition_cents, schedule_block=schedule_block,
    )
    return get_success_data(api_client.create_cohort(payload, REG))


# ---------------------------------------------------------------------------
# Tier 1 — student with a scored placement test (so confirm's placement gate passes)
# ---------------------------------------------------------------------------
def score_student_to_level(student_id, level="B1"):
    """Register and score a placement test so the student's placement_level == level."""
    pt = get_success_data(api_client.create_placement_test(
        f.create_placement_test_payload(student_id), REG))
    raw = _LEVEL_TO_RAW[level]
    get_success_data(api_client.score_placement_test(
        pt["id"], f.score_placement_test_payload(raw), INSTR))
    return pt


def create_placed_student(level="B1", track="GENERAL", is_international=False,
                          corporate_contract_id=None, **overrides):
    """Create a student and score them to `level` so they can be confirmed into a
    matching cohort. Returns the student dict (re-fetched so placement_level shows)."""
    stu = create_student(is_international=is_international, corporate_contract_id=corporate_contract_id,
                         track=track, **overrides)
    score_student_to_level(stu["id"], level)
    return get_success_data(api_client.get_student(stu["id"], REG))


# ---------------------------------------------------------------------------
# Tier 2 — enrollment creation + confirmation
# ---------------------------------------------------------------------------
def create_enrollment(student_id, cohort_id):
    """Create a PLACEMENT_PENDING enrollment. Returns the enrollment dict."""
    return get_success_data(api_client.create_enrollment(
        f.create_enrollment_payload(student_id, cohort_id), REG))


def confirm(enrollment_id, cohort_version, require_seat=True):
    """Confirm an enrollment with the given expected_cohort_version. Returns the
    confirm response data (ENROLLED or WAITLISTED)."""
    payload = f.confirm_enrollment_payload(cohort_version, require_seat=require_seat)
    return get_success_data(api_client.confirm_enrollment(enrollment_id, payload, REG))


def enroll_student(cohort, level="B1", track="GENERAL", is_international=False,
                   corporate_contract_id=None, require_seat=True):
    """Full chain: placed student -> enrollment -> confirm to ENROLLED on `cohort`.
    `cohort` is a cohort dict (must carry version). Returns (student, enrollment)
    where enrollment is the post-confirm (ENROLLED) data."""
    stu = create_placed_student(level=level, track=track, is_international=is_international,
                                corporate_contract_id=corporate_contract_id)
    enr = create_enrollment(stu["id"], cohort["id"])
    confirmed = confirm(enr["id"], cohort["version"], require_seat=require_seat)
    return stu, confirmed


def setup_enrolled_student(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                           base_tuition_cents=100000, schedule_block="MORNING",
                           is_international=False, corporate_contract_id=None,
                           term_start="2026-05-04T00:00:00Z", term_end="2026-08-01T00:00:00Z",
                           total_sessions=40):
    """Create cohort + placed student + enrollment confirmed ENROLLED.
    Returns (student, cohort, enrollment) — enrollment is the ENROLLED data."""
    cohort = create_cohort(level=level, track=track, capacity=capacity, weekly_hours=weekly_hours,
                           base_tuition_cents=base_tuition_cents, schedule_block=schedule_block,
                           term_start=term_start, term_end=term_end, total_sessions=total_sessions)
    stu, enr = enroll_student(cohort, level=level, track=track, is_international=is_international,
                              corporate_contract_id=corporate_contract_id)
    cohort = get_success_data(api_client.get_cohort(cohort["id"], REG))
    return stu, cohort, enr


def setup_pending_enrollment(level="B1", track="GENERAL", capacity=5, weekly_hours=18,
                             schedule_block="MORNING", is_international=False,
                             corporate_contract_id=None, score_level=None):
    """Create cohort + placed student + a PLACEMENT_PENDING enrollment (not yet
    confirmed). `score_level` overrides the placement test band (e.g. score A1
    while enrolling into a B1 cohort to force ERR_PLACEMENT_MISMATCH).
    Returns (student, cohort, enrollment)."""
    cohort = create_cohort(level=level, track=track, capacity=capacity, weekly_hours=weekly_hours,
                           schedule_block=schedule_block)
    placed_level = score_level if score_level is not None else level
    stu = create_placed_student(level=placed_level, track=track, is_international=is_international,
                                corporate_contract_id=corporate_contract_id)
    enr = create_enrollment(stu["id"], cohort["id"])
    cohort = get_success_data(api_client.get_cohort(cohort["id"], REG))
    return stu, cohort, enr


# ---------------------------------------------------------------------------
# Tier 3 — I-20 / visa lifecycle helpers
# ---------------------------------------------------------------------------
def issue_i20(student_id, reason=None):
    """DSO issues I-20: NONE -> INITIAL. Returns student dict."""
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.issue_i20(student_id, DSO, payload))


def activate_status(student_id, reason=None):
    """DSO activates: INITIAL -> ACTIVE. Returns student dict."""
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.activate_status(student_id, DSO, payload))


def place_probation(student_id, reason=None):
    """DSO places probation: ACTIVE -> PROBATION. Returns student dict."""
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.place_probation(student_id, DSO, payload))


def setup_active_international(weekly_hours=18, level="B1", track="GENERAL",
                              schedule_block="MORNING"):
    """International student, I-20 issued, ENROLLED into a `weekly_hours` cohort,
    then activated to ACTIVE visa status. Returns (student, cohort, enrollment)."""
    cohort = create_cohort(level=level, track=track, weekly_hours=weekly_hours,
                           schedule_block=schedule_block)
    stu = create_placed_student(level=level, track=track, is_international=True)
    issue_i20(stu["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    activate_status(stu["id"])
    stu = get_success_data(api_client.get_student(stu["id"], REG))
    enr = get_success_data(api_client.get_enrollment(enr["id"], REG))
    cohort = get_success_data(api_client.get_cohort(cohort["id"], REG))
    return stu, cohort, enr


# ---------------------------------------------------------------------------
# Tier 4 — attendance / progress / completion helpers
# ---------------------------------------------------------------------------
def mark_attendance(enrollment_id, session_index, status="PRESENT"):
    return get_success_data(api_client.create_attendance(
        f.create_attendance_payload(enrollment_id, session_index, status), INSTR))


def add_progress_report(enrollment_id, speaking=80, listening=80, reading=80, writing=80):
    return get_success_data(api_client.create_progress_report(
        f.create_progress_report_payload(enrollment_id, speaking, listening, reading, writing), INSTR))


def setup_completed_enrollment(level="B1", track="GENERAL", weekly_hours=9,
                               base_tuition_cents=100000, schedule_block="MORNING",
                               term_start="2026-04-01T00:00:00Z", term_end="2026-04-10T00:00:00Z",
                               total_sessions=10, present_sessions=1, absent_sessions=0,
                               speaking=80, listening=80, reading=80, writing=80,
                               complete_at="2026-04-11T00:00:00Z", is_international=False,
                               corporate_contract_id=None):
    """Full chain to a COMPLETED enrollment: cohort (short term) + placed student
    + ENROLLED + attendance marks + one progress report + clock past term_end +
    complete. Returns (student, cohort, enrollment) where enrollment is COMPLETED data."""
    cohort = create_cohort(level=level, track=track, weekly_hours=weekly_hours,
                           base_tuition_cents=base_tuition_cents, schedule_block=schedule_block,
                           term_start=term_start, term_end=term_end, total_sessions=total_sessions)
    stu = create_placed_student(level=level, track=track, is_international=is_international,
                                corporate_contract_id=corporate_contract_id)
    if is_international:
        issue_i20(stu["id"])
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    idx = 1
    for _ in range(present_sessions):
        mark_attendance(enr["id"], idx, "PRESENT")
        idx += 1
    for _ in range(absent_sessions):
        mark_attendance(enr["id"], idx, "ABSENT")
        idx += 1
    add_progress_report(enr["id"], speaking, listening, reading, writing)
    set_clock(complete_at)
    completed = get_success_data(api_client.complete_enrollment(enr["id"], REG))
    return stu, cohort, completed


# ---------------------------------------------------------------------------
# Tier 5 — waitlist / capacity scenarios
# ---------------------------------------------------------------------------
def setup_capacity1_with_waitlist(level="B1", track="GENERAL", schedule_block="MORNING"):
    """Capacity-1 cohort: student A confirmed ENROLLED (seat filled), student B
    confirmed -> WAITLISTED. Returns (cohort, student_a, enr_a, student_b, enr_b)
    where enr_a is ENROLLED data and enr_b is WAITLISTED data."""
    cohort = create_cohort(level=level, track=track, capacity=1, schedule_block=schedule_block)
    stu_a = create_placed_student(level=level, track=track)
    enr_a_pending = create_enrollment(stu_a["id"], cohort["id"])
    enr_a_data = confirm(enr_a_pending["id"], cohort["version"], require_seat=True)
    cohort = get_success_data(api_client.get_cohort(cohort["id"], REG))
    stu_b = create_placed_student(level=level, track=track)
    enr_b = create_enrollment(stu_b["id"], cohort["id"])
    enr_b_data = confirm(enr_b["id"], cohort["version"], require_seat=False)
    cohort = get_success_data(api_client.get_cohort(cohort["id"], REG))
    return cohort, stu_a, enr_a_data, stu_b, enr_b_data


def latest_cohort_version(cohort_id):
    """Re-fetch a cohort's live version (after a confirm has bumped it)."""
    return get_success_data(api_client.get_cohort(cohort_id, REG))["version"]


def latest_contract_version(contract_id):
    return get_success_data(api_client.get_corporate_contract(contract_id, REG))["version"]
