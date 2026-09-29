"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch through the endpoints the PRD declares.  All setup
calls use the lenient ``get_success_data`` validator so a broken precondition
surfaces as a setup failure rather than as a confusing assertion failure.
"""
from itertools import count

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    administration_status_payload,
    create_appeal_payload,
    create_course_payload,
    create_course_requisite_payload,
    create_determination_payload,
    create_override_payload,
    create_placement_rule_payload,
    create_registration_payload,
    create_section_payload,
    create_student_payload,
    create_test_administration_payload,
    create_test_attempt_payload,
    create_validation_study_payload,
    decide_appeal_payload,
    evidence_payload,
    grade_registration_payload,
    pair_section_payload,
    resubmit_appeal_payload,
    score_attempt_payload,
    section_status_payload,
    set_clock_payload,
    void_attempt_payload,
)
from .test_users import (
    DIRECTOR_1,
    INSTRUCTOR_1,
    PROCTOR_1,
    REGISTRAR_1,
    STAFF_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_student_headers,
    make_system_admin_headers,
)

_seq = count(1)


def _next(prefix: str) -> str:
    return f"{prefix}{next(_seq):04d}"


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(current_utc: str) -> dict:
    """Move the server's logical UTC clock to ``current_utc``."""
    return get_success_data(
        api_client.set_clock(
            set_clock_payload(current_utc), make_system_admin_headers()
        )
    )


# --------------------------------------------------------------------------- #
# Tier 1 — single-entity creation with declared defaults
# --------------------------------------------------------------------------- #
def new_student(**overrides) -> dict:
    """Register one student.  `student_number` is made unique unless overridden."""
    overrides.setdefault("student_number", _next("STU-"))
    overrides.setdefault("full_name", f"Student {overrides['student_number']}")
    payload = create_student_payload(**overrides)
    return get_success_data(
        api_client.create_student(payload, make_assessment_staff_headers())
    )


def new_course(**overrides) -> dict:
    """Create one catalogue course.  `course_code` is made unique unless
    overridden."""
    overrides.setdefault("course_code", _next("CRS-"))
    overrides.setdefault("title", f"Course {overrides['course_code']}")
    payload = create_course_payload(**overrides)
    return get_success_data(
        api_client.create_course(payload, make_system_admin_headers())
    )


def new_support_course(**overrides) -> dict:
    """Create a corequisite support course (`is_support_course` true, the office
    convention `level_rank` of 90, 1.0 unit unless overridden)."""
    overrides.setdefault("is_support_course", True)
    overrides.setdefault("level_rank", 90)
    overrides.setdefault("units", 1.0)
    return new_course(**overrides)


def new_requisite(course_id: str, requisite_course_id: str, **overrides) -> dict:
    """Declare one requisite edge between two courses."""
    payload = create_course_requisite_payload(course_id, requisite_course_id, **overrides)
    return get_success_data(
        api_client.create_course_requisite(payload, make_system_admin_headers())
    )


def new_rule(target_course_id: str, **overrides) -> dict:
    """Draft one placement rule; it starts in `status` DRAFT."""
    payload = create_placement_rule_payload(target_course_id, **overrides)
    return get_success_data(
        api_client.create_placement_rule(payload, make_assessment_director_headers())
    )


def activate_rule(rule_id: str, actor_id: str = DIRECTOR_1) -> dict:
    """Drive one rule DRAFT to ACTIVE."""
    return get_success_data(
        api_client.activate_placement_rule(
            rule_id, make_assessment_director_headers(actor_id)
        )
    )


def new_active_rule(target_course_id: str, **overrides) -> dict:
    """Draft a rule and activate it in one step."""
    rule = new_rule(target_course_id, **overrides)
    return activate_rule(rule["id"])


def retire_course(course_id: str) -> dict:
    return get_success_data(
        api_client.retire_course(course_id, make_system_admin_headers())
    )


