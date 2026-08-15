"""Composite setup helpers.

Multi-step API preconditions shared by many tests. Each helper builds its
preconditions from scratch through the public endpoints and returns the
created resources (dicts from the response envelope's ``data``).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_school_year_payload,
    create_security_plan_payload,
    create_family_payload,
    create_student_payload,
    create_teacher_payload,
    create_section_payload,
    create_enrollment_payload,
    create_invoice_payload,
    create_application_payload,
    create_session_payload,
    create_attendance_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_officer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: year + security plan progression
# ---------------------------------------------------------------------------

def create_year(**overrides):
    """Create a school year (SETUP). Returns the year dict."""
    resp = api_client.create_school_year(create_school_year_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_year_with_plan(**year_overrides):
    """Year (SETUP) + one SecurityPlan left in DRAFT. Returns (year, plan)."""
    year = create_year(**year_overrides)
    plan = get_success_data(
        api_client.create_security_plan(
            year["id"], create_security_plan_payload(), ADMIN
        ),
        201,
    )
    return year, plan


def setup_open_year(**year_overrides):
    """Year + SecurityPlan driven DRAFT -> SUBMITTED -> ACTIVE, then year OPEN.

    Returns (year, plan) with year already OPEN.
    """
    year, plan = create_year_with_plan(**year_overrides)
    get_success_data(api_client.submit_security_plan(plan["id"], ADMIN))
    plan = get_success_data(api_client.approve_security_plan(plan["id"], ADMIN))
    year = get_success_data(api_client.open_school_year(year["id"], ADMIN))
    return year, plan


# ---------------------------------------------------------------------------
# Tier 2: teachers and sections
# ---------------------------------------------------------------------------

def create_hired_teacher(**overrides):
    """Teacher walked APPLIED -> VETTED -> HIRED. Returns teacher dict."""
    teacher = get_success_data(
        api_client.create_teacher(create_teacher_payload(**overrides), ADMIN), 201
    )
    get_success_data(api_client.vet_teacher(teacher["id"], ADMIN))
    return get_success_data(api_client.hire_teacher(teacher["id"], ADMIN))


def create_staffed_section(year_id, teacher=None, **overrides):
    """Section in the given year. If teacher is None a fresh HIRED teacher is
    created and assigned. Returns (section, teacher)."""
    if teacher is None:
        teacher = create_hired_teacher()
    payload = create_section_payload(**overrides)
    payload["teacher_id"] = teacher["id"]
    section = get_success_data(
        api_client.create_section(year_id, payload, ADMIN), 201
    )
    return section, teacher


def setup_open_year_with_section(**overrides):
    """OPEN year + ACTIVE plan + HIRED teacher + staffed section.

    Returns dict(year, plan, teacher, section).
    """
    section_keys = {
        k: overrides.pop(k)
        for k in list(overrides.keys())
        if k
        in (
            "grade",
            "hebrew_level",
            "capacity",
            "room",
            "day_of_week",
            "start_time",
            "end_time",
        )
    }
    year, plan = setup_open_year(**overrides)
    section, teacher = create_staffed_section(year["id"], **section_keys)
    return {"year": year, "plan": plan, "teacher": teacher, "section": section}


# ---------------------------------------------------------------------------
# Tier 2b: families / students / enrollment
# ---------------------------------------------------------------------------

def create_family(**overrides):
    return get_success_data(
        api_client.create_family(create_family_payload(**overrides), ADMIN), 201
    )


def create_student(family_id, **overrides):
    return get_success_data(
        api_client.create_student(family_id, create_student_payload(**overrides), ADMIN),
        201,
    )


def enroll_student(section_id, student_id, expected_section_version):
    """Enroll one student (OCC version supplied by caller). Returns enrollment."""
    resp = api_client.create_enrollment(
        section_id,
        create_enrollment_payload(student_id, expected_section_version),
        ADMIN,
    )
    return get_success_data(resp, 201)


def enroll_student_fresh(section_id, student_id):
    """Read the section for its current version, then enroll. Returns enrollment."""
    section = get_success_data(api_client.get_section(section_id, ADMIN))
    return enroll_student(section_id, student_id, section["version"])


def enroll_students_sequential(section_id, student_ids):
    """Enroll each student in order, re-reading the section version between
    enrollments (each enrollment bumps the section version). Returns list of
    enrollment dicts in creation order (sibling rank order)."""
    enrollments = []
    for sid in student_ids:
        enrollments.append(enroll_student_fresh(section_id, sid))
    return enrollments


def setup_family_with_enrollment(section, num_students=1, family_overrides=None):
    """Family + num_students students + all enrolled into the section.

    Returns dict(family, students, enrollments).
    """
    family = create_family(**(family_overrides or {}))
    students = [
        create_student(
            family["id"], grade=section["grade"], hebrew_level=section["hebrew_level"]
        )
        for _ in range(num_students)
    ]
    enrollments = enroll_students_sequential(
        section["id"], [s["id"] for s in students]
    )
    return {"family": family, "students": students, "enrollments": enrollments}


def get_family(family_id):
    return get_success_data(api_client.get_family(family_id, ADMIN))


def get_section(section_id):
    return get_success_data(api_client.get_section(section_id, ADMIN))


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def get_milestone_for_student(student_id):
    """Return the (single) milestone auto-created for the student's first enrollment."""
    data, _meta = _list_milestones({"student_id": student_id})
    assert len(data) == 1, f"expected exactly one milestone for student {student_id}"
    return data[0]


