"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to reach a specific state that takes
several API calls to build (an ACTIVE enrollment alone is studio -> family ->
student -> instructor -> room -> enrollment -> activate). These helpers encapsulate
those preambles. They use get_success_data() (lenient) so setup failures surface as
clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: ownership-gated calls performed as an entity-backed role
(Instructor / ParentGuardian) use the per-instance header builders with the real
entity id. Studio-driving operations (StudioAdmin) and money operations
(BillingClerk) use opaque shared headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_studio_payload,
    create_family_payload,
    create_student_payload,
    create_instructor_payload,
    create_room_payload,
    create_enrollment_payload,
    create_occurrence_payload,
    create_invoice_payload,
    create_recital_event_payload,
    create_registration_payload,
    set_clock_payload,
    create_wallet_credit_payload,
)
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ─────────────────────────── Tier 1: Studio / Clock ───────────────────────────
def create_studio(**overrides) -> dict:
    """Create a bare studio. Pass overrides like makeup_credit_cap_per_enrollment."""
    res = api_client.create_studio(create_studio_payload(**overrides), ADMIN)
    return get_success_data(res)


def set_clock(studio_id: str, iso: str) -> dict:
    """Advance the deterministic studio clock to `iso`."""
    res = api_client.set_clock(studio_id, set_clock_payload(iso), ADMIN)
    return get_success_data(res)


# ─────────────────────────── Tier 2: Roster ───────────────────────────
def setup_roster(
    studio_overrides=None,
    family_overrides=None,
    instructor_overrides=None,
    room_overrides=None,
):
    """Studio + one Family + one Student + one PIANO Instructor (available Monday
    all day by default) + one PIANO Room.

    Returns (studio, family, student, instructor, room).
    """
    studio = create_studio(**(studio_overrides or {}))
    sid = studio["id"]

    family = get_success_data(
        api_client.create_family(sid, create_family_payload(**(family_overrides or {})), ADMIN)
    )
    student = get_success_data(
        api_client.create_student(sid, create_student_payload(family["id"]), ADMIN)
    )
    instructor = get_success_data(
        api_client.create_instructor(
            sid, create_instructor_payload(**(instructor_overrides or {})), ADMIN
        )
    )
    room = get_success_data(
        api_client.create_room(sid, create_room_payload(**(room_overrides or {})), ADMIN)
    )
    return studio, family, student, instructor, room


# ─────────────────────────── Tier 3: Enrollment lifecycle ──────────────────────
def create_enrollment(studio_id, student_id, instructor_id, room_id, **enrollment_overrides):
    """Create a PENDING_MATCH enrollment. Returns the enrollment object."""
    res = api_client.create_enrollment(
        studio_id,
        create_enrollment_payload(student_id, instructor_id, room_id, **enrollment_overrides),
        ADMIN,
    )
    return get_success_data(res)


def activate_enrollment(studio_id, enrollment):
    """Activate an enrollment using its current version. Returns the activated entity."""
    res = api_client.activate_enrollment(
        studio_id,
        enrollment["id"],
        {"expected_enrollment_version": enrollment["version"]},
        ADMIN,
    )
    return get_success_data(res)


def setup_active_enrollment(
    studio_overrides=None,
    family_overrides=None,
    instructor_overrides=None,
    room_overrides=None,
    enrollment_overrides=None,
):
    """Full roster + one ACTIVE enrollment.

    Returns (studio, family, student, instructor, room, enrollment) where the
    enrollment object reflects the post-activation state (version bumped).
    """
    studio, family, student, instructor, room = setup_roster(
        studio_overrides, family_overrides, instructor_overrides, room_overrides
    )
    enr = create_enrollment(
        studio["id"], student["id"], instructor["id"], room["id"], **(enrollment_overrides or {})
    )
    enr = activate_enrollment(studio["id"], enr)
    return studio, family, student, instructor, room, enr


# ───────────────── Tier 4: Occurrences + invoice lifecycle ─────────────────
def create_occurrence(studio_id, enrollment_id, start_utc):
    res = api_client.create_occurrence(
        studio_id, create_occurrence_payload(enrollment_id, start_utc), ADMIN
    )
    return get_success_data(res)


def complete_occurrence(studio_id, occ_id, instructor_id):
    """Complete an occurrence acting as the owning Instructor."""
    res = api_client.complete_occurrence(
        studio_id, occ_id, make_instructor_headers(instructor_id)
    )
    return get_success_data(res)


# Default four weekly January start instants used by the divergence/finalize fixtures.
JAN_SESSION_STARTS = [
    "2026-01-05T10:00:00.000Z",
    "2026-01-12T10:00:00.000Z",
    "2026-01-19T10:00:00.000Z",
    "2026-01-26T10:00:00.000Z",
]


