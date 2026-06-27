"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) for all setup calls so a broken
precondition surfaces as a clear "setup failed" error rather than a confusing
assertion failure deep inside a test.

Identity threading: after a Parent or Instructor entity is created, every
ownership-gated call uses make_parent_headers(parent["id"]) /
make_instructor_headers(instructor["id"]) — never the shared fallback constant.
SchoolAdmin / BillingAdmin are opaque, so they use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_location_payload,
    create_level_payload,
    create_skill_payload,
    create_instructor_payload,
    create_parent_payload,
    create_student_payload,
    create_class_session_payload,
    create_enrollment_payload,
    create_invoice_payload,
    create_makeup_booking_payload,
    create_assessment_payload,
)
from .test_users import (
    TEST_USERS,
    make_parent_headers,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


# ─── Clock control ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Move the logical clock to the supplied instant (SchoolAdmin)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Tier 1: base catalog primitives ──────────────────────────────────────
def create_location(**overrides):
    return get_success_data(
        api_client.create_location(create_location_payload(**overrides), ADMIN)
    )


def create_level(**overrides):
    return get_success_data(
        api_client.create_level(create_level_payload(**overrides), ADMIN)
    )


def create_skill(level_id, **overrides):
    return get_success_data(
        api_client.create_skill(level_id, create_skill_payload(**overrides), ADMIN)
    )


def create_instructor(certified_level_ids=None, **overrides):
    payload = create_instructor_payload(**overrides)
    if certified_level_ids is not None:
        payload["certified_level_ids"] = certified_level_ids
    return get_success_data(api_client.create_instructor(payload, ADMIN))


def create_parent(**overrides):
    return get_success_data(
        api_client.create_parent(create_parent_payload(**overrides), ADMIN)
    )


def create_student(parent, current_level_id, **overrides):
    """Create a student owned by `parent`, using parent-backed headers."""
    headers = make_parent_headers(parent["id"])
    return get_success_data(
        api_client.create_student(
            parent["id"], create_student_payload(current_level_id, **overrides), headers
        )
    )


def create_class_session(location_id, level_id, instructor_id, **overrides):
    return get_success_data(
        api_client.create_class_session(
            create_class_session_payload(
                location_id, level_id, instructor_id, **overrides
            ),
            ADMIN,
        )
    )


def open_session(session_id):
    return get_success_data(api_client.open_class_session(session_id, ADMIN))


def get_session_version(session_id):
    session = get_success_data(api_client.get_class_session(session_id, ADMIN))
    return session["version"]


# ─── Tier 2: opened-session scaffolds ─────────────────────────────────────
def setup_open_session(level_overrides=None, session_overrides=None,
                       clock="2026-01-05T00:00:00Z"):
    """Clock + location + level + certified instructor + OPEN class session.

    Returns a dict of the created entities plus the session's post-open
    version under key "session_version".
    """
    if clock is not None:
        set_clock(clock)
    location = create_location()
    level = create_level(**(level_overrides or {}))
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(
        location["id"], level["id"], instructor["id"], **(session_overrides or {})
    )
    opened = open_session(session["id"])
    return {
        "location": location,
        "level": level,
        "instructor": instructor,
        "session": opened,
        "session_version": opened["version"],
    }


def setup_parent_with_student(level_id, student_overrides=None):
    """Register a parent and add one student at `level_id`."""
    parent = create_parent()
    student = create_student(parent, level_id, **(student_overrides or {}))
    return parent, student


# ─── Tier 3: enrollment lifecycle shortcuts ───────────────────────────────
def create_active_enrollment(parent, student, session):
    """Create an ACTIVE enrollment into an OPEN session that has a free seat.

    Reads the session's current version immediately before the create so the
    OCC field is fresh. Uses parent-backed ownership headers.
    """
    headers = make_parent_headers(parent["id"])
    version = get_session_version(session["id"])
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(student["id"], session["id"], version), headers
        )
    )


def create_enrollment_with_version(parent, student_id, session_id, expected_version):
    """Create an enrollment with a caller-controlled expected version. Lenient;
    used by boundary/OCC setups that need the raw response."""
    headers = make_parent_headers(parent["id"])
    return api_client.create_enrollment(
        create_enrollment_payload(student_id, session_id, expected_version), headers
    )


