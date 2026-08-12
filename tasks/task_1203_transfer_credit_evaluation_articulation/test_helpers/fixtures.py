"""Composite setup helpers.

Each helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so every test starts
against an empty database). Setup calls use get_success_data() so failures
surface as clear setup errors. Ownership-gated calls thread entity ids
through make_student_headers().
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .factories import (
    create_partner_institution_payload,
    create_internal_course_payload,
    create_agreement_payload,
    create_equivalency_payload,
    create_student_payload,
    create_transcript_payload,
    create_transcript_course_payload,
    create_evaluation_payload,
    create_petition_payload,
    create_appeal_payload,
    create_pla_payload,
    create_transfer_guide_payload,
    create_amendment_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_staff_headers,
    make_evaluator_headers,
    make_faculty_headers,
    make_student_headers,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]
FACULTY = TEST_USERS["faculty_headers"]

# Distinct opaque identities used where the PRD demands two different actors
# (posting evaluator != finalizing evaluator; appeal reviewer != petition
# adjudicator).
EVAL_A = make_evaluator_headers("eval-a")
EVAL_B = make_evaluator_headers("eval-b")
FAC_1 = make_faculty_headers("fac-1")
FAC_2 = make_faculty_headers("fac-2")


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy builders
# ---------------------------------------------------------------------------

def create_partner(name="State University", code="SU", credit_system="SEMESTER", **overrides):
    """Create a partner institution. Returns the partner dict."""
    payload = create_partner_institution_payload(
        name=name, institution_code=code, credit_system=credit_system, **overrides
    )
    return get_success_data(api_client.create_partner_institution(payload, ADMIN))


def create_course(code="MATH-150", title="Calculus I", credit_hours=4.0,
                  level="LOWER", department="MATH", gened_tags=None, **overrides):
    """Create an internal catalog course. Returns the course dict."""
    payload = create_internal_course_payload(
        course_code=code, title=title, credit_hours=credit_hours, level=level,
        department=department, gened_tags=gened_tags if gened_tags is not None else [],
        **overrides,
    )
    return get_success_data(api_client.create_internal_course(payload, ADMIN))


def create_agreement(partner_id, program_scope="ALL",
                     effective_start="2024-08-01", effective_end="2027-07-31", **overrides):
    """Create an agreement in DRAFT. Returns the agreement dict."""
    payload = create_agreement_payload(
        partner_id, program_scope=program_scope,
        effective_start=effective_start, effective_end=effective_end, **overrides,
    )
    return get_success_data(api_client.create_articulation_agreement(payload, ADMIN))


def activate_agreement(agreement_id):
    return get_success_data(api_client.activate_agreement(agreement_id, ADMIN))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_articulation_agreement(agreement_id, ADMIN))


def add_equivalency(agreement_id, internal_course_id, external_course_code,
                    external_title=None, external_credit_hours=4.0,
                    effective_from="2024-08-01", effective_until="2027-07-31",
                    equivalency_type=None, activate_first=False):
    """Add an equivalency under an agreement, honoring the OCC version guard
    by reading the agreement's current version first. Returns the equivalency."""
    if activate_first:
        activate_agreement(agreement_id)
    current = get_agreement(agreement_id)
    overrides = {}
    if equivalency_type is not None:
        overrides["equivalency_type"] = equivalency_type
    payload = create_equivalency_payload(
        internal_course_id,
        expected_agreement_version=current["version"],
        external_course_code=external_course_code,
        external_title=external_title or external_course_code,
        external_credit_hours=external_credit_hours,
        effective_from=effective_from,
        effective_until=effective_until,
        **overrides,
    )
    return get_success_data(api_client.create_course_equivalency(agreement_id, payload, ADMIN))


def setup_active_agreement_with_equivalency(
    partner_credit_system="SEMESTER",
    course_kwargs=None,
    equivalency_kwargs=None,
    agreement_kwargs=None,
):
    """Partner + course + ACTIVE agreement + one equivalency.

    Returns (partner, course, agreement, equivalency).
    """
    partner = create_partner(credit_system=partner_credit_system)
    course = create_course(**(course_kwargs or {}))
    agreement = create_agreement(partner["id"], **(agreement_kwargs or {}))
    equivalency = add_equivalency(
        agreement["id"], course["id"], activate_first=True, **(equivalency_kwargs or {})
    )
    agreement = get_agreement(agreement["id"])
    return partner, course, agreement, equivalency


