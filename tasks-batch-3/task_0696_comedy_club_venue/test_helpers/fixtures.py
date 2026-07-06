"""Composite setup helpers for the Comedy Club & Live-Show Venue platform.

Most interesting claims require the system to be in a multi-step state (a venue,
a published show with a section + tier, sometimes a table + server, sometimes a
collected reservation, sometimes an ended show with an open settlement). These
helpers encapsulate those preambles so tests focus on assertions.

The harness restarts the server and clears the database before every test, so
every helper builds its preconditions from scratch using only PRD endpoints.
Setup calls use get_success_data() (lenient) so a setup failure reads as
"Setup failed" rather than a confusing assertion error.

Identity threading: the only entity-backed role is Performer. After creating a
Performer, ownership-gated calls (counter, own guest list) use
make_performer_headers(performer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_performer_headers,
    make_patron_headers,
)
from .factories import (
    create_venue_payload,
    create_show_payload,
    create_section_payload,
    create_table_payload,
    create_tier_payload,
    create_performer_payload,
    create_lineup_slot_payload,
    create_reservation_payload,
    create_server_payload,
    create_private_event_payload,
    create_guest_list_entry_payload,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=FLOOR):
    """Advance the server's logical clock to a supplied instant."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Tier 1: simple resource creation
# ---------------------------------------------------------------------------
def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), BOOKER))


def create_draft_show(venue_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_show(venue_id, create_show_payload(**overrides), BOOKER)
    )


def create_performer(**overrides) -> dict:
    return get_success_data(
        api_client.create_performer(create_performer_payload(**overrides), BOOKER)
    )


def create_server(**overrides) -> dict:
    return get_success_data(
        api_client.create_server(create_server_payload(**overrides), FLOOR)
    )


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — venue + show + section + tier
# ---------------------------------------------------------------------------
def setup_ga_show_on_sale(
    venue_overrides=None,
    show_overrides=None,
    ga_capacity=100,
    price_cents=4500,
    tier_overrides=None,
):
    """Active GA scenario: venue (OPEN) -> DRAFT show -> GA section -> GA tier ->
    publish to ON_SALE. Returns dict with venue, show, section, tier."""
    venue = create_venue(**(venue_overrides or {}))
    show = create_draft_show(venue["id"], **(show_overrides or {}))
    section = get_success_data(
        api_client.create_section(
            venue["id"], show["id"],
            create_section_payload(kind="GA", label="Standing", ga_capacity=ga_capacity),
            BOOKER,
        )
    )
    # Merge defaults with caller overrides so a tier_override of "name" or
    # "price_cents" replaces the default rather than colliding with an explicit
    # keyword (which would raise "multiple values for keyword argument").
    tier_kwargs = {"name": "GA", "price_cents": price_cents}
    tier_kwargs.update(tier_overrides or {})
    tier = get_success_data(
        api_client.create_tier(
            venue["id"], show["id"],
            create_tier_payload(section["id"], **tier_kwargs),
            BOOKER,
        )
    )
    get_success_data(api_client.publish_show(venue["id"], show["id"], BOOKER))
    show = get_success_data(api_client.get_show(show["id"], BOOKER))
    return {"venue": venue, "show": show, "section": section, "tier": tier}


def setup_table_show_on_sale(
    venue_overrides=None,
    show_overrides=None,
    seats=4,
    min_items_per_seat=None,
    price_cents=4500,
    server_overrides=None,
    assign_server=True,
):
    """Active TABLE scenario: venue -> DRAFT show -> TABLE section -> table ->
    (optionally) a server assigned to the table -> TABLE tier -> publish ON_SALE.
    Returns dict with venue, show, section, table (re-read after server assign),
    tier, server (or None), table_version (current table version)."""
    venue = create_venue(**(venue_overrides or {}))
    show = create_draft_show(venue["id"], **(show_overrides or {}))
    section = get_success_data(
        api_client.create_section(
            venue["id"], show["id"],
            create_section_payload(kind="TABLE", label="Floor", ga_capacity=None),
            BOOKER,
        )
    )
    table_payload = create_table_payload(table_number="T1", seats=seats)
    if min_items_per_seat is not None:
        table_payload["min_items_per_seat"] = min_items_per_seat
    table = get_success_data(
        api_client.create_table(venue["id"], show["id"], section["id"], table_payload, FLOOR)
    )
    tier = get_success_data(
        api_client.create_tier(
            venue["id"], show["id"],
            create_tier_payload(section["id"], name="Table Seat", price_cents=price_cents),
            BOOKER,
        )
    )
    server = None
    table_version = table["version"]
    if assign_server:
        server = create_server(**(server_overrides or {}))
        table = get_success_data(
            api_client.assign_server(table["id"], {"server_id": server["id"]}, FLOOR)
        )
        table_version = table["version"]
    get_success_data(api_client.publish_show(venue["id"], show["id"], BOOKER))
    show = get_success_data(api_client.get_show(show["id"], BOOKER))
    return {
        "venue": venue, "show": show, "section": section, "table": table,
        "tier": tier, "server": server, "table_version": table_version,
    }


