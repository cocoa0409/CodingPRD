"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

The test harness restarts the server (empty database) before every test, so every
fixture builds its entire precondition graph from scratch using PRD endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_venue_payload, create_attraction_payload, create_pricing_rule_payload,
    create_time_slot_payload, create_guest_payload, create_reservation_payload,
    create_ticket_payload, confirm_payload, create_scare_zone_payload,
    create_actor_shift_payload, create_pass_product_payload, create_pass_payload,
    create_closure_payload,
)
from .test_users import TEST_USERS, make_guest_headers

OPS = TEST_USERS["ops_headers"]
BOX = TEST_USERS["box_office_headers"]
ACTOR = TEST_USERS["actor_headers"]


# ─── Primitive single-step helpers ────────────────────────────────────────

def set_clock(iso: str):
    """Set the logical clock to an exact ISO 8601 UTC instant."""
    return get_success_data(api_client.set_clock(iso, OPS))


def create_venue(name="Fright Park"):
    """Create a venue. Returns the venue dict (CLEAR/OPEN, version 1)."""
    return get_success_data(api_client.create_venue(create_venue_payload(name=name), OPS))


def create_attraction(venue_id, **overrides):
    """Create an OPEN attraction under a venue. Returns the attraction dict."""
    return get_success_data(
        api_client.create_attraction(create_attraction_payload(venue_id, **overrides), OPS)
    )


def create_pricing_rule(attraction_id, tier="GA", **overrides):
    """Create a per-tier pricing rule. Returns the pricing rule dict."""
    return get_success_data(
        api_client.create_pricing_rule(
            attraction_id, create_pricing_rule_payload(tier=tier, **overrides), OPS
        )
    )


def create_time_slot(attraction_id, **overrides):
    """Create a SCHEDULED slot. Returns the slot dict (with version)."""
    return get_success_data(
        api_client.create_time_slot(attraction_id, create_time_slot_payload(**overrides), OPS)
    )


def create_guest(full_name="Test Guest", email="g@x.com", age=30):
    """Register a guest. Returns the guest dict (wallet 0, version 1)."""
    return get_success_data(
        api_client.create_guest(
            create_guest_payload(full_name=full_name, email=email, age=age), BOX
        )
    )


def create_reservation(venue_id, guest_id, **overrides):
    """Create a HELD reservation. Returns the reservation dict."""
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(venue_id, guest_id, **overrides), BOX
        )
    )


def add_ticket(reservation_id, time_slot_id, **overrides):
    """Add one ticket to a HELD reservation. Returns the ticket dict."""
    return get_success_data(
        api_client.add_ticket(
            reservation_id, create_ticket_payload(time_slot_id, **overrides), BOX
        )
    )


def get_slot_version(slot_id):
    """Re-read a slot and return its current version."""
    return get_success_data(api_client.get_time_slot(slot_id, BOX))["version"]


def get_attraction_version(attraction_id):
    """Re-read an attraction and return its current version."""
    return get_success_data(api_client.get_attraction(attraction_id, OPS))["version"]


# ─── Tier 1/2: Base scenarios ─────────────────────────────────────────────

