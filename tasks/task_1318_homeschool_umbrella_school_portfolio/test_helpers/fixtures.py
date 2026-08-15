"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the server is restarted with an empty database before each test). Setup calls
use the lenient get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ACCEPT_SCORES,
    CORE_SUBJECTS,
    GRADUATION_CREDIT_BLOCKS,
    REMEDIATION_SCORES,
)
from .factories import (
    create_academic_year_payload,
    create_attendance_entry_payload,
    create_coop_class_payload,
    create_course_credit_payload,
    create_curriculum_plan_payload,
    create_enrollment_payload,
    create_evaluation_payload,
    create_exam_session_payload,
    create_family_payload,
    create_graduation_application_payload,
    create_notice_payload,
    create_student_payload,
)
from .test_users import TEST_USERS, make_parent_headers

DIRECTOR = TEST_USERS["director_headers"]
DIRECTOR2 = TEST_USERS["director2_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
SELF_REGISTER = TEST_USERS["parent_headers"]  # only for POST /families itself


# ---------------------------------------------------------------------------
# Tier 0: clock and single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4). Returns the clock response data."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, DIRECTOR)
    )


def create_academic_year(**overrides):
    """Create an academic year in PLANNING. Returns the year resource."""
    return get_success_data(
        api_client.create_academic_year(create_academic_year_payload(**overrides), DIRECTOR)
    )


def create_open_year(**overrides):
    """Create an academic year and open it. Returns the OPEN year resource."""
    year = create_academic_year(**overrides)
    return get_success_data(api_client.open_academic_year(year["id"], DIRECTOR))


def create_family(display_name="Test Family", district_code="D-01", **overrides):
    """Self-register a family. Returns the Family resource; the family's id is
    the parent's X-User-ID for all subsequent ownership-gated calls."""
    return get_success_data(
        api_client.create_family(
            create_family_payload(display_name=display_name, district_code=district_code, **overrides),
            SELF_REGISTER,
        )
    )


def add_student(family, full_name="Test Student", date_of_birth="2016-01-01"):
    """Add a student to a family (own family only). Returns the Student."""
    return get_success_data(
        api_client.create_student(
            family["id"],
            create_student_payload(full_name=full_name, date_of_birth=date_of_birth),
            make_parent_headers(family["id"]),
        )
    )