# ---------------------------------------------------------------------------
# Tier 3: reservations in various lifecycle stages
# ---------------------------------------------------------------------------
def create_ga_reservation(scenario, patron_id="patron-default", party_size=2,
                          is_comp=False, headers=BOX_OFFICE):
    """Create a GA reservation against a setup_ga_show_on_sale scenario."""
    payload = create_reservation_payload(
        scenario["show"]["id"], scenario["section"]["id"], scenario["tier"]["id"],
        patron_id=patron_id, party_size=party_size, is_comp=is_comp,
    )
    return get_success_data(api_client.create_reservation(payload, headers))


def create_table_reservation(scenario, patron_id="patron-default", party_size=2,
                             headers=BOX_OFFICE):
    """Create a TABLE-section reservation against a setup_table_show_on_sale scenario."""
    payload = create_reservation_payload(
        scenario["show"]["id"], scenario["section"]["id"], scenario["tier"]["id"],
        patron_id=patron_id, party_size=party_size,
    )
    return get_success_data(api_client.create_reservation(payload, headers))


def reservation_collected(scenario, **res_overrides):
    """A GA reservation advanced to settlement_status TICKET_PAID."""
    res = create_ga_reservation(scenario, **res_overrides)
    res = get_success_data(api_client.collect_ticket(res["id"], BOX_OFFICE))
    return res


def assign_table_to_reservation(scenario, reservation_id, table_id=None,
                                table_version=None):
    """Assign the scenario's table to a reservation using the OCC version."""
    tid = table_id or scenario["table"]["id"]
    tv = table_version if table_version is not None else scenario["table_version"]
    return get_success_data(
        api_client.assign_table(
            reservation_id, {"table_id": tid, "expected_table_version": tv}, FLOOR
        )
    )


def create_table_reservation_assigned(scenario, patron_id="patron-default", party_size=2):
    """TABLE reservation created then assigned the scenario's table (status HELD)."""
    res = create_table_reservation(scenario, patron_id=patron_id, party_size=party_size)
    res = assign_table_to_reservation(scenario, res["id"])
    return res


# ---------------------------------------------------------------------------
# Tier 4: lineup-slot negotiation state
# ---------------------------------------------------------------------------
def setup_offered_lineup_slot(offered_fee_cents=30000, role="HEADLINER",
                              slot_order=1, standard_fee_cents=30000,
                              show_overrides=None):
    """Venue -> DRAFT show -> performer -> OFFERED lineup slot.
    Returns dict with venue, show, performer, slot."""
    venue = create_venue()
    show = create_draft_show(venue["id"], **(show_overrides or {}))
    performer = create_performer(standard_fee_cents=standard_fee_cents)
    slot = get_success_data(
        api_client.create_lineup_slot(
            create_lineup_slot_payload(
                show["id"], performer["id"], slot_order=slot_order, role=role,
                offered_fee_cents=offered_fee_cents,
            ),
            BOOKER,
        )
    )
    return {"venue": venue, "show": show, "performer": performer, "slot": slot}


def counter_slot(performer_id, slot_id, counter_fee_cents):
    """Performer counters an offer (ownership-gated; uses entity-backed headers)."""
    return get_success_data(
        api_client.counter_lineup_slot(
            slot_id, {"counter_fee_cents": counter_fee_cents},
            make_performer_headers(performer_id),
        )
    )


def revise_offer(slot_id, new_offered_fee_cents):
    """Booker revises an offer (COUNTERED -> OFFERED)."""
    return get_success_data(
        api_client.revise_offer(slot_id, {"new_offered_fee_cents": new_offered_fee_cents}, BOOKER)
    )


