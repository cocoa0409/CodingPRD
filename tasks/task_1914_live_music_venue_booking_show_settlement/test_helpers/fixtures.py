"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server, so no state carries
over). Lenient get_success_data is used internally so setup failures
surface as clear "Setup failed" errors.

BookingAgent calls that are ownership-gated (place / challenge / confirm /
release date holds) always thread the acting BookingAgent's id through
make_booking_agent_headers (PRD §2.1). Other roles are opaque and use the
shared TEST_USERS constants.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_ancillary_revenue_payload,
    create_artist_payload,
    create_booking_agent_payload,
    create_cancel_payload,
    create_date_hold_payload,
    create_expense_receipt_payload,
    create_offer_payload,
    create_postpone_payload,
    create_show_payload,
    create_support_act_payload,
    create_ticket_sale_payload,
    create_ticket_tier_payload,
    create_wire_transfer_payload,
)
from .test_users import TEST_USERS, make_booking_agent_headers

VM = TEST_USERS["venue_manager_headers"]
PROM = TEST_USERS["promoter_headers"]
PM = TEST_USERS["production_manager_headers"]
ACCT = TEST_USERS["accountant_headers"]

ADVANCE_ITEMS = (
    "hospitality",
    "tech",
    "backline",
    "production_requirements",
    "insurance_cert",
    "w9",
)


# ---------------------------------------------------------------------------
# Master data + clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, VM))


def create_artist(**overrides) -> dict:
    return get_success_data(
        api_client.create_artist(create_artist_payload(**overrides), VM)
    )


def create_agent(**overrides) -> dict:
    return get_success_data(
        api_client.create_booking_agent(create_booking_agent_payload(**overrides), VM)
    )


def get_show(show_id: str) -> dict:
    return get_success_data(api_client.get_show(show_id, VM))


