"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and returns the parsed `data` payloads.
Setup calls go through a lenient 2xx reader so a setup failure surfaces as a
clear "Setup failed" message instead of a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_advisor_payload, create_teacher_payload, create_pathway_payload,
    create_student_payload, create_plan_payload, create_enrollment_payload,
    create_application_payload, create_milestone_payload,
    create_rec_request_payload, create_certification_payload,
    create_site_payload, create_placement_payload, create_audit_payload,
    create_outcome_payload,
)
from .test_users import (
    TEST_USERS, make_advisor_headers, make_student_headers,
    make_teacher_headers,
)

ADMIN = TEST_USERS["district_admin_headers"]
WBL = TEST_USERS["wbl_coordinator_headers"]


def _ok(response, what: str):
    data = get_success_data(response)
    assert 200 <= response.status_code < 300, (
        f"Setup failed ({what}): {response.status_code} {response.text}"
    )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation
# ---------------------------------------------------------------------------

def create_advisor(**overrides) -> dict:
    return _ok(api_client.create_advisor(create_advisor_payload(**overrides), ADMIN),
               "create advisor")


def create_teacher(**overrides) -> dict:
    return _ok(api_client.create_teacher(create_teacher_payload(**overrides), ADMIN),
               "create teacher")


def create_pathway(**overrides) -> dict:
    return _ok(api_client.create_pathway(create_pathway_payload(**overrides), ADMIN),
               "create pathway")


def create_student(advisor_id=None, **overrides) -> dict:
    """Enroll a student. advisor_id=None exercises the auto-assignment selector."""
    payload = create_student_payload(**overrides)
    if advisor_id is not None:
        payload["advisor_id"] = advisor_id
    return _ok(api_client.create_student(payload, ADMIN), "create student")


def create_site(**overrides) -> dict:
    return _ok(api_client.create_placement_site(create_site_payload(**overrides),
                                                ADMIN),
               "create placement site")


def set_clock(to_iso8601: str):
    return _ok(api_client.set_clock(to_iso8601, ADMIN), "set clock")


def get_student(student_id) -> dict:
    return _ok(api_client.get_student(student_id, ADMIN), "get student")


def get_advisor(advisor_id) -> dict:
    return _ok(api_client.get_advisor(advisor_id, ADMIN), "get advisor")


def get_teacher(teacher_id) -> dict:
    return _ok(api_client.get_teacher(teacher_id, ADMIN), "get teacher")


def get_plan(plan_id, headers=None) -> dict:
    return _ok(api_client.get_plan(plan_id, headers or ADMIN), "get plan")


def get_equity_report(advisor_id) -> dict:
    return _ok(api_client.get_equity_report(advisor_id, ADMIN), "equity report")


# ---------------------------------------------------------------------------
# Tier 2 — plans and enrollments
# ---------------------------------------------------------------------------

def create_plan(student: dict, pathway_id: str, advisor_id: str,
                interest_inventory=None) -> dict:
    """Create a DRAFT plan with a fresh OCC baseline read of the student."""
    current = get_student(student["id"])
    payload = create_plan_payload(pathway_id, current["version"])
    if interest_inventory is not None:
        payload["interest_inventory"] = interest_inventory
    return _ok(
        api_client.create_plan(student["id"], payload,
                               make_advisor_headers(advisor_id)),
        "create plan",
    )


def activate_plan(plan_id: str, advisor_id: str) -> dict:
    return _ok(api_client.activate_plan(plan_id, make_advisor_headers(advisor_id)),
               "activate plan")


def create_active_plan(student: dict, pathway_id: str, advisor_id: str) -> dict:
    """Create + activate. Returns the ACTIVE plan."""
    plan = create_plan(student, pathway_id, advisor_id)
    return activate_plan(plan["id"], advisor_id)


def setup_student_with_active_plan(pathway_overrides=None, student_overrides=None,
                                   advisor_max_caseload=50) -> dict:
    """Advisor + pathway + student (explicitly assigned) + ACTIVE plan.

    Returns {"advisor", "pathway", "student", "plan"}.
    """
    advisor = create_advisor(max_caseload=advisor_max_caseload)
    pathway = create_pathway(**(pathway_overrides or {}))
    student = create_student(advisor_id=advisor["id"], **(student_overrides or {}))
    plan = create_active_plan(student, pathway["id"], advisor["id"])
    return {"advisor": advisor, "pathway": pathway, "student": student,
            "plan": plan}


