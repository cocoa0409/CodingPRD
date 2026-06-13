"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
(catalog -> unit -> customer -> reservation -> confirm -> fit-check -> pickup ->
return -> finalize, plus the party-coordination lifecycle). These helpers
encapsulate those sequences so tests focus on assertions.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors. Every helper builds its preconditions from scratch
against an empty database using only PRD-declared endpoints.

Identity threading: Customer is entity_backed, so ownership-gated Customer calls
(book own reservation, lock/dissolve own party) use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_catalog_payload,
    create_garment_unit_payload,
    create_customer_payload,
    create_measurement_profile_payload,
    create_reservation_payload,
    create_alteration_payload,
    create_fit_check_payload,
    create_party_order_payload,
    return_payload,
)
from .test_users import TEST_USERS, make_customer_headers

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]

# A fixed baseline clock instant before all the September event dates used below.
BASELINE_CLOCK = "2026-08-01T00:00:00Z"

# Chest measurement that recommends size M (96 <= 100 < 106), giving a PASS fit
# against an M-requested reservation.
CHEST_FOR_M = 100


# ─── Primitive builders ───────────────────────────────────────────────

def set_clock(to_iso: str = BASELINE_CLOCK):
    """Set the logical clock without sweeping (pure setup)."""
    get_success_data(api_client.clock_set({"to_iso8601": to_iso}, MANAGER))


def advance_clock(to_iso: str):
    """Advance the clock and run the overdue + cleaning sweep."""
    return api_client.clock_advance({"to_iso8601": to_iso}, MANAGER)


def create_catalog(**overrides):
    """Create a catalog. Returns the catalog dict."""
    return get_success_data(api_client.create_catalog(create_catalog_payload(**overrides), MANAGER))


def create_unit(catalog_id: str, size_code: str = "M"):
    """Add one garment unit to a catalog. Returns the unit dict."""
    return get_success_data(api_client.create_garment_unit(
        create_garment_unit_payload(catalog_id, size_code), MANAGER))


def create_customer(**overrides):
    """Register a customer (via StoreClerk). Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), CLERK))


def create_measurement_profile(customer_id: str, chest_cm: int = CHEST_FOR_M, **overrides):
    """Create a measurement profile for a customer. Returns the profile dict."""
    return get_success_data(api_client.create_measurement_profile(
        customer_id, create_measurement_profile_payload(chest_cm=chest_cm, **overrides), CLERK))


def create_reservation(customer_id: str, catalog_id: str, **overrides):
    """Book a PENDING reservation (via StoreClerk). Returns the reservation dict."""
    return get_success_data(api_client.create_reservation(
        create_reservation_payload(customer_id, catalog_id, **overrides), CLERK))


# ─── Tier 1/2: catalog + unit + customer base setup ───────────────────

def setup_catalog_unit_customer(catalog_overrides=None, size_code="M"):
    """Clock set + catalog + one unit + one customer.
    Returns (catalog, unit, customer)."""
    set_clock()
    catalog = create_catalog(**(catalog_overrides or {}))
    unit = create_unit(catalog["id"], size_code)
    customer = create_customer()
    return catalog, unit, customer


# ─── Tier 3: reservation lifecycle shortcuts ──────────────────────────

def confirm(reservation_id: str, expected_party_order_version=None):
    """Confirm a reservation. Returns the response (caller validates)."""
    payload = {}
    if expected_party_order_version is not None:
        payload["expected_party_order_version"] = expected_party_order_version
    return api_client.confirm_reservation(reservation_id, payload, CLERK)


def create_confirmed_reservation(catalog_overrides=None, size_code="M",
                                 requested_size_code="M", reservation_overrides=None):
    """Build catalog + unit + customer + a CONFIRMED reservation.
    Returns (catalog, unit, customer, reservation)."""
    catalog, unit, customer = setup_catalog_unit_customer(catalog_overrides, size_code)
    resv = create_reservation(customer["id"], catalog["id"],
                              requested_size_code=requested_size_code,
                              **(reservation_overrides or {}))
    resv = get_success_data(confirm(resv["id"]))
    return catalog, unit, customer, resv


def create_picked_up_reservation(catalog_overrides=None,
                                 reservation_overrides=None,
                                 chest_cm: int = CHEST_FOR_M):
    """Build catalog + unit + customer + measurement profile + a PICKED_UP
    reservation (confirm -> PASS fit-check -> pickup). The measurement profile's
    chest defaults so the recommended size matches the requested M, giving PASS.
    Returns (catalog, unit, customer, reservation)."""
    catalog, unit, customer = setup_catalog_unit_customer(catalog_overrides, "M")
    mp = create_measurement_profile(customer["id"], chest_cm=chest_cm)
    resv = create_reservation(customer["id"], catalog["id"],
                              requested_size_code="M", **(reservation_overrides or {}))
    resv = get_success_data(confirm(resv["id"]))
    get_success_data(api_client.create_fit_check(
        create_fit_check_payload(resv["id"], mp["id"]), CLERK))
    resv = get_success_data(api_client.pickup_reservation(resv["id"], CLERK))
    return catalog, unit, customer, resv


def return_reservation(reservation_id: str, returned_at_iso: str, disposition: str = "CLEAN"):
    """Record a return; returns the Settlement dict."""
    return get_success_data(api_client.return_reservation(
        reservation_id, return_payload(returned_at_iso, disposition), CLERK))


def create_settled_reservation(catalog_overrides=None, reservation_overrides=None,
                               returned_at_iso: str = "2026-09-03T12:00:00Z",
                               disposition: str = "CLEAN"):
    """Full lifecycle through SETTLED: picked up -> return -> finalize.
    Returns (catalog, unit, customer, reservation, settlement)."""
    catalog, unit, customer, resv = create_picked_up_reservation(
        catalog_overrides=catalog_overrides, reservation_overrides=reservation_overrides)
    settlement = return_reservation(resv["id"], returned_at_iso, disposition)
    get_success_data(api_client.finalize_settlement(settlement["id"], CLERK))
    resv = get_success_data(api_client.get_reservation(resv["id"], CLERK))
    return catalog, unit, customer, resv, settlement


# ─── Tier 4: party-coordination lifecycle ─────────────────────────────

def create_party(coordinator_id: str, required_member_count: int = 1,
                 event_date_iso: str = "2026-09-06T00:00:00Z"):
    """Create a PartyOrder coordinated by coordinator_id. Returns the party dict.
    Uses the coordinator's own Customer identity (ownership-gated create)."""
    return get_success_data(api_client.create_party_order(
        create_party_order_payload(coordinator_id,
                                   event_date_iso=event_date_iso,
                                   required_member_count=required_member_count),
        make_customer_headers(coordinator_id)))


