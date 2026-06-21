"""Composite setup helpers for multi-step test prerequisites.

The test harness restarts the API server and wipes the database before every
test, so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. All setup calls use get_success_data() (lenient) so a
broken precondition surfaces as a clear "Setup step failed" error rather than a
confusing assertion failure.

Identity threading: the Customer role is entity_backed. Any ownership-gated
Customer call threads the real Customer.id through make_customer_headers(id);
the shared TEST_USERS["customer_headers"] constant is never used for ownership.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_package_payload,
    create_vehicle_size_rate_payload,
    create_addon_payload,
    create_service_bay_payload,
    create_mobile_unit_payload,
    create_membership_payload,
    create_appointment_payload,
    create_addon_line_payload,
    create_photo_payload,
    create_rework_claim_payload,
)
from .test_users import TEST_USERS, make_customer_headers

SCHEDULER = TEST_USERS["scheduler_headers"]
DETAILER = TEST_USERS["detailer_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ─── Clock control ────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server's logical UTC clock (Scheduler-authorized).

    The clock endpoint returns 200 with no business resource, so we assert the
    2xx status directly rather than parsing a resource envelope out of it.
    """
    resp = api_client.set_clock(to_iso8601, SCHEDULER)
    assert 200 <= resp.status_code < 300, (
        f"Setup step (set_clock {to_iso8601}) failed with HTTP {resp.status_code}: {resp.text}"
    )
    return resp


# ─── Tier 0: Catalog & resource seeding ───────────────────────────────

def seed_package(tier="FULL", **overrides):
    return get_success_data(
        api_client.create_package(create_package_payload(tier=tier, **overrides), SCHEDULER)
    )


def seed_vehicle_size_rate(vehicle_size="SEDAN", **overrides):
    return get_success_data(
        api_client.create_vehicle_size_rate(
            create_vehicle_size_rate_payload(vehicle_size=vehicle_size, **overrides), SCHEDULER
        )
    )


def seed_addon(addon_code="ENGINE_BAY", **overrides):
    return get_success_data(
        api_client.create_addon(create_addon_payload(addon_code=addon_code, **overrides), SCHEDULER)
    )


def create_customer(email="cust@example.com", full_name="Test Customer", **overrides):
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(email=email, full_name=full_name, **overrides), SCHEDULER
        )
    )


def create_service_bay(bay_code="BAY-1", supports_ceramic=False, **overrides):
    return get_success_data(
        api_client.create_service_bay(
            create_service_bay_payload(bay_code=bay_code, supports_ceramic=supports_ceramic, **overrides),
            SCHEDULER,
        )
    )


def create_mobile_unit(unit_code="UNIT-1", travel_buffer_minutes=30, **overrides):
    return get_success_data(
        api_client.create_mobile_unit(
            create_mobile_unit_payload(
                unit_code=unit_code, travel_buffer_minutes=travel_buffer_minutes, **overrides
            ),
            SCHEDULER,
        )
    )


def seed_catalog(tiers=("FULL",), sizes=("SEDAN",), addons=(), clock="2026-06-15T08:00:00Z"):
    """Set the clock then seed the requested package tiers, size rates, and
    add-ons. Returns nothing — callers seed only what their pricing needs."""
    if clock is not None:
        set_clock(clock)
    for t in tiers:
        seed_package(tier=t)
    for s in sizes:
        seed_vehicle_size_rate(vehicle_size=s)
    for a in addons:
        seed_addon(addon_code=a)


# ─── Tier 1: Membership progression ───────────────────────────────────

def create_active_membership(customer_id, default_vehicle_size="SEDAN"):
    """Create a PENDING_PAYMENT membership for an existing customer and
    activate it (grants 1 credit, freezes wash_credit_value_cents, sets
    Customer.membership_id). Returns the activated membership."""
    cust_headers = make_customer_headers(customer_id)
    mem = get_success_data(
        api_client.create_membership(
            create_membership_payload(customer_id, default_vehicle_size=default_vehicle_size),
            cust_headers,
        )
    )
    return get_success_data(api_client.activate_membership(mem["id"], cust_headers))


