"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors, not confusing downstream assertion failures.

Identity threading: Teacher and Guardian are entity_backed:Guardian. Every
ownership-gated call uses make_teacher_headers(guardian_id) /
make_guardian_headers(guardian_id) with the real Guardian id — never the shared
TEST_USERS fallback. The server starts empty before every test, so each fixture
builds its entire precondition chain from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_student_payload,
    create_guardian_payload,
    create_vehicle_payload,
    create_scholarship_pool_payload,
    create_field_trip_payload,
    create_permission_slip_payload,
    create_emergency_contact_payload,
    create_scholarship_grant_payload,
    create_chaperone_payload,
    create_transport_booking_payload,
    create_approval_payload,
    create_attendance_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    make_principal_headers,
    make_district_admin_headers,
)


_DISTRICT = TEST_USERS["district_admin_headers"]
_PRINCIPAL = TEST_USERS["principal_headers"]


# ─── Primitive creators ───────────────────────────────────────────────────────
def create_guardian(full_name="G", email=None, phone="555-0000"):
    """Register a guardian. Returns the guardian entity (carries id)."""
    payload = create_guardian_payload(
        full_name=full_name, email=email or unique_email("g"), phone=phone
    )
    return get_success_data(api_client.create_guardian(payload, _DISTRICT))


def create_teacher_guardian(full_name="Teacher G", email=None):
    """Register the Guardian that backs a Teacher identity. Returns its id."""
    return create_guardian(full_name=full_name, email=email or unique_email("teacher"))["id"]


def create_student(teacher_id, full_name="S", grade_level=5, special_needs=None,
                   home_school_code="SCH1"):
    """Register a student (acting as the teacher)."""
    payload = create_student_payload(
        full_name=full_name, grade_level=grade_level, home_school_code=home_school_code
    )
    if special_needs is not None:
        payload["special_needs"] = special_needs
    return get_success_data(api_client.create_student(payload, make_teacher_headers(teacher_id)))


def create_vehicle(label="Bus", seat_capacity=40):
    return get_success_data(
        api_client.create_vehicle(
            create_vehicle_payload(label=label, seat_capacity=seat_capacity), _DISTRICT
        )
    )


def create_scholarship_pool(name="Pool", total_cents=100_000):
    return get_success_data(
        api_client.create_scholarship_pool(
            create_scholarship_pool_payload(name=name, total_cents=total_cents), _DISTRICT
        )
    )


# ─── Tier 1: Trip state progression ───────────────────────────────────────────
def create_draft_trip(teacher_id, **trip_overrides):
    """Create a DRAFT field trip organized by teacher_id. Returns the trip."""
    payload = create_field_trip_payload(teacher_id, **trip_overrides)
    return get_success_data(
        api_client.create_field_trip(payload, make_teacher_headers(teacher_id))
    )


def submit_trip(teacher_id, trip_id):
    return get_success_data(api_client.submit_trip(trip_id, make_teacher_headers(teacher_id)))


def principal_decision(trip_id, decision, comment=None):
    payload = create_approval_payload("PRINCIPAL", decision)
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(api_client.create_approval(trip_id, payload, _PRINCIPAL))


def district_decision(trip_id, decision, comment=None):
    payload = create_approval_payload("DISTRICT", decision)
    if comment is not None:
        payload["comment"] = comment
    return get_success_data(api_client.create_approval(trip_id, payload, _DISTRICT))


def create_pending_principal_trip(teacher_id=None, **trip_overrides):
    """Create + submit a trip → PENDING_PRINCIPAL. Returns (teacher_id, trip)."""
    teacher_id = teacher_id or create_teacher_guardian()
    trip = create_draft_trip(teacher_id, **trip_overrides)
    submit_trip(teacher_id, trip["id"])
    trip = get_success_data(
        api_client.get_field_trip(trip["id"], make_teacher_headers(teacher_id))
    )
    return teacher_id, trip