def create_student(major="MATH", catalog_year=2026, **overrides):
    """Register a transfer student. Returns the student dict."""
    payload = create_student_payload(declared_major=major, catalog_year=catalog_year, **overrides)
    return get_success_data(api_client.create_student(payload, ADMIN))


def create_transcript(student_id, partner_id, courses=None, term_completed="2025-06-15", **overrides):
    """Intake a transcript. Returns the transcript dict (RECEIVED)."""
    if courses is None:
        courses = [create_transcript_course_payload()]
    payload = create_transcript_payload(
        student_id, partner_id, term_completed=term_completed, courses=courses, **overrides
    )
    return get_success_data(api_client.create_transcript(payload, STAFF))


def verify_transcript(transcript_id):
    return get_success_data(api_client.verify_transcript(transcript_id, STAFF))


def create_verified_transcript(student_id, partner_id, courses=None, term_completed="2025-06-15"):
    """Transcript intake + verify. Returns the VERIFIED transcript."""
    transcript = create_transcript(student_id, partner_id, courses=courses, term_completed=term_completed)
    return get_success_data(api_client.verify_transcript(transcript["id"], STAFF))


# ---------------------------------------------------------------------------
# Tier 3: evaluation lifecycle
# ---------------------------------------------------------------------------

def create_evaluation(student_id, transcript_id):
    return get_success_data(
        api_client.create_evaluation(create_evaluation_payload(student_id, transcript_id), EVALUATOR)
    )


def get_evaluation_lines(evaluation_id):
    return get_success_data(api_client.list_evaluation_line_items(evaluation_id, EVALUATOR))


def setup_evaluation_in_review(
    partner_credit_system="SEMESTER",
    course_kwargs=None,
    equivalency_kwargs=None,
    transcript_courses=None,
    term_completed="2025-06-15",
    student_major="MATH",
):
    """Full chain through to an IN_REVIEW evaluation.

    Returns dict with partner, course, agreement, equivalency, student,
    transcript, evaluation, lines.
    """
    partner, course, agreement, equivalency = setup_active_agreement_with_equivalency(
        partner_credit_system=partner_credit_system,
        course_kwargs=course_kwargs,
        equivalency_kwargs=equivalency_kwargs,
    )
    student = create_student(major=student_major)
    transcript = create_verified_transcript(
        student["id"], partner["id"], courses=transcript_courses, term_completed=term_completed
    )
    evaluation = create_evaluation(student["id"], transcript["id"])
    lines = get_evaluation_lines(evaluation["id"])
    get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))
    return {
        "partner": partner,
        "course": course,
        "agreement": agreement,
        "equivalency": equivalency,
        "student": student,
        "transcript": transcript,
        "evaluation": evaluation,
        "lines": lines,
    }


def adopt_all_lines(evaluation_id, lines, headers=None):
    """Adopt every line (auto-match confirmation, empty body)."""
    headers = headers or EVALUATOR
    for line in lines:
        get_success_data(api_client.adopt_line_item(line["id"], {}, headers))


def finalize_evaluation(evaluation_id, headers=None):
    return get_success_data(api_client.finalize_evaluation(evaluation_id, headers or EVAL_A))


def post_evaluation(evaluation_id, headers=None):
    return get_success_data(api_client.post_evaluation(evaluation_id, headers or EVAL_B))


def setup_posted_evaluation(
    partner_credit_system="SEMESTER",
    course_kwargs=None,
    equivalency_kwargs=None,
    transcript_courses=None,
    term_completed="2025-06-15",
    student_major="MATH",
):
    """Full chain through to a POSTED evaluation: start-review, adopt all
    lines, finalize as eval-a, post as eval-b (maker-checker segregation).

    Returns the same context dict as setup_evaluation_in_review, with the
    evaluation refreshed to its POSTED state.
    """
    ctx = setup_evaluation_in_review(
        partner_credit_system=partner_credit_system,
        course_kwargs=course_kwargs,
        equivalency_kwargs=equivalency_kwargs,
        transcript_courses=transcript_courses,
        term_completed=term_completed,
        student_major=student_major,
    )
    adopt_all_lines(ctx["evaluation"]["id"], ctx["lines"])
    finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)
    post_evaluation(ctx["evaluation"]["id"], EVAL_B)
    ctx["evaluation"] = get_success_data(api_client.get_evaluation(ctx["evaluation"]["id"], EVALUATOR))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: petition / appeal lifecycle
# ---------------------------------------------------------------------------

