"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its world from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup step failed" rather than a confusing assertion error.

Identity threading: any Rider call that is ownership-gated uses
make_rider_headers(rider["id"]) — never the shared TEST_USERS["rider_headers"]
fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fare_product_payload,
    create_rider_payload,
    create_funding_source_payload,
    create_reduced_fare_card_payload,
    create_benefit_allocation_payload,
    create_fare_week_payload,
    create_tap_payload,
    load_payload,
    verify_payload,
    clock_payload,
)
from .test_users import TEST_USERS, make_rider_headers, make_anonymous_headers


# ─── Atomic building blocks ───────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Move the server clock (FareAdmin test-driving capability, §2.8)."""
    return get_success_data(api_client.set_clock(
        clock_payload(to_iso8601), TEST_USERS["fare_admin_headers"]))


def make_fare_product(**overrides):
    """Create an ACTIVE fare product. Returns the product dict."""
    return get_success_data(api_client.create_fare_product(
        create_fare_product_payload(**overrides), TEST_USERS["fare_admin_headers"]))


def register_rider(**overrides):
    """Register a rider (Anonymous). Returns the rider dict (carries version)."""
    return get_success_data(api_client.create_rider(
        create_rider_payload(**overrides), make_anonymous_headers()))


def add_funding_source(rider_id, **overrides):
    """Attach a funding source owned by rider_id. Returns the source dict."""
    return get_success_data(api_client.create_funding_source(
        create_funding_source_payload(rider_id, **overrides),
        make_rider_headers(rider_id)))


def load_balance(rider_id, fs_id, amount_cents):
    """Load stored value onto a funding source. Returns the updated source."""
    return get_success_data(api_client.load_funding_source(
        fs_id, load_payload(amount_cents), make_rider_headers(rider_id)))


def open_week(rider_id, week_start_date="2026-06-01", zone_code="ZONEX"):
    """Open a fare week for rider_id. Returns the week dict."""
    return get_success_data(api_client.create_fare_week(
        create_fare_week_payload(rider_id, week_start_date=week_start_date,
                                 zone_code=zone_code),
        make_rider_headers(rider_id)))


def record_tap(rider_id, fare_week_id, funding_source_id, tapped_at):
    """Record a PENDING tap owned by rider_id. Returns the tap dict."""
    return get_success_data(api_client.create_tap(
        create_tap_payload(rider_id, fare_week_id, funding_source_id, tapped_at),
        make_rider_headers(rider_id)))


def settle(tap_id):
    """Settle a tap (PaymentGateway). Returns the settle response data (CAPTURED on success)."""
    return get_success_data(api_client.settle_tap(
        tap_id, TEST_USERS["payment_gateway_headers"]))


def create_verified_card(rider_id, program_code="SENIOR", expires_on="2027-01-01"):
    """Apply for a card and verify it (echoing the issued token). Returns the verified card."""
    card = get_success_data(api_client.create_reduced_fare_card(
        create_reduced_fare_card_payload(rider_id, program_code=program_code,
                                         expires_on=expires_on),
        make_rider_headers(rider_id)))
    verified = get_success_data(api_client.verify_reduced_fare_card(
        card["id"], verify_payload(card["verification_token"]),
        TEST_USERS["fare_admin_headers"]))
    return verified, card["verification_token"]


def fund_allocation(rider_id, expected_rider_version, **overrides):
    """Create a benefit allocation. Returns the allocation dict."""
    return get_success_data(api_client.create_benefit_allocation(
        create_benefit_allocation_payload(rider_id, expected_rider_version, **overrides),
        TEST_USERS["employer_admin_headers"]))


# ─── Composite worlds ─────────────────────────────────────────────────────

def setup_funded_rider(clock="2026-06-01T12:00:00Z", zone_code="ZONEX",
                       balance=100000, week_start="2026-06-01",
                       product_overrides=None, rider_overrides=None,
                       email="rider@example.com"):
    """Product + clock + rider + funded ACTIVE source + OPEN fare week.

    Returns dict: {product, rider, funding_source, week} (all entity dicts).
    The week's zone_code matches the product zone.
    """
    # Merge zone_code into the product overrides so callers may also pass an
    # explicit zone_code inside product_overrides without colliding on the kwarg.
    prod_kwargs = {"zone_code": zone_code}
    prod_kwargs.update(product_overrides or {})
    zone_code = prod_kwargs["zone_code"]
    product = make_fare_product(**prod_kwargs)
    set_clock(clock)
    rider = register_rider(home_zone_code=zone_code, email=email,
                           **(rider_overrides or {}))
    fs = add_funding_source(rider["id"])
    if balance > 0:
        fs = load_balance(rider["id"], fs["id"], balance)
    week = open_week(rider["id"], week_start_date=week_start, zone_code=zone_code)
    return {"product": product, "rider": rider, "funding_source": fs, "week": week}


def create_captured_tap(world, tapped_at):
    """Record a tap into world['week'] and settle it. Returns the settled tap dict.

    Asserts nothing about the outcome status — caller inspects the returned dict.
    """
    tap = record_tap(world["rider"]["id"], world["week"]["id"],
                     world["funding_source"]["id"], tapped_at)
    return settle(tap["id"])


def setup_world_with_captured_tap(clock="2026-06-01T12:00:00Z", zone_code="ZONEX",
                                  balance=100000, week_start="2026-06-01",
                                  product_overrides=None, tapped_at="2026-06-01T09:00:00Z"):
    """Funded rider + one CAPTURED tap. Returns (world, captured_tap)."""
    world = setup_funded_rider(clock=clock, zone_code=zone_code, balance=balance,
                               week_start=week_start, product_overrides=product_overrides)
    captured = create_captured_tap(world, tapped_at)
    return world, captured


def get_funding_source(rider_id, fs_id):
    return get_success_data(api_client.get_funding_source(
        fs_id, make_rider_headers(rider_id)))


def get_fare_week(rider_id, week_id):
    return get_success_data(api_client.get_fare_week(
        week_id, make_rider_headers(rider_id)))


def get_tap(rider_id, tap_id):
    return get_success_data(api_client.get_tap(
        tap_id, make_rider_headers(rider_id)))


def get_allocation(rider_id, alloc_id):
    return get_success_data(api_client.get_benefit_allocation(
        alloc_id, make_rider_headers(rider_id)))