def create_approved_trip(teacher_id=None, **trip_overrides):
    """Drive a fresh trip through the full approval chain to APPROVED.

    Returns (teacher_id, trip) where trip is the re-read APPROVED entity.
    """
    teacher_id = teacher_id or create_teacher_guardian()
    trip = create_draft_trip(teacher_id, **trip_overrides)
    submit_trip(teacher_id, trip["id"])
    principal_decision(trip["id"], "APPROVE")
    district_decision(trip["id"], "APPROVE")
    trip = get_success_data(
        api_client.get_field_trip(trip["id"], make_teacher_headers(teacher_id))
    )
    return teacher_id, trip


# ─── Tier 2: Slip building blocks ─────────────────────────────────────────────
def create_slip(teacher_id, trip_id, student_id, guardian_id, **overrides):
    """Teacher creates a permission slip. Returns the slip."""
    payload = create_permission_slip_payload(student_id, guardian_id, **overrides)
    return get_success_data(
        api_client.create_permission_slip(trip_id, payload, make_teacher_headers(teacher_id))
    )


def add_emergency_contact(actor_id, trip_id, slip_id, as_role="Teacher"):
    """Add one emergency contact to a slip (default: acting as the teacher)."""
    headers = make_teacher_headers(actor_id) if as_role == "Teacher" else make_guardian_headers(actor_id)
    return get_success_data(
        api_client.create_emergency_contact(
            trip_id, slip_id, create_emergency_contact_payload(), headers
        )
    )


def sign_slip(guardian_id, trip_id, slip_id):
    return get_success_data(
        api_client.sign_slip(trip_id, slip_id, make_guardian_headers(guardian_id))
    )


def create_signed_slip(teacher_id, trip_id, student_id, guardian_id, **overrides):
    """Create slip + emergency contact + sign. Returns the SIGNED slip."""
    slip = create_slip(teacher_id, trip_id, student_id, guardian_id, **overrides)
    add_emergency_contact(teacher_id, trip_id, slip["id"])
    return sign_slip(guardian_id, trip_id, slip["id"])


def pay_slip(guardian_id, trip_id, slip_id, amount_cents):
    return get_success_data(
        api_client.pay_slip(
            trip_id, slip_id, {"amount_cents": amount_cents}, make_guardian_headers(guardian_id)
        )
    )


# ─── Tier 2: Chaperone building blocks ────────────────────────────────────────
def invite_chaperone(teacher_id, trip_id, guardian_id, background_check_ref="BG-REF",
                     assigned_student_id=None):
    payload = create_chaperone_payload(guardian_id)
    if background_check_ref is not None:
        payload["background_check_ref"] = background_check_ref
    if assigned_student_id is not None:
        payload["assigned_student_id"] = assigned_student_id
    return get_success_data(
        api_client.create_chaperone(trip_id, payload, make_teacher_headers(teacher_id))
    )


def confirm_chaperone(guardian_id, trip_id, chaperone_id):
    return get_success_data(
        api_client.confirm_chaperone(trip_id, chaperone_id, make_guardian_headers(guardian_id))
    )


def clear_chaperone(trip_id, chaperone_id):
    return get_success_data(api_client.clear_chaperone(trip_id, chaperone_id, _PRINCIPAL))


def create_cleared_chaperone(teacher_id, trip_id, background_check_ref="BG-REF",
                             chaperone_guardian=None):
    """Invite + confirm + clear a chaperone (background ref present).

    Returns the CLEARED chaperone. Creates its own backing guardian unless one is
    supplied.
    """
    g = chaperone_guardian or create_guardian(full_name="Chap")
    chap = invite_chaperone(teacher_id, trip_id, g["id"], background_check_ref=background_check_ref)
    confirm_chaperone(g["id"], trip_id, chap["id"])
    return clear_chaperone(trip_id, chap["id"])


# ─── Tier 2: Transport building blocks ────────────────────────────────────────
def request_booking(teacher_id, trip_id, vehicle_id, seat_count):
    return get_success_data(
        api_client.create_transport_booking(
            trip_id, create_transport_booking_payload(vehicle_id, seat_count),
            make_teacher_headers(teacher_id),
        )
    )


def confirm_booking(teacher_id, trip_id, booking_id):
    return get_success_data(
        api_client.confirm_booking(trip_id, booking_id, make_teacher_headers(teacher_id))
    )


def create_confirmed_booking(teacher_id, trip_id, vehicle_id, seat_count):
    """Request + confirm a transport booking. Returns the CONFIRMED booking."""
    bk = request_booking(teacher_id, trip_id, vehicle_id, seat_count)
    return confirm_booking(teacher_id, trip_id, bk["id"])


