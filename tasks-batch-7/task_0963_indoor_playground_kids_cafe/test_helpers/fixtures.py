"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints. Setup calls use get_success_data() (lenient)
so failures surface as clear setup errors rather than confusing assertions.

Identity threading: Guardian/FrontDesk/CafeStaff/Manager are entity-backed
roles, so every ownership- or staff-gated call uses a per-instance header
built from the real entity id — never a shared placeholder.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_membership_plan_payload, create_guardian_payload, create_child_payload,
    create_waiver_payload, create_session_slot_payload, create_visit_payload,
    create_party_room_payload, create_party_package_payload,
    create_party_booking_payload, create_cafe_menu_item_payload,
    create_cafe_order_payload, order_line, create_staff_member_payload,
    create_sanitation_task_payload, create_incident_payload,
    create_loyalty_adjustment_payload,
)
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS, make_guardian_headers, make_front_desk_headers,
    make_cafe_staff_headers, make_manager_headers,
)

_STAFF_ROLE_TO_HEADER_ROLE = {
    "FRONT_DESK": "FrontDesk",
    "CAFE_STAFF": "CafeStaff",
    "MANAGER": "Manager",
}


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (Admin-only, PRD §2.4)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["admin_headers"]))


def reset_clock():
    """Set the logical clock to the canonical test start instant."""
    return set_clock(TEST_DEFAULTS["CLOCK_START"])


def run_ops_as_admin():
    return get_success_data(api_client.run_ops(TEST_USERS["admin_headers"]))


# ─── Staff ────────────────────────────────────────────

def make_staff(role: str, full_name: str = "Staff Member") -> dict:
    """Create an ACTIVE StaffMember with the given role (Admin-only)."""
    return get_success_data(api_client.create_staff_member(
        create_staff_member_payload(full_name=full_name, role=role),
        TEST_USERS["admin_headers"]))


def staff_headers(staff: dict) -> dict:
    """Build the acting headers for a StaffMember, role-matched per PRD §2.1."""
    header_role = _STAFF_ROLE_TO_HEADER_ROLE[staff["role"]]
    if header_role == "FrontDesk":
        return make_front_desk_headers(staff["id"])
    if header_role == "CafeStaff":
        return make_cafe_staff_headers(staff["id"])
    return make_manager_headers(staff["id"])


def setup_staff_trio() -> dict:
    """One ACTIVE staff member per staff role, with acting headers."""
    fd = make_staff("FRONT_DESK", "FD One")
    mgr = make_staff("MANAGER", "Mgr One")
    cafe = make_staff("CAFE_STAFF", "Cafe One")
    return {
        "fd": fd, "mgr": mgr, "cafe": cafe,
        "fd_headers": staff_headers(fd),
        "mgr_headers": staff_headers(mgr),
        "cafe_headers": staff_headers(cafe),
    }


# ─── Guardians / children / waivers / membership ──────

def register_guardian(full_name="Test Guardian", email="g@x.com", phone="111") -> dict:
    """Self-register a guardian (Anonymous). Returns the Guardian."""
    return get_success_data(api_client.create_guardian(
        create_guardian_payload(full_name=full_name, email=email, phone=phone),
        TEST_USERS["anonymous_headers"]))


def guardian_headers(guardian: dict) -> dict:
    return make_guardian_headers(guardian["id"])


def get_guardian_fresh(guardian_id: str, headers: dict) -> dict:
    return get_success_data(api_client.get_guardian(guardian_id, headers))


def create_plus_plan(**overrides) -> dict:
    """The standard membership plan used across tests (8 credits, 10% discounts,
    socks included)."""
    return get_success_data(api_client.create_membership_plan(
        create_membership_plan_payload(**overrides), TEST_USERS["admin_headers"]))


def enroll_guardian(guardian: dict, plan_id: str) -> dict:
    """Enroll the guardian in a plan (own act). Returns updated Guardian."""
    return get_success_data(api_client.enroll_membership(
        guardian["id"], {"membership_plan_id": plan_id}, guardian_headers(guardian)))


def sign_waiver(guardian: dict) -> dict:
    """Sign a waiver for the guardian, reading the current guardian version
    first so the OCC field is fresh. Returns the Waiver."""
    g = get_guardian_fresh(guardian["id"], guardian_headers(guardian))
    return get_success_data(api_client.create_waiver(
        guardian["id"], create_waiver_payload(g["version"]),
        guardian_headers(guardian)))


def add_child(guardian: dict, full_name="Kid", birth_date="2020-01-15",
              allergies=None) -> dict:
    payload = create_child_payload(full_name=full_name, birth_date=birth_date)
    if allergies is not None:
        payload["allergies"] = allergies
    return get_success_data(api_client.create_child(
        guardian["id"], payload, guardian_headers(guardian)))


