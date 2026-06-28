"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading: a Student is registered with parent_user_id; ownership-gated Parent
calls (accept-offer, decline-offer, resubmit, book) must use make_parent_headers with the
SAME parent id. Guide slot-control calls (complete/no-show/cancel) must use
make_guide_headers with the SAME guide id that opened the slot. These helpers thread those
ids automatically.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_tier_payload, create_classroom_payload, create_student_payload,
    create_application_payload, accept_offer_payload, create_payment_payload,
    create_staff_assignment_payload, create_conference_slot_payload, book_slot_payload,
)
from .test_users import (
    TEST_USERS, make_parent_headers, make_guide_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Tier 0: Logical clock ─────────────────────────────

def set_clock(iso8601: str):
    """Set the server logical clock. Returns the current_utc echo."""
    return get_success_data(api_client.set_clock(iso8601, REGISTRAR))


# ─── Tier 1: Primitive creators ────────────────────────

def create_tier(**overrides):
    """Create a tuition tier. Returns the tier entity."""
    return get_success_data(
        api_client.create_tier(create_tier_payload(**overrides), REGISTRAR))


def create_classroom(**overrides):
    """Create a classroom. Returns the classroom entity (version starts at 1)."""
    return get_success_data(
        api_client.create_classroom(create_classroom_payload(**overrides), COMPLIANCE))


def assign_staff(classroom_id, expected_classroom_version, staff_name="Maria"):
    """Assign one staff member to a classroom under OCC. Returns the assignment."""
    return get_success_data(api_client.create_staff_assignment(
        create_staff_assignment_payload(classroom_id, expected_classroom_version, staff_name),
        COMPLIANCE,
    ))


def create_student(parent_user_id="parent-1", **overrides):
    """Register a student owned by parent_user_id. Returns the student."""
    payload = create_student_payload(parent_user_id=parent_user_id, **overrides)
    return get_success_data(
        api_client.create_student(payload, make_parent_headers(parent_user_id)))


def create_room_with_staff(level="PRIMARY", capacity=5, min_age_months=36,
                           max_age_months=72, name="Room", staff=1):
    """Create a classroom and assign `staff` staff members. Returns (room, current_version).

    Each staff assignment advances Classroom.version by 1, so the returned version is the
    fresh version after the last assignment (suitable for a subsequent OCC write)."""
    room = create_classroom(name=name, level=level, capacity=capacity,
                            min_age_months=min_age_months, max_age_months=max_age_months)
    version = room["version"]
    for i in range(staff):
        sa = assign_staff(room["id"], version, staff_name=f"Staff {i + 1}")
        version = sa["version"] if "version" in sa else version + 1
        # Re-read to get the authoritative classroom version after the cascade.
        room = get_success_data(api_client.get_classroom(room["id"], COMPLIANCE))
        version = room["version"]
    return room, version


# ─── Tier 2: Application lifecycle ─────────────────────

def submit_application(student_id, classroom_id, tier_id, parent_user_id="parent-1",
                       **overrides):
    """Submit an application as the owning parent. Returns the application (SUBMITTED)."""
    payload = create_application_payload(student_id, classroom_id, tier_id, **overrides)
    return get_success_data(
        api_client.create_application(payload, make_parent_headers(parent_user_id)))


def application_under_review(student_id, classroom_id, tier_id, parent_user_id="parent-1",
                             **app_overrides):
    """Submit + start-review. Returns the application in UNDER_REVIEW."""
    app = submit_application(student_id, classroom_id, tier_id,
                             parent_user_id=parent_user_id, **app_overrides)
    get_success_data(api_client.start_review(app["id"], REGISTRAR))
    return get_success_data(api_client.get_application(app["id"], REGISTRAR))


def application_offered(student_id, classroom_id, tier_id, parent_user_id="parent-1",
                        **app_overrides):
    """Submit + start-review + offer. Returns the application in OFFERED."""
    app = application_under_review(student_id, classroom_id, tier_id,
                                   parent_user_id=parent_user_id, **app_overrides)
    return get_success_data(api_client.offer(app["id"], REGISTRAR))


def application_waitlisted(student_id, classroom_id, tier_id, parent_user_id="parent-1",
                           **app_overrides):
    """Submit + start-review + waitlist. Returns the application in WAITLISTED."""
    app = application_under_review(student_id, classroom_id, tier_id,
                                   parent_user_id=parent_user_id, **app_overrides)
    return get_success_data(api_client.waitlist(app["id"], REGISTRAR))


def enroll_child(student_id, classroom_id, tier_id, parent_user_id="parent-1",
                 program_start_date="2026-09-01T00:00:00Z", **app_overrides):
    """Full path submit -> review -> offer -> accept-offer. Returns the Enrollment
    (placement PLACED, billing DEPOSIT_DUE) with computed tuition/deposit fields."""
    app = application_offered(student_id, classroom_id, tier_id,
                              parent_user_id=parent_user_id, **app_overrides)
    enr = get_success_data(api_client.accept_offer(
        app["id"], accept_offer_payload(program_start_date),
        make_parent_headers(parent_user_id),
    ))
    return enr


# ─── Tier 3: Compliant-room enrollment shortcut ────────

def setup_enrolled_child(level="PRIMARY", capacity=5, base_annual_cents=1_000_000,
                         deposit_pct=0.10, installments=10, tier_code="STD",
                         tier_overrides=None, parent_user_id="parent-1",
                         dob="2022-09-01T00:00:00Z", program_start_date="2026-09-01T00:00:00Z",
                         clock="2026-09-01T00:00:00Z", min_age_months=36, max_age_months=72,
                         app_overrides=None):
    """Clock + compliant staffed room + tier + enrolled child.

    Returns (room, tier, student, enrollment). The most common composite setup:
    a single child PLACED in a COMPLIANT classroom."""
    set_clock(clock)
    tier_kwargs = dict(code=tier_code, level=level, base_annual_cents=base_annual_cents,
                       deposit_pct=deposit_pct, installments=installments)
    tier_kwargs.update(tier_overrides or {})
    tier = create_tier(**tier_kwargs)
    room, _ = create_room_with_staff(level=level, capacity=capacity,
                                     min_age_months=min_age_months,
                                     max_age_months=max_age_months, staff=1)
    student = create_student(parent_user_id=parent_user_id, date_of_birth=dob)
    enr = enroll_child(student["id"], room["id"], tier["id"],
                       parent_user_id=parent_user_id,
                       program_start_date=program_start_date, **(app_overrides or {}))
    return room, tier, student, enr


def capture_deposit(enrollment_id, amount_cents):
    """Capture a DEPOSIT payment. Returns the Payment."""
    return get_success_data(api_client.create_payment(
        create_payment_payload(enrollment_id, "DEPOSIT", amount_cents), REGISTRAR))


def capture_installment(enrollment_id, amount_cents):
    """Capture an INSTALLMENT payment. Returns the Payment."""
    return get_success_data(api_client.create_payment(
        create_payment_payload(enrollment_id, "INSTALLMENT", amount_cents), REGISTRAR))


def setup_withdrawn_with_payments(deposit_cents=100_000, installment_cents=600_000,
                                  program_start_date="2026-09-01T00:00:00Z",
                                  clock="2026-09-01T00:00:00Z"):
    """Enrolled child, deposit + one installment captured (paid_to_date = sum), then
    WITHDRAWN. Returns (room, tier, student, enrollment). Used by refund tests:
    deposit 100000 + installment 600000 => paid_to_date 700000."""
    room, tier, student, enr = setup_enrolled_child(
        base_annual_cents=1_000_000, deposit_pct=0.10, installments=10,
        program_start_date=program_start_date, clock=clock)
    capture_deposit(enr["id"], deposit_cents)
    capture_installment(enr["id"], installment_cents)
    get_success_data(api_client.withdraw(enr["id"], REGISTRAR))
    enr = get_success_data(api_client.get_enrollment(enr["id"], REGISTRAR))
    return room, tier, student, enr


# ─── Tier 4: Accumulation / ratio boundary targeting ───

def fill_room_to_count(room_id, tier_id, target_placed, parent_prefix="filler",
                       dob="2022-09-01T00:00:00Z",
                       program_start_date="2026-09-01T00:00:00Z"):
    """Place `target_placed` distinct children into the room via offer + accept-offer.

    Each child gets its own parent_user_id so ownership checks pass. Returns the list of
    enrollment ids. Used to reach an exact placed_count for ratio/capacity boundary tests."""
    enr_ids = []
    for i in range(target_placed):
        puid = f"{parent_prefix}-{i}"
        student = create_student(parent_user_id=puid, full_name=f"Filler {i}",
                                 date_of_birth=dob)
        enr = enroll_child(student["id"], room_id, tier_id, parent_user_id=puid,
                           program_start_date=program_start_date)
        enr_ids.append(enr["id"])
    return enr_ids


def setup_room_at_placed_count(level="PRIMARY", capacity=20, placed=10, staff=1,
                               min_age_months=36, max_age_months=72,
                               clock="2026-09-01T00:00:00Z"):
    """Clock + staffed room + `placed` children PLACED. Returns (room, tier, enr_ids).

    For ratio-boundary tests: place exactly `placed` children with `staff` staff so the
    room sits at a known compliance posture, then offer/accept one more to cross the boundary."""
    set_clock(clock)
    tier = create_tier(code="STD", level=level, base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room = create_classroom(name="Boundary Room", level=level, capacity=capacity,
                            min_age_months=min_age_months, max_age_months=max_age_months)
    version = room["version"]
    for i in range(staff):
        sa = assign_staff(room["id"], version, staff_name=f"Staff {i + 1}")
        room = get_success_data(api_client.get_classroom(room["id"], COMPLIANCE))
        version = room["version"]
    enr_ids = fill_room_to_count(room["id"], tier["id"], placed,
                                 dob="2022-09-01T00:00:00Z" if level != "TODDLER"
                                 else "2024-09-01T00:00:00Z",
                                 program_start_date=clock)
    room = get_success_data(api_client.get_classroom(room["id"], REGISTRAR))
    return room, tier, enr_ids


# ─── Tier 5: Conference slot setups ────────────────────

def open_slot(classroom_id, guide_user_id="guide-1",
              start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z"):
    """Open a conference slot as the guide. Returns the slot (OPEN)."""
    return get_success_data(api_client.create_conference_slot(
        create_conference_slot_payload(guide_user_id, classroom_id, start_at, end_at),
        make_guide_headers(guide_user_id),
    ))


def book_slot(slot_id, booked_student_id, parent_user_id="parent-1"):
    """Book a slot as the owning parent. Returns the slot (BOOKED)."""
    return get_success_data(api_client.book_slot(
        slot_id, book_slot_payload(booked_student_id), make_parent_headers(parent_user_id)))


def setup_booked_slot(start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z",
                      guide_user_id="guide-1", parent_user_id="parent-1",
                      clock="2026-09-01T00:00:00Z"):
    """Enrolled child + an opened slot booked for that child. Returns (room, student, slot)."""
    room, tier, student, enr = setup_enrolled_child(parent_user_id=parent_user_id,
                                                     clock=clock)
    slot = open_slot(room["id"], guide_user_id=guide_user_id, start_at=start_at, end_at=end_at)
    slot = book_slot(slot["id"], student["id"], parent_user_id=parent_user_id)
    return room, student, slot