def get_show_version(show_id: str) -> int:
    return get_show(show_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: show creation + date-hold confirm
# ---------------------------------------------------------------------------

def create_show(artist_id: str, agent: Optional[dict] = None, **overrides) -> dict:
    """Create a Show as either a BookingAgent (default) or VenueManager.

    When agent is provided the call is made as that agent with the
    entity-backed identity header.
    """
    payload = create_show_payload(artist_id, **overrides)
    if agent is not None:
        headers = make_booking_agent_headers(agent["id"])
    else:
        headers = VM
    return get_success_data(api_client.create_show(payload, headers))


def place_hold(show_id: str, agent: dict, priority: str = "P1") -> dict:
    """Place a DateHold as the given agent (entity-backed identity)."""
    payload = create_date_hold_payload(priority, agent["id"])
    return get_success_data(
        api_client.create_date_hold(
            show_id, payload, make_booking_agent_headers(agent["id"]),
        )
    )


def confirm_hold(show_id: str, hold_id: str, agent: dict) -> dict:
    """Confirm a hold. Reads the show's current version for OCC."""
    version = get_show_version(show_id)
    return get_success_data(
        api_client.confirm_date_hold(
            show_id, hold_id, {"expected_show_version": version},
            make_booking_agent_headers(agent["id"]),
        )
    )


def create_confirmed_show(artist_id: str, agent: dict,
                          priority: str = "P1", **show_overrides) -> Tuple[dict, dict]:
    """Create a Show + place a hold + confirm it. Returns (show, hold)."""
    show = create_show(artist_id, agent=agent, **show_overrides)
    hold = place_hold(show["id"], agent, priority=priority)
    confirm_hold(show["id"], hold["id"], agent)
    return get_show(show["id"]), hold


# ---------------------------------------------------------------------------
# Tier 2: offer / deal
# ---------------------------------------------------------------------------

def create_offer(show_id: str, as_role: str = "BOOKING_AGENT",
                 agent: Optional[dict] = None, **overrides) -> dict:
    payload = create_offer_payload(**overrides)
    if as_role == "BOOKING_AGENT":
        if agent is None:
            raise AssertionError("Setup failed: agent required for agent-side offer")
        headers = make_booking_agent_headers(agent["id"])
    elif as_role == "VENUE_MANAGER":
        headers = VM
    else:
        raise AssertionError(f"Setup failed: unknown offer role {as_role}")
    return get_success_data(api_client.create_offer(show_id, payload, headers))


def accept_offer(show_id: str, offer_id: str, as_role: str = "VENUE_MANAGER",
                 agent: Optional[dict] = None) -> dict:
    version = get_show_version(show_id)
    if as_role == "VENUE_MANAGER":
        headers = VM
    elif as_role == "BOOKING_AGENT":
        if agent is None:
            raise AssertionError("Setup failed: agent required for agent-side accept")
        headers = make_booking_agent_headers(agent["id"])
    else:
        raise AssertionError(f"Setup failed: unknown accept role {as_role}")
    return get_success_data(
        api_client.accept_offer(
            show_id, offer_id, {"expected_show_version": version}, headers,
        )
    )


def create_show_with_deal(artist: Optional[dict] = None,
                          agent: Optional[dict] = None,
                          offer_overrides=None,
                          show_overrides=None) -> Tuple[dict, dict, dict, dict]:
    """Build a Show in CONFIRMED with an accepted Deal.

    Returns (artist, agent, show, deal).
    """
    artist = artist or create_artist()
    agent = agent or create_agent()
    show, _hold = create_confirmed_show(artist["id"], agent, **(show_overrides or {}))
    offer = create_offer(
        show["id"], as_role="BOOKING_AGENT", agent=agent, **(offer_overrides or {}),
    )
    deal = accept_offer(show["id"], offer["id"], as_role="VENUE_MANAGER")
    return artist, agent, get_show(show["id"]), deal


# ---------------------------------------------------------------------------
# Tier 3: deposits + tiers + on-sale
# ---------------------------------------------------------------------------

def pay_deposit(show_id: str, artist_id: str, amount_cents: int) -> dict:
    """Initiate + complete an ARTIST_DEPOSIT wire. Returns the completed wire."""
    wire = get_success_data(api_client.create_wire_transfer(
        show_id,
        create_wire_transfer_payload(
            "ARTIST_DEPOSIT", amount_cents, recipient_artist_id=artist_id,
        ),
        ACCT,
    ))
    return get_success_data(
        api_client.complete_wire_transfer(show_id, wire["id"], ACCT)
    )


def create_tier(show_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_ticket_tier(
            show_id, create_ticket_tier_payload(**overrides), PROM,
        )
    )


def place_on_sale(show_id: str) -> dict:
    version = get_show_version(show_id)
    return get_success_data(
        api_client.place_on_sale(show_id, {"expected_show_version": version}, PROM)
    )


def create_on_sale_show(artist: Optional[dict] = None,
                        agent: Optional[dict] = None,
                        offer_overrides=None,
                        show_overrides=None,
                        tier_overrides=None,
                        pay_full_deposit: bool = True,
                        deposit_amount_cents: Optional[int] = None,
                        on_sale_clock: str = "2026-08-10T10:00:01Z",
                        ) -> Tuple[dict, dict, dict, dict, dict]:
    """Walk a Show all the way to ON_SALE.

    Returns (artist, agent, show, deal, tier). Advances the house clock to
    on_sale_clock before calling the on-sale endpoint.
    """
    artist, agent, show, deal = create_show_with_deal(
        artist=artist, agent=agent,
        offer_overrides=offer_overrides, show_overrides=show_overrides,
    )
    if pay_full_deposit:
        amount = (
            deposit_amount_cents
            if deposit_amount_cents is not None
            else show["deposit_required_cents"]
        )
        if amount and amount > 0:
            pay_deposit(show["id"], artist["id"], amount)
    tier = create_tier(show["id"], **(tier_overrides or {}))
    set_clock(on_sale_clock)
    place_on_sale(show["id"])
    return artist, agent, get_show(show["id"]), deal, tier


# ---------------------------------------------------------------------------
# Tier 4: sales + advance + show-night
# ---------------------------------------------------------------------------

def sell_tickets(show_id: str, tier_id: str, quantity: int) -> dict:
    return get_success_data(
        api_client.create_ticket_sale(
            show_id, create_ticket_sale_payload(tier_id, quantity), PROM,
        )
    )


def complete_all_advance_items(show_id: str) -> None:
    for item in ADVANCE_ITEMS:
        get_success_data(api_client.complete_advance_item(show_id, item, PM))


def advance_show(show_id: str) -> dict:
    """Complete every checklist item then drive ON_SALE -> ADVANCED."""
    complete_all_advance_items(show_id)
    return get_success_data(api_client.complete_advance(show_id, PM))


def create_show_night_show(artist: Optional[dict] = None,
                           agent: Optional[dict] = None,
                           offer_overrides=None,
                           show_overrides=None,
                           tier_overrides=None,
                           show_night_clock: Optional[str] = None,
                           ) -> Tuple[dict, dict, dict, dict, dict]:
    """Walk a Show all the way to SHOW_NIGHT (post-advance, clock into the
    doors-open window).

    Returns (artist, agent, show, deal, tier).
    """
    artist, agent, show, deal, tier = create_on_sale_show(
        artist=artist, agent=agent,
        offer_overrides=offer_overrides, show_overrides=show_overrides,
        tier_overrides=tier_overrides,
    )
    advance_show(show["id"])
    # Move the logical clock into the doors-open window so the show flips to
    # SHOW_NIGHT lazily on next read.
    if show_night_clock is None:
        show_night_clock = show["doors_at_utc"].replace("T19:00:00Z", "T20:00:00Z")
    set_clock(show_night_clock)
    # Touch the show so the lazy transition fires.
    return artist, agent, get_show(show["id"]), deal, tier


# ---------------------------------------------------------------------------
# Tier 5: expenses, ancillary, support, settlement
# ---------------------------------------------------------------------------

def submit_expense(show_id: str, as_role: str = "PROMOTER", **overrides) -> dict:
    headers = PROM if as_role == "PROMOTER" else VM
    return get_success_data(
        api_client.create_expense_receipt(
            show_id, create_expense_receipt_payload(**overrides), headers,
        )
    )


def approve_expense(show_id: str, receipt_id: str) -> dict:
    return get_success_data(
        api_client.approve_expense_receipt(show_id, receipt_id, VM)
    )


def reject_expense(show_id: str, receipt_id: str, reason: str = "no invoice") -> dict:
    return get_success_data(
        api_client.reject_expense_receipt(
            show_id, receipt_id, {"rejection_reason": reason}, VM,
        )
    )


def record_ancillary(show_id: str, as_role: str = "PROMOTER", **overrides) -> dict:
    headers = PROM if as_role == "PROMOTER" else VM
    return get_success_data(
        api_client.create_ancillary_revenue(
            show_id, create_ancillary_revenue_payload(**overrides), headers,
        )
    )


def create_support(show_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_support_act(
            show_id, create_support_act_payload(**overrides), PROM,
        )
    )


def create_draft_settlement(show_id: str) -> dict:
    return get_success_data(api_client.create_settlement(show_id, PROM))


def submit_settlement(show_id: str, promoter_user_id: str = "prom-1") -> dict:
    """Submit the show's settlement as the given (opaque) Promoter id."""
    version = get_show_version(show_id)
    headers = TEST_USERS["promoter_headers"] if promoter_user_id == "prom-1" else {
        "X-User-ID": promoter_user_id,
        "X-User-Role": "Promoter",
        "Content-Type": "application/json",
    }
    return get_success_data(
        api_client.submit_settlement(
            show_id, {"expected_show_version": version}, headers,
        )
    )


# ---------------------------------------------------------------------------
# Cancellation / wires
# ---------------------------------------------------------------------------

def cancel_show(show_id: str, reason: str = "VENUE", as_role: str = "VENUE_MANAGER",
                agent: Optional[dict] = None) -> dict:
    if as_role == "BOOKING_AGENT":
        if agent is None:
            raise AssertionError("Setup failed: agent required for agent cancel")
        headers = make_booking_agent_headers(agent["id"])
    elif as_role == "PROMOTER":
        headers = PROM
    else:
        headers = VM
    return get_success_data(
        api_client.cancel_show(show_id, create_cancel_payload(reason), headers)
    )


def postpone_show(show_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.postpone_show(show_id, create_postpone_payload(**overrides), VM)
    )