def setup_single_active_enrollment(level_overrides=None, session_overrides=None,
                                   student_overrides=None,
                                   clock="2026-01-05T00:00:00Z"):
    """OPEN session + parent + student + one ACTIVE enrollment.

    Returns a dict with keys: location, level, instructor, session, parent,
    student, enrollment.
    """
    env = setup_open_session(
        level_overrides=level_overrides,
        session_overrides=session_overrides,
        clock=clock,
    )
    parent, student = setup_parent_with_student(
        env["level"]["id"], student_overrides=student_overrides
    )
    enrollment = create_active_enrollment(parent, student, env["session"])
    env.update({"parent": parent, "student": student, "enrollment": enrollment})
    return env


def pause_enrollment(parent, enrollment_id):
    headers = make_parent_headers(parent["id"])
    return get_success_data(api_client.pause_enrollment(enrollment_id, headers))


def issued_skip_credit(student_id):
    """Return the single ISSUED makeup credit for `student_id` (most setups
    create exactly one via a pause)."""
    credits = get_success_data(
        api_client.list_makeup_credits(
            ADMIN, params={"student_id": student_id, "status": "ISSUED"}
        )
    )
    assert credits, f"expected at least one ISSUED credit for student {student_id}"
    return credits[0]


def list_issued_credits(student_id):
    return get_success_data(
        api_client.list_makeup_credits(
            ADMIN, params={"student_id": student_id, "status": "ISSUED"}
        )
    )


# ─── Tier 4: capacity-1 waitlist scaffold ─────────────────────────────────
def setup_capacity1_with_waitlist(clock="2026-01-05T00:00:00Z"):
    """Capacity-1 OPEN session with P1/S1 ACTIVE and P2/S2 WAITLISTED behind it.

    Returns a dict: location, level, instructor, session, p1, s1, enr1,
    p2, s2, enr2.
    """
    env = setup_open_session(
        level_overrides={
            "name": "Solo",
            "max_students_per_instructor": 1,
            "min_age_months": 36,
            "max_age_months": 200,
        },
        clock=clock,
    )
    level_id = env["level"]["id"]
    session = env["session"]

    p1 = create_parent(full_name="P1", email="p1@x.com")
    s1 = create_student(p1, level_id, full_name="S1")
    enr1 = create_active_enrollment(p1, s1, session)

    p2 = create_parent(full_name="P2", email="p2@x.com")
    s2 = create_student(p2, level_id, full_name="S2")
    # S2 lands WAITLISTED (capacity full).
    enr2 = create_active_enrollment(p2, s2, session)

    env.update(
        {"p1": p1, "s1": s1, "enr1": enr1, "p2": p2, "s2": s2, "enr2": enr2}
    )
    return env


# ─── Tier 5: assessment lifecycle scaffolds ───────────────────────────────
def create_assessment(instructor, enrollment_id, skill_scores):
    headers = make_instructor_headers(instructor["id"])
    return get_success_data(
        api_client.create_assessment(
            create_assessment_payload(enrollment_id, skill_scores), headers
        )
    )


def submit_assessment(instructor, assessment_id):
    headers = make_instructor_headers(instructor["id"])
    return get_success_data(api_client.submit_assessment(assessment_id, headers))