def setup_customer_with_active_membership(
    email="mem@example.com", default_vehicle_size="SEDAN", clock="2026-06-15T08:00:00Z",
):
    """Seed clock, create a customer, and give them an ACTIVE membership.
    Returns (customer, membership). Catalog (WASH + the credit size rate) must
    be seeded by the caller before activation values the wash credit."""
    if clock is not None:
        set_clock(clock)
    cust = create_customer(email=email)
    mem = create_active_membership(cust["id"], default_vehicle_size=default_vehicle_size)
    return cust, mem


# ─── Tier 2: Booking ──────────────────────────────────────────────────

def book_shop_appointment(customer_id, bay, tier="FULL", vehicle_size="SEDAN",
                          scheduled_start_utc="2026-06-15T09:00:00Z", **overrides):
    """Book a SHOP appointment using the bay's current version for the OCC
    check. `bay` is the ServiceBay dict (must carry a current `version`)."""
    payload = create_appointment_payload(
        customer_id, tier=tier, vehicle_size=vehicle_size, location_mode="SHOP",
        scheduled_start_utc=scheduled_start_utc, service_bay_id=bay["id"],
        expected_service_bay_version=bay["version"], **overrides,
    )
    return get_success_data(
        api_client.create_appointment(payload, make_customer_headers(customer_id))
    )


def book_mobile_appointment(customer_id, unit_id, tier="FULL", vehicle_size="SEDAN",
                            scheduled_start_utc="2026-06-15T09:00:00Z", **overrides):
    """Book a MOBILE appointment on the given unit."""
    payload = create_appointment_payload(
        customer_id, tier=tier, vehicle_size=vehicle_size, location_mode="MOBILE",
        scheduled_start_utc=scheduled_start_utc, mobile_unit_id=unit_id, **overrides,
    )
    return get_success_data(
        api_client.create_appointment(payload, make_customer_headers(customer_id))
    )


def add_addon_line(appointment_id, customer_id, addon_code="ENGINE_BAY"):
    return get_success_data(
        api_client.add_appointment_addon(
            appointment_id, create_addon_line_payload(addon_code=addon_code),
            make_customer_headers(customer_id),
        )
    )


# ─── Tier 3: Work lifecycle progression ───────────────────────────────

def attach_photo(appointment_id, phase="BEFORE", image_url=None):
    return get_success_data(
        api_client.add_photo(
            appointment_id,
            create_photo_payload(phase=phase, image_url=image_url or f"s3://{phase.lower()}.jpg"),
            DETAILER,
        )
    )


def advance_to_in_service(appointment_id):
    """BOOKED -> CHECKED_IN -> IN_PREP (BEFORE photo) -> IN_SERVICE."""
    get_success_data(api_client.check_in(appointment_id, DETAILER))
    attach_photo(appointment_id, "BEFORE")
    get_success_data(api_client.start_prep(appointment_id, DETAILER))
    return get_success_data(api_client.start_service(appointment_id, DETAILER))


def advance_to_ready_non_ceramic(appointment_id):
    """Drive a non-ceramic appointment all the way to READY (attaches AFTER
    photo, finish-service fires the final-price cascade)."""
    advance_to_in_service(appointment_id)
    attach_photo(appointment_id, "AFTER")
    return get_success_data(api_client.finish_service(appointment_id, DETAILER))


def advance_to_curing_ceramic(appointment_id):
    """Drive a CERAMIC appointment to CURING (finish-service from IN_SERVICE)."""
    advance_to_in_service(appointment_id)
    attach_photo(appointment_id, "AFTER")
    return get_success_data(api_client.finish_service(appointment_id, DETAILER))


