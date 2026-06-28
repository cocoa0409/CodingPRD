"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty DB) before every test, so every helper
builds its preconditions from scratch using only PRD-declared endpoints.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating an entity_backed Host/Driver, every
ownership-gated call uses make_host_headers(host_id) / make_driver_headers(driver_id)
with the real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_host_payload, create_driver_payload, topup_payload,
    create_spot_payload, create_pricing_event_payload, create_booking_payload,
    create_transfer_offer_payload, create_violation_payload, set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_host_headers, make_driver_headers, make_admin_headers,
    make_anonymous_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Primitive builders ─────────────────────────────────────────────────────

def register_host(**overrides) -> dict:
    """Register a Host. Returns the Host resource."""
    return get_success_data(api_client.create_host(create_host_payload(**overrides), ANON))


def register_driver(**overrides) -> dict:
    """Register a Driver. Returns the Driver resource."""
    return get_success_data(api_client.create_driver(create_driver_payload(**overrides), ANON))


def fund_driver(driver_id: str, amount_cents: int) -> dict:
    """Credit a driver's wallet. Returns the updated Driver (ownership-gated by driver)."""
    return get_success_data(api_client.topup_wallet(
        driver_id, topup_payload(amount_cents), make_driver_headers(driver_id)))


def create_spot(host_id: str, **overrides) -> dict:
    """Create a LISTED Spot owned by host_id. Returns the Spot (ownership-gated by host)."""
    return get_success_data(api_client.create_spot(
        create_spot_payload(host_id, **overrides), make_host_headers(host_id)))


def create_pricing_event(zone_code, window_start, window_end, surge_multiplier_bps, **overrides) -> dict:
    """Create an ACTIVE PricingEvent. Returns the event (PlatformAdmin)."""
    return get_success_data(api_client.create_pricing_event(
        create_pricing_event_payload(zone_code, window_start, window_end,
                                     surge_multiplier_bps, **overrides), ADMIN))


def set_clock(to_iso8601: str) -> None:
    """Advance the server logical clock. PlatformAdmin may set it."""
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def get_spot_version(host_id: str, spot_id: str) -> int:
    """Read the current Spot.version (host can read its own spot)."""
    return get_success_data(api_client.get_spot(spot_id, make_host_headers(host_id)))["version"]


def get_booking_version(driver_id: str, booking_id: str) -> int:
    """Read the current Booking.version (driver who holds it can read it)."""
    return get_success_data(api_client.get_booking(booking_id, make_driver_headers(driver_id)))["version"]


