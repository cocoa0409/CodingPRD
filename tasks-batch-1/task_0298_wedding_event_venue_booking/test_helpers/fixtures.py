"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: Coordinator and Client are entity-backed roles. After a
fixture creates a Coordinator / Client, every ownership-gated call uses
make_coordinator_headers(coordinator_id) / make_client_headers(client_id) with
the real entity id — never the shared fallback constant.

The harness restarts the server (empty DB) before every test, so each fixture
builds its entire precondition state from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BASE_CLOCK_ISO,
    EVENT_DATE,
    CEREMONY_START,
    CEREMONY_END,
    RECEPTION_START,
    RECEPTION_END,
    STANDARD_DEPOSIT_CENTS,
)
from .factories import (
    create_venue_payload,
    create_space_payload,
    create_package_payload,
    create_coordinator_payload,
    create_client_payload,
    create_booking_payload,
    create_hold_payload,
    create_payment_payload,
    create_vendor_payload,
    create_coi_payload,
    create_guarantee_payload,
    create_reschedule_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_coordinator_headers,
    make_client_headers,
    make_finance_officer_headers,
)


VA = TEST_USERS["venue_admin_headers"]
FO = TEST_USERS["finance_officer_headers"]


def set_clock(iso: str = BASE_CLOCK_ISO):
    """Set the test-driving clock to the given UTC instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, VA))


# ───────────────────────── Tier 1 / Tier 2: base inventory ─────────────────────────

def create_inventory(
    cancellation_tier: str = "STANDARD",
    force_majeure_fee_pct: float = 0.0,
    space_overrides: dict = None,
    package_overrides: dict = None,
    coordinator_cap: int = 8,
    with_space: bool = True,
    with_coordinator: bool = True,
    clock_iso: str = BASE_CLOCK_ISO,
):
    """Build a venue with one space, one package, one coordinator, one client,
    and set the clock. Returns a dict of created ids (and the coordinator/client
    headers threaded to their real ids).
    """
    set_clock(clock_iso)
    venue = get_success_data(api_client.create_venue(
        create_venue_payload(
            name="Lakeside Manor",
            cancellation_tier=cancellation_tier,
            force_majeure_fee_pct=force_majeure_fee_pct,
        ), VA))
    out = {"venue_id": venue["id"], "venue": venue}

    if with_space:
        space = get_success_data(api_client.create_space(
            venue["id"], create_space_payload(**(space_overrides or {})), VA))
        out["space_id"] = space["id"]
        out["space"] = space

    package = get_success_data(api_client.create_package(
        venue["id"], create_package_payload(**(package_overrides or {})), VA))
    out["package_id"] = package["id"]
    out["package"] = package

    if with_coordinator:
        coordinator = get_success_data(api_client.create_coordinator(
            venue["id"], create_coordinator_payload(active_booking_cap=coordinator_cap), VA))
        out["coordinator_id"] = coordinator["id"]
        out["coordinator"] = coordinator
        out["coord_headers"] = make_coordinator_headers(coordinator["id"])

    client = get_success_data(api_client.create_client(
        create_client_payload(email=unique_email()), VA))
    out["client_id"] = client["id"]
    out["client"] = client
    out["client_headers"] = make_client_headers(client["id"])

    return out


def create_inquiry_booking(inv: dict, booking_overrides: dict = None, assign_coordinator: bool = True):
    """Create an INQUIRY booking under the given inventory; optionally assign the
    coordinator. Returns the booking dict (latest representation captured)."""
    client_headers = inv["client_headers"]
    booking = get_success_data(api_client.create_booking(
        create_booking_payload(
            inv["client_id"], inv["venue_id"], inv["package_id"],
            **(booking_overrides or {})),
        client_headers))
    if assign_coordinator and "coordinator_id" in inv:
        booking = get_success_data(api_client.assign_coordinator(
            booking["id"], {"coordinator_id": inv["coordinator_id"]}, inv["coord_headers"]))
    return booking


def add_both_holds(inv: dict, booking: dict, space_id: str = None):
    """Create a CEREMONY and a RECEPTION hold on the booking, threading the OCC
    version forward. Returns the booking dict refreshed after the two holds."""
    coord = inv["coord_headers"]
    sid = space_id or inv["space_id"]
    v = booking["version"]
    h1 = get_success_data(api_client.create_hold(
        booking["id"], create_hold_payload(sid, "CEREMONY", v), coord))
    # The booking version advanced by the hold create; refetch to thread it.
    bk = get_success_data(api_client.get_booking(booking["id"], coord))
    h2 = get_success_data(api_client.create_hold(
        booking["id"], create_hold_payload(sid, "RECEPTION", bk["version"]), coord))
    bk = get_success_data(api_client.get_booking(booking["id"], coord))
    return bk, h1, h2


def place_soft_hold(inv: dict, booking_id: str):
    """Transition the booking INQUIRY -> HELD."""
    return get_success_data(api_client.place_hold(booking_id, inv["coord_headers"]))


def pay_deposit(inv: dict, booking_id: str, amount_cents: int = STANDARD_DEPOSIT_CENTS, method: str = "ACH"):
    """Post an INBOUND deposit payment (FinanceOfficer)."""
    return get_success_data(api_client.post_payment(
        booking_id, create_payment_payload("INBOUND", amount_cents, method), FO))


def confirm(inv: dict, booking_id: str):
    """Transition the booking HELD -> CONFIRMED."""
    return get_success_data(api_client.confirm_booking(booking_id, inv["coord_headers"]))


# ───────────────────────── Tier 3: full-lifecycle shortcuts ─────────────────────────

def setup_held_booking(
    cancellation_tier: str = "STANDARD",
    force_majeure_fee_pct: float = 0.0,
    space_overrides: dict = None,
    package_overrides: dict = None,
    booking_overrides: dict = None,
):
    """Full chain to a HELD booking with both holds present and coordinator
    assigned (NO deposit paid). Returns (inv, booking)."""
    inv = create_inventory(
        cancellation_tier=cancellation_tier,
        force_majeure_fee_pct=force_majeure_fee_pct,
        space_overrides=space_overrides,
        package_overrides=package_overrides,
    )
    booking = create_inquiry_booking(inv, booking_overrides=booking_overrides)
    booking, _, _ = add_both_holds(inv, booking)
    booking = place_soft_hold(inv, booking["id"])
    return inv, booking


def setup_confirmed_booking(
    cancellation_tier: str = "STANDARD",
    force_majeure_fee_pct: float = 0.0,
    space_overrides: dict = None,
    package_overrides: dict = None,
    booking_overrides: dict = None,
    deposit_cents: int = STANDARD_DEPOSIT_CENTS,
):
    """Full chain to a CONFIRMED booking: inventory -> booking -> assign ->
    2 holds -> place-hold -> deposit paid -> confirm. Returns (inv, booking)
    where booking is the post-confirm representation (provisional charge present).
    """
    inv, booking = setup_held_booking(
        cancellation_tier=cancellation_tier,
        force_majeure_fee_pct=force_majeure_fee_pct,
        space_overrides=space_overrides,
        package_overrides=package_overrides,
        booking_overrides=booking_overrides,
    )
    pay_deposit(inv, booking["id"], amount_cents=deposit_cents)
    booking = confirm(inv, booking["id"])
    return inv, booking


def setup_confirmed_with_cleared_vendor(
    vendor_role: str = "FLORAL",
    coi_expires_on: str = "2026-12-31",
    cancellation_tier: str = "STANDARD",
    force_majeure_fee_pct: float = 0.0,
):
    """CONFIRMED booking with one CLEARED required-COI vendor. Returns
    (inv, booking, vendor)."""
    inv = create_inventory(
        cancellation_tier=cancellation_tier,
        force_majeure_fee_pct=force_majeure_fee_pct,
    )
    booking = create_inquiry_booking(inv)
    booking, _, _ = add_both_holds(inv, booking)
    # Add the vendor and clear it before placing the hold (order is immaterial to
    # the vendor; it only needs to exist on the booking).
    vendor = get_success_data(api_client.create_vendor(
        booking["id"], create_vendor_payload(vendor_role=vendor_role), inv["coord_headers"]))
    vendor = get_success_data(api_client.upload_coi(
        vendor["id"], create_coi_payload(coi_expires_on), inv["coord_headers"]))
    booking = place_soft_hold(inv, booking["id"])
    pay_deposit(inv, booking["id"])
    booking = confirm(inv, booking["id"])
    return inv, booking, vendor


def setup_guaranteed_booking(
    guaranteed_count: int = 150,
    cancellation_tier: str = "STANDARD",
    space_overrides: dict = None,
):
    """CONFIRMED booking carried through to GUARANTEED with the given count.
    Returns (inv, booking)."""
    inv, booking = setup_confirmed_booking(
        cancellation_tier=cancellation_tier,
        space_overrides=space_overrides,
    )
    booking = get_success_data(api_client.guarantee_booking(
        booking["id"], create_guarantee_payload(guaranteed_count), inv["coord_headers"]))
    return inv, booking


def get_milestones(inv: dict, booking_id: str):
    """Return the list of milestone dicts for a booking, sorted by sequence."""
    res = api_client.list_milestones(booking_id, inv["coord_headers"])
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("data", data)
    return sorted(rows, key=lambda m: m["sequence"])


def get_holds(inv: dict, booking_id: str):
    """Return the list of SpaceHold dicts for a booking."""
    res = api_client.list_holds_for_booking(booking_id, inv["coord_headers"])
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("data", data)


def get_payments(inv: dict, booking_id: str):
    """Return the list of Payment dicts for a booking."""
    res = api_client.list_payments(booking_id, inv["coord_headers"])
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("data", data)


def get_vendors(inv: dict, booking_id: str):
    res = api_client.list_vendors(booking_id, inv["coord_headers"])
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("data", data)


def propose_reschedule(inv, booking, reason_kind, new_date,
                       cs, ce, rs, re_, supersedes_request_id=None):
    """Client proposes a reschedule round. Returns the request dict."""
    payload = create_reschedule_payload(reason_kind, new_date, cs, ce, rs, re_)
    if supersedes_request_id is not None:
        payload["supersedes_request_id"] = supersedes_request_id
    return get_success_data(api_client.create_reschedule_request(
        booking["id"], payload, inv["client_headers"]))