def advance_ceramic_to_ready(appointment_id, release_utc):
    """Set the clock to the vehicle release instant and finish the cure
    (CURING -> READY). `release_utc` is the appointment's vehicle_release_utc."""
    advance_to_curing_ceramic(appointment_id)
    set_clock(release_utc)
    return get_success_data(api_client.finish_cure(appointment_id, DETAILER))


def pay_full(appointment_id, customer_id, amount_cents):
    """Pay the exact outstanding balance (appointment must be READY)."""
    return get_success_data(
        api_client.pay(appointment_id, {"amount_cents": amount_cents}, make_customer_headers(customer_id))
    )


def release_appointment(appointment_id):
    return get_success_data(api_client.release(appointment_id, DETAILER))


# ─── Tier 3b: Full-lifecycle shortcuts (to RELEASED) ──────────────────

def complete_non_ceramic_to_released(customer_id, unit_id, tier="FULL",
                                     vehicle_size="SEDAN", amount_cents=12000,
                                     scheduled_start_utc="2026-06-15T09:00:00Z"):
    """Book MOBILE -> drive to READY -> pay -> release. Returns the released
    appointment. Default 12000 matches FULL/SEDAN non-member."""
    appt = book_mobile_appointment(
        customer_id, unit_id, tier=tier, vehicle_size=vehicle_size,
        scheduled_start_utc=scheduled_start_utc,
    )
    advance_to_ready_non_ceramic(appt["id"])
    pay_full(appt["id"], customer_id, amount_cents)
    release_appointment(appt["id"])
    return get_success_data(api_client.get_appointment(appt["id"], make_customer_headers(customer_id)))


def complete_ceramic_shop_to_released(customer_id, bay, vehicle_size="SEDAN",
                                      amount_cents=50000,
                                      booking_start="2026-03-01T08:00:00Z",
                                      release_utc="2026-03-02T12:45:00Z"):
    """Book a CERAMIC SHOP appointment and drive it through cure, pay, release.
    Returns the released appointment. Defaults match a 50000 CERAMIC/SEDAN whose
    1725-minute window from 2026-03-01T08:00 releases at 2026-03-02T12:45."""
    appt = book_shop_appointment(
        customer_id, bay, tier="CERAMIC", vehicle_size=vehicle_size,
        scheduled_start_utc=booking_start,
    )
    advance_ceramic_to_ready(appt["id"], release_utc)
    pay_full(appt["id"], customer_id, amount_cents)
    release_appointment(appt["id"])
    return get_success_data(api_client.get_appointment(appt["id"], make_customer_headers(customer_id)))


# ─── Tier 4: Rework claim setup ───────────────────────────────────────

def file_rework_claim(customer_id, original_appointment_id, reason="defect noted",
                      filing_clock=None):
    """File a rework claim against a RELEASED appointment. Optionally set the
    clock first (to control filed_within_window). Returns the claim."""
    if filing_clock is not None:
        set_clock(filing_clock)
    return get_success_data(
        api_client.create_rework_claim(
            create_rework_claim_payload(original_appointment_id, reason=reason),
            make_customer_headers(customer_id),
        )
    )


def setup_released_ceramic_with_in_window_claim(
    email="rework@example.com", booking_start="2026-03-01T08:00:00Z",
    release_utc="2026-03-02T12:45:00Z", filing_clock="2026-03-10T00:00:00Z",
):
    """Full chain: seed CERAMIC catalog -> customer -> released CERAMIC/SEDAN
    appointment -> rework claim filed inside the 90-day window. Returns
    (customer, bay, original_appointment, claim)."""
    set_clock(booking_start)
    seed_package(tier="CERAMIC")
    seed_vehicle_size_rate(vehicle_size="SEDAN")
    cust = create_customer(email=email)
    bay = create_service_bay(bay_code="RW-BAY", supports_ceramic=True)
    orig = complete_ceramic_shop_to_released(
        cust["id"], bay, booking_start=booking_start, release_utc=release_utc,
    )
    claim = file_rework_claim(cust["id"], orig["id"], filing_clock=filing_clock)
    return cust, bay, orig, claim