# --------------------------------------------------------------------------- #
# Tier 2 — catalogue + policy composites
# --------------------------------------------------------------------------- #
def setup_course_with_active_test_score_rule(
    course_overrides=None, **rule_overrides
) -> tuple:
    """One ACTIVE course plus one ACTIVE `TEST_SCORE` placement rule targeting it.

    Returns ``(course, rule)``.  This is the most reused preamble in the suite:
    the selector refuses to mint anything when the candidate set is empty.
    """
    course = new_course(**(course_overrides or {}))
    rule_overrides.setdefault("measure_type", "TEST_SCORE")
    rule_overrides.setdefault("min_score", 0)
    rule_overrides.setdefault("subject_area", course["subject_area"])
    rule = new_active_rule(course["id"], **rule_overrides)
    return course, rule


def setup_course_with_active_transcript_rule(
    course_overrides=None, **rule_overrides
) -> tuple:
    """One ACTIVE course plus one ACTIVE `TRANSCRIPT_GPA` rule targeting it."""
    course = new_course(**(course_overrides or {}))
    rule_overrides.setdefault("measure_type", "TRANSCRIPT_GPA")
    rule_overrides.setdefault("min_hs_gpa", 0.00)
    rule_overrides.setdefault("subject_area", course["subject_area"])
    rule = new_active_rule(course["id"], **rule_overrides)
    return course, rule


def setup_coreq_course_pair(
    primary_overrides=None, support_overrides=None
) -> tuple:
    """A transfer-level primary course, a support course, and the ACTIVE
    `COREQUISITE` requisite edge joining the primary to the support.

    Returns ``(primary_course, support_course, requisite)``.
    """
    primary = new_course(**(primary_overrides or {}))
    support_defaults = {"subject_area": primary["subject_area"]}
    support_defaults.update(support_overrides or {})
    support = new_support_course(**support_defaults)
    requisite = new_requisite(
        primary["id"], support["id"], requisite_type="COREQUISITE"
    )
    return primary, support, requisite


def setup_coreq_required_rule(
    primary_overrides=None, support_overrides=None, **rule_overrides
) -> tuple:
    """Primary + support courses joined by a COREQUISITE edge, plus an ACTIVE
    rule targeting the primary with `coreq_required` true.

    Returns ``(primary_course, support_course, requisite, rule)``.
    """
    primary, support, requisite = setup_coreq_course_pair(
        primary_overrides, support_overrides
    )
    rule_overrides.setdefault("measure_type", "TEST_SCORE")
    rule_overrides.setdefault("min_score", 0)
    rule_overrides.setdefault("subject_area", primary["subject_area"])
    rule_overrides["coreq_course_id"] = support["id"]
    rule_overrides["coreq_required"] = True
    rule = new_active_rule(primary["id"], **rule_overrides)
    return primary, support, requisite, rule


def setup_blocking_prerequisite(
    course_overrides=None, prereq_overrides=None, **edge_overrides
) -> tuple:
    """A course carrying one ACTIVE BLOCKING PREREQUISITE edge on a second course.

    Returns ``(course, prerequisite_course, requisite)``.
    """
    course = new_course(**(course_overrides or {}))
    prereq_defaults = {"subject_area": course["subject_area"], "level_rank": 80}
    prereq_defaults.update(prereq_overrides or {})
    prereq_course = new_course(**prereq_defaults)
    edge_overrides.setdefault("requisite_type", "PREREQUISITE")
    edge_overrides.setdefault("enforcement", "BLOCKING")
    requisite = new_requisite(course["id"], prereq_course["id"], **edge_overrides)
    return course, prereq_course, requisite


# --------------------------------------------------------------------------- #
# Tier 3 — test sessions and attempts
# --------------------------------------------------------------------------- #
def new_administration(proctor_user_id: str = PROCTOR_1, **overrides) -> dict:
    """Schedule one proctored session; it opens in `status` SCHEDULED."""
    overrides.setdefault("room_code", TEST_DEFAULTS["ROOM_CODE"])
    payload = create_test_administration_payload(proctor_user_id, **overrides)
    return get_success_data(
        api_client.create_test_administration(payload, make_assessment_staff_headers())
    )