def get_commitment_for_family(family_id):
    """Return the (single) volunteer commitment auto-created for the family's
    first enrollment of the year."""
    data, _meta = _list_commitments({"family_id": family_id})
    assert len(data) == 1, f"expected exactly one commitment for family {family_id}"
    return data[0]


def _list_milestones(params):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_milestones(ADMIN, params=params)
    return validate_paginated(resp)


def _list_commitments(params):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_commitments(ADMIN, params=params)
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 3: invoicing / payments
# ---------------------------------------------------------------------------

def issue_invoice_fresh(family_id, school_year_id):
    """Read the family for its current version, then issue the invoice."""
    family = get_family(family_id)
    resp = api_client.issue_invoice(
        family_id,
        create_invoice_payload(school_year_id, family["version"]),
        ADMIN,
    )
    return get_success_data(resp, 201)


def post_payment(family_id, amount_cents, method="CARD"):
    resp = api_client.post_payment(
        family_id, {"amount_cents": amount_cents, "method": method}, ADMIN
    )
    return get_success_data(resp, 201)


def setup_family_with_invoice(year, section, num_students=1, family_overrides=None):
    """Family + students enrolled + TUITION invoice issued. Returns
    dict(family, students, enrollments, invoice)."""
    bundle = setup_family_with_enrollment(section, num_students, family_overrides)
    invoice = issue_invoice_fresh(bundle["family"]["id"], year["id"])
    bundle["invoice"] = invoice
    return bundle


# ---------------------------------------------------------------------------
# Tier 4: sessions / attendance / milestone accumulation
# ---------------------------------------------------------------------------

def create_sessions(section_id, dates):
    """Create one session per date. Returns list of session dicts."""
    sessions = []
    for d in dates:
        sessions.append(
            get_success_data(
                api_client.create_session(
                    section_id, create_session_payload(session_date=d), ADMIN
                ),
                201,
            )
        )
    return sessions


def hold_sessions(session_ids):
    for sid in session_ids:
        get_success_data(api_client.hold_session(sid, ADMIN))


def post_marks(session_id, student_id, status):
    return get_success_data(
        api_client.post_attendance(
            session_id, create_attendance_payload(student_id, status), ADMIN
        )
    )


def setup_section_with_attendance(marks, num_scheduled_extra=0, clock_to=None):
    """Full attendance scenario.

    ``marks`` is a list of attendance marks applied to one enrolled student,
    one per created session (each held in turn). ``num_scheduled_extra`` extra
    sessions are created AFTER the held ones and left SCHEDULED.

    Returns dict(year, section, teacher, family, student, enrollment,
    held_sessions, scheduled_sessions, milestone).
    """
    ctx = setup_open_year_with_section()
    year, section = ctx["year"], ctx["section"]
    fam_bundle = setup_family_with_enrollment(section, 1)
    student = fam_bundle["students"][0]

    n_held = len(marks)
    dates = [
        # spread Sundays inside the standard year window
        "2026-09-13", "2026-09-20", "2026-09-27", "2026-10-04",
        "2026-10-11", "2026-10-18", "2026-10-25", "2026-11-01",
    ][: n_held + num_scheduled_extra]
    sessions = create_sessions(section["id"], dates)
    held, scheduled = sessions[:n_held], sessions[n_held:]

    if clock_to is None:
        clock_to = f"{dates[n_held - 1]}T12:00:00Z" if n_held else None
    if clock_to:
        get_success_data(
            api_client.set_clock({"to_iso8601": clock_to}, ADMIN)
        )
    hold_sessions([s["id"] for s in held])
    for session, mark in zip(held, marks):
        post_marks(session["id"], student["id"], mark)

    milestone = get_milestone_for_student(student["id"])
    return {
        **ctx,
        "family": fam_bundle["family"],
        "student": student,
        "enrollment": fam_bundle["enrollments"][0],
        "held_sessions": held,
        "scheduled_sessions": scheduled,
        "milestone": milestone,
    }


# ---------------------------------------------------------------------------
# Tier 4b: volunteer / milestone scheduling
# ---------------------------------------------------------------------------

def fulfill_commitment(commitment_id, hours=8, note="Volunteer shift"):
    """Log enough hours in one entry to reach FULFILLED. Returns commitment."""
    return get_success_data(
        api_client.add_volunteer_entry(commitment_id, {"hours": hours, "note": note}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 5: assistance pipeline
# ---------------------------------------------------------------------------

def create_application_under_review(family_id, school_year_id, officer_id="officer-1"):
    """Application created then moved to UNDER_REVIEW by the given officer id."""
    app = get_success_data(
        api_client.create_application(
            family_id, create_application_payload(school_year_id), ADMIN
        ),
        201,
    )
    get_success_data(
        api_client.start_review(app["id"], make_officer_headers(officer_id))
    )
    return get_success_data(
        api_client.get_application(app["id"], make_officer_headers(officer_id))
    )


def decide_application(app_id, payload, admin_id="admin-9"):
    resp = api_client.decide_application(app_id, payload, make_admin_headers(admin_id))
    return resp
