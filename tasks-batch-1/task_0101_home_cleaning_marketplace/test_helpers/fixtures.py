"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before every individual test.
Fixtures use get_success_data() (lenient) internally so setup failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_customer_headers, make_cleaner_headers,
)
from .factories import (
    create_customer_payload, create_address_payload, create_cleaner_payload,
    create_pricing_plan_payload, create_booking_payload,
    create_booking_series_payload, create_preferred_pro_payload,
)
from .constants import TEST_POSTAL_CODE

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server's test-driving clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def seed_loyalty(customer_id: str, count: int):
    """Seed a customer's lifetime_booking_count directly via the test endpoint."""
    return get_success_data(
        api_client.set_loyalty_count(
            {"customer_id": customer_id, "lifetime_booking_count": count}, ADMIN
        )
    )


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creators / state progression
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ANON))


def create_address(customer_id: str, **overrides) -> dict:
    hdr = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_address(create_address_payload(customer_id, **overrides), hdr)
    )


def create_active_plan(**overrides) -> dict:
    """Create a pricing plan and activate it. Returns the activated plan."""
    plan = get_success_data(api_client.create_pricing_plan(create_pricing_plan_payload(**overrides), ADMIN))
    activated = get_success_data(
        api_client.activate_pricing_plan(plan["id"], {"expected_plan_version": plan["version"]}, ADMIN)
    )
    return activated


def create_applied_cleaner(**overrides) -> dict:
    return get_success_data(api_client.create_cleaner(create_cleaner_payload(**overrides), ANON))


def create_active_cleaner(**overrides) -> dict:
    """Walk a cleaner APPLIED -> CHECK_PENDING -> CHECK_PASSED -> ACTIVE. Returns the ACTIVE cleaner."""
    cleaner = create_applied_cleaner(**overrides)
    cid = cleaner["id"]
    bc = get_success_data(api_client.create_background_check(cid, {"provider_ref": "ext-1"}, ADMIN))
    get_success_data(api_client.adjudicate_background_check(bc["id"], {"result": "CLEAR"}, ADMIN))
    activated = get_success_data(api_client.activate_cleaner(cid, ADMIN))
    return activated


def create_check_passed_cleaner(**overrides) -> dict:
    """Cleaner walked to CHECK_PASSED but NOT activated."""
    cleaner = create_applied_cleaner(**overrides)
    cid = cleaner["id"]
    bc = get_success_data(api_client.create_background_check(cid, {"provider_ref": "ext-1"}, ADMIN))
    get_success_data(api_client.adjudicate_background_check(bc["id"], {"result": "CLEAR"}, ADMIN))
    return get_success_data(api_client.get_cleaner(cid, ADMIN))


def create_check_failed_cleaner(**overrides) -> dict:
    """Cleaner adjudicated ADVERSE -> terminal CHECK_FAILED."""
    cleaner = create_applied_cleaner(**overrides)
    cid = cleaner["id"]
    bc = get_success_data(api_client.create_background_check(cid, {"provider_ref": "ext-bad"}, ADMIN))
    get_success_data(api_client.adjudicate_background_check(bc["id"], {"result": "ADVERSE"}, ADMIN))
    return get_success_data(api_client.get_cleaner(cid, ADMIN))


def create_suspended_cleaner(**overrides) -> dict:
    """Cleaner walked to ACTIVE then SUSPENDED. Returns the SUSPENDED cleaner."""
    cleaner = create_active_cleaner(**overrides)
    return get_success_data(api_client.suspend_cleaner(cleaner["id"], ADMIN))


# ---------------------------------------------------------------------------
# Tier 2 — composite scenarios (plan + active cleaner + customer + address)
# ---------------------------------------------------------------------------
def setup_booking_world(home_size="STUDIO", postal_code=TEST_POSTAL_CODE,
                        clock="2026-06-01T00:00:00Z", loyalty_count=None,
                        plan_overrides=None):
    """Active plan + one ACTIVE serving cleaner + customer + one address.

    Returns dict with keys: plan, cleaner, customer, address.
    Sets the clock first. Optionally seeds loyalty_count on the customer.
    """
    set_clock(clock)
    plan = create_active_plan(**(plan_overrides or {}))
    cleaner = create_active_cleaner(service_postal_codes=[postal_code])
    customer = create_customer()
    if loyalty_count is not None:
        seed_loyalty(customer["id"], loyalty_count)
        customer = get_success_data(api_client.get_customer(customer["id"], ADMIN))
    address = create_address(customer["id"], postal_code=postal_code, home_size=home_size)
    return {"plan": plan, "cleaner": cleaner, "customer": customer, "address": address}


