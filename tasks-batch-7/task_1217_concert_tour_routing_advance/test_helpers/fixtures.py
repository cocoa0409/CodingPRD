"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds its preconditions from scratch against a freshly started
server, using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() validator so a setup failure surfaces as a clear
"Setup step failed" error naming the offending step.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_tour_payload, create_market_payload, create_venue_payload,
    create_routing_leg_payload, create_show_payload, create_hold_payload,
    counter_hold_payload, respond_counter_payload, confirm_show_payload,
    approve_section_payload, update_tickets_payload, create_budget_line_payload,
    create_marketing_spend_payload, submit_settlement_payload,
    create_compliance_hold_payload,
)
from .test_users import TEST_USERS

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]
VENUE_REP = TEST_USERS["venue_rep_headers"]
ACCOUNTANT = TEST_USERS["settlement_accountant_headers"]

PACKET_SECTIONS = ("tech_rider", "hospitality", "immigration")


# ─── Tier 1: clock + tour shell ────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.5 admin capability)."""
    return get_success_data(api_client.set_current_utc(to_iso8601, TM))


def create_tour(start_clock: str = "2026-06-01T00:00:00Z", **tour_overrides) -> dict:
    """Set the logical clock and create a tour. Returns the Tour (PLANNING/OPEN)."""
    if start_clock is not None:
        set_clock(start_clock)
    return get_success_data(api_client.create_tour(create_tour_payload(**tour_overrides), TM))


def create_market(tour_id: str, **market_overrides) -> dict:
    return get_success_data(
        api_client.create_market(tour_id, create_market_payload(**market_overrides), TM))


def create_venue(tour_id: str, market_id: str, **venue_overrides) -> dict:
    return get_success_data(
        api_client.create_venue(tour_id, create_venue_payload(market_id, **venue_overrides), TM))


def create_staged_tour(start_clock: str = "2026-06-01T00:00:00Z",
                       tour_overrides=None, market_overrides=None,
                       venue_overrides=None, start_routing: bool = True) -> dict:
    """Tour + one market + one venue, optionally moved to ROUTING (PRD §3.1).

    Returns {"tour": Tour, "market": Market, "venue": Venue}.
    """
    tour = create_tour(start_clock=start_clock, **(tour_overrides or {}))
    market = create_market(tour["id"], **(market_overrides or {}))
    venue = create_venue(tour["id"], market["id"], **(venue_overrides or {}))
    if start_routing:
        tour = get_success_data(api_client.start_routing(tour["id"], TM))
    return {"tour": tour, "market": market, "venue": venue}


# ─── Tier 2: shows and holds ───────────────────────────

def create_show(tour_id: str, market_id: str, venue_id: str, **show_overrides) -> dict:
    """Create a show; it enters HOLD_REQUESTED with an auto-created advance packet."""
    return get_success_data(
        api_client.create_show(tour_id, create_show_payload(market_id, venue_id,
                                                            **show_overrides), TM))


def place_hold(tour_id: str, show_id: str, **hold_overrides) -> dict:
    """Promoter places a PENDING hold (PRD §3.3)."""
    return get_success_data(
        api_client.create_hold(tour_id, show_id, create_hold_payload(**hold_overrides),
                               PROMOTER))


def accept_hold(tour_id: str, show_id: str, hold_id: str) -> dict:
    """Promoter accepts the hold; first acceptance moves show to HOLD_PLACED."""
    return get_success_data(api_client.accept_hold(tour_id, show_id, hold_id, PROMOTER))


def get_show(tour_id: str, show_id: str) -> dict:
    return get_success_data(api_client.get_show(tour_id, show_id, TM))


def get_tour(tour_id: str) -> dict:
    return get_success_data(api_client.get_tour(tour_id, TM))


def get_venue(tour_id: str, venue_id: str) -> dict:
    return get_success_data(api_client.get_venue(tour_id, venue_id, TM))


def get_hold(tour_id: str, show_id: str, hold_id: str) -> dict:
    return get_success_data(api_client.get_hold(tour_id, show_id, hold_id, TM))


def get_packet(tour_id: str, show_id: str) -> dict:
    return get_success_data(api_client.get_advance_packet(tour_id, show_id, TM))


def create_show_with_accepted_hold(tour_id: str, market_id: str, venue_id: str,
                                   hold_overrides=None, **show_overrides):
    """Show + promoter hold accepted. Returns (show_in_HOLD_PLACED, hold_ACCEPTED)."""
    show = create_show(tour_id, market_id, venue_id, **show_overrides)
    hold = place_hold(tour_id, show["id"], **(hold_overrides or {}))
    accept_hold(tour_id, show["id"], hold["id"])
    show = get_show(tour_id, show["id"])
    hold = get_hold(tour_id, show["id"], hold["id"])
    return show, hold


# ─── Tier 3: confirm / advance / perform lifecycle ─────

def confirm_show(tour_id: str, show_id: str) -> dict:
    """Confirm a HOLD_PLACED show under the OCC gate (PRD §3.4).

    Reads the tour's current version and supplies it as expected_tour_version.
    Returns the CONFIRMED show.
    """
    tour = get_tour(tour_id)
    return get_success_data(
        api_client.confirm_show(tour_id, show_id,
                                confirm_show_payload(tour["version"]), TM))