def create_booking(spot_id, driver_id, rate_kind, start_at, end_at, expected_spot_version,
                   **overrides) -> dict:
    """Create a Booking (driver action). Returns the Booking. Caller supplies the
    fresh expected_spot_version (read just before, since each prior booking bumps it)."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(spot_id, driver_id, rate_kind, start_at, end_at,
                               expected_spot_version, **overrides),
        make_driver_headers(driver_id)))


# ─── Tier 1/2: Common scenario scaffolds ────────────────────────────────────

def setup_host_driver_spot(host_overrides=None, driver_overrides=None, spot_overrides=None,
                           wallet_cents=5000):
    """Register a Host, a Driver funded to wallet_cents, and a LISTED Spot.

    Returns (host, driver, spot). The spot starts at version 1.
    """
    host = register_host(**(host_overrides or {}))
    driver = register_driver(**(driver_overrides or {}))
    if wallet_cents:
        fund_driver(driver["id"], wallet_cents)
    spot = create_spot(host["id"], **(spot_overrides or {}))
    return host, driver, spot


def setup_reserved_booking(rate_kind="HOURLY",
                           start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z",
                           wallet_cents=5000, spot_overrides=None, clock=None):
    """Host + funded Driver + LISTED Spot + one RESERVED Booking.

    Optionally sets the clock before booking creation. Returns (host, driver, spot, booking).
    """
    host, driver, spot = setup_host_driver_spot(
        wallet_cents=wallet_cents, spot_overrides=spot_overrides)
    if clock is not None:
        set_clock(clock)
    booking = create_booking(spot["id"], driver["id"], rate_kind, start_at, end_at,
                             spot["version"])
    return host, driver, spot, booking


def setup_checked_in_booking(start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T11:00:00Z",
                             checkin_clock="2026-04-08T10:00:00Z",
                             setup_clock="2026-04-08T09:00:00Z",
                             wallet_cents=5000, spot_overrides=None):
    """Host + funded Driver + LISTED Spot + one CHECKED_IN Booking.

    Sets setup_clock before creation, then checkin_clock and checks in. Returns
    (host, driver, spot, booking) where booking reflects the check-in response.
    """
    host, driver, spot = setup_host_driver_spot(
        wallet_cents=wallet_cents, spot_overrides=spot_overrides)
    set_clock(setup_clock)
    booking = create_booking(spot["id"], driver["id"], "HOURLY", start_at, end_at,
                             spot["version"])
    set_clock(checkin_clock)
    booking = get_success_data(
        api_client.check_in_booking(booking["id"], make_driver_headers(driver["id"])))
    return host, driver, spot, booking


def checkout_at(driver_id: str, booking_id: str, checkout_clock: str) -> dict:
    """Advance the clock to checkout_clock and check the booking out. Returns the
    checked-out Booking response."""
    set_clock(checkout_clock)
    return get_success_data(
        api_client.check_out_booking(booking_id, make_driver_headers(driver_id)))


# ─── Tier 3: Violation lifecycle ─────────────────────────────────────────────

def log_violation(host_id: str, booking_id: str, violation_kind: str, base_points: int) -> dict:
    """Log an OPEN ViolationRecord against a booking (Host reports). Returns the record."""
    return get_success_data(api_client.create_violation(
        create_violation_payload(booking_id, violation_kind, base_points),
        make_host_headers(host_id)))


def confirm_violation(violation_id: str) -> dict:
    """Confirm a violation (PlatformAdmin). Returns the confirmed record."""
    return get_success_data(api_client.confirm_violation(violation_id, ADMIN))


def setup_driver_with_confirmed_violation(violation_kind="OVERSTAY", base_points=4,
                                          wallet_cents=5000):
    """Host + Driver + Spot + RESERVED Booking + one CONFIRMED ViolationRecord on the driver.

    Returns (host, driver, spot, booking, violation) where the violation is CONFIRMED.
    """
    host, driver, spot, booking = setup_reserved_booking(wallet_cents=wallet_cents)
    vr = log_violation(host["id"], booking["id"], violation_kind, base_points)
    vr = confirm_violation(vr["id"])
    return host, driver, spot, booking, vr


def setup_suspended_driver(no_show_base_points=4, wallet_cents=10000):
    """Drive a Driver to SUSPENDED via a confirmed NO_SHOW violation.

    A NO_SHOW (weight 3) with base_points=4 and no priors assesses 12 >= 10 -> SUSPENDED.
    The booking the violation is logged against is created at clock 2026-04-08T09:00:00Z.
    Returns (host, driver, spot, booking, violation).
    """
    host, driver, spot = setup_host_driver_spot(wallet_cents=wallet_cents)
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-09T10:00:00Z", "2026-04-09T11:00:00Z", spot["version"])
    vr = log_violation(host["id"], booking["id"], "NO_SHOW", no_show_base_points)
    vr = confirm_violation(vr["id"])
    return host, driver, spot, booking, vr


# ─── Tier 4: Transfer-offer lifecycle ────────────────────────────────────────

def create_transfer_offer(from_driver_id: str, booking_id: str, to_driver_id: str,
                          expected_booking_version: int) -> dict:
    """Create a PENDING TransferOffer (offeror = from_driver_id holds the booking)."""
    return get_success_data(api_client.create_transfer_offer(
        create_transfer_offer_payload(booking_id, to_driver_id, expected_booking_version),
        make_driver_headers(from_driver_id)))


def setup_pending_transfer_offer(wallet_a=5000, wallet_b=5000,
                                 start_at="2026-04-20T10:00:00Z", end_at="2026-04-20T11:00:00Z",
                                 clock="2026-04-08T09:00:00Z"):
    """Host + Spot + two funded Drivers (a holds the booking, b is the recipient) +
    a RESERVED Booking held by a + a PENDING TransferOffer from a to b (created before start).

    Returns (host, driver_a, driver_b, spot, booking, offer).
    """
    host = register_host()
    driver_a = register_driver()
    driver_b = register_driver()
    if wallet_a:
        fund_driver(driver_a["id"], wallet_a)
    if wallet_b:
        fund_driver(driver_b["id"], wallet_b)
    spot = create_spot(host["id"])
    if clock is not None:
        set_clock(clock)
    booking = create_booking(spot["id"], driver_a["id"], "HOURLY", start_at, end_at,
                             spot["version"])
    bv = get_booking_version(driver_a["id"], booking["id"])
    offer = create_transfer_offer(driver_a["id"], booking["id"], driver_b["id"], bv)
    return host, driver_a, driver_b, spot, booking, offer


# ─── Tier 5: No-show / payout reversal ───────────────────────────────────────

def mark_no_show(booking_id: str) -> dict:
    """Mark a RESERVED expired booking NO_SHOW (PlatformAdmin). Returns the booking."""
    return get_success_data(api_client.mark_no_show(booking_id, ADMIN))


def setup_no_show_with_earning(host_overrides=None, spot_overrides=None,
                               start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T13:00:00Z",
                               rate_kind="HOURLY",
                               pricing_event=None, wallet_cents=5000,
                               setup_clock="2026-04-08T09:00:00Z",
                               expiry_clock="2026-04-08T13:20:00Z"):
    """Host + funded Driver + Spot (+ optional PricingEvent) + a Booking driven to NO_SHOW.

    The no-show posts an EARNING ledger entry. Returns (host, driver, spot, booking)
    where booking reflects the marked-no-show response.

    pricing_event, if given, is a dict of kwargs for create_pricing_event (zone_code,
    window_start, window_end, surge_multiplier_bps).
    """
    host = register_host(**(host_overrides or {}))
    driver = register_driver()
    if wallet_cents:
        fund_driver(driver["id"], wallet_cents)
    spot = create_spot(host["id"], **(spot_overrides or {}))
    if pricing_event is not None:
        create_pricing_event(**pricing_event)
    set_clock(setup_clock)
    booking = create_booking(spot["id"], driver["id"], rate_kind, start_at, end_at,
                             spot["version"])
    set_clock(expiry_clock)
    booking = mark_no_show(booking["id"])
    return host, driver, spot, booking
