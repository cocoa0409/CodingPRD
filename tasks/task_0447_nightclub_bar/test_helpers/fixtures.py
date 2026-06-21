"""Composite setup helpers for multi-step test prerequisites (Nightclub & Bar Service).

Each helper builds its preconditions from scratch using only PRD-declared endpoints
(the per-test server starts against an empty DB). Uses get_success_data() so a broken
setup surfaces as a clear "Setup step failed" error rather than a confusing assertion.

Identity note: all roles are opaque operator identities (PRD §2.1); ownership is never
matched against X-User-ID, so the shared role headers are canonical throughout.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_promoter_payload,
    create_guest_list_payload,
    create_id_check_payload,
    create_entry_payload,
    create_reservation_payload,
    create_tab_payload,
    create_tab_item_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]
DOOR = TEST_USERS["door_host_headers"]
BAR = TEST_USERS["bartender_headers"]
SECURITY = TEST_USERS["security_officer_headers"]


# ─── Logical clock ───────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: Base entities ───────────────────────────────────────────────────

def create_venue(**overrides) -> dict:
    """Create a venue (posture OPEN, version 1). Returns the venue."""
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), ADMIN))


def create_promoter(venue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_promoter(create_promoter_payload(venue_id, **overrides), FLOOR)
    )


def create_guest_list_entry(venue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_guest_list_entry(create_guest_list_payload(venue_id, **overrides), DOOR)
    )


def create_id_check(venue_id: str, **overrides) -> dict:
    """Run an ID check; returns the IdCheck (with computed outcome)."""
    return get_success_data(
        api_client.create_id_check(create_id_check_payload(venue_id, **overrides), DOOR)
    )


def create_pass_id_check(venue_id: str, patron_name: str = "Patron", **overrides) -> dict:
    """A comfortably-of-age, unexpired ID check that yields outcome PASS."""
    overrides.setdefault("date_of_birth", "1990-01-01")
    overrides.setdefault("id_expiry", "2030-01-01")
    return create_id_check(venue_id, patron_name=patron_name, **overrides)


# ─── Tier 2: Admission helpers ───────────────────────────────────────────────

def admit_patron(venue_id: str, expected_venue_version: int, patron_name: str = "Patron",
                 guest_list_entry_id=None, **overrides):
    """Create a PASS id-check + admit one patron. Returns (entry, new_venue_version).

    Threads the venue version: the admit bumps Venue.version, so the returned
    value is the version to use on the next OCC-guarded write.
    """
    idc = create_pass_id_check(venue_id, patron_name=patron_name)
    payload_overrides = dict(overrides)
    if guest_list_entry_id is not None:
        payload_overrides["guest_list_entry_id"] = guest_list_entry_id
    entry = get_success_data(
        api_client.create_entry(
            create_entry_payload(venue_id, idc["id"], expected_venue_version, **payload_overrides),
            DOOR,
        )
    )
    venue = get_success_data(api_client.get_venue(venue_id, ADMIN))
    return entry, venue["version"]


def venue_at_capacity(capacity: int = 1, **venue_overrides):
    """Create a venue at exactly `capacity` and admit `capacity` patrons so the
    room is full (posture AT_CAPACITY). Returns (venue, current_version).

    Uses real admit calls so each Entry is a normal INSIDE row.
    """
    venue = create_venue(fire_code_capacity=capacity, **venue_overrides)
    version = venue["version"]
    for i in range(capacity):
        _, version = admit_patron(venue["id"], version, patron_name=f"P{i}")
    venue = get_success_data(api_client.get_venue(venue["id"], ADMIN))
    return venue, venue["version"]


def venue_with_injected_occupancy(target_inside: int, **venue_overrides):
    """Create a venue and seed occupancy to `target_inside` via the admin
    occupancy injector. Returns (venue_after_inject, current_version).

    Used to reach the surge band cheaply (occupancy >= ceil(0.9*capacity)).
    """
    venue = create_venue(**venue_overrides)
    injected = get_success_data(api_client.inject_occupancy(venue["id"], target_inside, ADMIN))
    return injected, injected["version"]


# ─── Tier 3: Reservation helpers ─────────────────────────────────────────────

def book_reservation(venue_id: str, expected_venue_version: int, **overrides):
    """Book a reservation. Returns (reservation, new_venue_version)."""
    reservation = get_success_data(
        api_client.create_reservation(
            create_reservation_payload(venue_id, expected_venue_version, **overrides), FLOOR
        )
    )
    venue = get_success_data(api_client.get_venue(venue_id, ADMIN))
    return reservation, venue["version"]


def book_and_seat_reservation(venue_id: str, expected_venue_version: int, **overrides):
    """Book then seat a reservation. Returns (reservation_seated, new_venue_version)."""
    reservation, version = book_reservation(venue_id, expected_venue_version, **overrides)
    seated = get_success_data(api_client.seat_reservation(reservation["id"], FLOOR))
    return seated, version


# ─── Tier 4: Tab helpers ─────────────────────────────────────────────────────

def open_tab(venue_id: str, **overrides) -> dict:
    """Open a bar tab (status OPEN). Returns the tab."""
    return get_success_data(api_client.create_tab(create_tab_payload(venue_id, **overrides), BAR))


def add_item(tab_id: str, **overrides) -> dict:
    """Add a line item to a tab. Returns the TabItem."""
    return get_success_data(
        api_client.add_tab_item(tab_id, create_tab_item_payload(**overrides), BAR)
    )


def tab_with_items(venue_id: str, items: list, **tab_overrides):
    """Open a tab and add each item in `items` (a list of factory-override dicts).
    Returns (tab, [item, ...])."""
    tab = open_tab(venue_id, **tab_overrides)
    created = [add_item(tab["id"], **it) for it in items]
    return tab, created


def reservation_tab_with_items(venue_id: str, reservation_id: str, items: list, **tab_overrides):
    """Open a tab linked to a (seated) reservation and add items.
    Returns (tab, [item, ...])."""
    tab = open_tab(venue_id, reservation_id=reservation_id, **tab_overrides)
    created = [add_item(tab["id"], **it) for it in items]
    return tab, created


# ─── Tier 5: Last-call / closing clock states ────────────────────────────────

def venue_in_last_call(closing_time_utc: str = "2026-03-16T06:00:00Z",
                       last_call_offset_minutes: int = 30,
                       clock_at: str = "2026-03-16T05:45:00Z",
                       **venue_overrides):
    """Create a venue then advance the clock into its last-call window.
    Returns the venue read back after the clock advance (posture LAST_CALL).

    Default: closing 06:00, offset 30 -> LAST_CALL begins 05:30; clock set to 05:45.
    """
    venue = create_venue(
        closing_time_utc=closing_time_utc,
        last_call_offset_minutes=last_call_offset_minutes,
        **venue_overrides,
    )
    set_clock(clock_at)
    return get_success_data(api_client.get_venue(venue["id"], ADMIN))


def closed_venue(**venue_overrides) -> dict:
    """Create a venue and operator-close it (posture CLOSED). Returns the closed venue."""
    venue = create_venue(**venue_overrides)
    return get_success_data(api_client.close_venue(venue["id"], FLOOR))
