"""Composite setup helpers for multi-step test prerequisites (Travel Agency Tour Booking API).

Uses get_success_data() (lenient validator) internally, so setup failures surface as
clear "setup failed" errors rather than confusing assertion failures. Every fixture
builds its preconditions from scratch using only PRD-declared endpoints, because the
harness restarts the server (empty DB) before every test.

Identity threading: AgencyAdmin/TravelAgent are opaque, so their shared header constants
are used directly. Supplier confirm/reject is ownership-gated, so those calls use
make_supplier_headers(supplier_id) with the real Supplier.id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_agency_payload, set_clock_payload, create_customer_payload,
    create_supplier_payload, create_tour_package_payload, create_booking_payload,
    add_traveler_payload, create_component_payload, create_insurance_payload,
    create_payment_payload, reserve_payload, confirm_payload,
)
from .test_users import TEST_USERS, make_supplier_headers

ADMIN = TEST_USERS["agency_admin_headers"]
AGENT = TEST_USERS["travel_agent_headers"]

# Default timestamps reused across fixtures.
DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"
DEFAULT_DEPARTURE = "2026-06-01T00:00:00.000Z"
DEFAULT_COMP_START = "2026-06-01T08:00:00.000Z"
DEFAULT_COMP_END = "2026-06-01T12:00:00.000Z"


# ─── Tier 1: Primitive provisioning ──────────────────────────────────────
def create_agency(name="Globe Tours", currency="USD", clock=None):
    """Create an agency; optionally set its simulation clock. Returns the agency dict."""
    ag = get_success_data(api_client.create_agency(
        create_agency_payload(name=name, currency=currency), ADMIN))
    if clock is not None:
        ag = get_success_data(api_client.set_clock(ag["id"], set_clock_payload(clock), ADMIN))
    return ag


def create_customer(agency_id, email="c@x.com", full_name="C One"):
    return get_success_data(api_client.create_customer(
        create_customer_payload(agency_id, email=email, full_name=full_name), ADMIN))


def create_supplier(agency_id, kind="FLIGHT", name="AutoAir", auto_confirm=False):
    return get_success_data(api_client.create_supplier(
        create_supplier_payload(agency_id, kind=kind, name=name, auto_confirm=auto_confirm), ADMIN))


def create_published_package(agency_id, **pkg_overrides):
    """Create a package and publish it. Returns the published package dict."""
    pkg = get_success_data(api_client.create_tour_package(
        create_tour_package_payload(agency_id, **pkg_overrides), AGENT))
    return get_success_data(api_client.publish_tour_package(pkg["id"], AGENT))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, AGENT))


def _booking_version(booking_id):
    return get_booking(booking_id)["version"]


# ─── Tier 2: Booking assembly ────────────────────────────────────────────
def open_draft_booking(agency_id, customer_id, package_id, departure_date=DEFAULT_DEPARTURE):
    """Open a DRAFT booking against a PUBLISHED package. Returns the booking dict."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(agency_id, customer_id, package_id,
                               departure_date=departure_date), AGENT))


def add_travelers(booking_id, count, start_version):
    """Add `count` travelers one at a time, threading expected_booking_version through
    the OCC check. Returns the booking's version after the final add."""
    version = start_version
    for i in range(count):
        get_success_data(api_client.add_traveler(
            booking_id, add_traveler_payload(version, full_name=f"T{i + 1}"), AGENT))
        version = _booking_version(booking_id)
    return version


def attach_insurance(booking_id, coverage_tier):
    return get_success_data(api_client.create_insurance_policy(
        create_insurance_payload(booking_id, coverage_tier), AGENT))


def request_component(booking_id, supplier_id, kind="FLIGHT",
                      starts_at=DEFAULT_COMP_START, ends_at=DEFAULT_COMP_END,
                      is_mandatory=True):
    return get_success_data(api_client.create_component(
        create_component_payload(booking_id, supplier_id, kind, starts_at, ends_at,
                                 is_mandatory=is_mandatory), AGENT))


def setup_draft_booking_with_travelers(num_travelers=1, clock=DEFAULT_CLOCK,
                                       departure_date=DEFAULT_DEPARTURE, pkg_overrides=None):
    """Active agency + customer + published package + DRAFT booking with `num_travelers`.
    Returns dict with keys: agency, customer, package, booking_id, version.
    """
    pkg_overrides = pkg_overrides or {}
    agency = create_agency(clock=clock)
    customer = create_customer(agency["id"])
    package = create_published_package(agency["id"], **pkg_overrides)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date=departure_date)
    version = booking["version"]
    if num_travelers > 0:
        version = add_travelers(booking["id"], num_travelers, version)
    return {
        "agency": agency,
        "customer": customer,
        "package": package,
        "booking_id": booking["id"],
        "version": version,
    }


# ─── Tier 3: Reservation + milestone shortcuts ───────────────────────────
def get_milestone_id(booking_id, kind):
    """Return the id of the booking's DEPOSIT or BALANCE milestone via the filtered list."""
    res = api_client.list_milestones(AGENT, params={"booking_id": booking_id, "kind": kind})
    items = res.json().get("data", [])
    assert items, f"setup failed: no {kind} milestone found for booking {booking_id}"
    return items[0]["id"]


