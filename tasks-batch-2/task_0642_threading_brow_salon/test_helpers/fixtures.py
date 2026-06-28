"""Composite setup helpers for the salon API.

These encapsulate the multi-step preambles that most test claims require: a salon
must be created, opened, and stocked with chairs / technicians / menu items /
members / packages before a queue ticket can be seated into a visit, completed,
settled, or voided. Each helper uses get_success_data() (lenient) internally so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion error.

Identity threading: Technician and Member are entity-backed roles (PRD §2.1), so
any ownership-gated call uses make_technician_headers(tech_id) /
make_member_headers(member_id) with the real entity id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_member_headers,
)
from . import factories as f
from .constants import TEST_CLOCK

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# --------------------------------------------------------------------------
# Tier 0: clock
# --------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the server logical clock (SalonManager-only test-driving capability)."""
    return get_success_data(api_client.set_clock(iso8601, MANAGER))


# --------------------------------------------------------------------------
# Tier 1: state progression — salon
# --------------------------------------------------------------------------
def create_salon(**overrides) -> dict:
    """Create a CLOSED salon. Returns the salon resource."""
    payload = f.create_salon_payload(**overrides)
    return get_success_data(api_client.create_salon(payload, MANAGER))


def create_and_open_salon(set_default_clock=True, **overrides) -> dict:
    """Create a salon and transition it to OPEN. Returns the OPEN salon resource
    (so its current version is the post-open version)."""
    if set_default_clock:
        set_clock(TEST_CLOCK)
    salon = create_salon(**overrides)
    opened = get_success_data(
        api_client.open_salon(
            salon["id"], {"expected_salon_version": salon["version"]}, MANAGER
        )
    )
    return opened


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy — floor resources
# --------------------------------------------------------------------------
def add_chair(salon_id, **overrides) -> dict:
    payload = f.create_chair_payload(salon_id, **overrides)
    return get_success_data(api_client.create_chair(payload, MANAGER))


def add_technician(salon_id, **overrides) -> dict:
    payload = f.create_technician_payload(salon_id, **overrides)
    return get_success_data(api_client.create_technician(payload, MANAGER))


def add_service_item(salon_id, **overrides) -> dict:
    payload = f.create_service_menu_item_payload(salon_id, **overrides)
    return get_success_data(api_client.create_service_menu_item(payload, MANAGER))


def add_add_on(salon_id, **overrides) -> dict:
    payload = f.create_add_on_payload(salon_id, **overrides)
    return get_success_data(api_client.create_add_on(payload, MANAGER))


def add_retail_product(salon_id, **overrides) -> dict:
    payload = f.create_retail_product_payload(salon_id, **overrides)
    return get_success_data(api_client.create_retail_product(payload, MANAGER))


def add_member(salon_id, **overrides) -> dict:
    payload = f.create_member_payload(salon_id, **overrides)
    return get_success_data(api_client.create_member(payload, FRONT_DESK))


def add_active_package(member_id, tier="SILVER") -> dict:
    """Create a PENDING package and activate it (member acts on own package)."""
    pkg = get_success_data(
        api_client.create_package(f.create_package_payload(member_id, tier), FRONT_DESK)
    )
    activated = get_success_data(
        api_client.activate_package(pkg["id"], make_member_headers(member_id))
    )
    return activated


def setup_open_salon_basic(
    sanitation_minutes=5,
    certified_addon_codes=None,
    tech_cert_expiry=None,
    package_eligible=False,
    loyalty_earn_rate_bps=500,
    **salon_overrides,
) -> dict:
    """Active salon + one OPEN chair + one AVAILABLE technician + one LISTED menu item
    + one member. Returns a dict of all created resources keyed by short names.

    The returned salon's `version` is the live version (advances as chairs are seated).
    """
    salon = create_and_open_salon(
        loyalty_earn_rate_bps=loyalty_earn_rate_bps, **salon_overrides
    )
    chair = add_chair(salon["id"], sanitation_minutes=sanitation_minutes)
    tech_kwargs = {}
    if certified_addon_codes is not None:
        tech_kwargs["certified_addon_codes"] = certified_addon_codes
    if tech_cert_expiry is not None:
        tech_kwargs["sanitation_cert_expiry"] = tech_cert_expiry
    tech = add_technician(salon["id"], **tech_kwargs)
    svc = add_service_item(salon["id"], package_eligible=package_eligible)
    member = add_member(salon["id"])
    return {
        "salon": salon,
        "chair": chair,
        "tech": tech,
        "svc": svc,
        "member": member,
    }


# --------------------------------------------------------------------------
# Tier 3: queue + seating lifecycle shortcuts
# --------------------------------------------------------------------------
def join_queue(salon_id, member_id, service_item_id) -> dict:
    payload = f.create_queue_ticket_payload(salon_id, member_id, service_item_id)
    return get_success_data(api_client.create_queue_ticket(payload, FRONT_DESK))


def call_ticket(ticket_id, allow_skip=False) -> dict:
    payload = {"allow_skip": True} if allow_skip else {}
    return get_success_data(api_client.call_queue_ticket(ticket_id, FRONT_DESK, payload))


def join_and_call(salon_id, member_id, service_item_id, allow_skip=False) -> dict:
    """Create a WAITING ticket and move it to CALLED. Returns the CALLED ticket."""
    ticket = join_queue(salon_id, member_id, service_item_id)
    call_ticket(ticket["id"], allow_skip=allow_skip)
    return ticket