def add_enrollment(student_id: str, plan_id: str, advisor_id: str,
                   course_code: str, credits, term=None) -> dict:
    payload = create_enrollment_payload(plan_id, course_code, credits)
    if term is not None:
        payload["term"] = term
    return _ok(
        api_client.create_enrollment(student_id, payload,
                                     make_advisor_headers(advisor_id)),
        "create enrollment",
    )


def transition_enrollment(enrollment_id: str, advisor_id: str,
                          to_status: str, grade=None) -> dict:
    payload = {"to_status": to_status}
    if grade is not None:
        payload["grade"] = grade
    return _ok(
        api_client.transition_enrollment(enrollment_id, payload,
                                         make_advisor_headers(advisor_id)),
        f"transition enrollment -> {to_status}",
    )


def enroll_and_complete(enrollment_id: str, advisor_id: str, grade="PASS") -> dict:
    """PLANNED -> ENROLLED -> COMPLETED."""
    transition_enrollment(enrollment_id, advisor_id, "ENROLLED")
    return transition_enrollment(enrollment_id, advisor_id, "COMPLETED", grade=grade)


def add_completed_enrollment(student_id: str, plan_id: str, advisor_id: str,
                             course_code: str, credits, grade="PASS") -> dict:
    enr = add_enrollment(student_id, plan_id, advisor_id, course_code, credits)
    return enroll_and_complete(enr["id"], advisor_id, grade)


# ---------------------------------------------------------------------------
# Tier 3 — applications and milestones
# ---------------------------------------------------------------------------

def create_application(student: dict, **overrides) -> dict:
    return _ok(
        api_client.create_application(student["id"],
                                      create_application_payload(**overrides),
                                      make_student_headers(student["id"])),
        "create application",
    )


def list_milestones(application_id: str, headers=None) -> list:
    return _ok(api_client.list_application_milestones(application_id,
                                                      headers or ADMIN),
               "list milestones")


def create_application_with_milestones(student: dict, **overrides):
    """Create an application; returns (application, seeded_milestones)."""
    app = create_application(student, **overrides)
    milestones = list_milestones(app["id"], make_student_headers(student["id"]))
    return app, milestones


def complete_milestone(milestone_id: str, student: dict) -> dict:
    return _ok(
        api_client.transition_milestone(milestone_id, {"to_status": "COMPLETED"},
                                        make_student_headers(student["id"])),
        "complete milestone",
    )


def waive_milestone(milestone_id: str, advisor_id: str) -> dict:
    return _ok(
        api_client.transition_milestone(milestone_id, {"to_status": "WAIVED"},
                                        make_advisor_headers(advisor_id)),
        "waive milestone",
    )


def transition_application(application_id: str, student: dict,
                           to_status: str) -> dict:
    return _ok(
        api_client.transition_application(application_id,
                                          {"to_status": to_status},
                                          make_student_headers(student["id"])),
        f"application -> {to_status}",
    )


# ---------------------------------------------------------------------------
# Tier 3 — recommendation requests
# ---------------------------------------------------------------------------

def create_rec_request(student: dict, teacher_id: str, due_at=None,
                       application_id=None) -> dict:
    payload = create_rec_request_payload(
        teacher_id, due_at or TEST_DEFAULTS["REC_DUE"])
    if application_id is not None:
        payload["application_id"] = application_id
    return _ok(
        api_client.create_recommendation_request(student["id"], payload,
                                                 make_student_headers(student["id"])),
        "create recommendation request",
    )


def transition_rec_request(request_id: str, headers: dict, to_status: str,
                           **extra) -> dict:
    payload = {"to_status": to_status}
    payload.update(extra)
    return _ok(
        api_client.transition_recommendation_request(request_id, payload, headers),
        f"recommendation request -> {to_status}",
    )


# ---------------------------------------------------------------------------
# Tier 3 — certifications and placements
# ---------------------------------------------------------------------------

def create_certification(student_id: str, cert_code: str) -> dict:
    return _ok(
        api_client.create_certification(student_id,
                                        create_certification_payload(cert_code),
                                        WBL),
        "create certification",
    )


def transition_certification(certification_id: str, to_status: str,
                             exam_at=None) -> dict:
    payload = {"to_status": to_status}
    if exam_at is not None:
        payload["exam_at"] = exam_at
    return _ok(
        api_client.transition_certification(certification_id, payload, WBL),
        f"certification -> {to_status}",
    )


def schedule_certification(certification_id: str, exam_at=None) -> dict:
    return transition_certification(certification_id, "EXAM_SCHEDULED",
                                    exam_at or TEST_DEFAULTS["EXAM_AT"])


