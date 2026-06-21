"""Composite setup helpers.

Encapsulates the multi-step API sequences needed to drive the system into the
states tests assert against. Every helper builds its preconditions from scratch
using only PRD-declared endpoints (the harness restarts the server with an empty
database before each test). Helpers use get_success_data() so a broken setup
surfaces as a clear "Setup failed" rather than a confusing assertion error.

Identity threading: Host and Guest are entity-backed. Every ownership-gated call
uses make_host_headers(host["id"]) / make_guest_headers(guest["id"]) with the real
entity id, never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_host_payload, create_guest_payload, create_listing_payload,
    create_rate_plan_payload, create_booking_payload, create_claim_payload,
    create_channel_connection_payload, create_calendar_block_payload,
    create_imported_reservation_payload,
)
from .test_users import make_host_headers, make_guest_headers, admin_headers, anonymous_headers


# --------------------------------------------------------------------------
# Identity primitives
# --------------------------------------------------------------------------
def create_host(**overrides) -> dict:
    """Register a host. Returns the Host resource."""
    resp = api_client.create_host(create_host_payload(**overrides), headers=anonymous_headers())
    return get_success_data(resp)


def create_guest(**overrides) -> dict:
    """Register a guest with screening attributes. Returns the Guest resource."""
    resp = api_client.create_guest(create_guest_payload(**overrides), headers=anonymous_headers())
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> dict:
    """Advance the test-driving clock. Returns {current_utc: ...}."""
    resp = api_client.set_clock(to_iso8601, headers=admin_headers())
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 1: Listing state progression
# --------------------------------------------------------------------------
def create_draft_listing(host=None, listing_overrides=None) -> tuple:
    """Create a host (if not given) and a DRAFT listing.
    Returns (host, listing)."""
    if host is None:
        host = create_host()
    listing_overrides = listing_overrides or {}
    resp = api_client.create_listing(
        create_listing_payload(host["id"], **listing_overrides),
        headers=make_host_headers(host["id"]),
    )
    listing = get_success_data(resp)
    return host, listing


def add_rate_plan(host, listing, **rate_plan_overrides) -> dict:
    """Attach a rate plan to a listing. Returns the RatePlan."""
    resp = api_client.create_rate_plan(
        create_rate_plan_payload(listing["id"], **rate_plan_overrides),
        headers=make_host_headers(host["id"]),
    )
    return get_success_data(resp)


def create_listed_listing(host=None, listing_overrides=None, rate_plan_overrides=None) -> tuple:
    """Create a host + DRAFT listing + one rate plan, then publish to LISTED.
    Returns (host, listing) where listing reflects the LISTED state."""
    host, listing = create_draft_listing(host=host, listing_overrides=listing_overrides)
    add_rate_plan(host, listing, **(rate_plan_overrides or {}))
    resp = api_client.publish_listing(listing["id"], headers=make_host_headers(host["id"]))
    listing = get_success_data(resp)
    return host, listing


def get_calendar_version(listing_id, headers) -> int:
    """Read the listing's live calendar_version (for OCC-guarded writes)."""
    resp = api_client.get_listing(listing_id, headers=headers)
    return get_success_data(resp)["calendar_version"]


# --------------------------------------------------------------------------
# Tier 2: Channel connections
# --------------------------------------------------------------------------
def create_connected_channel(host, listing, channel="AIRBNB") -> dict:
    """Create a channel connection and connect it (CONNECTED).
    Returns the ChannelConnection."""
    resp = api_client.create_channel_connection(
        create_channel_connection_payload(listing["id"], channel=channel),
        headers=make_host_headers(host["id"]),
    )
    cc = get_success_data(resp)
    resp = api_client.connect_channel(cc["id"], headers=make_host_headers(host["id"]))
    return get_success_data(resp)