def setup_venue_attraction_slot(att_overrides=None, slot_overrides=None,
                                pricing_overrides=None, with_pricing=True):
    """
    Venue + one OPEN attraction + (optional) GA pricing rule + one SCHEDULED slot.

    Returns (venue, attraction, slot). The slot dict carries its initial version.
    This is the most common base for reservation/pricing/capacity tests.
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"], **(att_overrides or {}))
    if with_pricing:
        create_pricing_rule(attraction["id"], **(pricing_overrides or {}))
    slot = create_time_slot(attraction["id"], **(slot_overrides or {}))
    return venue, attraction, slot


def create_held_reservation_with_ticket(venue_id, slot_id, guest=None,
                                        ticket_overrides=None, res_overrides=None):
    """
    A guest + HELD reservation with one ticket on `slot_id`.

    Returns (guest, reservation, ticket). Creates a fresh guest unless one is passed.
    """
    if guest is None:
        guest = create_guest()
    reservation = create_reservation(venue_id, guest["id"], **(res_overrides or {}))
    ticket = add_ticket(reservation["id"], slot_id, **(ticket_overrides or {}))
    return guest, reservation, ticket


def confirm_reservation(reservation_id, slot_id, headers=BOX):
    """Confirm a HELD reservation against the slot's current version. Returns the
    reservation dict after confirm."""
    slot_v = get_slot_version(slot_id)
    return get_success_data(
        api_client.confirm_reservation(reservation_id, confirm_payload(slot_v), headers)
    )


def create_reserved_reservation(venue_id, slot_id, guest=None,
                                ticket_overrides=None, res_overrides=None):
    """
    Full path to a RESERVED reservation of one ticket on `slot_id`.

    Returns (guest, reservation_after_confirm, ticket).
    """
    guest, reservation, ticket = create_held_reservation_with_ticket(
        venue_id, slot_id, guest=guest,
        ticket_overrides=ticket_overrides, res_overrides=res_overrides
    )
    reservation = confirm_reservation(reservation["id"], slot_id)
    return guest, reservation, ticket


def create_paid_reservation(venue_id, slot_id, guest=None,
                            ticket_overrides=None, res_overrides=None):
    """
    RESERVED + PAID reservation of one ticket on `slot_id`.

    Returns (guest, reservation_after_pay, ticket).
    """
    guest, reservation, ticket = create_reserved_reservation(
        venue_id, slot_id, guest=guest,
        ticket_overrides=ticket_overrides, res_overrides=res_overrides
    )
    reservation = get_success_data(api_client.pay_reservation(reservation["id"], BOX))
    return guest, reservation, ticket


# ─── Tier 4: Demand-ratio targeting (pricing boundary fixtures) ────────────

def preload_slot_to_demand_ratio(venue_id, slot_id, num_members,
                                 ticket_overrides=None):
    """
    Pre-load a slot to a known reserved_count by confirming a seed reservation of
    `num_members` GA tickets. After this call the slot's demand_ratio reflects
    num_members / capacity, so the NEXT confirm prices off that snapshot.

    Returns the slot dict re-read after the seed confirm (carrying the new version).
    """
    seed_guest = create_guest(full_name="Seed Guest", email="seed@x.com")
    seed_res = create_reservation(venue_id, seed_guest["id"])
    for _ in range(num_members):
        add_ticket(seed_res["id"], slot_id, **(ticket_overrides or {}))
    confirm_reservation(seed_res["id"], slot_id)
    return get_success_data(api_client.get_time_slot(slot_id, BOX))


def setup_priced_ticket_at_demand_ratio(preload_members, capacity,
                                        pricing_overrides=None):
    """
    Build the state for a dynamic-pricing assertion: a venue + attraction + GA
    pricing rule + slot of `capacity`, pre-loaded to `preload_members` reserved
    members (so demand_ratio == preload_members / capacity), then a fresh HELD
    reservation with one GA ticket ready to confirm.

    Returns (venue, attraction, slot_after_preload, reservation, ticket).
    The caller confirms `reservation` to freeze the ticket's price off the snapshot.
    """
    venue, attraction, slot = setup_venue_attraction_slot(
        slot_overrides={"capacity": capacity},
        pricing_overrides=pricing_overrides or {},
    )
    if preload_members > 0:
        slot = preload_slot_to_demand_ratio(venue["id"], slot["id"], preload_members)
    buyer = create_guest(full_name="Buyer", email="buyer@x.com")
    reservation = create_reservation(venue["id"], buyer["id"])
    ticket = add_ticket(reservation["id"], slot["id"])
    return venue, attraction, slot, reservation, ticket


# ─── Tier 3: Scare zones / actor shifts / admission readiness ──────────────

def create_staffed_zone(attraction_id, actor_user_id="actor-1", min_actors=1,
                        shift_start="2026-10-31T18:00:00Z",
                        shift_end="2026-10-31T22:00:00Z"):
    """
    Create a scare zone under an attraction and bring it to STAFFED by scheduling
    and checking in `min_actors` actor shifts. Assumes the clock is already inside
    the shift window. Returns (zone, list_of_shifts).
    """
    zone = get_success_data(
        api_client.create_scare_zone(
            attraction_id, create_scare_zone_payload(min_actors=min_actors), OPS
        )
    )
    shifts = []
    for i in range(min_actors):
        # Distinct actor_user_id per shift so the 30-min rest-buffer rule never trips.
        uid = f"{actor_user_id}-{i}" if min_actors > 1 else actor_user_id
        shift = get_success_data(
            api_client.create_actor_shift(
                zone["id"],
                create_actor_shift_payload(uid, shift_start, shift_end),
                OPS,
            )
        )
        get_success_data(api_client.check_in_shift(shift["id"], ACTOR))
        shifts.append(shift)
    return zone, shifts


def setup_admission_ready(clock="2026-10-31T18:30:00Z",
                          att_overrides=None,
                          slot_overrides=None,
                          ticket_overrides=None,
                          staff_zone=True,
                          min_actors=1):
    """
    Full setup for an admit test: clock inside window, venue + attraction +
    pricing + slot, an optional STAFFED scare zone, and a RESERVED+PAID reservation
    of one ticket on the slot.

    Returns (venue, attraction, slot, zone_or_None, guest, reservation, ticket).
    """
    set_clock(clock)
    venue = create_venue()
    attraction = create_attraction(venue["id"], **(att_overrides or {}))
    create_pricing_rule(attraction["id"])
    zone = None
    if staff_zone:
        zone, _ = create_staffed_zone(attraction["id"], min_actors=min_actors)
    slot = create_time_slot(attraction["id"], **(slot_overrides or {}))
    guest, reservation, ticket = create_paid_reservation(
        venue["id"], slot["id"], ticket_overrides=ticket_overrides
    )
    return venue, attraction, slot, zone, guest, reservation, ticket


# ─── Passes ────────────────────────────────────────────────────────────────

def create_pass_product(venue_id, kind="SEASON", **overrides):
    """Create a pass product under a venue. Returns the pass product dict."""
    return get_success_data(
        api_client.create_pass_product(
            venue_id, create_pass_product_payload(kind=kind, **overrides), OPS
        )
    )


def issue_pass(pass_product_id, guest_id):
    """Issue (purchase) a pass for a guest. Returns the pass dict."""
    return get_success_data(
        api_client.create_pass(create_pass_payload(pass_product_id, guest_id), BOX)
    )


# ─── Attraction pause / closure helpers ────────────────────────────────────

def open_closure(attraction_id, reason="SAFETY"):
    """Open a closure on an attraction at its current version (pauses it).
    Returns the closure dict."""
    att_v = get_attraction_version(attraction_id)
    return get_success_data(
        api_client.create_closure(
            attraction_id, create_closure_payload(reason, att_v), OPS
        )
    )