def create_enrollment(student, family, academic_year_id, grade_level):
    """Enroll a student into a year. Returns the REGISTERED Enrollment."""
    return get_success_data(
        api_client.create_enrollment(
            student["id"],
            create_enrollment_payload(academic_year_id, grade_level),
            make_parent_headers(family["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: enrollment prerequisites (notice + plan) and activation
# ---------------------------------------------------------------------------

def create_acknowledged_notice(enrollment, family, district_code="D-01"):
    """Create -> file -> acknowledge a notice of intent. Returns the notice."""
    notice = get_success_data(
        api_client.create_notice(
            enrollment["id"], create_notice_payload(district_code=district_code),
            make_parent_headers(family["id"]),
        )
    )
    get_success_data(api_client.file_notice(notice["id"], make_parent_headers(family["id"])))
    return get_success_data(api_client.acknowledge_notice(notice["id"], REGISTRAR))


def create_approved_plan(enrollment, family, subjects=None, reviewer_headers=None):
    """Create -> submit -> APPROVE a curriculum plan. Returns the APPROVED plan."""
    plan = get_success_data(
        api_client.create_curriculum_plan(
            enrollment["id"],
            create_curriculum_plan_payload(subjects=subjects),
            make_parent_headers(family["id"]),
        )
    )
    get_success_data(
        api_client.submit_curriculum_plan(plan["id"], make_parent_headers(family["id"]))
    )
    return get_success_data(
        api_client.review_curriculum_plan(
            plan["id"], {"decision": "APPROVE"}, reviewer_headers or REVIEWER
        )
    )


def activate_enrollment(enrollment):
    """REGISTERED -> ACTIVE. Returns the ACTIVE enrollment."""
    return get_success_data(api_client.activate_enrollment(enrollment["id"], REGISTRAR))


def setup_registered_enrollment(year_id, grade_level, family_name="Test Family",
                                district_code="D-01", student_name="Test Student",
                                date_of_birth="2016-01-01"):
    """Family + student + REGISTERED enrollment (no notice/plan yet).

    Returns ctx dict: family, student, enrollment, parent_headers.
    """
    family = create_family(display_name=family_name, district_code=district_code)
    student = add_student(family, full_name=student_name, date_of_birth=date_of_birth)
    enrollment = create_enrollment(student, family, year_id, grade_level)
    return {
        "family": family,
        "student": student,
        "enrollment": enrollment,
        "parent_headers": make_parent_headers(family["id"]),
    }


def setup_active_enrollment(year_id, grade_level, family_name="Test Family",
                            district_code="D-01", student_name="Test Student",
                            date_of_birth="2016-01-01"):
    """Full activation preamble: family + student + enrollment REGISTERED +
    ACKNOWLEDGED notice + APPROVED plan + activate.

    Returns ctx dict: family, student, enrollment (ACTIVE), notice, plan,
    parent_headers.
    """
    ctx = setup_registered_enrollment(
        year_id, grade_level, family_name, district_code, student_name, date_of_birth
    )
    ctx["notice"] = create_acknowledged_notice(
        ctx["enrollment"], ctx["family"], district_code=district_code
    )
    ctx["plan"] = create_approved_plan(ctx["enrollment"], ctx["family"])
    ctx["enrollment"] = activate_enrollment(ctx["enrollment"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: attendance
# ---------------------------------------------------------------------------

def log_attendance(enrollment, family, entry_date, minutes):
    """Log one instructional day. Returns the created AttendanceEntry."""
    return get_success_data(
        api_client.create_attendance_entry(
            enrollment["id"],
            create_attendance_entry_payload(entry_date=entry_date, minutes=minutes),
            make_parent_headers(family["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: portfolios
# ---------------------------------------------------------------------------

def create_draft_portfolio(enrollment, family):
    """Create the enrollment's DRAFT portfolio."""
    return get_success_data(
        api_client.create_portfolio(enrollment["id"], make_parent_headers(family["id"]))
    )


def create_submitted_portfolio(enrollment, family):
    """Create + submit a portfolio (attempt_count 1). Returns SUBMITTED portfolio."""
    portfolio = create_draft_portfolio(enrollment, family)
    return get_success_data(
        api_client.submit_portfolio(portfolio["id"], make_parent_headers(family["id"]))
    )


def evaluate_portfolio(portfolio_id, overall_outcome="ACCEPTED", subject_scores=None,
                       reviewer_headers=None, notes=None):
    """Record a reviewer evaluation. Returns the raw response."""
    payload = create_evaluation_payload(
        overall_outcome=overall_outcome,
        subject_scores=subject_scores
        or (ACCEPT_SCORES if overall_outcome == "ACCEPTED" else REMEDIATION_SCORES),
    )
    if notes is not None:
        payload["notes"] = notes
    return api_client.create_evaluation(
        portfolio_id, payload, reviewer_headers or REVIEWER
    )


def create_accepted_portfolio(enrollment, family, reviewer_headers=None):
    """Create + submit + ACCEPT a portfolio. Returns the ACCEPTED portfolio."""
    portfolio = create_submitted_portfolio(enrollment, family)
    get_success_data(
        evaluate_portfolio(
            portfolio["id"], "ACCEPTED", reviewer_headers=reviewer_headers
        )
    )
    return get_success_data(api_client.get_portfolio(portfolio["id"], REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 2/3: exam sessions and registrations
# ---------------------------------------------------------------------------

def create_exam_session(year_id, **overrides):
    """Create a SCHEDULED exam session. Returns the session."""
    return get_success_data(
        api_client.create_exam_session(
            year_id, create_exam_session_payload(**overrides), REGISTRAR
        )
    )


def create_open_exam_session(year_id, **overrides):
    """Create + open registration. Returns the REGISTRATION_OPEN session."""
    session = create_exam_session(year_id, **overrides)
    return get_success_data(api_client.open_exam_registration(session["id"], REGISTRAR))


def register_exam(session_id, enrollment_id, family_id):
    """Register an enrollment for a session. Returns the raw response."""
    return api_client.create_exam_registration(
        session_id, {"enrollment_id": enrollment_id}, make_parent_headers(family_id)
    )


def register_exam_ok(session_id, enrollment_id, family_id):
    """Register an enrollment for a session, expecting success."""
    return get_success_data(register_exam(session_id, enrollment_id, family_id))


def setup_administered_registration(year_id, grade_level, session_overrides=None,
                                    family_name="Test Family", district_code="D-01",
                                    student_name="Test Student",
                                    date_of_birth="2015-01-01"):
    """ACTIVE enrollment + one ADMINISTERED session with the student REGISTERED.

    Returns (ctx, session, registration).
    """
    ctx = setup_active_enrollment(
        year_id, grade_level, family_name=family_name, district_code=district_code,
        student_name=student_name, date_of_birth=date_of_birth,
    )
    overrides = dict(session_overrides or {})
    overrides.setdefault("target_grades", [grade_level])
    session = create_open_exam_session(year_id, **overrides)
    registration = register_exam_ok(session["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    get_success_data(api_client.close_exam_registration(session["id"], REGISTRAR))
    session = get_success_data(api_client.administer_exam_session(session["id"], REGISTRAR))
    return ctx, session, registration


# ---------------------------------------------------------------------------
# Tier 2/3: co-op classes and enrollments
# ---------------------------------------------------------------------------

def create_coop_class(year_id, **overrides):
    """Create a DRAFT co-op class. Returns the class."""
    return get_success_data(
        api_client.create_coop_class(
            year_id, create_coop_class_payload(**overrides), REGISTRAR
        )
    )


def create_open_coop_class(year_id, **overrides):
    """Create + open a co-op class. Returns the OPEN class."""
    coop_class = create_coop_class(year_id, **overrides)
    return get_success_data(api_client.open_coop_class(coop_class["id"], REGISTRAR))


def register_coop(coop_class_id, enrollment_id, family_id):
    """Register an enrollment into a class with a fresh OCC class version.
    Returns the raw response (may be a success or an error)."""
    current = get_success_data(api_client.get_coop_class(coop_class_id, REGISTRAR))
    return api_client.create_coop_enrollment(
        coop_class_id,
        {
            "enrollment_id": enrollment_id,
            "expected_coop_class_version": current["version"],
        },
        make_parent_headers(family_id),
    )


def register_coop_ok(coop_class_id, enrollment_id, family_id):
    """Register an enrollment into a class, expecting success."""
    return get_success_data(register_coop(coop_class_id, enrollment_id, family_id))


def get_ledger(family_id):
    """Read the family's computed fee ledger."""
    return get_success_data(api_client.get_family_ledger(family_id, REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 3: course credits
# ---------------------------------------------------------------------------

def create_planned_credit(enrollment, family, subject="ELECTIVE",
                          course_title="Course", planned_hours=120, **overrides):
    """Plan a course credit (PLANNED). Returns the credit."""
    return get_success_data(
        api_client.create_course_credit(
            enrollment["id"],
            create_course_credit_payload(
                subject=subject, course_title=course_title,
                planned_hours=planned_hours, **overrides,
            ),
            make_parent_headers(family["id"]),
        )
    )


def complete_credit(credit, family, completed_hours=120, letter_grade="A"):
    """PLANNED -> COMPLETED. Returns the raw response."""
    return api_client.complete_course_credit(
        credit["id"],
        {"completed_hours": completed_hours, "letter_grade": letter_grade},
        make_parent_headers(family["id"]),
    )


def create_posted_credit(enrollment, family, subject, course_title, completed_hours,
                         letter_grade="A"):
    """Plan -> complete -> verify(APPROVE) -> post. Returns the POSTED credit."""
    credit = create_planned_credit(
        enrollment, family, subject=subject, course_title=course_title,
        planned_hours=completed_hours,
    )
    get_success_data(complete_credit(credit, family, completed_hours, letter_grade))
    get_success_data(
        api_client.verify_course_credit(credit["id"], {"decision": "APPROVE"}, REGISTRAR)
    )
    return get_success_data(api_client.post_course_credit(credit["id"], REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 5: graduation
# ---------------------------------------------------------------------------

def create_graduation_application(student, family, academic_year_id):
    """Parent applies for graduation. Returns the SUBMITTED application."""
    return get_success_data(
        api_client.create_graduation_application(
            student["id"],
            create_graduation_application_payload(academic_year_id),
            make_parent_headers(family["id"]),
        )
    )


def setup_graduation_candidate(year_id, grade_level=12,
                               credit_blocks=None,
                               family_name="Grad Family", district_code="D-90",
                               student_name="Senior", date_of_birth="2008-01-01",
                               portfolio_reviewer_headers=None):
    """ACTIVE enrollment + all credit blocks POSTED + ACCEPTED portfolio +
    SUBMITTED graduation application.

    Returns ctx dict with family, student, enrollment, portfolio, application,
    parent_headers, credits.
    """
    ctx = setup_active_enrollment(
        year_id, grade_level, family_name=family_name, district_code=district_code,
        student_name=student_name, date_of_birth=date_of_birth,
    )
    ctx["credits"] = [
        create_posted_credit(ctx["enrollment"], ctx["family"], subject, title, hours, grade)
        for subject, title, hours, grade in (
            credit_blocks if credit_blocks is not None else GRADUATION_CREDIT_BLOCKS
        )
    ]
    ctx["portfolio"] = create_accepted_portfolio(
        ctx["enrollment"], ctx["family"],
        reviewer_headers=portfolio_reviewer_headers,
    )
    ctx["application"] = create_graduation_application(
        ctx["student"], ctx["family"], year_id
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: compliance reports
# ---------------------------------------------------------------------------

def create_year_with_registered_enrollment(label, start_date, end_date,
                                           notice_filing_deadline,
                                           portfolio_due_date,
                                           state_report_due_date,
                                           mid_year_date, grade_level=4,
                                           family=None, student=None,
                                           family_name="Report Family",
                                           district_code="D-95"):
    """OPEN year + (optionally provided) family/student + one REGISTERED enrollment.
    Returns (year, family, student, enrollment)."""
    year = create_open_year(
        label=label, start_date=start_date, end_date=end_date,
        notice_filing_deadline=notice_filing_deadline,
        portfolio_due_date=portfolio_due_date,
        state_report_due_date=state_report_due_date,
        mid_year_date=mid_year_date,
    )
    if family is None:
        family = create_family(display_name=family_name, district_code=district_code)
    if student is None:
        student = add_student(family)
    enrollment = create_enrollment(student, family, year["id"], grade_level)
    return year, family, student, enrollment