# ─── Tier 3: Lockable / locked roster scenarios ───────────────────────────────
def get_trip_version(teacher_id, trip_id):
    trip = get_success_data(api_client.get_field_trip(trip_id, make_teacher_headers(teacher_id)))
    return trip["version"]


def lock_roster(teacher_id, trip_id, expected_trip_version):
    return get_success_data(
        api_client.lock_roster(
            trip_id, {"expected_trip_version": expected_trip_version},
            make_teacher_headers(teacher_id),
        )
    )


def setup_lockable_trip(seat_count=3, **trip_overrides):
    """Build a trip that is APPROVED and satisfies every lock precondition:
    1 SIGNED slip, 1 CLEARED chaperone, 1 CONFIRMED transport booking with enough
    seats. The trip is NOT locked. Returns a dict bundle of the created ids.
    """
    teacher_id, trip = create_approved_trip(**trip_overrides)
    trip_id = trip["id"]

    g_a = create_guardian(full_name="Slip G")
    student = create_student(teacher_id, full_name="Slip S", grade_level=9)
    slip = create_signed_slip(teacher_id, trip_id, student["id"], g_a["id"])

    chap = create_cleared_chaperone(teacher_id, trip_id)

    vehicle = create_vehicle(label="Lock Bus", seat_capacity=40)
    booking = create_confirmed_booking(teacher_id, trip_id, vehicle["id"], seat_count)

    return {
        "teacher_id": teacher_id,
        "trip": trip,
        "trip_id": trip_id,
        "guardian_a": g_a,
        "student": student,
        "slip": slip,
        "chaperone": chap,
        "vehicle": vehicle,
        "booking": booking,
    }


def setup_three_signed_slips_locked_ready(transport_cost_cents=10_000, base_fee_cents=1000,
                                          deposit_cents=0, grade_band="MIDDLE"):
    """Build an APPROVED trip with three SIGNED slips signed in order a<b<c, one
    CLEARED chaperone, and a CONFIRMED 3-seat booking — ready to lock.

    Returns a dict with teacher_id, trip_id, slip ids (a/b/c), guardian ids, and
    the vehicle. The transport-cost split across 3 confirmed slips is the
    canonical 10000/3 waterfall.
    """
    teacher_id, trip = create_approved_trip(
        grade_band=grade_band,
        capacity=5,
        base_fee_cents=base_fee_cents,
        transport_cost_cents=transport_cost_cents,
        deposit_cents=deposit_cents,
    )
    trip_id = trip["id"]

    g_a = create_guardian(full_name="GA")
    g_b = create_guardian(full_name="GB")
    g_c = create_guardian(full_name="GC")
    st_a = create_student(teacher_id, full_name="SA", grade_level=7)
    st_b = create_student(teacher_id, full_name="SB", grade_level=7)
    st_c = create_student(teacher_id, full_name="SC", grade_level=7)

    slip_a = create_signed_slip(teacher_id, trip_id, st_a["id"], g_a["id"])
    slip_b = create_signed_slip(teacher_id, trip_id, st_b["id"], g_b["id"])
    slip_c = create_signed_slip(teacher_id, trip_id, st_c["id"], g_c["id"])

    chap = create_cleared_chaperone(teacher_id, trip_id)

    vehicle = create_vehicle(label="Tri Bus", seat_capacity=40)
    booking = create_confirmed_booking(teacher_id, trip_id, vehicle["id"], 3)

    return {
        "teacher_id": teacher_id,
        "trip_id": trip_id,
        "guardian_a": g_a["id"],
        "guardian_b": g_b["id"],
        "guardian_c": g_c["id"],
        "slip_a": slip_a,
        "slip_b": slip_b,
        "slip_c": slip_c,
        "chaperone": chap,
        "vehicle": vehicle,
        "booking": booking,
    }


