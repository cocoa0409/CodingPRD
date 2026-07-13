"""Composite setup helpers for the Boat Club API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server against an empty database before each
test). Setup calls use the lenient ``get_success_data`` validator so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading: the Member role is entity-backed, so every ownership-gated
Member call threads ``make_member_headers(member_id)`` — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from . import factories as f

ADMIN = TEST_USERS["club_admin_headers"]
STAFF = TEST_USERS["dock_staff_headers"]

# Certification session windows (independent of the logical clock).
_ORIENTATION_WINDOW = ("2026-05-02T09:00:00Z", "2026-05-02T11:00:00Z")
_BASIC_WINDOW = ("2026-05-02T12:00:00Z", "2026-05-02T14:00:00Z")
_ADVANCED_WINDOW = ("2026-05-02T15:00:00Z", "2026-05-02T17:00:00Z")


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------- #
# Single-entity builders
# --------------------------------------------------------------------------- #
def make_tier(tier_code: str = "SAIL", **overrides) -> dict:
    return get_success_data(api_client.create_tier(f.create_tier_payload(tier_code, **overrides), ADMIN))


def make_dock(**overrides) -> dict:
    return get_success_data(api_client.create_dock(f.create_dock_payload(**overrides), ADMIN))


def make_boat(dock_id: str, boat_type: str = "PONTOON") -> dict:
    return get_success_data(api_client.create_boat(f.create_boat_payload(dock_id, boat_type), ADMIN))


def make_member(membership_tier: str, home_dock_id: str, full_name: str = "A", email: str = "a@x.com") -> dict:
    return get_success_data(
        api_client.create_member(
            f.create_member_payload(membership_tier, home_dock_id, full_name, email), ADMIN
        )
    )


def make_session(dock_id: str, session_type: str, window, capacity: int = 5) -> dict:
    return get_success_data(
        api_client.create_training_session(
            f.create_training_session_payload(dock_id, session_type, window[0], window[1], capacity=capacity),
            ADMIN,
        )
    )


def enroll(member_id: str, session_id: str) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            f.create_enrollment_payload(member_id, session_id), make_member_headers(member_id)
        )
    )


def mark_attendance(enrollment_id: str, attended: bool) -> dict:
    return get_success_data(api_client.mark_attendance(enrollment_id, {"attended": attended}, STAFF))


# --------------------------------------------------------------------------- #
# Certification ladder
# --------------------------------------------------------------------------- #
def certify_orientation(member_id: str, dock_id: str):
    """Attend an ORIENTATION session: member becomes ACTIVE, orientation_completed=true."""
    session = make_session(dock_id, "ORIENTATION", _ORIENTATION_WINDOW)
    enr = enroll(member_id, session["id"])
    mark_attendance(enr["id"], True)


def certify_basic(member_id: str, dock_id: str):
    """Attend a BASIC_CERT session (orientation must already be complete): grants BASIC."""
    session = make_session(dock_id, "BASIC_CERT", _BASIC_WINDOW)
    enr = enroll(member_id, session["id"])
    mark_attendance(enr["id"], True)


def certify_advanced(member_id: str, dock_id: str):
    """Attend an ADVANCED_CERT session (BASIC must already be held): grants ADVANCED."""
    session = make_session(dock_id, "ADVANCED_CERT", _ADVANCED_WINDOW)
    enr = enroll(member_id, session["id"])
    mark_attendance(enr["id"], True)


# --------------------------------------------------------------------------- #
# Composite: an ACTIVE, BASIC-certified member at a home dock with boats
# --------------------------------------------------------------------------- #
def setup_active_basic_member(
    tier_code: str = "SAIL",
    tier_overrides: dict = None,
    boats=("PONTOON",),
    dock_is_reciprocal: bool = False,
    full_name: str = "A",
    email: str = "a@x.com",
) -> dict:
    """Create tier + home dock + boats + a member advanced to ACTIVE/BASIC.

    Returns a dict with: tier, dock_id, boat_ids (list), member_id, member.
    """
    tier = make_tier(tier_code, **(tier_overrides or {}))
    dock = make_dock(is_reciprocal=dock_is_reciprocal)
    boat_ids = [make_boat(dock["id"], bt)["id"] for bt in boats]
    member = make_member(tier_code, dock["id"], full_name, email)
    certify_orientation(member["id"], dock["id"])
    certify_basic(member["id"], dock["id"])
    member = get_member(member["id"])
    return {
        "tier": tier,
        "dock_id": dock["id"],
        "boat_ids": boat_ids,
        "member_id": member["id"],
        "member": member,
    }


# --------------------------------------------------------------------------- #
# Reservation lifecycle convenience
# --------------------------------------------------------------------------- #
def request_reservation(member_id, dock_id, boat_type, start_time, end_time) -> dict:
    return get_success_data(
        api_client.create_reservation(
            f.create_reservation_payload(member_id, dock_id, boat_type, start_time, end_time),
            make_member_headers(member_id),
        )
    )


def confirm_reservation(member_id, reservation_id) -> dict:
    return get_success_data(api_client.confirm_reservation(reservation_id, make_member_headers(member_id)))


def checkout_reservation(member_id, reservation_id, fuel_at_checkout) -> dict:
    return get_success_data(
        api_client.checkout_reservation(
            reservation_id, {"fuel_at_checkout": fuel_at_checkout}, make_member_headers(member_id)
        )
    )


def return_reservation(member_id, reservation_id, fuel_at_return, cleaning_state=None) -> dict:
    payload = {"fuel_at_return": fuel_at_return}
    if cleaning_state is not None:
        payload["cleaning_state"] = cleaning_state
    return get_success_data(
        api_client.return_reservation(reservation_id, payload, make_member_headers(member_id))
    )


def create_confirmed_reservation(member_id, dock_id, boat_type, start_time, end_time) -> dict:
    """Request then confirm a reservation; returns the CONFIRMED reservation."""
    r = request_reservation(member_id, dock_id, boat_type, start_time, end_time)
    return confirm_reservation(member_id, r["id"])


# --------------------------------------------------------------------------- #
# Damage report / fee helpers
# --------------------------------------------------------------------------- #
def file_damage_report(reservation_id, boat_id, severity, repair_cost_cents) -> dict:
    return get_success_data(
        api_client.create_damage_report(
            f.create_damage_report_payload(reservation_id, boat_id, severity, repair_cost_cents), STAFF
        )
    )


def assess_damage_report(report_id) -> dict:
    return get_success_data(api_client.assess_damage_report(report_id, STAFF))


def assessed_damage_fee(reservation_id, boat_id, severity, repair_cost_cents) -> dict:
    """File and assess a damage report; returns the assessed DamageReport."""
    dr = file_damage_report(reservation_id, boat_id, severity, repair_cost_cents)
    return assess_damage_report(dr["id"])


def find_fees(member_id=None, fee_type=None, reservation_id=None, status=None) -> list:
    params = {}
    if member_id is not None:
        params["member_id"] = member_id
    if fee_type is not None:
        params["fee_type"] = fee_type
    if reservation_id is not None:
        params["reservation_id"] = reservation_id
    if status is not None:
        params["status"] = status
    data, _meta = _paginated(api_client.list_fees(ADMIN, params=params))
    return data


# --------------------------------------------------------------------------- #
# Dues invoice helpers
# --------------------------------------------------------------------------- #
def issue_dues_invoice(member_id, period_start, period_end, expected_member_version) -> dict:
    return get_success_data(
        api_client.create_dues_invoice(
            member_id,
            f.create_dues_invoice_payload(period_start, period_end, expected_member_version),
            ADMIN,
        )
    )


def pay_dues_invoice(member_id, invoice_id) -> dict:
    return get_success_data(api_client.pay_dues_invoice(invoice_id, make_member_headers(member_id)))


# --------------------------------------------------------------------------- #
# Read helpers
# --------------------------------------------------------------------------- #
def get_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def get_member_version(member_id) -> int:
    return get_member(member_id)["version"]


def get_boat(boat_id) -> dict:
    return get_success_data(api_client.get_boat(boat_id, ADMIN))


def get_reservation(reservation_id) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


def get_dues_invoice(invoice_id) -> dict:
    return get_success_data(api_client.get_dues_invoice(invoice_id, ADMIN))


def get_fee(fee_id) -> dict:
    return get_success_data(api_client.get_fee(fee_id, ADMIN))


def suspend_member(member_id):
    return get_success_data(api_client.suspend_member(member_id, {"reason": "for-cause"}, ADMIN))


def reinstate_member(member_id):
    return get_success_data(api_client.reinstate_member(member_id, ADMIN))


def run_sweep():
    return get_success_data(api_client.run_no_show_sweep(ADMIN))


def waive_fee(fee_id):
    return get_success_data(api_client.waive_fee(fee_id, STAFF))


# --------------------------------------------------------------------------- #
# Internal
# --------------------------------------------------------------------------- #
def _paginated(response):
    body = response.json()
    assert response.status_code == 200, f"list failed: {response.status_code} {response.text}"
    return body["data"], body["meta"]