def open_administration(administration_id: str, proctor_user_id: str = PROCTOR_1) -> dict:
    """Drive one session SCHEDULED to OPEN as its assigned proctor."""
    return get_success_data(
        api_client.set_test_administration_status(
            administration_id,
            administration_status_payload("OPEN"),
            make_proctor_headers(proctor_user_id),
        )
    )


def setup_open_administration(proctor_user_id: str = PROCTOR_1, **overrides) -> dict:
    """Schedule a session and open it.  Returns the OPEN session."""
    administration = new_administration(proctor_user_id, **overrides)
    return open_administration(administration["id"], proctor_user_id)


def book_attempt(student_id: str, administration_id: str) -> dict:
    """Book one seat for a student; the attempt begins in `state` BOOKED."""
    return get_success_data(
        api_client.create_test_attempt(
            create_test_attempt_payload(student_id, administration_id),
            make_assessment_staff_headers(),
        )
    )


def score_attempt(
    attempt_id: str, raw_score: int, proctor_user_id: str = PROCTOR_1, **overrides
) -> dict:
    """Check a booked attempt in and score it as the assigned proctor."""
    headers = make_proctor_headers(proctor_user_id)
    get_success_data(api_client.check_in_test_attempt(attempt_id, headers))
    return get_success_data(
        api_client.score_test_attempt(
            attempt_id, score_attempt_payload(raw_score, **overrides), headers
        )
    )


def setup_scored_attempt(
    student_id: str,
    raw_score: int,
    proctor_user_id: str = PROCTOR_1,
    administration_overrides=None,
    **score_overrides,
) -> tuple:
    """Open a session, book the student into it and score the attempt.

    Returns ``(administration, attempt)`` with the attempt in `state` SCORED.
    """
    administration = setup_open_administration(
        proctor_user_id, **(administration_overrides or {})
    )
    attempt = book_attempt(student_id, administration["id"])
    scored = score_attempt(
        attempt["id"], raw_score, proctor_user_id, **score_overrides
    )
    return administration, scored


def setup_student_with_scored_attempt(
    raw_score: int = 96,
    student_overrides=None,
    administration_overrides=None,
    **score_overrides,
) -> tuple:
    """A fresh student holding one SCORED attempt.

    Returns ``(student, administration, attempt)``.
    """
    student = new_student(**(student_overrides or {}))
    administration, attempt = setup_scored_attempt(
        student["id"],
        raw_score,
        administration_overrides=administration_overrides,
        **score_overrides,
    )
    return student, administration, attempt


def void_attempt(attempt_id: str, void_reason: str = "ADMIN_CORRECTION") -> dict:
    return get_success_data(
        api_client.void_test_attempt(
            attempt_id, void_attempt_payload(void_reason), make_assessment_staff_headers()
        )
    )


# --------------------------------------------------------------------------- #
# Tier 3 — determinations
# --------------------------------------------------------------------------- #
def current_student_version(student_id: str) -> int:
    """Read the student's current `version` — the echo the selector demands."""
    student = get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )
    return student["version"]


def mint_determination(
    student_id: str, subject_area: str = "MATH", actor_id: str = STAFF_1, **overrides
) -> dict:
    """Run the multiple-measures selector, reading the student's `version` first."""
    payload = create_determination_payload(
        student_id,
        current_student_version(student_id),
        subject_area=subject_area,
        **overrides,
    )
    return get_success_data(
        api_client.create_placement_determination(
            payload, make_assessment_staff_headers(actor_id)
        )
    )


def set_evidence(determination_id: str, target_evidence_state: str, **overrides) -> dict:
    return get_success_data(
        api_client.set_determination_evidence(
            determination_id,
            evidence_payload(target_evidence_state, **overrides),
            make_assessment_staff_headers(),
        )
    )