def create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z", **booking_overrides) -> dict:
    """Create a one-time booking owned by world['customer'] at world['address']."""
    cust = world["customer"]
    hdr = make_customer_headers(cust["id"])
    payload = create_booking_payload(
        cust["id"], world["address"]["id"], world["plan"]["id"], scheduled_start, **booking_overrides
    )
    return get_success_data(api_client.create_booking(payload, hdr))


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_completed_booking(home_size="TWO_BR", add_ons=("DEEP_CLEAN",),
                            supplies_provided_by="CLEANER", rating=5,
                            booking_start="2026-06-10T09:00:00Z",
                            complete_clock="2026-06-10T11:00:00Z",
                            loyalty_count=None):
    """Build a world, create + complete a one-time booking.

    Returns dict: plan, cleaner, customer, address, booking (refreshed COMPLETED).
    """
    world = setup_booking_world(home_size=home_size, loyalty_count=loyalty_count)
    booking = create_one_time_booking(
        world, scheduled_start=booking_start,
        add_ons=list(add_ons), supplies_provided_by=supplies_provided_by,
    )
    set_clock(complete_clock)
    cleaner_hdr = make_cleaner_headers(world["cleaner"]["id"])
    body = {"rating": rating} if rating is not None else {}
    completed = get_success_data(api_client.complete_booking(booking["id"], body, cleaner_hdr))
    world["booking"] = completed
    return world


def setup_reclean_requested(home_size="TWO_BR", add_ons=("DEEP_CLEAN",),
                            supplies_provided_by="CLEANER"):
    """Complete a booking then request a reclean. Returns world with 'booking'
    in RECLEAN_REQUESTED state."""
    world = setup_completed_booking(
        home_size=home_size, add_ons=add_ons, supplies_provided_by=supplies_provided_by
    )
    cust_hdr = make_customer_headers(world["customer"]["id"])
    requested = get_success_data(api_client.request_reclean(world["booking"]["id"], cust_hdr))
    world["booking"] = requested
    return world


def setup_reclean_scheduled(reclean_start="2026-06-13T09:00:00Z", **kwargs):
    """Complete + request + schedule a reclean. Returns world with:
    'booking' (original, RECLEAN_SCHEDULED) and 'reclean_booking' (new is_reclean)."""
    world = setup_reclean_requested(**kwargs)
    scheduled = get_success_data(
        api_client.schedule_reclean(world["booking"]["id"], {"scheduled_start": reclean_start}, ADMIN)
    )
    world["reclean_booking"] = scheduled
    # refresh original
    world["booking"] = get_success_data(api_client.get_booking(world["booking"]["id"], ADMIN))
    return world


# ---------------------------------------------------------------------------
# Tier 4 — series scenarios
# ---------------------------------------------------------------------------
def setup_series(world=None, cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z",
                 home_size="STUDIO", **series_overrides):
    """Active plan + ACTIVE cleaner + customer + address + a WEEKLY/BIWEEKLY series.

    Returns dict: plan, cleaner, customer, address, series.
    """
    if world is None:
        world = setup_booking_world(home_size=home_size)
    cust = world["customer"]
    hdr = make_customer_headers(cust["id"])
    payload = create_booking_series_payload(
        cust["id"], world["address"]["id"], world["plan"]["id"],
        first_occurrence_date, cadence=cadence, **series_overrides
    )
    series = get_success_data(api_client.create_booking_series(payload, hdr))
    world["series"] = series
    return world


def setup_series_with_one_occurrence(home_size="STUDIO", cadence="WEEKLY",
                                     first_occurrence_date="2026-06-20T09:00:00Z"):
    """A series with exactly one generated SCHEDULED booking.

    Returns world dict with: plan, cleaner, customer, address, series (refreshed),
    booking (the generated occurrence).
    """
    world = setup_series(cadence=cadence, first_occurrence_date=first_occurrence_date, home_size=home_size)
    series = world["series"]
    # PRD §3.4: a PlatformAdmin may generate only against a series whose
    # next_occurrence_date is at or before the current clock. The series was
    # created with the clock back at booking-world default (2026-06-01); advance
    # the clock to the first occurrence instant so generation is due.
    set_clock(first_occurrence_date)
    booking = get_success_data(
        api_client.generate_occurrence(series["id"], {"expected_series_version": series["version"]}, ADMIN)
    )
    world["booking"] = booking
    world["series"] = get_success_data(api_client.get_booking_series(series["id"], ADMIN))
    return world


# ---------------------------------------------------------------------------
# Tier 5 — multi-cleaner worlds (for assignment / double-booking)
# ---------------------------------------------------------------------------
def setup_two_cleaner_world(home_size="STUDIO", postal_code=TEST_POSTAL_CODE,
                            clock="2026-06-01T00:00:00Z"):
    """Active plan + two ACTIVE cleaners (c1, c2) serving the same area + customer + address.

    Returns dict: plan, cleaner, cleaner2, customer, address.
    """
    set_clock(clock)
    plan = create_active_plan()
    c1 = create_active_cleaner(service_postal_codes=[postal_code])
    c2 = create_active_cleaner(service_postal_codes=[postal_code])
    customer = create_customer()
    address = create_address(customer["id"], postal_code=postal_code, home_size=home_size)
    return {"plan": plan, "cleaner": c1, "cleaner2": c2, "customer": customer, "address": address}
