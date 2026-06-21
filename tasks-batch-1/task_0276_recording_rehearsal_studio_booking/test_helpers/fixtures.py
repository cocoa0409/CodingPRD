"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the booking to be in a specific (schedule_status,
settlement_status) state that takes 5-15 API calls to reach. These helpers encapsulate
those preambles so tests focus on assertions.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup step failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1): Client and Engineer are entity-backed. Any ownership-gated
call uses make_client_headers(client_id) / make_engineer_headers(engineer_id) with the real
entity id, never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_studio_payload,
    create_room_payload,
    create_engineer_payload,
    create_gear_item_payload,
    register_client_payload,
    create_booking_payload,
    create_payment_payload,
    create_gear_rental_payload,
    create_engineer_assignment_payload,
    create_lockout_contract_payload,
    check_out_payload,
    delivery_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_engineer_headers,
)
from .constants import BASE_CLOCK

SM = TEST_USERS["studio_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Clock control ────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server wall clock (PRD §2.11)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, SM))


# ─── Tier 1/2: Base studio + inventory builders ───────
def setup_studio(clock=BASE_CLOCK, **studio_overrides):
    """Set clock and bootstrap a studio. Returns the studio dict."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.create_studio(create_studio_payload(**studio_overrides), SM))


def setup_room(studio_id, **overrides):
    return get_success_data(api_client.create_room(create_room_payload(studio_id, **overrides), SM))


def setup_engineer(studio_id, **overrides):
    return get_success_data(api_client.create_engineer(create_engineer_payload(studio_id, **overrides), SM))


def setup_gear_item(studio_id, **overrides):
    return get_success_data(api_client.create_gear_item(create_gear_item_payload(studio_id, **overrides), SM))


def setup_client(studio_id, **overrides):
    return get_success_data(api_client.register_client(register_client_payload(studio_id, **overrides), ANON))


def setup_studio_room_client(clock=BASE_CLOCK, studio_overrides=None, room_overrides=None, client_overrides=None):
    """Common base: clock + studio + room + client. Returns (studio, room, client)."""
    studio = setup_studio(clock=clock, **(studio_overrides or {}))
    room = setup_room(studio["id"], **(room_overrides or {}))
    client = setup_client(studio["id"], **(client_overrides or {}))
    return studio, room, client


# ─── Tier 3: Booking lifecycle shortcuts ──────────────
def create_booking(studio, room, client, **booking_overrides):
    """Create a HELD booking owned by `client`. Returns the booking dict."""
    headers = make_client_headers(client["id"])
    payload = create_booking_payload(studio["id"], room["id"], client["id"], **booking_overrides)
    return get_success_data(api_client.create_booking(payload, headers))


def pay_deposit(booking, client, amount_cents=None):
    """Pay the exact deposit for a HELD booking. Returns the payment dict."""
    headers = make_client_headers(client["id"])
    amt = amount_cents if amount_cents is not None else booking["deposit_due_cents"]
    return get_success_data(
        api_client.create_payment(booking["id"], create_payment_payload("DEPOSIT", amt), headers)
    )


def confirm(booking):
    """Confirm a deposit-paid HELD booking (StudioManager). Returns updated booking."""
    return get_success_data(api_client.confirm_booking(booking["id"], SM))


def check_in(booking):
    return get_success_data(api_client.check_in_booking(booking["id"], SM))


def check_out(booking, actual_end_at):
    return get_success_data(
        api_client.check_out_booking(booking["id"], check_out_payload(actual_end_at), SM)
    )


def create_confirmed_booking(studio, room, client, deposit_cents=None, **booking_overrides):
    """HELD -> deposit paid -> CONFIRMED. Returns the confirmed booking dict."""
    booking = create_booking(studio, room, client, **booking_overrides)
    pay_deposit(booking, client, deposit_cents)
    return confirm(booking)


def create_in_session_booking(studio, room, client, deposit_cents=None,
                              session_start_clock=None, **booking_overrides):
    """HELD -> deposit -> CONFIRMED -> check-in (IN_SESSION). Returns the booking dict.

    session_start_clock advances the clock to at/after start_at so check-in is allowed.
    """
    booking = create_confirmed_booking(studio, room, client, deposit_cents, **booking_overrides)
    if session_start_clock is not None:
        set_clock(session_start_clock)
    return check_in(booking)


def create_completed_booking(studio, room, client, deposit_cents=None,
                            session_start_clock=None, actual_end_at=None, **booking_overrides):
    """Full schedule walk to COMPLETED (settlement BALANCE_DUE). Returns the checked-out booking."""
    booking = create_in_session_booking(
        studio, room, client, deposit_cents, session_start_clock, **booking_overrides
    )
    end = actual_end_at if actual_end_at is not None else booking["end_at"]
    return check_out(booking, end)


def pay_balance(booking, client, amount_cents):
    """Pay a balance on a BALANCE_DUE booking (Client, exact external residue)."""
    headers = make_client_headers(client["id"])
    return get_success_data(
        api_client.create_payment(booking["id"], create_payment_payload("BALANCE", amount_cents), headers)
    )


def create_settled_booking(studio, room, client, deposit_cents=None,
                          session_start_clock=None, actual_end_at=None, **booking_overrides):
    """Full walk to COMPLETED + SETTLED. Returns the settled booking dict.

    Balance is computed as the booking's remaining external residue (no wallet credit).
    """
    booking = create_completed_booking(
        studio, room, client, deposit_cents, session_start_clock, actual_end_at, **booking_overrides
    )
    residue = booking["total_charge_cents"] - booking["amount_paid_cents"]
    if residue > 0:
        pay_balance(booking, client, residue)
    return get_success_data(api_client.get_booking(booking["id"], SM))


# ─── Gear rentals ─────────────────────────────────────
def add_gear_rental(booking, gear_item, units, expected_version=None):
    """Add a gear rental to a booking (StudioManager). expected_version defaults to
    the booking's current version. Returns the gear-rental dict."""
    ver = expected_version if expected_version is not None else booking["version"]
    return get_success_data(
        api_client.create_gear_rental(
            booking["id"], create_gear_rental_payload(gear_item["id"], units, ver), SM
        )
    )


def fresh_booking_version(booking_id):
    """Re-read a booking and return its current version (for OCC token threading)."""
    bk = get_success_data(api_client.get_booking(booking_id, SM))
    return bk["version"]


# ─── Engineer assignments ─────────────────────────────
def assign_engineer(booking, engineer):
    """Assign an engineer to a booking (StudioManager). Returns the assignment dict."""
    return get_success_data(
        api_client.create_engineer_assignment(
            booking["id"], create_engineer_assignment_payload(engineer["id"]), SM
        )
    )


# ─── Session delivery ─────────────────────────────────
def deliver(booking, engineer, file_manifest=None):
    """Engineer delivers/re-delivers a session package. Returns the delivery dict."""
    headers = make_engineer_headers(engineer["id"])
    return get_success_data(
        api_client.deliver_session(booking["id"], delivery_payload(file_manifest), headers)
    )


def request_revision(booking, client):
    headers = make_client_headers(client["id"])
    return get_success_data(api_client.request_revision(booking["id"], headers))


def accept_delivery(booking, client):
    headers = make_client_headers(client["id"])
    return get_success_data(api_client.accept_delivery(booking["id"], headers))


# ─── Lockout contracts ────────────────────────────────
def create_lockout_contract(studio, room, client, **overrides):
    """Create a DRAFT lockout contract (StudioManager). Returns the contract dict."""
    return get_success_data(
        api_client.create_lockout_contract(
            create_lockout_contract_payload(studio["id"], room["id"], client["id"], **overrides), SM
        )
    )


def activate_lockout_contract(contract, expected_room_version):
    """Activate a DRAFT lockout (StudioManager). Returns the activated contract dict."""
    return get_success_data(
        api_client.activate_lockout_contract(
            contract["id"], {"expected_room_version": expected_room_version}, SM
        )
    )


def list_series_occurrences(contract_id):
    """List the occurrence bookings materialized for a contract.

    PRD §3.7/§3.8: activation materializes one anchor booking (is_series_anchor=true)
    plus one occurrence per masked weekday, "each occurrence pointing back to the anchor
    through its parent_series_id". So occurrences filter by parent_series_id == the
    anchor's id (not the contract's id). Resolve the anchor first from the contract's
    room/client, then list its occurrences.
    """
    contract = get_success_data(api_client.get_lockout_contract(contract_id, SM))
    room_bookings, _ = _paginate(
        api_client.list_bookings(SM, params={"room_id": contract["room_id"]})
    )
    anchors = [
        b for b in room_bookings
        if b.get("is_series_anchor") and b.get("client_id") == contract["client_id"]
    ]
    if not anchors:
        return []
    anchor_id = anchors[0]["id"]
    data, _ = _paginate(
        api_client.list_bookings(SM, params={"parent_series_id": anchor_id})
    )
    return data


# ─── Read helpers ─────────────────────────────────────
def _paginate(response):
    body = response.json()
    return body["data"], body["meta"]


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, SM))


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, SM))


def get_room(room_id):
    return get_success_data(api_client.get_room(room_id, SM))


def get_engineer_assignment(assign_id):
    return get_success_data(api_client.get_engineer_assignment(assign_id, SM))


def get_gear_rental(rental_id):
    return get_success_data(api_client.get_gear_rental(rental_id, SM))


def list_booking_payments(booking_id):
    data, _ = _paginate(api_client.list_booking_payments(booking_id, SM))
    return data


def list_overtime_records(booking_id):
    data, _ = _paginate(api_client.list_booking_overtime_records(booking_id, SM))
    return data


def list_booking_delivery(booking_id):
    data, _ = _paginate(api_client.list_booking_delivery(booking_id, SM))
    return data


def find_refund_payment(booking_id):
    """Return the single REFUND payment for a booking, or None."""
    refunds = [p for p in list_booking_payments(booking_id) if p["kind"] == "REFUND"]
    return refunds[0] if refunds else None
