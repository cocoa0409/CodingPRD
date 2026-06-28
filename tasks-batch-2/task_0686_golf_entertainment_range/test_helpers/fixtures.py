"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken setup step
surfaces as a clear "setup failed" rather than a confusing downstream assertion.

Identity threading rule (PRD §2.1): Guest is entity_backed. Any ownership-gated
Guest call uses make_guest_headers(member["id"]) so X-User-ID equals the owning
member's id; the shared TEST_USERS["guest_headers"] is never used for owned
mutations.

Because the harness restarts the server (empty DB) before every test, every
fixture builds its world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_bay_payload,
    create_member_payload,
    create_game_card_payload,
    create_gift_card_payload,
    create_reservation_payload,
    create_session_payload,
    create_event_package_payload,
    fb_item_payload,
    create_queue_ticket_payload,
    create_lesson_payload,
)
from .test_users import TEST_USERS, make_guest_headers

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Advance the server's logical clock to the given ISO instant."""
    return get_success_data(api_client.set_clock(iso, RM))


# ─── Tier 1: primitive creators ───────────────────────────────────────────
def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), RM))


def create_bay(venue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bay(create_bay_payload(venue_id, **overrides), RM))


def create_member(**overrides) -> dict:
    return get_success_data(api_client.create_member(create_member_payload(**overrides), RM))


def create_member_with_wallet(amount_cents: int, **overrides) -> dict:
    """Create a member then top up the wallet by amount_cents. Returns the member
    after top-up (so wallet_balance_cents == amount_cents)."""
    member = create_member(**overrides)
    if amount_cents > 0:
        member = get_success_data(
            api_client.wallet_topup(member["id"], {"amount_cents": amount_cents}, RM))
    return member


def create_game_card(member_id: str, credits_total: int = 1) -> dict:
    return get_success_data(
        api_client.create_game_card(create_game_card_payload(member_id, credits_total), RM))


def create_gift_card(face_value_cents: int = 5000) -> dict:
    return get_success_data(
        api_client.create_gift_card(create_gift_card_payload(face_value_cents), RM))


# ─── Tier 2: venue + bay + member bundle ──────────────────────────────────
def setup_venue_bay_member(venue_overrides=None, bay_overrides=None,
                           member_overrides=None, wallet_cents=0):
    """Create a venue, one bay on it, and one member (optionally with wallet).
    Returns (venue, bay, member)."""
    venue = create_venue(**(venue_overrides or {}))
    bay = create_bay(venue["id"], **(bay_overrides or {}))
    if wallet_cents:
        member = create_member_with_wallet(wallet_cents, **(member_overrides or {}))
    else:
        member = create_member(**(member_overrides or {}))
    return venue, bay, member


# ─── Tier 3: reservation lifecycle ────────────────────────────────────────
def create_hold_reservation(venue_id, bay_id, member_id, start_utc, end_utc,
                            time_band, **overrides) -> dict:
    """Create a HOLD reservation as the owning Guest (ownership-gated)."""
    payload = create_reservation_payload(
        venue_id, bay_id, member_id, start_utc, end_utc, time_band, **overrides)
    return get_success_data(
        api_client.create_reservation(payload, make_guest_headers(member_id)))


def confirm_reservation(reservation_id, member_id, expected_bay_version, **overrides) -> dict:
    """Confirm a HOLD as the owning Guest."""
    payload = {"expected_bay_version": expected_bay_version}
    payload.update(overrides)
    return get_success_data(
        api_client.confirm_reservation(reservation_id, payload, make_guest_headers(member_id)))


def setup_confirmed_reservation(start_utc="2026-06-02T18:00:00Z",
                                end_utc="2026-06-02T19:00:00Z",
                                time_band="PEAK", day_type="WEEKDAY",
                                pay_source="WALLET", tier="PLATINUM",
                                wallet_cents=50000, base_rate_cents=2500,
                                clock="2026-06-01T12:00:00Z",
                                venue_overrides=None):
    """Full path to a CONFIRMED reservation on a fresh venue/bay/member.

    Default PEAK / WEEKDAY / 60-min / base 2500 yields quoted_price_cents == 6800
    (gross 2500*2*1.60 = 8000; PLATINUM 0.15 discount 1200; 8000-1200 = 6800).

    Returns (venue, bay, member, reservation). The returned bay carries the
    pre-confirm version (1); after confirm the live Bay.version is 2.
    """
    if clock:
        set_clock(clock)
    vo = {"base_rate_cents_per_half_hour": base_rate_cents}
    if venue_overrides:
        vo.update(venue_overrides)
    venue = create_venue(**vo)
    bay = create_bay(venue["id"])
    member = create_member_with_wallet(wallet_cents, tier=tier)
    res = create_hold_reservation(
        venue["id"], bay["id"], member["id"], start_utc, end_utc, time_band,
        day_type=day_type, pay_source=pay_source)
    confirmed = confirm_reservation(res["id"], member["id"], bay["version"])
    return venue, bay, member, confirmed