def create_manual_block(host, listing, **block_overrides) -> dict:
    """Create a MANUAL ACTIVE calendar block, reading the live calendar_version
    first so the OCC guard passes. Returns the CalendarBlock."""
    cv = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    resp = api_client.create_calendar_block(
        listing["id"],
        create_calendar_block_payload(cv, **block_overrides),
        headers=make_host_headers(host["id"]),
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 3: Bookings — state progression shortcuts
# --------------------------------------------------------------------------
def create_booking(host, listing, guest, **booking_overrides) -> dict:
    """Create a REQUESTED booking on a LISTED listing, reading the live
    calendar_version first. Returns the Booking."""
    cv = get_calendar_version(listing["id"], headers=make_guest_headers(guest["id"]))
    resp = api_client.create_booking(
        create_booking_payload(listing["id"], guest["id"], cv, **booking_overrides),
        headers=make_guest_headers(guest["id"]),
    )
    return get_success_data(resp)


def setup_requested_booking(host_overrides=None, guest_overrides=None,
                            listing_overrides=None, rate_plan_overrides=None,
                            booking_overrides=None, clock=None) -> dict:
    """Full setup to a REQUESTED booking.
    Returns dict(host, guest, listing, booking)."""
    host = create_host(**(host_overrides or {}))
    guest = create_guest(**(guest_overrides or {}))
    _, listing = create_listed_listing(
        host=host,
        listing_overrides=listing_overrides,
        rate_plan_overrides=rate_plan_overrides,
    )
    if clock is not None:
        set_clock(clock)
    booking = create_booking(host, listing, guest, **(booking_overrides or {}))
    return {"host": host, "guest": guest, "listing": listing, "booking": booking}


def setup_screening_booking(**kwargs) -> dict:
    """Drive a booking to SCREENING (host screens). Returns the same dict plus
    the refreshed booking."""
    ctx = setup_requested_booking(**kwargs)
    resp = api_client.screen_booking(
        ctx["booking"]["id"], headers=make_host_headers(ctx["host"]["id"]))
    ctx["booking"] = get_success_data(resp)
    return ctx


def setup_approved_booking(**kwargs) -> dict:
    """Drive a booking to APPROVED (screen + approve). Requires a guest whose
    screening passes (default factory guest is verified, no chargeback, 0 priors).
    Returns dict(host, guest, listing, booking)."""
    # Default guest must pass screening unless overridden.
    guest_overrides = kwargs.pop("guest_overrides", None) or {}
    guest_overrides.setdefault("govt_id_verified", True)
    guest_overrides.setdefault("prior_cancellations", 0)
    guest_overrides.setdefault("chargeback_flag", False)
    ctx = setup_screening_booking(guest_overrides=guest_overrides, **kwargs)
    resp = api_client.approve_booking(
        ctx["booking"]["id"], headers=make_host_headers(ctx["host"]["id"]))
    ctx["booking"] = get_success_data(resp)
    return ctx


def setup_confirmed_booking(**kwargs) -> dict:
    """Drive a booking to CONFIRMED (screen + approve + confirm). Confirmation
    creates the SecurityDeposit (AUTHORIZED) and Payout (SCHEDULED).
    Returns dict(host, guest, listing, booking, deposit, payout)."""
    ctx = setup_approved_booking(**kwargs)
    resp = api_client.confirm_booking(
        ctx["booking"]["id"], headers=make_guest_headers(ctx["guest"]["id"]))
    ctx["booking"] = get_success_data(resp)
    ctx["deposit"] = get_booking_deposit(ctx["host"], ctx["booking"])
    ctx["payout"] = get_booking_payout(ctx["host"], ctx["booking"])
    return ctx


def setup_in_stay_booking(check_in_clock="2026-07-10T12:00:00Z", **kwargs) -> dict:
    """Drive a booking to IN_STAY by advancing the clock to at/after check_in.
    Returns dict with refreshed booking. Default check_in is 2026-07-10."""
    ctx = setup_confirmed_booking(**kwargs)
    set_clock(check_in_clock)
    resp = api_client.get_booking(
        ctx["booking"]["id"], headers=make_host_headers(ctx["host"]["id"]))
    ctx["booking"] = get_success_data(resp)
    return ctx


def setup_completed_booking(check_in_clock="2026-07-10T12:00:00Z",
                            check_out_clock="2026-07-13T12:00:00Z", **kwargs) -> dict:
    """Drive a booking to COMPLETED (in_stay then complete after check_out).
    Returns dict with refreshed booking."""
    ctx = setup_in_stay_booking(check_in_clock=check_in_clock, **kwargs)
    set_clock(check_out_clock)
    resp = api_client.complete_booking(
        ctx["booking"]["id"], headers=make_host_headers(ctx["host"]["id"]))
    ctx["booking"] = get_success_data(resp)
    return ctx


# --------------------------------------------------------------------------
# Tier 3 helpers: satellite record reads
# --------------------------------------------------------------------------
def get_booking_deposit(host, booking) -> dict:
    """Read the single SecurityDeposit for a booking via reverse reachability."""
    resp = api_client.list_booking_security_deposits(
        booking["id"], headers=make_host_headers(host["id"]))
    data = get_success_data(resp)
    return data[0]


def get_booking_payout(host, booking) -> dict:
    """Read the single Payout for a booking via reverse reachability."""
    resp = api_client.list_booking_payouts(
        booking["id"], headers=make_host_headers(host["id"]))
    data = get_success_data(resp)
    return data[0]


def get_latest_screening_result(host, booking) -> dict:
    """Read the latest ScreeningResult for a booking (created_at ascending, so
    the last element is the most recent)."""
    resp = api_client.list_booking_screening_results(
        booking["id"], headers=make_host_headers(host["id"]))
    data = get_success_data(resp)
    return data[-1] if data else None


# --------------------------------------------------------------------------
# Tier 4: Damage-claim lifecycle shortcuts
# --------------------------------------------------------------------------
def file_claim(host, deposit, amount_cents, **overrides) -> dict:
    """File a DamageClaim against a deposit (booking must be IN_STAY/COMPLETED).
    Returns the DamageClaim (FILED)."""
    resp = api_client.file_claim(
        deposit["id"],
        create_claim_payload(deposit["id"], amount_cents, **overrides),
        headers=make_host_headers(host["id"]),
    )
    return get_success_data(resp)


def setup_filed_claim(amount_cents=6000,
                      claim_clock="2026-07-11T00:00:00Z",
                      in_stay_clock="2026-07-10T12:00:00Z",
                      deposit_cents=10000, **kwargs) -> dict:
    """Confirmed booking -> IN_STAY -> file one FILED claim.
    Returns dict(host, guest, listing, booking, deposit, payout, claim)."""
    listing_overrides = kwargs.pop("listing_overrides", None) or {}
    listing_overrides.setdefault("security_deposit_cents", deposit_cents)
    listing_overrides.setdefault("payout_delay_days", 1)
    ctx = setup_in_stay_booking(
        check_in_clock=in_stay_clock, listing_overrides=listing_overrides, **kwargs)
    set_clock(claim_clock)
    ctx["claim"] = file_claim(ctx["host"], ctx["deposit"], amount_cents)
    return ctx


def setup_under_review_claim(**kwargs) -> dict:
    """As setup_filed_claim, then admin moves the claim to UNDER_REVIEW.
    Returns dict including the refreshed claim."""
    ctx = setup_filed_claim(**kwargs)
    resp = api_client.review_claim(ctx["claim"]["id"], headers=admin_headers())
    ctx["claim"] = get_success_data(resp)
    return ctx


def setup_approved_claim(**kwargs) -> dict:
    """As setup_under_review_claim, then admin approves (waterfall debit).
    Returns dict including the refreshed claim and a refreshed deposit."""
    ctx = setup_under_review_claim(**kwargs)
    resp = api_client.approve_claim(ctx["claim"]["id"], headers=admin_headers())
    ctx["claim"] = get_success_data(resp)
    resp = api_client.get_security_deposit(ctx["deposit"]["id"], headers=admin_headers())
    ctx["deposit"] = get_success_data(resp)
    return ctx
