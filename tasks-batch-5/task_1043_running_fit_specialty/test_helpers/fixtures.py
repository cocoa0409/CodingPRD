"""Composite setup helpers.

Every test starts against a fresh, empty database (the harness restarts the
server before each test). All helpers therefore build their preconditions from
scratch using only PRD-declared endpoints, and use the lenient get_success_data
validator so setup problems surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_staff_headers,
)
from . import factories as f

SM = TEST_USERS["store_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso="2026-07-01T00:00:00Z"):
    return get_success_data(api.set_clock(iso, SM))


# --------------------------------------------------------------------------
# Tier 1: single-entity builders
# --------------------------------------------------------------------------
def new_member(api, **overrides) -> dict:
    """Register a member (version 1, BRONZE, no subscription). Returns Member."""
    return get_success_data(api.create_member(f.create_member_payload(**overrides), ANON))


def new_store(api, session_room_count=1, **overrides) -> dict:
    return get_success_data(
        api.create_store(f.create_store_payload(session_room_count=session_room_count, **overrides), SM)
    )


def new_staff(api, store_id, role_type="BOTH", **overrides) -> dict:
    return get_success_data(
        api.create_staff(f.create_staff_payload(store_id, role_type=role_type, **overrides), SM)
    )


def new_product(api, **overrides) -> dict:
    return get_success_data(api.create_product(f.create_product_payload(**overrides), SM))


def new_event(api, **overrides) -> dict:
    return get_success_data(api.create_event(f.create_event_payload(**overrides), SM))


# --------------------------------------------------------------------------
# Tier 2/3: subscriptions
# --------------------------------------------------------------------------
def new_subscription(api, member_id, member_version, tier="CLUB_BASIC") -> dict:
    """Create a PENDING subscription for the member (advances Member.version)."""
    hdr = make_member_headers(member_id)
    return get_success_data(
        api.create_subscription(member_id, f.create_subscription_payload(member_version, tier=tier), hdr)
    )


def create_active_subscription(api, tier="CLUB_PRO"):
    """Register a member and create + activate a subscription of the given tier.

    Returns (member, subscription) both freshly fetched. member reflects
    version after the subscription create (== 2)."""
    member = new_member(api)
    hdr = make_member_headers(member["id"])
    sub = new_subscription(api, member["id"], member["version"], tier=tier)
    sub = get_success_data(api.activate_subscription(sub["id"], hdr))
    member = get_success_data(api.get_member(member["id"], SM))
    return member, sub


# --------------------------------------------------------------------------
# Tier 2/3: orders
# --------------------------------------------------------------------------
def new_cart_order(api, member_id) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.create_order(f.create_order_payload(member_id), hdr))


def add_line(api, order_id, member_id, product_id, qty=1) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.add_order_line(order_id, f.order_line_payload(product_id, qty), hdr))


def new_placed_order(api, member_id, product_id, qty=1) -> dict:
    """CART order with one line -> PLACED. Returns the placed Order."""
    hdr = make_member_headers(member_id)
    order = new_cart_order(api, member_id)
    add_line(api, order["id"], member_id, product_id, qty)
    return get_success_data(api.place_order(order["id"], hdr))


def new_fulfilled_order(api, member_id, product_id, staff_id, qty=1) -> dict:
    """CART -> PLACED -> FULFILLED. Returns the fulfilled Order."""
    order = new_placed_order(api, member_id, product_id, qty)
    return get_success_data(api.fulfill_order(order["id"], make_staff_headers(staff_id)))


# --------------------------------------------------------------------------
# Tier 3: fitting appointments
# --------------------------------------------------------------------------
def new_appointment(api, member_id, fitter_id, **overrides) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(
        api.create_appointment(f.create_appointment_payload(member_id, fitter_id, **overrides), hdr)
    )


def complete_appointment(api, appointment_id, fitter_id, gait_result=None) -> dict:
    return get_success_data(
        api.complete_appointment(appointment_id, f.complete_payload(gait_result), make_staff_headers(fitter_id))
    )


# --------------------------------------------------------------------------
# Tier 3: training sessions + enrollments
# --------------------------------------------------------------------------
def new_session(api, coach_id, store_id, **overrides) -> dict:
    return get_success_data(api.create_session(f.create_session_payload(coach_id, store_id, **overrides), SM))


def enroll(api, session_id, member_id) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.create_enrollment(session_id, f.create_enrollment_payload(member_id), hdr))


# --------------------------------------------------------------------------
# Tier 3: race registrations
# --------------------------------------------------------------------------
def register_for_event(api, event_id, member_id) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.create_registration(event_id, f.create_registration_payload(member_id), hdr))


def pay_registration(api, registration_id, member_id) -> dict:
    return get_success_data(api.pay_registration(registration_id, make_member_headers(member_id)))


def allocate_registration(api, registration_id, staff_id) -> dict:
    return get_success_data(api.allocate_registration(registration_id, make_staff_headers(staff_id)))


# --------------------------------------------------------------------------
# Tier 3: shoe pairs
# --------------------------------------------------------------------------
def new_shoe_pair(api, member_id, product_id) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.create_shoe_pair(f.create_shoe_pair_payload(member_id, product_id), hdr))


def log_run(api, shoe_pair_id, member_id, distance_km, **overrides) -> dict:
    hdr = make_member_headers(member_id)
    return get_success_data(api.add_run_log(shoe_pair_id, f.run_log_payload(distance_km, **overrides), hdr))


# --------------------------------------------------------------------------
# Fresh-read convenience (all reads use StoreManager, permitted on every GET)
# --------------------------------------------------------------------------
def get_member(api, member_id) -> dict:
    return get_success_data(api.get_member(member_id, SM))


def get_order(api, order_id) -> dict:
    return get_success_data(api.get_order(order_id, SM))


def get_product(api, product_id) -> dict:
    return get_success_data(api.get_product(product_id, SM))


def get_event(api, event_id) -> dict:
    return get_success_data(api.get_event(event_id, SM))


def get_registration(api, registration_id) -> dict:
    return get_success_data(api.get_registration(registration_id, SM))


def get_subscription(api, subscription_id) -> dict:
    return get_success_data(api.get_subscription(subscription_id, SM))


def get_session(api, session_id) -> dict:
    return get_success_data(api.get_session(session_id, SM))


def get_enrollment(api, enrollment_id) -> dict:
    return get_success_data(api.get_enrollment(enrollment_id, SM))


def get_appointment(api, appointment_id) -> dict:
    return get_success_data(api.get_appointment(appointment_id, SM))


def get_shoe_pair(api, shoe_pair_id) -> dict:
    return get_success_data(api.get_shoe_pair(shoe_pair_id, SM))