def setup_session_on_confirmed_reservation(**overrides):
    """A CONFIRMED reservation realized by an OPEN walk-in/reserved GameSession.

    Returns (venue, bay, member, reservation, session). The session is started by
    FrontDesk naming the reservation_id. Bay becomes OCCUPIED.
    """
    venue, bay, member, res = setup_confirmed_reservation(**overrides)
    session = get_success_data(api_client.create_session(
        create_session_payload(bay["id"], member["id"], reservation_id=res["id"]), FD))
    return venue, bay, member, res, session


# ─── Tier 3b: walk-in session (directly started) ──────────────────────────
def setup_walkin_session(member_overrides=None):
    """Venue + bay + member + an OPEN walk-in GameSession started directly by
    FrontDesk (reservation_id null). Returns (venue, bay, member, session)."""
    venue, bay, member = setup_venue_bay_member(member_overrides=member_overrides)
    session = get_success_data(api_client.create_session(
        create_session_payload(bay["id"], member["id"]), FD))
    return venue, bay, member, session


def append_shots(session_id, points_list):
    """Append a sequence of shots (one call each). Returns the last session view."""
    last = None
    for pts in points_list:
        last = get_success_data(api_client.record_shot(session_id, {"points": pts}, FD))
    return last


# ─── Tier 4: F&B tab on a session ─────────────────────────────────────────
def open_session_tab(session_id) -> dict:
    return get_success_data(api_client.create_fb_tab({"session_id": session_id}, FD))


def open_event_tab(event_package_id) -> dict:
    return get_success_data(
        api_client.create_fb_tab({"event_package_id": event_package_id}, FD))


def add_items(tab_id, items):
    """items is a list of (name, unit_price_cents, qty) tuples. Returns last view."""
    last = None
    for name, price, qty in items:
        last = get_success_data(
            api_client.add_fb_item(tab_id, fb_item_payload(name, price, qty), FD))
    return last


def close_tab(tab_id) -> dict:
    return get_success_data(api_client.close_fb_tab(tab_id, FD))


def setup_open_session_tab_with_items(items, session_overrides=None):
    """Walk-in session + an OPEN session FBTab carrying the given line items.
    Returns (venue, bay, member, session, tab). Totals on the returned tab
    reflect every appended item.
    """
    venue, bay, member, session = setup_walkin_session(
        member_overrides=(session_overrides or {}).get("member_overrides"))
    tab = open_session_tab(session["id"])
    if items:
        tab = add_items(tab["id"], items)
    return venue, bay, member, session, tab


# ─── Tier 5: event package lifecycle ──────────────────────────────────────
def create_quoted_event(venue_id, organizer_member_id, headcount_estimate,
                        per_head_package_cents, **overrides) -> dict:
    payload = create_event_package_payload(
        venue_id, organizer_member_id, headcount_estimate, per_head_package_cents,
        **overrides)
    return get_success_data(api_client.create_event_package(payload, RM))


def setup_confirmed_event(headcount_estimate=20, per_head_package_cents=6500,
                          bay_block_cents=15000, deposit_cents=140000,
                          wallet_cents=200000, bay_count=4):
    """Venue + organizer (wallet topped) + a CONFIRMED EventPackage with the
    deposit already debited. Returns (venue, organizer, event)."""
    venue = create_venue(bay_count=bay_count)
    organizer = create_member_with_wallet(wallet_cents, tier="PLATINUM")
    event = create_quoted_event(
        venue["id"], organizer["id"], headcount_estimate, per_head_package_cents,
        bay_block_cents=bay_block_cents, deposit_cents=deposit_cents)
    confirmed = get_success_data(api_client.confirm_event_package(event["id"], RM))
    return venue, organizer, confirmed


def setup_confirmed_event_with_closed_tab(catering_cents=8200, **event_overrides):
    """Confirmed event + one CLOSED event FBTab whose total includes the catering
    line item. Returns (venue, organizer, event, tab)."""
    venue, organizer, event = setup_confirmed_event(**event_overrides)
    tab = open_event_tab(event["id"])
    add_items(tab["id"], [("Catering", catering_cents, 1)])
    tab = close_tab(tab["id"])
    return venue, organizer, event, tab


# ─── Tier 6: walk-in queue ────────────────────────────────────────────────
def create_queue_ticket(venue_id, member_id, **overrides) -> dict:
    """Create a WAITING queue ticket as the owning Guest."""
    payload = create_queue_ticket_payload(venue_id, member_id, **overrides)
    return get_success_data(
        api_client.create_queue_ticket(payload, make_guest_headers(member_id)))


def take_bay_out_of_service(bay_id, expected_bay_version) -> dict:
    return get_success_data(api_client.bay_out_of_service(
        bay_id, {"expected_bay_version": expected_bay_version}, RM))


# ─── Tier 7: lessons ──────────────────────────────────────────────────────
def create_lesson(venue_id, bay_id, member_id, kind, start_utc, end_utc, **overrides) -> dict:
    """Create a SCHEDULED lesson as the owning Guest."""
    payload = create_lesson_payload(
        venue_id, bay_id, member_id, kind, start_utc, end_utc, **overrides)
    return get_success_data(
        api_client.create_lesson(payload, make_guest_headers(member_id)))
