"""Composite setup helpers for the degree-audit test suite.

Most testable states (a CURRENT FINAL audit, an UNDER_REVIEW application, a
conferred degree) take 5–15 API calls to reach; these helpers encapsulate those
chains so tests focus on assertions. All setup calls use get_success_data() so
failures surface as clear "Setup failed" errors.

Ownership note: application creation and submission are Student-only and
ownership-gated, so those calls always use make_student_headers(student["id"]).
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload,
    create_audit_payload,
    create_course_payload,
    create_enrollment_payload,
    create_honors_policy_payload,
    create_program_payload,
    create_requirement_group_payload,
    create_student_payload,
    create_student_program_payload,
    create_waiver_payload,
)

REGISTRAR = None  # resolved lazily below to avoid circular import surprises


def _registrar():
    from .test_users import TEST_USERS
    return TEST_USERS["registrar_headers"]


def _sysadmin():
    from .test_users import TEST_USERS
    return TEST_USERS["sysadmin_headers"]


def _student_hdr(student_id: str):
    from .test_users import make_student_headers
    return make_student_headers(student_id)


def _advisor_hdr(user_id: str):
    from .test_users import make_advisor_headers
    return make_advisor_headers(user_id)


# ─── Clock ─────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the server-held logical clock (SystemAdmin-only, PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _sysadmin()))


# ─── Tier 1: single-resource creation ──────────────────

def make_program(**overrides) -> dict:
    """Create a program catalog-year version (RegistrarStaff). Returns Program."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), _registrar()))


def make_requirement_group(program_id: str, **overrides) -> dict:
    """Create a requirement group under a program. Returns RequirementGroup."""
    return get_success_data(api_client.create_requirement_group(
        program_id, create_requirement_group_payload(**overrides), _registrar()))


def make_honors_policy(program_id: str, **overrides) -> dict:
    """Create an honors policy under a program. Returns HonorsPolicy."""
    return get_success_data(api_client.create_honors_policy(
        program_id, create_honors_policy_payload(**overrides), _registrar()))


def make_course(**overrides) -> dict:
    """Create a course. Returns Course."""
    return get_success_data(api_client.create_course(create_course_payload(**overrides), _registrar()))


def make_student(**overrides) -> dict:
    """Create a student. Returns Student."""
    return get_success_data(api_client.create_student(create_student_payload(**overrides), _registrar()))


def enroll(student_id: str, course_id: str, term: str, grade=None, is_transfer=None) -> dict:
    """Create an enrollment. With grade -> starts COMPLETED; without -> IN_PROGRESS."""
    payload = create_enrollment_payload(course_id, term=term)
    if grade is not None:
        payload["grade"] = grade
    if is_transfer is not None:
        payload["is_transfer"] = is_transfer
    return get_success_data(api_client.create_enrollment(student_id, payload, _registrar()))


def declare(student_id: str, program_id: str, catalog_year: int = 2024, as_student: bool = False) -> dict:
    """Declare a major. Returns the ACTIVE StudentProgram (version 1)."""
    headers = _student_hdr(student_id) if as_student else _registrar()
    return get_success_data(api_client.declare_program(
        student_id, create_student_program_payload(program_id, catalog_year=catalog_year), headers))


# ─── Tier 2: audits (OCC-protected) ────────────────────

def run_audit(student_program_id: str, audit_kind: str, target_program_id=None,
              expected_version=None) -> dict:
    """Run a degree audit. Reads the declaration's current version first unless
    expected_version is given explicitly (stale-version tests pass it)."""
    if expected_version is None:
        expected_version = get_success_data(
            api_client.get_student_program(student_program_id, _registrar()))["version"]
    payload = create_audit_payload(audit_kind, expected_version)
    if target_program_id is not None:
        payload["target_program_id"] = target_program_id
    return get_success_data(api_client.create_audit(student_program_id, payload, _registrar()))