def setup_reserved_booking(num_travelers=1, clock=DEFAULT_CLOCK,
                           departure_date=DEFAULT_DEPARTURE, pkg_overrides=None,
                           auto_confirm=True, premium_insurance=False,
                           comp_start=DEFAULT_COMP_START, comp_end=DEFAULT_COMP_END):
    """Full chain to a RESERVED booking with one mandatory FLIGHT component.

    Returns dict with: agency, customer, package, supplier, booking_id, version,
    deposit_ms_id, balance_ms_id, component_id.
    With auto_confirm=True the component is CONFIRMED at request time. With
    premium_insurance=True a PREMIUM policy is attached before reserve.
    """
    pkg_overrides = pkg_overrides or {}
    agency = create_agency(clock=clock)
    customer = create_customer(agency["id"])
    supplier = create_supplier(agency["id"], kind="FLIGHT", auto_confirm=auto_confirm)
    package = create_published_package(agency["id"], **pkg_overrides)
    booking = open_draft_booking(agency["id"], customer["id"], package["id"],
                                 departure_date=departure_date)
    version = add_travelers(booking["id"], num_travelers, booking["version"])
    if premium_insurance:
        attach_insurance(booking["id"], "PREMIUM")
    component = request_component(booking["id"], supplier["id"], kind="FLIGHT",
                                  starts_at=comp_start, ends_at=comp_end)
    version = _booking_version(booking["id"])
    reserved = get_success_data(api_client.reserve_booking(
        booking["id"], reserve_payload(version), AGENT))
    return {
        "agency": agency,
        "customer": customer,
        "package": package,
        "supplier": supplier,
        "booking_id": booking["id"],
        "version": reserved["version"],
        "deposit_ms_id": get_milestone_id(booking["id"], "DEPOSIT"),
        "balance_ms_id": get_milestone_id(booking["id"], "BALANCE"),
        "component_id": component["id"],
    }


def pay_milestone(booking_id, milestone_id, amount_cents, method="CARD"):
    return get_success_data(api_client.create_payment(
        create_payment_payload(booking_id, milestone_id, amount_cents, method=method), AGENT))


def setup_reserved_deposit_settled(num_travelers=1, deposit_amount=20000,
                                   clock=DEFAULT_CLOCK, departure_date=DEFAULT_DEPARTURE,
                                   pkg_overrides=None, auto_confirm=True):
    """RESERVED booking whose DEPOSIT milestone has been SETTLED by an exact payment.
    Returns the dict from setup_reserved_booking, with refreshed version.
    """
    ctx = setup_reserved_booking(num_travelers=num_travelers, clock=clock,
                                 departure_date=departure_date, pkg_overrides=pkg_overrides,
                                 auto_confirm=auto_confirm)
    pay_milestone(ctx["booking_id"], ctx["deposit_ms_id"], deposit_amount)
    ctx["version"] = _booking_version(ctx["booking_id"])
    return ctx


def setup_confirmed_booking(num_travelers=1, deposit_amount=20000,
                            clock=DEFAULT_CLOCK, departure_date=DEFAULT_DEPARTURE,
                            pkg_overrides=None):
    """CONFIRMED booking: reserve -> settle deposit -> confirm. auto_confirm supplier so
    the mandatory component is CONFIRMED. Returns the reserved-context dict, refreshed.
    """
    ctx = setup_reserved_deposit_settled(num_travelers=num_travelers,
                                         deposit_amount=deposit_amount, clock=clock,
                                         departure_date=departure_date,
                                         pkg_overrides=pkg_overrides, auto_confirm=True)
    confirmed = get_success_data(api_client.confirm_booking(
        ctx["booking_id"], confirm_payload(ctx["version"]), AGENT))
    ctx["version"] = confirmed["version"]
    return ctx


# ─── Tier 4: Cancellation-ready (paid-in-full) booking ───────────────────
def setup_reserved_paid_in_full(num_travelers=5, deposit_amount=99000, balance_amount=396000,
                                clock=DEFAULT_CLOCK, departure_date="2026-01-31T00:00:00.000Z",
                                pkg_overrides=None, comp_start="2026-01-31T08:00:00.000Z",
                                comp_end="2026-01-31T12:00:00.000Z"):
    """RESERVED booking with a PREMIUM policy, both DEPOSIT and BALANCE milestones SETTLED.

    Used by cancellation-refund difficulty instances (5 travelers @95000 + PREMIUM ins
    20000 => grand 495000, deposit 99000, balance 396000, paid 495000).
    Returns dict with: agency, customer, booking_id, version, deposit_ms_id, balance_ms_id.
    """
    pkg_overrides = pkg_overrides or {"deposit_pct": 20, "min_group_size_for_discount": 5}
    ctx = setup_reserved_booking(num_travelers=num_travelers, clock=clock,
                                 departure_date=departure_date, pkg_overrides=pkg_overrides,
                                 auto_confirm=True, premium_insurance=True,
                                 comp_start=comp_start, comp_end=comp_end)
    pay_milestone(ctx["booking_id"], ctx["deposit_ms_id"], deposit_amount)
    pay_milestone(ctx["booking_id"], ctx["balance_ms_id"], balance_amount)
    ctx["version"] = _booking_version(ctx["booking_id"])
    return ctx


# ─── Tier 5: Manual-supplier scenarios (no auto-confirm) ─────────────────
def setup_reserved_manual_component(num_travelers=1, clock=DEFAULT_CLOCK,
                                    departure_date=DEFAULT_DEPARTURE, pkg_overrides=None):
    """RESERVED booking whose mandatory FLIGHT component is on a MANUAL supplier and is
    still REQUESTED. Returns dict like setup_reserved_booking (supplier is manual).
    """
    return setup_reserved_booking(num_travelers=num_travelers, clock=clock,
                                  departure_date=departure_date, pkg_overrides=pkg_overrides,
                                  auto_confirm=False)


def supplier_confirm_component(supplier_id, component_id):
    return get_success_data(api_client.confirm_component(
        component_id, make_supplier_headers(supplier_id)))


def supplier_reject_component(supplier_id, component_id):
    return get_success_data(api_client.reject_component(
        component_id, make_supplier_headers(supplier_id)))