def finalize_determination(determination_id: str) -> dict:
    return get_success_data(
        api_client.finalize_placement_determination(
            determination_id, make_assessment_staff_headers()
        )
    )


def setup_test_placed_student(
    raw_score: int = 96,
    student_overrides=None,
    course_overrides=None,
    **rule_overrides,
) -> dict:
    """The canonical placement bundle: an ACTIVE test-score rule, a student with
    one SCORED attempt, and the determination the selector minted for them.

    Returns a dict with keys ``course``, ``rule``, ``student``,
    ``administration``, ``attempt`` and ``determination``.
    """
    course, rule = setup_course_with_active_test_score_rule(
        course_overrides, **rule_overrides
    )
    student = new_student(**(student_overrides or {}))
    administration, attempt = setup_scored_attempt(student["id"], raw_score)
    determination = mint_determination(
        student["id"], subject_area=course["subject_area"]
    )
    return {
        "course": course,
        "rule": rule,
        "student": student,
        "administration": administration,
        "attempt": attempt,
        "determination": determination,
    }


def setup_verified_placed_student(raw_score: int = 96, **kwargs) -> dict:
    """A placement bundle whose determination has been driven to
    `evidence_state` VERIFIED (the precondition for finalizing and for
    confirming a registration)."""
    bundle = setup_test_placed_student(raw_score, **kwargs)
    if bundle["determination"]["evidence_state"] != "VERIFIED":
        bundle["determination"] = set_evidence(
            bundle["determination"]["id"], "VERIFIED"
        )
    return bundle


# --------------------------------------------------------------------------- #
# Tier 3 — sections and pairing
# --------------------------------------------------------------------------- #
def new_section(course_id: str, **overrides) -> dict:
    """Plan one section; it opens with `status` PLANNED and `pairing_state`
    UNPAIRED."""
    payload = create_section_payload(course_id, **overrides)
    return get_success_data(
        api_client.create_section(payload, make_registrar_headers())
    )


def set_section_status(section_id: str, target_status: str, actor_id=REGISTRAR_1) -> dict:
    return get_success_data(
        api_client.set_section_status(
            section_id,
            section_status_payload(target_status),
            make_registrar_headers(actor_id),
        )
    )


def setup_open_section(course_id: str, **overrides) -> dict:
    """Plan a section and open it.  Returns the OPEN section."""
    section = new_section(course_id, **overrides)
    return set_section_status(section["id"], "OPEN")


def pair_sections(primary_section_id: str, support_section_id: str) -> dict:
    return get_success_data(
        api_client.pair_section(
            primary_section_id,
            pair_section_payload(support_section_id),
            make_registrar_headers(),
        )
    )


def setup_paired_sections(
    primary_course_id: str,
    support_course_id: str,
    primary_overrides=None,
    support_overrides=None,
    open_both: bool = True,
) -> tuple:
    """Plan a primary and a support section in the same term, pair them while
    both are PLANNED, then optionally open both.

    Returns ``(primary_section, support_section)`` read back after pairing.
    """
    primary_defaults = {"term_code": TEST_DEFAULTS["TERM_CODE"]}
    primary_defaults.update(primary_overrides or {})
    support_defaults = {
        "term_code": primary_defaults["term_code"],
        "room_code": "R02",
        "meets_start_at": "2026-09-01T10:00:00Z",
        "meets_end_at": "2026-09-01T11:00:00Z",
    }
    support_defaults.update(support_overrides or {})
    primary = new_section(primary_course_id, **primary_defaults)
    support = new_section(support_course_id, **support_defaults)
    pair_sections(primary["id"], support["id"])
    if open_both:
        set_section_status(support["id"], "OPEN")
        set_section_status(primary["id"], "OPEN")
    return read_section(primary["id"]), read_section(support["id"])


def read_section(section_id: str) -> dict:
    return get_success_data(
        api_client.get_section(section_id, make_registrar_headers())
    )