def setup_slot_at_counter_limit(offered_fee_cents=20000):
    """Drive a lineup slot through three counters so counter_rounds == 3,
    currently COUNTERED. Returns dict with venue, show, performer, slot."""
    ctx = setup_offered_lineup_slot(offered_fee_cents=offered_fee_cents,
                                    role="FEATURE", standard_fee_cents=offered_fee_cents)
    pid = ctx["performer"]["id"]
    sid = ctx["slot"]["id"]
    counter_slot(pid, sid, offered_fee_cents + 1000)   # round 1
    revise_offer(sid, offered_fee_cents + 1500)
    counter_slot(pid, sid, offered_fee_cents + 2000)   # round 2
    revise_offer(sid, offered_fee_cents + 2500)
    counter_slot(pid, sid, offered_fee_cents + 3000)   # round 3
    ctx["slot"] = get_success_data(api_client.get_lineup_slot(sid, BOOKER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: private buyout state
# ---------------------------------------------------------------------------
def setup_private_held(buyout_fee_cents=500000, deposit_pct=None, show_overrides=None):
    """Venue -> DRAFT show -> HELD PrivateEvent (show now PRIVATE_HELD).
    Returns dict with venue, show, private_event."""
    venue = create_venue()
    show = create_draft_show(venue["id"], **(show_overrides or {}))
    pe_payload = create_private_event_payload(show["id"], buyout_fee_cents=buyout_fee_cents)
    if deposit_pct is not None:
        pe_payload["deposit_pct"] = deposit_pct
    pe = get_success_data(api_client.create_private_event(pe_payload, BOOKER))
    show = get_success_data(api_client.get_show(show["id"], BOOKER))
    return {"venue": venue, "show": show, "private_event": pe}


def setup_confirmed_buyout(buyout_fee_cents=500000, deposit_pct=None, show_overrides=None):
    """A PRIVATE_HELD show with a CONFIRMED PrivateEvent. Returns same shape."""
    ctx = setup_private_held(buyout_fee_cents=buyout_fee_cents, deposit_pct=deposit_pct,
                             show_overrides=show_overrides)
    ctx["private_event"] = get_success_data(
        api_client.confirm_private_event(ctx["private_event"]["id"], BOOKER)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 6: settlement / terminal state
# ---------------------------------------------------------------------------
def open_settlement_after_end(venue_id, show_id, ends_after_iso):
    """Advance the clock past ends_at and open a settlement. Returns the settlement."""
    set_clock(ends_after_iso)
    return get_success_data(api_client.create_settlement({"show_id": show_id}, FLOOR))


def setup_ga_show_settlement_open(ga_capacity=100, price_cents=4500,
                                  show_overrides=None, venue_overrides=None,
                                  ends_after_iso="2026-04-08T06:00:00Z"):
    """GA show that ended with an OPEN settlement (show SETTLING, posture
    RECONCILING). Returns dict with venue, show, section, tier, settlement."""
    sc = setup_ga_show_on_sale(
        venue_overrides=venue_overrides, show_overrides=show_overrides,
        ga_capacity=ga_capacity, price_cents=price_cents,
    )
    settlement = open_settlement_after_end(sc["venue"]["id"], sc["show"]["id"], ends_after_iso)
    sc["settlement"] = settlement
    sc["show"] = get_success_data(api_client.get_show(sc["show"]["id"], BOOKER))
    return sc


def setup_settled_show(ends_after_iso="2026-05-09T06:00:00Z", show_overrides=None):
    """Full lifecycle through SETTLED: GA show ended, settlement opened then
    finalized. Returns dict with venue, show, section, tier, settlement."""
    sc = setup_ga_show_settlement_open(show_overrides=show_overrides,
                                       ends_after_iso=ends_after_iso)
    sc["settlement"] = get_success_data(
        api_client.finalize_settlement(sc["settlement"]["id"], FLOOR)
    )
    sc["show"] = get_success_data(api_client.get_show(sc["show"]["id"], BOOKER))
    return sc


# ---------------------------------------------------------------------------
# Tier 7: guest list
# ---------------------------------------------------------------------------
def setup_listed_guest_entry(scenario=None, party_size=2, minimum_waived=False,
                             as_performer=False):
    """A LISTED guest-list entry on an ON_SALE GA show, hosted by a performer.
    If scenario is None, builds a fresh GA show on sale. Returns dict with
    scenario, performer, guest_entry."""
    sc = scenario or setup_ga_show_on_sale()
    performer = create_performer()
    payload = create_guest_list_entry_payload(
        sc["show"]["id"], performer["id"], party_size=party_size,
        minimum_waived=minimum_waived,
    )
    if as_performer:
        headers = make_performer_headers(performer["id"])
    else:
        headers = BOOKER
    entry = get_success_data(api_client.create_guest_list_entry(payload, headers))
    return {"scenario": sc, "performer": performer, "guest_entry": entry}