def setup_submitted_strict_ready_assessment(next_level=True,
                                            clock="2026-01-05T00:00:00Z"):
    """A SUBMITTED, strict_ready assessment (single skill scored 1.0) on an
    ACTIVE Level-1 enrollment. Level 1 has a next_level (Level 2) when
    next_level=True.

    Returns a dict: level (Level 1), next_level_id, instructor, session,
    parent, student, enrollment, assessment.
    """
    set_clock(clock)
    location = create_location()
    next_level_id = None
    if next_level:
        lvl2 = create_level(
            name="Level 2",
            sequence_order=2,
            min_age_months=36,
            max_age_months=200,
            max_students_per_instructor=6,
            monthly_tuition_cents=13000,
        )
        next_level_id = lvl2["id"]
    lvl1_kwargs = dict(
        name="Level 1",
        sequence_order=1,
        min_age_months=36,
        max_age_months=200,
        max_students_per_instructor=4,
        monthly_tuition_cents=12000,
    )
    if next_level_id:
        lvl1_kwargs["next_level_id"] = next_level_id
    level = create_level(**lvl1_kwargs)
    skill = create_skill(level["id"], name="Back Float 10s", weight=1.0)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    session = create_class_session(location["id"], level["id"], instructor["id"])
    session = open_session(session["id"])
    parent, student = setup_parent_with_student(level["id"])
    enrollment = create_active_enrollment(parent, student, session)
    assessment = create_assessment(
        instructor, enrollment["id"], [{"skill_id": skill["id"], "score": 1.0}]
    )
    submit_assessment(instructor, assessment["id"])
    return {
        "location": location,
        "level": level,
        "next_level_id": next_level_id,
        "skill": skill,
        "instructor": instructor,
        "session": session,
        "parent": parent,
        "student": student,
        "enrollment": enrollment,
        "assessment": assessment,
    }


# ─── Tier 6: invoice scaffolds ────────────────────────────────────────────
def create_invoice(parent_id, cycle_start, cycle_end, due_at, variant="FORWARD_LOOKING"):
    return get_success_data(
        api_client.create_invoice(
            create_invoice_payload(
                parent_id, cycle_start, cycle_end, due_at, variant=variant
            ),
            BILLING,
        )
    )


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


def setup_single_enrollment_for_billing(clock="2026-01-01T00:00:00Z",
                                        tuition_cents=12000, day_of_week=1,
                                        join_clock="2026-01-01T00:00:00Z"):
    """One ACTIVE Level-1 enrollment whose tuition basis is `tuition_cents`, in a
    session that meets on `day_of_week`. Wide age band so any student is eligible.

    The enrollment is activated while the clock is at `join_clock` (defaulting to
    the cycle start 2026-01-01) so its `joined_at` lands on or before the cycle
    start — i.e. NOT a mid-cycle join. Per PRD §3.9 the variant branch
    (FORWARD_LOOKING full cycle vs. CHRONOLOGICAL delivered-so-far) is only
    reached when `joined_at` is not strictly after `cycle_start`; a mid-cycle
    join would instead force the on-or-after-join-date window for both variants,
    collapsing the variant distinction. After activating, the clock is advanced
    to `clock` so the billing math evaluates against the requested instant.

    Returns a dict: level, session, parent, student, enrollment.
    """
    env = setup_open_session(
        level_overrides={
            "min_age_months": 0,
            "max_age_months": 200,
            "max_students_per_instructor": 4,
            "monthly_tuition_cents": tuition_cents,
        },
        session_overrides={"day_of_week": day_of_week},
        clock=join_clock,
    )
    parent, student = setup_parent_with_student(env["level"]["id"])
    enrollment = create_active_enrollment(parent, student, env["session"])
    if clock is not None and clock != join_clock:
        set_clock(clock)
    env.update({"parent": parent, "student": student, "enrollment": enrollment})
    return env


# ─── Tier 7: makeup booking scaffold ──────────────────────────────────────
def setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z",
                                level_overrides=None, session_overrides=None):
    """OPEN session + parent + student + ACTIVE enrollment paused once, yielding
    exactly one ISSUED SKIP credit.

    Returns a dict: location, level, instructor, session, parent, student,
    enrollment, credit.
    """
    env = setup_single_active_enrollment(
        level_overrides=level_overrides or {
            "min_age_months": 36,
            "max_age_months": 200,
            "max_students_per_instructor": 4,
        },
        session_overrides=session_overrides,
        clock=clock,
    )
    pause_enrollment(env["parent"], env["enrollment"]["id"])
    env["credit"] = issued_skip_credit(env["student"]["id"])
    return env


def book_makeup(parent, credit_id, target_session_id, occurrence_date):
    headers = make_parent_headers(parent["id"])
    return get_success_data(
        api_client.create_makeup_booking(
            create_makeup_booking_payload(
                credit_id, target_session_id, occurrence_date
            ),
            headers,
        )
    )