# --------------------------------------------------------------------------- #
# Tier 4 — registrations, seats and overrides
# --------------------------------------------------------------------------- #
def hold_seat(student_id: str, section_id: str, headers=None, **overrides) -> dict:
    """Hold one seat, reading the section's current `version` immediately first."""
    section = read_section(section_id)
    payload = create_registration_payload(
        student_id, section_id, section["version"], **overrides
    )
    return get_success_data(
        api_client.create_registration(
            payload, headers or make_registrar_headers()
        )
    )


def confirm_seat(registration_id: str, actor_id: str = REGISTRAR_1) -> dict:
    return get_success_data(
        api_client.confirm_registration(
            registration_id, make_registrar_headers(actor_id)
        )
    )


def setup_enrolled_registration(
    student_id: str, section_id: str, **overrides
) -> dict:
    """Hold a seat and confirm it.  Returns the confirmed registration."""
    registration = hold_seat(student_id, section_id, **overrides)
    return confirm_seat(registration["id"])


def drop_registration(registration_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.drop_registration(
            registration_id, headers or make_registrar_headers()
        )
    )


def grade_registration(registration_id: str, final_grade: str) -> dict:
    return get_success_data(
        api_client.grade_registration(
            registration_id,
            grade_registration_payload(final_grade),
            make_instructor_headers(),
        )
    )


def new_override(
    student_id: str, course_id: str, requisite_id: str, actor_id=INSTRUCTOR_1, **overrides
) -> dict:
    """Issue one time-boxed prerequisite waiver; it opens in `state` ISSUED."""
    payload = create_override_payload(student_id, course_id, requisite_id, **overrides)
    return get_success_data(
        api_client.create_prerequisite_override(
            payload, make_instructor_headers(actor_id)
        )
    )


def revoke_override(override_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.revoke_prerequisite_override(
            override_id, headers or make_registrar_headers()
        )
    )


def setup_completed_course_registration(
    student_id: str, course_id: str, final_grade: str = "B", **section_overrides
) -> dict:
    """Drive one student all the way to a graded COMPLETED registration on a
    section of ``course_id`` — the shape prerequisite satisfaction reads and the
    validation cohorts draw from.

    The section is opened, the seat held and confirmed, the section closed and
    the grade posted after the meeting block has ended.
    """
    section_overrides.setdefault("meets_start_at", "2026-01-05T09:00:00Z")
    section_overrides.setdefault("meets_end_at", "2026-01-05T10:00:00Z")
    section = setup_open_section(course_id, **section_overrides)
    registration = setup_enrolled_registration(student_id, section["id"])
    set_section_status(section["id"], "CLOSED")
    return grade_registration(registration["id"], final_grade)


def setup_graded_cohort_row(
    course_id: str,
    student_overrides=None,
    final_grade: str = "B",
    section_overrides=None,
) -> tuple:
    """A student with a graded COMPLETED registration on a section of
    ``course_id``.  Returns ``(student, registration)``."""
    student = new_student(**(student_overrides or {}))
    registration = setup_completed_course_registration(
        student["id"], course_id, final_grade, **(section_overrides or {})
    )
    return student, registration


# --------------------------------------------------------------------------- #
# Tier 4 — appeals
# --------------------------------------------------------------------------- #
def current_determination_version(determination_id: str) -> int:
    determination = get_success_data(
        api_client.get_placement_determination(
            determination_id, make_assessment_staff_headers()
        )
    )
    return determination["version"]


def file_appeal(
    determination_id: str, requested_course_id: str, headers=None, **overrides
) -> dict:
    """File one appeal, reading the determination's current `version` first."""
    payload = create_appeal_payload(
        determination_id,
        requested_course_id,
        current_determination_version(determination_id),
        **overrides,
    )
    return get_success_data(
        api_client.create_placement_appeal(
            payload, headers or make_registrar_headers()
        )
    )


def start_appeal_review(appeal_id: str, actor_id: str = REGISTRAR_1) -> dict:
    return get_success_data(
        api_client.start_appeal_review(appeal_id, make_registrar_headers(actor_id))
    )