def setup_guardian_with_child_and_waiver(email="g@x.com", full_name="Test Guardian",
                                         child_birth_date="2020-01-15",
                                         child_allergies=None,
                                         plan: dict = None) -> dict:
    """Guardian (+ optional plan enrollment) + signed waiver + one child."""
    guardian = register_guardian(full_name=full_name, email=email)
    if plan is not None:
        guardian = enroll_guardian(guardian, plan["id"])
    waiver = sign_waiver(guardian)
    child = add_child(guardian, birth_date=child_birth_date,
                      allergies=child_allergies)
    return {"guardian": guardian, "child": child, "waiver": waiver,
            "g_headers": guardian_headers(guardian)}


# ─── Session slots ────────────────────────────────────

def create_slot(mgr_headers: dict, slot_date=None, start_at=None, end_at=None,
                capacity=10) -> dict:
    payload = create_session_slot_payload(
        slot_date=slot_date or TEST_DEFAULTS["SLOT_DATE"],
        start_at=start_at or TEST_DEFAULTS["SLOT_START"],
        end_at=end_at or TEST_DEFAULTS["SLOT_END"],
        capacity=capacity)
    return get_success_data(api_client.create_session_slot(payload, mgr_headers))


def create_open_slot(mgr_headers: dict, **kwargs) -> dict:
    """Create a slot and open it for admissions. Returns the OPEN slot."""
    slot = create_slot(mgr_headers, **kwargs)
    return get_success_data(api_client.open_session_slot(slot["id"], mgr_headers))


def get_slot_fresh(slot_id: str, headers: dict) -> dict:
    return get_success_data(api_client.get_session_slot(slot_id, headers))


# ─── Visits ───────────────────────────────────────────

def create_reservation(guardian: dict, slot: dict, child: dict,
                       booked_duration_minutes: int = 60,
                       use_credit: bool = False) -> dict:
    payload = create_visit_payload(
        slot["id"], child["id"], guardian["id"],
        booked_duration_minutes=booked_duration_minutes)
    if use_credit:
        payload["use_credit"] = True
    return get_success_data(api_client.create_visit(payload, guardian_headers(guardian)))


def setup_reserved_visit(plan: dict = None, capacity: int = 10,
                         booked_duration_minutes: int = 60,
                         use_credit: bool = False,
                         email="visit-guardian@x.com",
                         slot_date=None, start_at=None, end_at=None) -> dict:
    """Full chain: staff trio + OPEN slot + guardian (optionally enrolled)
    + waiver + child + one RESERVED visit. Clock left at CLOCK_START."""
    reset_clock()
    staff = setup_staff_trio()
    slot = create_open_slot(staff["mgr_headers"], capacity=capacity,
                            slot_date=slot_date, start_at=start_at, end_at=end_at)
    ctx = setup_guardian_with_child_and_waiver(email=email, plan=plan)
    visit = create_reservation(ctx["guardian"], slot, ctx["child"],
                               booked_duration_minutes=booked_duration_minutes,
                               use_credit=use_credit)
    return {**staff, **ctx, "slot": slot, "visit": visit}


def check_in_visit(visit: dict, staff_hdrs: dict, sock_method="OWN_GRIP_SOCKS",
                   grip_socks_order_id=None) -> dict:
    payload = {"sock_method": sock_method}
    if grip_socks_order_id is not None:
        payload["grip_socks_order_id"] = grip_socks_order_id
    return get_success_data(api_client.check_in_visit(visit["id"], payload, staff_hdrs))


def setup_checked_in_visit(plan: dict = None, checkin_clock: str = None,
                           sock_method="OWN_GRIP_SOCKS", **kwargs) -> dict:
    """A RESERVED visit walked through check-in at the given logical time."""
    ctx = setup_reserved_visit(plan=plan, **kwargs)
    set_clock(checkin_clock or TEST_DEFAULTS["CHECKIN_TIME"])
    visit = check_in_visit(ctx["visit"], ctx["fd_headers"], sock_method=sock_method)
    ctx["visit"] = visit
    return ctx


def get_visit_fresh(visit_id: str, headers: dict) -> dict:
    return get_success_data(api_client.get_visit(visit_id, headers))


# ─── Party inventory and bookings ─────────────────────

def create_std_package(**overrides) -> dict:
    return get_success_data(api_client.create_party_package(
        create_party_package_payload(**overrides), TEST_USERS["admin_headers"]))


def create_party_room(name="Room A", capacity_children=20) -> dict:
    return get_success_data(api_client.create_party_room(
        create_party_room_payload(name=name, capacity_children=capacity_children),
        TEST_USERS["admin_headers"]))


def current_room_version(room_id: str) -> int:
    room = get_success_data(
        api_client.get_party_room(room_id, TEST_USERS["anonymous_headers"]))
    return room["version"]