def setup_party_with_confirmed_member(required_member_count: int = 1,
                                      event_date_iso: str = "2026-09-06T00:00:00Z",
                                      reservation_overrides=None):
    """Catalog + unit + coordinator-customer + a PartyOrder with one CONFIRMED
    member reservation booked by the coordinator. With required_member_count == 1
    this leaves the party READY; with 2+, FORMING.

    Returns dict with keys:
      catalog, unit, coordinator, party, party_version_after_confirm, reservation
    """
    set_clock()
    catalog = create_catalog()
    unit = create_unit(catalog["id"], "M")
    coordinator = create_customer()
    coord_headers = make_customer_headers(coordinator["id"])

    party = create_party(coordinator["id"], required_member_count, event_date_iso)

    resv = get_success_data(api_client.create_reservation(
        create_reservation_payload(
            coordinator["id"], catalog["id"], requested_size_code="M",
            event_date_iso=event_date_iso,
            party_order_id=party["id"],
            **(reservation_overrides or {})),
        coord_headers))
    # Confirm consumes the party's current version, then bumps it.
    get_success_data(confirm(resv["id"], expected_party_order_version=party["version"]))
    party_after = get_success_data(api_client.get_party_order(party["id"], coord_headers))

    return {
        "catalog": catalog,
        "unit": unit,
        "coordinator": coordinator,
        "party": party,
        "party_version_after_confirm": party_after["version"],
        "reservation": resv,
    }


def setup_ready_party_locked(event_date_iso: str = "2026-09-06T00:00:00Z"):
    """A READY party (required 1, one confirmed member) that the coordinator then
    LOCKS. Returns the dict from setup_party_with_confirmed_member plus
    'party_version_after_lock'."""
    info = setup_party_with_confirmed_member(
        required_member_count=1, event_date_iso=event_date_iso)
    coord_headers = make_customer_headers(info["coordinator"]["id"])
    locked = get_success_data(api_client.lock_party_order(
        info["party"]["id"],
        {"expected_party_order_version": info["party_version_after_confirm"]},
        coord_headers))
    info["party_version_after_lock"] = locked["version"]
    return info


# ─── Ledger inspection ────────────────────────────────────────────────

def ledger_for_reservation(reservation_id: str):
    """Return the list of LedgerEntry dicts scoped to one reservation."""
    res = api_client.list_ledger_entries(CLERK, params={"reservation_id": reservation_id})
    return get_success_data(res)


def available_unit_count(catalog_id: str, size_code: str = "M"):
    """Return total_count of AVAILABLE units of a given size in a catalog."""
    res = api_client.list_garment_units(
        CLERK, params={"catalog_id": catalog_id, "status": "AVAILABLE", "size_code": size_code})
    body = res.json()
    return body["meta"]["total_count"]