def setup_signed_slips_count(count, grade_band="MIDDLE", capacity=20, special_needs_first=False,
                             has_water_activity=None):
    """Build an APPROVED trip with `count` SIGNED slips. If special_needs_first is
    True, the first signed slip is for a special_needs student.

    Returns a dict with teacher_id, trip_id, and the list of signed slips.
    """
    overrides = {"grade_band": grade_band, "capacity": capacity,
                 "base_fee_cents": 0, "transport_cost_cents": 0}
    if has_water_activity is not None:
        overrides["has_water_activity"] = has_water_activity
    teacher_id, trip = create_approved_trip(**overrides)
    trip_id = trip["id"]

    slips = []
    for i in range(count):
        g = create_guardian(full_name=f"G{i}")
        sn = special_needs_first and i == 0
        st = create_student(teacher_id, full_name=f"S{i}", grade_level=3,
                            special_needs=(True if sn else None))
        slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        slips.append({"slip": slip, "guardian_id": g["id"], "student_id": st["id"]})

    return {"teacher_id": teacher_id, "trip_id": trip_id, "slips": slips}


# ─── Tier 4: Paid-slip scenarios for refund tests ─────────────────────────────
def setup_approved_trip_with_paid_slip(base_fee_cents=1000, transport_cost_cents=0,
                                       deposit_cents=0):
    """Build an APPROVED trip with ONE slip SIGNED then PAID at its provisional fee.

    With a single signed slip the provisional transport_share is
    ceil(transport_cost_cents / 1); fee_due = base_fee + transport_share. Returns a
    dict with teacher_id, trip_id, guardian_a, slip, and the fee that was paid.
    """
    teacher_id, trip = create_approved_trip(
        capacity=5, base_fee_cents=base_fee_cents,
        transport_cost_cents=transport_cost_cents, deposit_cents=deposit_cents,
    )
    trip_id = trip["id"]
    g_a = create_guardian(full_name="Payer")
    st_a = create_student(teacher_id, full_name="Payee", grade_level=4)
    slip = create_signed_slip(teacher_id, trip_id, st_a["id"], g_a["id"])
    # Read back the live fee and pay exactly that.
    slip = get_success_data(api_client.get_permission_slip(slip["id"], make_teacher_headers(teacher_id)))
    fee = slip["fee_due_cents"]
    pay_slip(g_a["id"], trip_id, slip["id"], fee)
    slip = get_success_data(api_client.get_permission_slip(slip["id"], make_teacher_headers(teacher_id)))
    return {
        "teacher_id": teacher_id,
        "trip_id": trip_id,
        "guardian_a": g_a["id"],
        "slip": slip,
        "paid_fee_cents": fee,
        "vehicle": None,
    }


# ─── Tier 5: Full lifecycle to COMPLETED ──────────────────────────────────────
def setup_completed_trip():
    """Drive a trip all the way to COMPLETED: lock → start → RETURN headcount →
    complete. Returns a dict bundle including the completed trip and slip id.
    """
    bundle = setup_lockable_trip(seat_count=1, capacity=5, grade_band="HIGH",
                                 base_fee_cents=0, transport_cost_cents=0)
    teacher_id = bundle["teacher_id"]
    trip_id = bundle["trip_id"]
    slip_id = bundle["slip"]["id"]

    version = get_trip_version(teacher_id, trip_id)
    lock_roster(teacher_id, trip_id, version)
    get_success_data(api_client.start_trip(trip_id, make_teacher_headers(teacher_id)))
    get_success_data(
        api_client.create_attendance(
            trip_id, create_attendance_payload(slip_id, "RETURN", True),
            make_teacher_headers(teacher_id),
        )
    )
    completed = get_success_data(api_client.complete_trip(trip_id, make_teacher_headers(teacher_id)))
    bundle["completed_trip"] = completed
    return bundle


def setup_in_progress_trip_no_return_headcount():
    """Drive a trip to IN_PROGRESS with one CONFIRMED slip and NO return
    attendance recorded. Returns the lockable bundle plus the trip_id."""
    bundle = setup_lockable_trip(seat_count=1, capacity=5, grade_band="HIGH",
                                 base_fee_cents=0, transport_cost_cents=0)
    teacher_id = bundle["teacher_id"]
    trip_id = bundle["trip_id"]
    version = get_trip_version(teacher_id, trip_id)
    lock_roster(teacher_id, trip_id, version)
    get_success_data(api_client.start_trip(trip_id, make_teacher_headers(teacher_id)))
    return bundle