def endorse_appeal(appeal_id: str, actor_id: str = INSTRUCTOR_1, **overrides) -> dict:
    payload = overrides or None
    return get_success_data(
        api_client.endorse_placement_appeal(
            appeal_id, make_instructor_headers(actor_id), payload
        )
    )


def resubmit_appeal(appeal_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_placement_appeal(
            appeal_id,
            resubmit_appeal_payload(**overrides),
            headers or make_registrar_headers(),
        )
    )


def decide_appeal(
    appeal_id: str, decision: str, actor_id: str = REGISTRAR_1, **overrides
) -> dict:
    return get_success_data(
        api_client.decide_placement_appeal(
            appeal_id,
            decide_appeal_payload(decision, **overrides),
            make_registrar_headers(actor_id),
        )
    )


def setup_appeal_under_review(
    bundle=None, requested_course_id=None, reviewer_id: str = REGISTRAR_1, **appeal_overrides
) -> dict:
    """A placement bundle plus an appeal driven to UNDER_REVIEW.

    ``bundle`` may be the output of :func:`setup_test_placed_student`; when it is
    omitted a fresh bundle is built.  The reviewer differs from the
    determination's author so the segregation-of-duties check passes.

    Returns the bundle extended with ``requested_course`` and ``appeal``.
    """
    bundle = bundle or setup_test_placed_student()
    if requested_course_id is None:
        requested_course = new_course(
            subject_area=bundle["course"]["subject_area"], level_rank=100
        )
        requested_course_id = requested_course["id"]
    else:
        requested_course = None
    appeal = file_appeal(
        bundle["determination"]["id"], requested_course_id, **appeal_overrides
    )
    appeal = start_appeal_review(appeal["id"], reviewer_id)
    bundle = dict(bundle)
    bundle["requested_course"] = requested_course
    bundle["requested_course_id"] = requested_course_id
    bundle["appeal"] = appeal
    return bundle


def setup_appeal_endorsed(
    bundle=None,
    requested_course_id=None,
    reviewer_id: str = REGISTRAR_1,
    endorser_id: str = INSTRUCTOR_1,
    **appeal_overrides,
) -> dict:
    """An appeal driven all the way to INSTRUCTOR_ENDORSED — the only state a
    GRANT may be decided from."""
    bundle = setup_appeal_under_review(
        bundle, requested_course_id, reviewer_id, **appeal_overrides
    )
    bundle["appeal"] = endorse_appeal(bundle["appeal"]["id"], endorser_id)
    return bundle


# --------------------------------------------------------------------------- #
# Tier 5 — validation studies
# --------------------------------------------------------------------------- #
def propose_study(
    candidate_rule_id: str,
    window_start_at: str,
    window_end_at: str,
    actor_id: str = STAFF_1,
    **overrides,
) -> dict:
    payload = create_validation_study_payload(
        candidate_rule_id, window_start_at, window_end_at, **overrides
    )
    return get_success_data(
        api_client.create_validation_study(
            payload, make_assessment_staff_headers(actor_id)
        )
    )


def run_study(study_id: str, actor_id: str = STAFF_1) -> dict:
    return get_success_data(
        api_client.run_validation_study(
            study_id, make_assessment_staff_headers(actor_id)
        )
    )


def setup_completed_study(
    candidate_rule_id: str,
    window_start_at: str,
    window_end_at: str,
    clock_after_window: str = None,
    proposer_id: str = STAFF_1,
    **overrides,
) -> dict:
    """Propose a study over a closed observation window and run it to COMPLETED.

    When ``clock_after_window`` is supplied the logical clock is moved there
    first, since a run requires `window_end_at` to be at or before the clock.
    """
    if clock_after_window:
        set_clock(clock_after_window)
    study = propose_study(
        candidate_rule_id, window_start_at, window_end_at, proposer_id, **overrides
    )
    return run_study(study["id"], proposer_id)