def setup_issued_invoice_with_completed_sessions(
    hourly_rate_cents=6000,
    duration_min=60,
    session_starts=None,
    billing_period="2026-01",
    complete_all=True,
    family_overrides=None,
    credit_wallet_cents=None,
    instructor_availability_all_day=True,
):
    """Build an ACTIVE enrollment, create N SCHEDULED January occurrences, issue an
    invoice for the period, then (optionally) complete every occurrence and advance
    the clock to the period end (2026-02-01) so the invoice is finalizable.

    Returns a dict with keys: studio, family, student, instructor, room,
    enrollment, occurrences, invoice.
    """
    session_starts = session_starts if session_starts is not None else list(JAN_SESSION_STARTS)
    instr_overrides = {"hourly_rate_cents": hourly_rate_cents}
    if instructor_availability_all_day:
        instr_overrides["weekly_availability"] = [
            {"weekday": 0, "start_min": 0, "end_min": 1440}
        ]

    studio, family, student, instructor, room, enr = setup_active_enrollment(
        family_overrides=family_overrides,
        instructor_overrides=instr_overrides,
        enrollment_overrides={"duration_min": duration_min, "weekday": 0, "start_min": 600},
    )
    sid = studio["id"]

    if credit_wallet_cents is not None:
        get_success_data(
            api_client.credit_wallet(
                sid, family["id"], create_wallet_credit_payload(credit_wallet_cents), BILLING
            )
        )

    occurrences = [create_occurrence(sid, enr["id"], s) for s in session_starts]

    invoice = get_success_data(
        api_client.create_invoice(
            sid, create_invoice_payload(enr["id"], billing_period), BILLING
        )
    )

    if complete_all:
        # Advance to a clock at/after the last session so completion is allowed,
        # but still inside the billing period.
        set_clock(sid, "2026-01-27T00:00:00.000Z")
        for occ in occurrences:
            complete_occurrence(sid, occ["id"], instructor["id"])
        # Advance past the billing period so the invoice can be finalized.
        set_clock(sid, "2026-02-01T00:00:00.000Z")

    return {
        "studio": studio,
        "family": family,
        "student": student,
        "instructor": instructor,
        "room": room,
        "enrollment": enr,
        "occurrences": occurrences,
        "invoice": invoice,
    }


# ───────────────── Tier 5: Multi-enrollment family (discount tiers) ─────────────
def setup_family_with_active_enrollments(
    count,
    hourly_rate_cents=6000,
    duration_min=60,
    family_overrides=None,
):
    """One Family with `count` ACTIVE enrollments on a single PIANO instructor
    (available Monday 09:00-18:00) across distinct rooms and non-overlapping
    consecutive Monday slots, so neither instructor- nor room-double-booking fires.

    Returns (studio, family, [enrollments]).
    """
    studio = create_studio()
    sid = studio["id"]
    family = get_success_data(
        api_client.create_family(sid, create_family_payload(**(family_overrides or {})), ADMIN)
    )
    instructor = get_success_data(
        api_client.create_instructor(
            sid,
            create_instructor_payload(
                instruments=["PIANO"],
                weekly_availability=[{"weekday": 0, "start_min": 540, "end_min": 1080}],
                hourly_rate_cents=hourly_rate_cents,
            ),
            ADMIN,
        )
    )

    enrollments = []
    start = 540  # 09:00, step by 120 min to stay clear of the room turnover buffer
    for i in range(count):
        student = get_success_data(
            api_client.create_student(sid, create_student_payload(family["id"]), ADMIN)
        )
        room = get_success_data(
            api_client.create_room(
                sid, create_room_payload(room_name=f"R{i}", supported_instruments=["PIANO"]), ADMIN
            )
        )
        enr = create_enrollment(
            sid,
            student["id"],
            instructor["id"],
            room["id"],
            instrument="PIANO",
            weekday=0,
            start_min=start + i * 120,
            duration_min=duration_min,
        )
        enr = activate_enrollment(sid, enr)
        enrollments.append(enr)

    return studio, get_success_data(api_client.get_family(sid, family["id"], ADMIN)), enrollments


# ───────────────── Tier 6: Recital + registrations ─────────────
def setup_recital_with_registrations(
    venue_capacity,
    num_students,
    register_count,
    clock="2026-03-01T00:00:00.000Z",
    event_start_utc="2026-04-01T18:00:00.000Z",
    registration_deadline_utc="2026-03-30T00:00:00.000Z",
):
    """Studio (clock set before the deadline) + one Family + `num_students` students +
    a REG_OPEN RecitalEvent, with the first `register_count` students registered (in
    creation order).

    Returns (studio, family, [students], event, [registrations]).
    """
    studio = create_studio()
    sid = studio["id"]
    family = get_success_data(api_client.create_family(sid, create_family_payload(), ADMIN))
    students = [
        get_success_data(api_client.create_student(sid, create_student_payload(family["id"]), ADMIN))
        for _ in range(num_students)
    ]
    set_clock(sid, clock)
    event = get_success_data(
        api_client.create_recital_event(
            sid,
            create_recital_event_payload(
                venue_capacity, event_start_utc, registration_deadline_utc
            ),
            ADMIN,
        )
    )
    registrations = []
    for i in range(register_count):
        reg = get_success_data(
            api_client.create_registration(
                sid, create_registration_payload(event["id"], students[i]["id"]), ADMIN
            )
        )
        registrations.append(reg)
    return studio, family, students, event, registrations