def setup_petition_required_line(course_kwargs=None, transcript_courses=None,
                                 student_major="MATH", term_completed="2025-06-15"):
    """Partner + course + student + transcript with a course having NO
    equivalency, producing an IN_REVIEW evaluation whose line is
    PETITION_REQUIRED.

    Returns dict with partner, course, student, transcript, evaluation, line.
    """
    partner = create_partner()
    course = create_course(**(course_kwargs or {"code": "ART-200", "title": "Sculpture I", "department": "ART"}))
    student = create_student(major=student_major)
    if transcript_courses is None:
        transcript_courses = [
            create_transcript_course_payload(
                external_course_code="ART-210", title="Sculpture", credit_hours=4.0, grade="A"
            )
        ]
    transcript = create_verified_transcript(
        student["id"], partner["id"], courses=transcript_courses, term_completed=term_completed
    )
    evaluation = create_evaluation(student["id"], transcript["id"])
    lines = get_evaluation_lines(evaluation["id"])
    get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))
    return {
        "partner": partner,
        "course": course,
        "student": student,
        "transcript": transcript,
        "evaluation": evaluation,
        "lines": lines,
        "line": lines[0],
    }


def file_petition(line_item_id, proposed_internal_course_id, student_id, syllabus_ref="s3://syllabi/p.pdf"):
    """Student files a petition on their own line. Returns the petition."""
    payload = create_petition_payload(
        line_item_id, proposed_internal_course_id, syllabus_ref=syllabus_ref
    )
    return get_success_data(api_client.create_petition(payload, make_student_headers(student_id)))


def adjudicate_petition(petition_id, decision, note="Faculty rationale recorded here",
                        awarded_internal_course_id=None, headers=None):
    payload = {"decision": decision, "adjudication_note": note}
    if awarded_internal_course_id is not None:
        payload["awarded_internal_course_id"] = awarded_internal_course_id
    return get_success_data(api_client.adjudicate_petition(petition_id, payload, headers or FAC_1))


def setup_denied_petition(**kwargs):
    """PETITION_REQUIRED line + petition reviewed and DENIED by fac-1.

    Returns the setup_petition_required_line context plus "petition".
    """
    ctx = setup_petition_required_line(**kwargs)
    petition = file_petition(ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"])
    get_success_data(api_client.start_petition_review(petition["id"], FAC_1))
    adjudicate_petition(petition["id"], "DENIED", headers=FAC_1)
    ctx["petition"] = get_success_data(api_client.get_petition(petition["id"], FACULTY))
    return ctx


def file_appeal(petition_id, student_id, grounds="Appeal grounds with sufficient detail"):
    payload = create_appeal_payload(petition_id, grounds=grounds)
    return get_success_data(api_client.create_appeal(payload, make_student_headers(student_id)))


# ---------------------------------------------------------------------------
# Tier 3: PLA lifecycle
# ---------------------------------------------------------------------------

def create_pla(student_id, claimed_credits=4.0, source_type="MILITARY_JST", **overrides):
    """Student submits a prior-learning assessment on their own record."""
    payload = create_pla_payload(
        student_id, claimed_credits=claimed_credits, source_type=source_type, **overrides
    )
    return get_success_data(api_client.create_pla(payload, make_student_headers(student_id)))


def verify_pla(pla_id, verified_credits):
    return get_success_data(
        api_client.verify_pla(pla_id, {"verified_credits": verified_credits}, EVALUATOR)
    )


def credit_pla(pla_id):
    return get_success_data(api_client.credit_pla(pla_id, EVALUATOR))


def setup_student_with_credited_pla(credits=24.0, major="HIST"):
    """Student with one PLA already CREDITED at `credits`. Returns (student, pla)."""
    student = create_student(major=major)
    pla = create_pla(student["id"], claimed_credits=credits)
    verify_pla(pla["id"], credits)
    pla = credit_pla(pla["id"])
    return student, pla


# ---------------------------------------------------------------------------
# Tier 2: transfer guides
# ---------------------------------------------------------------------------

def create_guide(partner_id, catalog_year=2026):
    return get_success_data(
        api_client.create_transfer_guide(create_transfer_guide_payload(partner_id, catalog_year=catalog_year), ADMIN)
    )


def setup_published_guide():
    """Partner + ACTIVE agreement + published guide pinning it.
    Returns (partner, agreement, guide)."""
    partner = create_partner()
    agreement = create_agreement(partner["id"])
    activate_agreement(agreement["id"])
    guide = create_guide(partner["id"])
    guide = get_success_data(api_client.publish_transfer_guide(guide["id"], ADMIN))
    return partner, agreement, guide