def list_audits(student_program_id: str, **params):
    """List audits of a declaration. Returns (data_list, meta_dict)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_audits(student_program_id, _registrar(), params=params or None))


# ─── Tier 3: waivers / exceptions ──────────────────────

def file_waiver(student_program_id: str, requirement_group_id: str, kind: str,
                requester_role: str = "student", requester_student_id=None,
                requester_advisor_id: str = "adv-1", **overrides) -> dict:
    """File a SUBSTITUTION or WAIVER exception. Returns the SUBMITTED waiver."""
    if requester_role == "student":
        headers = _student_hdr(requester_student_id)
    else:
        headers = _advisor_hdr(requester_advisor_id)
    return get_success_data(api_client.create_waiver(
        student_program_id,
        create_waiver_payload(requirement_group_id, kind, **overrides),
        headers))


def advisor_approve(waiver_id: str, advisor_id: str = "adv-2") -> dict:
    return get_success_data(api_client.advisor_decision(
        waiver_id, {"decision": "APPROVE"}, _advisor_hdr(advisor_id)))


def advisor_deny(waiver_id: str, advisor_id: str = "adv-2", reason: str = "not justified") -> dict:
    return get_success_data(api_client.advisor_decision(
        waiver_id, {"decision": "DENY", "decision_reason": reason}, _advisor_hdr(advisor_id)))


def registrar_approve(waiver_id: str) -> dict:
    return get_success_data(api_client.registrar_decision(
        waiver_id, {"decision": "APPROVE"}, _registrar()))


def registrar_deny(waiver_id: str, reason: str = "insufficient justification") -> dict:
    return get_success_data(api_client.registrar_decision(
        waiver_id, {"decision": "DENY", "decision_reason": reason}, _registrar()))


# ─── Tier 4: graduation application pipeline ───────────

def open_application(student_program_id: str, student_id: str, **overrides) -> dict:
    """Create a DRAFT graduation application as the owning student."""
    return get_success_data(api_client.create_application(
        student_program_id, create_application_payload(**overrides), _student_hdr(student_id)))


def submit_application(application_id: str, student_id: str) -> dict:
    return get_success_data(api_client.submit_application(application_id, _student_hdr(student_id)))


def begin_review(application_id: str) -> dict:
    return get_success_data(api_client.begin_review(application_id, _registrar()))


def decide(application_id: str, decision: str, reason=None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["decision_reason"] = reason
    return get_success_data(api_client.decide_application(application_id, payload, _registrar()))


def confer(application_id: str) -> dict:
    return get_success_data(api_client.confer_application(application_id, _registrar()))


# ─── Tier 5: full graduation pipeline ──────────────────

def setup_graduation_pipeline(
    program_overrides=None,
    groups=None,
    honors_policy=None,
    student_overrides=None,
    enrollment_specs=(),
    catalog_year: int = 2024,
    audit_kinds=("FINAL",),
    application_overrides=None,
    walk_to=None,
):
    """Build a full scenario: program (+groups, +policy), student, enrollments,
    declaration, audits, and optionally a graduation application walked to the
    requested state.

    enrollment_specs: iterable of dicts {course_code, term, grade (omit/None for
        IN_PROGRESS), is_transfer, credits, title}. One course is created per spec.
    audit_kinds: kinds to run after declaration (each via run_audit with a fresh
        OCC version).
    walk_to: None | "DRAFT" | "SUBMITTED" | "UNDER_REVIEW" | "CLEARED" |
        "CONDITIONALLY_CLEARED" | "DENIED" | "CONFERRED".

    Returns SimpleNamespace(program, groups, policy, student, enrollments,
    student_program, audits, application, diploma).
    """
    program = make_program(**(program_overrides or {}))
    group_objs = [make_requirement_group(program["id"], **g) for g in (groups or [])]
    policy = make_honors_policy(program["id"], **honors_policy) if honors_policy else None

    student = make_student(**(student_overrides or {}))
    enrollments = []
    # Reuse one course per course_code within a single setup: specs that repeat
    # a code mean "the same course taken again in a later term" (legal per PRD
    # §3.2 — the duplicate-enrollment rule is per student+course+term), while
    # course codes are globally unique, so re-creating would 409.
    course_cache = {}
    for spec in enrollment_specs:
        code = spec["course_code"]
        if code not in course_cache:
            course_cache[code] = make_course(
                course_code=code,
                title=spec.get("title", code),
                credits=spec.get("credits", 3),
            )
        course = course_cache[code]
        enrollments.append(enroll(
            student["id"], course["id"], spec["term"],
            grade=spec.get("grade"), is_transfer=spec.get("is_transfer"),
        ))

    sp = declare(student["id"], program["id"], catalog_year=catalog_year)

    audits = {}
    for kind in audit_kinds:
        audits[kind] = run_audit(sp["id"], kind)

    application = None
    diploma = None
    if walk_to:
        application = open_application(sp["id"], student["id"], **(application_overrides or {}))
        if walk_to != "DRAFT":
            application = submit_application(application["id"], student["id"])
        if walk_to not in ("DRAFT", "SUBMITTED"):
            application = begin_review(application["id"])
        if walk_to in ("CLEARED", "CONDITIONALLY_CLEARED", "DENIED", "CONFERRED"):
            decision = "CLEARED" if walk_to == "CONFERRED" else walk_to
            application = decide(application["id"], decision,
                                 reason="requirements unmet" if decision == "DENIED" else None)
        if walk_to == "CONFERRED":
            application = confer(application["id"])
            diplomas, _meta = list_diplomas(application_id=application["id"])
            diploma = diplomas[0] if diplomas else None

    return SimpleNamespace(
        program=program,
        groups=group_objs,
        policy=policy,
        student=student,
        enrollments=enrollments,
        student_program=sp,
        audits=audits,
        application=application,
        diploma=diploma,
    )


def list_diplomas(**params):
    """List diplomas with filters. Returns (data_list, meta_dict)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_diplomas(_registrar(), params=params or None))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, _registrar()))


def get_student_program(student_program_id: str) -> dict:
    return get_success_data(api_client.get_student_program(student_program_id, _registrar()))


def get_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, _registrar()))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, _registrar()))


def get_waiver(waiver_id: str) -> dict:
    return get_success_data(api_client.get_waiver(waiver_id, _registrar()))