def create_confirmed_show(tour_id: str, market_id: str, venue_id: str,
                          hold_overrides=None, **show_overrides):
    """Show driven to CONFIRMED. Returns (show, hold)."""
    show, hold = create_show_with_accepted_hold(
        tour_id, market_id, venue_id, hold_overrides=hold_overrides, **show_overrides)
    show = confirm_show(tour_id, show["id"])
    return show, hold


def submit_and_approve_section(tour_id: str, show_id: str, section: str) -> dict:
    """Submit one packet section (TourManager) then approve it (VenueRep) under
    the packet OCC gate (PRD §3.5). Returns the updated AdvancePacket."""
    get_success_data(api_client.submit_packet_section(tour_id, show_id, section, TM))
    packet = get_packet(tour_id, show_id)
    return get_success_data(
        api_client.approve_packet_section(tour_id, show_id, section,
                                          approve_section_payload(packet["packet_revision"]),
                                          VENUE_REP))


def approve_all_sections(tour_id: str, show_id: str) -> dict:
    """Drive all three packet sections to APPROVED. Returns the packet."""
    packet = None
    for section in PACKET_SECTIONS:
        packet = submit_and_approve_section(tour_id, show_id, section)
    return packet


def advance_show(tour_id: str, show_id: str) -> dict:
    """Advance a CONFIRMED show whose packet is fully approved (PRD §3.5)."""
    return get_success_data(api_client.advance_show(tour_id, show_id, TM))


def create_advanced_show(tour_id: str, market_id: str, venue_id: str,
                         hold_overrides=None, **show_overrides):
    """Show driven to ADVANCED with all packet sections APPROVED.

    Returns (show, hold).
    """
    show, hold = create_confirmed_show(tour_id, market_id, venue_id,
                                       hold_overrides=hold_overrides, **show_overrides)
    approve_all_sections(tour_id, show["id"])
    show = advance_show(tour_id, show["id"])
    return show, hold


def _day_after(iso_date: str) -> str:
    d = date.fromisoformat(iso_date) + timedelta(days=1)
    return d.isoformat()


def create_performed_show(tour_id: str, market_id: str, venue_id: str,
                          show_date: str = "2026-08-01",
                          hold_overrides=None, **show_overrides):
    """Show driven to PERFORMED: advanced, then clock moved past the show date's
    end-of-day UTC and mark-performed called (PRD §3.7). Returns (show, hold)."""
    show, hold = create_advanced_show(tour_id, market_id, venue_id,
                                      hold_overrides=hold_overrides,
                                      show_date=show_date, **show_overrides)
    set_clock(f"{_day_after(show_date)}T00:00:01Z")
    show = get_success_data(api_client.mark_show_performed(tour_id, show["id"], TM))
    return show, hold


# ─── Tier 4: settlement lifecycle ──────────────────────

def get_settlement(tour_id: str, show_id: str) -> dict:
    return get_success_data(api_client.get_settlement(tour_id, show_id, TM))


def submit_settlement(tour_id: str, show_id: str, promoter_headers=None,
                      **submit_overrides) -> dict:
    """Promoter submits the settlement (PRD §3.7). Returns the SUBMITTED settlement."""
    return get_success_data(
        api_client.submit_settlement(tour_id, show_id,
                                     submit_settlement_payload(**submit_overrides),
                                     promoter_headers or PROMOTER))


def verify_settlement(tour_id: str, show_id: str, accountant_headers=None) -> dict:
    return get_success_data(
        api_client.verify_settlement(tour_id, show_id, accountant_headers or ACCOUNTANT))


def pay_settlement(tour_id: str, show_id: str, accountant_headers=None) -> dict:
    return get_success_data(
        api_client.pay_settlement(tour_id, show_id, accountant_headers or ACCOUNTANT))


def settle_show_paid(tour_id: str, show_id: str, **submit_overrides) -> dict:
    """Drive a PERFORMED show's settlement to PAID (show becomes SETTLED)."""
    submit_settlement(tour_id, show_id, **submit_overrides)
    verify_settlement(tour_id, show_id)
    return pay_settlement(tour_id, show_id)


# ─── Tier 5: misc composites ───────────────────────────

def open_compliance_hold(tour_id: str, **hold_overrides) -> dict:
    """TourManager opens a manual compliance hold (PRD §3.8)."""
    return get_success_data(
        api_client.create_compliance_hold(tour_id,
                                          create_compliance_hold_payload(**hold_overrides),
                                          TM))


def counter_hold_once(tour_id: str, show_id: str, hold_id: str, **counter_overrides) -> dict:
    """Promoter counters a PENDING hold, reading a fresh show version for the
    OCC field (PRD §2.8, §3.3). Returns the COUNTERED hold."""
    show = get_success_data(api_client.get_show(tour_id, show_id, PROMOTER))
    return get_success_data(
        api_client.counter_hold(tour_id, show_id, hold_id,
                                counter_hold_payload(show["version"], **counter_overrides),
                                PROMOTER))