def pass_certification(student_id: str, cert_code: str, exam_at=None) -> dict:
    """REGISTERED -> EXAM_SCHEDULED -> PASSED. Returns the PASSED record."""
    cert = create_certification(student_id, cert_code)
    schedule_certification(cert["id"], exam_at)
    return transition_certification(cert["id"], "PASSED")


def create_placement(student_id: str, site_id: str, term_start=None, term_end=None,
                     hours_per_week=10) -> dict:
    payload = create_placement_payload(
        site_id,
        term_start or TEST_DEFAULTS["TERM_START"],
        term_end or TEST_DEFAULTS["TERM_END"],
        hours_per_week,
    )
    return _ok(api_client.create_placement(student_id, payload, WBL),
               "create placement")


def transition_placement(placement_id: str, to_status: str,
                         hours_logged=None) -> dict:
    payload = {"to_status": to_status}
    if hours_logged is not None:
        payload["hours_logged"] = hours_logged
    return _ok(api_client.transition_placement(placement_id, payload, WBL),
               f"placement -> {to_status}")


def confirm_placement(placement_id: str) -> dict:
    return transition_placement(placement_id, "CONFIRMED")


def complete_placement(placement_id: str, hours_logged) -> dict:
    """CONFIRMED -> ACTIVE -> COMPLETED with the given verified hours."""
    transition_placement(placement_id, "ACTIVE")
    return transition_placement(placement_id, "COMPLETED", hours_logged=hours_logged)


# ---------------------------------------------------------------------------
# Tier 4 — senior audits, certification, graduation
# ---------------------------------------------------------------------------

def create_senior_audit(student_id: str, auditor_advisor_id: str) -> dict:
    return _ok(
        api_client.create_senior_audit(student_id,
                                       create_audit_payload(auditor_advisor_id),
                                       ADMIN),
        "create senior audit",
    )


def get_senior_audit(audit_id) -> dict:
    return _ok(api_client.get_senior_audit(audit_id, ADMIN), "get senior audit")


def transition_audit(audit_id: str, auditor_id: str, to_status: str,
                     flag_reason=None) -> dict:
    payload = {"to_status": to_status}
    if flag_reason is not None:
        payload["flag_reason"] = flag_reason
    return _ok(
        api_client.transition_senior_audit(audit_id, payload,
                                           make_advisor_headers(auditor_id)),
        f"senior audit -> {to_status}",
    )


def setup_audit_in_review(student_overrides=None, pathway_overrides=None,
                          credits=24, grade="PASS") -> dict:
    """Advisors AX (assigned) + AY (auditor), grade-12 student with an ACTIVE
    plan and one COMPLETED enrollment worth `credits`, audit IN_REVIEW.

    With a requirement-free pathway and 24 credits, every graduation gate
    passes. Returns {"assigned", "auditor", "pathway", "student", "plan",
    "enrollment", "audit"}.
    """
    assigned = create_advisor()
    auditor = create_advisor()
    pathway = create_pathway(**(pathway_overrides or {}))
    student = create_student(advisor_id=assigned["id"], **(student_overrides or {}))
    plan = create_active_plan(student, pathway["id"], assigned["id"])
    enrollment = add_completed_enrollment(student["id"], plan["id"],
                                          assigned["id"], "CR24", credits, grade)
    audit = create_senior_audit(student["id"], auditor["id"])
    transition_audit(audit["id"], auditor["id"], "IN_REVIEW")
    return {"assigned": assigned, "auditor": auditor, "pathway": pathway,
            "student": student, "plan": plan, "enrollment": enrollment,
            "audit": audit}


def setup_certified_audit(**kwargs) -> dict:
    """Same as setup_audit_in_review but the audit is CERTIFIED."""
    ctx = setup_audit_in_review(**kwargs)
    transition_audit(ctx["audit"]["id"], ctx["auditor"]["id"], "CERTIFIED")
    ctx["audit"] = _ok(api_client.get_senior_audit(ctx["audit"]["id"], ADMIN),
                       "re-read certified audit")
    return ctx


def setup_graduated_student(**kwargs) -> dict:
    """Full lifecycle: certified audit + graduation. Returns the context dict
    from setup_certified_audit plus the refreshed "student"."""
    ctx = setup_certified_audit(**kwargs)
    _ok(api_client.graduate_student(ctx["student"]["id"], ADMIN),
        "graduate student")
    ctx["student"] = get_student(ctx["student"]["id"])
    return ctx
