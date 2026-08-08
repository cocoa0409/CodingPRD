"""Composite setup helpers.

Every test runs against a freshly restarted, empty server, so each helper builds all of
its preconditions from scratch using only PRD-declared endpoints. Helpers use the lenient
get_success_data() validator so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import make_host_headers, make_traveler_headers, make_admin_headers, ANON_HEADERS
from .factories import (
    create_host_payload, create_traveler_payload, create_insurance_plan_payload,
    create_location_payload, create_booking_payload, seal_entry,
)
from .constants import DEFAULT_CLOCK


# --------------------------------------------------------------------------- #
# Primitive creators                                                          #
# --------------------------------------------------------------------------- #

def set_clock(api, iso):
    admin = make_admin_headers()
    return get_success_data(api.set_clock({"to_iso8601": iso}, admin))


def create_host(api, **overrides):
    admin = make_admin_headers()
    return get_success_data(api.create_host(create_host_payload(**overrides), admin))


def create_traveler(api, **overrides):
    return get_success_data(api.create_traveler(create_traveler_payload(**overrides), ANON_HEADERS))


def create_insurance_plan(api, **overrides):
    admin = make_admin_headers()
    return get_success_data(api.create_insurance_plan(create_insurance_plan_payload(**overrides), admin))


def create_location(api, host_id, **overrides):
    host_headers = make_host_headers(host_id)
    return get_success_data(api.create_location(host_id, create_location_payload(**overrides), host_headers))


def open_location(api, host_id, location_id):
    host_headers = make_host_headers(host_id)
    return get_success_data(
        api.set_location_status(location_id, {"to_status": "OPEN"}, host_headers)
    )


def location_version(api, location_id, headers):
    return get_success_data(api.get_location(location_id, headers))["version"]


# --------------------------------------------------------------------------- #
# Environment: host + traveler + plan + OPEN location                         #
# --------------------------------------------------------------------------- #

def setup_open_location(api, *, clock=DEFAULT_CLOCK,
                        platform_fee_bps=None, max_concurrent_bookings=None,
                        tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
                        daily_bag_capacity=10, oversize_capacity=5,
                        per_bag_day_rate_cents=500, oversize_surcharge_cents_per_day=300,
                        host_email="host@example.com", traveler_email="traveler@example.com"):
    """Clock set + ACTIVE host + traveler + insurance plan + one OPEN location.

    Returns a dict context with entities and pre-threaded ownership headers.
    """
    set_clock(api, clock)

    host_overrides = {"email": host_email}
    if platform_fee_bps is not None:
        host_overrides["platform_fee_bps"] = platform_fee_bps
    if max_concurrent_bookings is not None:
        host_overrides["max_concurrent_bookings"] = max_concurrent_bookings
    host = create_host(api, **host_overrides)
    host_headers = make_host_headers(host["id"])

    traveler = create_traveler(api, email=traveler_email)
    traveler_headers = make_traveler_headers(traveler["id"])

    plan = create_insurance_plan(
        api, tier=tier, per_bag_coverage_cents=per_bag_coverage_cents,
        premium_cents_per_bag_day=premium_cents_per_bag_day,
    )

    location = create_location(
        api, host["id"], daily_bag_capacity=daily_bag_capacity, oversize_capacity=oversize_capacity,
        per_bag_day_rate_cents=per_bag_day_rate_cents,
        oversize_surcharge_cents_per_day=oversize_surcharge_cents_per_day,
    )
    location = open_location(api, host["id"], location["id"])

    return {
        "admin_headers": make_admin_headers(),
        "host": host,
        "host_headers": host_headers,
        "traveler": traveler,
        "traveler_headers": traveler_headers,
        "plan": plan,
        "location": location,
    }


def create_additional_open_location(api, ctx, **overrides):
    """Add a second OPEN location under the same host as ctx. Returns the location."""
    host_id = ctx["host"]["id"]
    loc = create_location(api, host_id, **overrides)
    return open_location(api, host_id, loc["id"])


# --------------------------------------------------------------------------- #
# Booking lifecycle                                                           #
# --------------------------------------------------------------------------- #

def create_booking(api, ctx, *, check_in_date, check_out_date, bags,
                   location=None, expected_location_version=None):
    """Create a booking in the ctx environment.

    If expected_location_version is None the current live Location.version is read and
    used, so callers that do not care about OCC always pass a fresh version.
    """
    loc = location or ctx["location"]
    traveler_headers = ctx["traveler_headers"]
    if expected_location_version is None:
        expected_location_version = location_version(api, loc["id"], traveler_headers)
    payload = create_booking_payload(
        loc["id"], ctx["traveler"]["id"], ctx["plan"]["id"],
        check_in_date, check_out_date, bags,
        expected_location_version=expected_location_version,
    )
    return get_success_data(api.create_booking(payload, traveler_headers))


def get_bags(api, ctx, booking_id):
    return get_success_data(api.list_booking_bags(booking_id, ctx["host_headers"]))


def dropoff(api, ctx, booking_id, seal_codes=None):
    """Seal every bag of the booking and drop off. seal_codes optional per-bag override."""
    bags = get_bags(api, ctx, booking_id)
    seals = []
    for i, bag in enumerate(bags):
        code = (seal_codes[i] if seal_codes else f"SL-{booking_id[:4]}-{i}")
        seals.append(seal_entry(bag["id"], code))
    return get_success_data(api.dropoff_booking(booking_id, {"seals": seals}, ctx["host_headers"]))


def pickup(api, ctx, booking_id, presented_seals=None):
    payload = {}
    if presented_seals is not None:
        payload["presented_seals"] = presented_seals
    return get_success_data(api.pickup_booking(booking_id, payload, ctx["host_headers"]))


def setup_reserved_booking(api, *, check_in_date="2026-06-10", check_out_date="2026-06-11",
                           bags=None, **env_kwargs):
    """Environment + one RESERVED booking. Returns (ctx, booking, bags)."""
    ctx = setup_open_location(api, **env_kwargs)
    if bags is None:
        bags = [{"declared_value_cents": 1000, "dimension_sum_cm": 100}]
    booking = create_booking(api, ctx, check_in_date=check_in_date,
                             check_out_date=check_out_date, bags=bags)
    bag_rows = get_bags(api, ctx, booking["id"])
    return ctx, booking, bag_rows


def setup_stored_booking(api, *, check_in_date="2026-06-10", check_out_date="2026-06-11",
                         bags=None, seal_codes=None, **env_kwargs):
    """Environment + booking dropped off (STORED). Returns (ctx, booking, bags)."""
    ctx, booking, bag_rows = setup_reserved_booking(
        api, check_in_date=check_in_date, check_out_date=check_out_date, bags=bags, **env_kwargs
    )
    dropoff(api, ctx, booking["id"], seal_codes=seal_codes)
    booking = get_success_data(api.get_booking(booking["id"], ctx["host_headers"]))
    return ctx, booking, bag_rows


def setup_completed_booking(api, *, check_in_date="2026-06-10", check_out_date="2026-06-11",
                            pickup_clock=None, bags=None, seal_codes=None, **env_kwargs):
    """Environment + booking dropped off and picked up (COMPLETED). Returns (ctx, booking, bags).

    pickup_clock, if given, advances the logical clock before pickup (drives overage / hold).
    """
    ctx, booking, bag_rows = setup_stored_booking(
        api, check_in_date=check_in_date, check_out_date=check_out_date,
        bags=bags, seal_codes=seal_codes, **env_kwargs
    )
    if pickup_clock is not None:
        set_clock(api, pickup_clock)
    booking = pickup(api, ctx, booking["id"])
    return ctx, booking, bag_rows


def get_only_payout(api, ctx):
    """Return the single payout in the system (list is admin/host readable)."""
    payouts = get_success_data(api.list_payouts(ctx["admin_headers"]))
    return payouts[0]


# --------------------------------------------------------------------------- #
# Claim lifecycle                                                             #
# --------------------------------------------------------------------------- #

def file_claim(api, ctx, booking_id, bag_id, *, reason="DAMAGE", description="d",
               claimed_amount_cents=1000):
    payload = {
        "bag_id": bag_id, "reason": reason, "description": description,
        "claimed_amount_cents": claimed_amount_cents,
    }
    return get_success_data(api.create_claim(booking_id, payload, ctx["traveler_headers"]))


def review_claim(api, ctx, claim_id):
    return get_success_data(api.review_claim(claim_id, ctx["admin_headers"]))