def book_party(guardian: dict, room: dict, package: dict,
               start_at=None, child_count: int = 10) -> dict:
    """Create a HELD party booking, reading the room's current version first
    (each created booking bumps the room version — OCC per PRD §2.7)."""
    payload = create_party_booking_payload(
        room["id"], package["id"], guardian["id"],
        expected_party_room_version=current_room_version(room["id"]),
        start_at=start_at or TEST_DEFAULTS["WEEKDAY_PARTY_START"],
        child_count=child_count)
    return get_success_data(
        api_client.create_party_booking(payload, guardian_headers(guardian)))


def setup_party_context(with_plan: bool = False, email="party-guardian@x.com",
                        package_overrides=None, room_capacity=20) -> dict:
    """STD package + ACTIVE room + guardian (optionally a PLUS member)."""
    reset_clock()
    plan = create_plus_plan() if with_plan else None
    package = create_std_package(**(package_overrides or {}))
    room = create_party_room(capacity_children=room_capacity)
    guardian = register_guardian(email=email)
    if plan is not None:
        guardian = enroll_guardian(guardian, plan["id"])
    return {"plan": plan, "package": package, "room": room, "guardian": guardian,
            "g_headers": guardian_headers(guardian)}


def setup_confirmed_booking(start_at=None, child_count: int = 10,
                            with_plan: bool = False,
                            email="party-guardian@x.com",
                            package_overrides=None) -> dict:
    """Party context + a HELD booking walked through confirm (CONFIRMED)."""
    ctx = setup_party_context(with_plan=with_plan, email=email,
                              package_overrides=package_overrides)
    booking = book_party(ctx["guardian"], ctx["room"], ctx["package"],
                         start_at=start_at, child_count=child_count)
    booking = get_success_data(
        api_client.confirm_party_booking(booking["id"], ctx["g_headers"]))
    ctx["booking"] = booking
    return ctx


# ─── Cafe ─────────────────────────────────────────────

def create_menu_item(name="Latte", price_cents=425, allergen_tags=None,
                     is_grip_socks=False) -> dict:
    payload = create_cafe_menu_item_payload(name=name, price_cents=price_cents)
    if allergen_tags is not None:
        payload["allergen_tags"] = allergen_tags
    if is_grip_socks:
        payload["is_grip_socks"] = True
    return get_success_data(
        api_client.create_cafe_menu_item(payload, TEST_USERS["admin_headers"]))


def place_order(guardian: dict, lines: list, child_ids=None,
                points_to_redeem: int = 0, visit_id=None,
                party_booking_id=None) -> dict:
    payload = create_cafe_order_payload(
        guardian["id"], lines, child_ids=child_ids if child_ids is not None else [])
    if points_to_redeem:
        payload["points_to_redeem"] = points_to_redeem
    if visit_id is not None:
        payload["visit_id"] = visit_id
    if party_booking_id is not None:
        payload["party_booking_id"] = party_booking_id
    return get_success_data(
        api_client.create_cafe_order(payload, guardian_headers(guardian)))


def serve_order(order: dict, cafe_hdrs: dict) -> dict:
    """PLACED -> PREPARING -> SERVED. Returns the SERVED order."""
    get_success_data(api_client.start_preparing_cafe_order(order["id"], cafe_hdrs))
    return get_success_data(api_client.serve_cafe_order(order["id"], cafe_hdrs))


def seed_points(guardian: dict, mgr_headers: dict, points: int,
                note="seed") -> dict:
    """Manager-posted manual ADJUSTMENT granting signed points."""
    return get_success_data(api_client.create_loyalty_adjustment(
        guardian["id"], create_loyalty_adjustment_payload(points, note),
        mgr_headers))


def setup_cafe_guardian(email="cafe-guardian@x.com", with_plan=False,
                        seed_point_amount=0) -> dict:
    """Cafe staff + manager + guardian (optional PLUS plan, optional seeded
    points) + the standard Latte menu item."""
    reset_clock()
    staff = setup_staff_trio()
    plan = create_plus_plan() if with_plan else None
    guardian = register_guardian(email=email)
    if plan is not None:
        guardian = enroll_guardian(guardian, plan["id"])
    if seed_point_amount:
        seed_points(guardian, staff["mgr_headers"], seed_point_amount)
    latte = create_menu_item("Latte", 425, allergen_tags=["MILK"])
    return {**staff, "plan": plan, "guardian": guardian,
            "g_headers": guardian_headers(guardian), "latte": latte}


# ─── Sanitation / incidents ───────────────────────────

def create_sanitation_task(mgr_headers: dict, room: dict, kind="BALL_PIT_WASH",
                           due_at="2026-06-02T00:00:00Z") -> dict:
    return get_success_data(api_client.create_sanitation_task(
        create_sanitation_task_payload(room["id"], kind=kind, due_at=due_at),
        mgr_headers))


def create_incident(staff_hdrs: dict, kind="INJURY", severity="LOW",
                    description="incident", visit_id=None) -> dict:
    payload = create_incident_payload(kind=kind, severity=severity,
                                      description=description)
    if visit_id is not None:
        payload["visit_id"] = visit_id
    return get_success_data(api_client.create_incident(payload, staff_hdrs))