def seat_visit(
    salon_id, ticket_id, chair_id, technician_id, expected_salon_version,
    membership_package_id=None,
) -> dict:
    """Seat a CALLED ticket into an IN_SERVICE visit. Returns the visit resource."""
    overrides = {}
    if membership_package_id is not None:
        overrides["membership_package_id"] = membership_package_id
    payload = f.create_service_visit_payload(
        salon_id, ticket_id, chair_id, technician_id, expected_salon_version, **overrides
    )
    return get_success_data(api_client.create_service_visit(payload, FRONT_DESK))


def setup_seated_visit(
    sanitation_minutes=5,
    certified_addon_codes=None,
    package_eligible=False,
    tier=None,
    loyalty_earn_rate_bps=500,
) -> dict:
    """Full preamble through an IN_SERVICE / UNPAID seated visit.

    Returns a dict with salon, chair, tech, svc, member, (package), ticket, visit.
    If tier is given, the member gets an ACTIVE package of that tier and the visit
    is seated drawing from it.
    """
    base = setup_open_salon_basic(
        sanitation_minutes=sanitation_minutes,
        certified_addon_codes=certified_addon_codes,
        package_eligible=package_eligible,
        loyalty_earn_rate_bps=loyalty_earn_rate_bps,
    )
    salon, chair, tech, svc, member = (
        base["salon"], base["chair"], base["tech"], base["svc"], base["member"]
    )
    package = None
    if tier is not None:
        package = add_active_package(member["id"], tier)
    ticket = join_and_call(salon["id"], member["id"], svc["id"])
    visit = seat_visit(
        salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"],
        membership_package_id=(package["id"] if package else None),
    )
    return {
        "salon": salon,
        "chair": chair,
        "tech": tech,
        "svc": svc,
        "member": member,
        "package": package,
        "ticket": ticket,
        "visit": visit,
    }


def add_addon_line(visit_id, add_on_id, technician_id, quantity=1) -> dict:
    """Add an ADDON line as the assigned technician (ownership-gated when acting as tech)."""
    payload = f.create_line_item_payload("ADDON", add_on_id, quantity=quantity)
    return get_success_data(
        api_client.add_line_item(visit_id, payload, make_technician_headers(technician_id))
    )


def add_retail_line(visit_id, retail_id, quantity=1) -> dict:
    payload = f.create_line_item_payload("RETAIL", retail_id, quantity=quantity)
    return get_success_data(api_client.add_line_item(visit_id, payload, FRONT_DESK))


def complete_visit(visit_id, technician_id) -> dict:
    """Complete the service as the assigned technician."""
    return get_success_data(
        api_client.complete_service_visit(visit_id, make_technician_headers(technician_id))
    )


def settle_visit(visit_id, redeem_points=None) -> dict:
    payload = {"redeem_points": redeem_points} if redeem_points is not None else {}
    return get_success_data(api_client.settle_service_visit(visit_id, FRONT_DESK, payload))


# --------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# --------------------------------------------------------------------------
def drive_member_to_strikes(salon_id, service_item_id, num_strikes) -> dict:
    """Create a member and record `num_strikes` no-shows on them.

    Each iteration: join queue -> call -> no-show. Returns the member resource
    (re-read so loyalty_balance / no_show_strikes / status are recomputed).
    Requires the salon to be OPEN.
    """
    member = add_member(salon_id)
    for _ in range(num_strikes):
        ticket = join_queue(salon_id, member["id"], service_item_id)
        call_ticket(ticket["id"])
        get_success_data(api_client.no_show_queue_ticket(ticket["id"], FRONT_DESK))
    return get_success_data(api_client.get_member(member["id"], FRONT_DESK))


def setup_divergence_visit(tier="SILVER", package_eligible=True, loyalty_earn_rate_bps=500):
    """Seated visit with TINT add-on + SERUM retail lines drawing from a `tier` package.

    Mirrors the dual_variant / combinatorial difficulty preambles:
      service BROW_THREAD base 2000 (package_eligible), AddOn TINT 1500, RetailProduct
      SERUM unit 3000 stock 10, member with an ACTIVE `tier` package, technician
      certified for TINT. Returns dict with salon, chair, tech, svc, tint, serum,
      member, package, ticket, visit.
    """
    salon = create_and_open_salon(loyalty_earn_rate_bps=loyalty_earn_rate_bps)
    chair = add_chair(salon["id"], sanitation_minutes=5)
    tech = add_technician(salon["id"], certified_addon_codes=["TINT"])
    svc = add_service_item(salon["id"], code="BROW_THREAD", base_price_cents=2000,
                           est_minutes=15, package_eligible=package_eligible)
    tint = add_add_on(salon["id"], code="TINT", name="Brow Tint", price_cents=1500,
                      requires_certification=True)
    serum = add_retail_product(salon["id"], sku="SERUM", name="Brow Serum",
                               unit_price_cents=3000, initial_stock_qty=10)
    member = add_member(salon["id"])
    package = add_active_package(member["id"], tier)
    ticket = join_and_call(salon["id"], member["id"], svc["id"])
    visit = seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"],
                       salon["version"], membership_package_id=package["id"])
    add_addon_line(visit["id"], tint["id"], tech["id"], quantity=1)
    add_retail_line(visit["id"], serum["id"], quantity=1)
    return {
        "salon": salon, "chair": chair, "tech": tech, "svc": svc,
        "tint": tint, "serum": serum, "member": member, "package": package,
        "ticket": ticket, "visit": visit,
    }
