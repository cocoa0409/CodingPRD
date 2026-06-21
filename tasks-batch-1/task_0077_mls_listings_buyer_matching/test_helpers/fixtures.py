"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.
Fixtures use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: ListingAgent and BuyerAgent are entity_backed by Agent, so
ownership-gated calls always pass the acting Agent's own id as X-User-ID via
make_listing_agent_headers / make_buyer_agent_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_listing_agent_headers,
    make_buyer_agent_headers,
    anon_headers,
)
from . import factories as f


# ---------------------------------------------------------------------------
# Participant registry
# ---------------------------------------------------------------------------

def create_brokerage(total_pct=0.06, coop_pct=0.50, name="Acme Realty"):
    resp = api_client.create_brokerage(
        f.create_brokerage_payload(
            name=name,
            default_total_commission_pct=total_pct,
            default_coop_split_pct=coop_pct,
        ),
        headers=anon_headers(),
    )
    return get_success_data(resp)


def create_agent(brokerage_id, full_name="Agent", license_no=None):
    payload = f.create_agent_payload(brokerage_id, full_name=full_name)
    if license_no is not None:
        payload["license_no"] = license_no
    resp = api_client.create_agent(payload, headers=anon_headers())
    return get_success_data(resp)


def suspend_agent(agent_id):
    resp = api_client.suspend_agent(agent_id, headers=anon_headers())
    return get_success_data(resp)


def create_buyer(buyer_agent_id, **overrides):
    resp = api_client.create_buyer(
        f.create_buyer_payload(buyer_agent_id, **overrides),
        headers=make_buyer_agent_headers(buyer_agent_id),
    )
    return get_success_data(resp)


def setup_participants(total_pct=0.06, coop_pct=0.50, buyer_overrides=None):
    """Brokerage + one listing agent + one buyer agent + one buyer.

    Returns dict: brokerage, listing_agent, buyer_agent, buyer.
    """
    brk = create_brokerage(total_pct, coop_pct)
    la = create_agent(brk["id"], full_name="Lara Listing")
    ba = create_agent(brk["id"], full_name="Ben Buyer")
    buyer = create_buyer(ba["id"], **(buyer_overrides or {}))
    return {"brokerage": brk, "listing_agent": la, "buyer_agent": ba, "buyer": buyer}


# ---------------------------------------------------------------------------
# Listing / lockbox state progression
# ---------------------------------------------------------------------------

def create_draft_listing(listing_agent_id, list_price_cents=50_000_000,
                         address=None, **overrides):
    payload = f.create_listing_payload(
        listing_agent_id, list_price_cents=list_price_cents, **overrides)
    if address is not None:
        payload["address"] = address
    resp = api_client.create_listing(
        payload, headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def install_lockbox(listing_id, listing_agent_id, **overrides):
    resp = api_client.create_lockbox(
        listing_id, f.create_lockbox_payload(**overrides),
        headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def activate_listing(listing_id, listing_agent_id):
    resp = api_client.activate_listing(
        listing_id, headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def setup_active_listing(list_price_cents=50_000_000, total_pct=0.06,
                         coop_pct=0.50, turnaround_minutes=None,
                         buyer_overrides=None):
    """Active listing with an installed lockbox and a registered buyer.

    Returns dict: brokerage, listing_agent, buyer_agent, buyer, listing,
    lockbox. The listing object is the post-activation snapshot.
    """
    p = setup_participants(total_pct, coop_pct, buyer_overrides)
    listing = create_draft_listing(p["listing_agent"]["id"],
                                    list_price_cents=list_price_cents)
    lb_overrides = {}
    if turnaround_minutes is not None:
        lb_overrides["turnaround_minutes"] = turnaround_minutes
    lockbox = install_lockbox(listing["id"], p["listing_agent"]["id"], **lb_overrides)
    listing = activate_listing(listing["id"], p["listing_agent"]["id"])
    p["listing"] = listing
    p["lockbox"] = lockbox
    return p


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

def submit_offer(listing_id, buyer_id, buyer_agent_id,
                 initial_price_cents=49_000_000, earnest_money_cents=0,
                 requested_contingencies=None):
    payload = f.create_offer_payload(
        buyer_id, buyer_agent_id,
        initial_price_cents=initial_price_cents,
        earnest_money_cents=earnest_money_cents)
    if requested_contingencies is not None:
        payload["requested_contingencies"] = requested_contingencies
    resp = api_client.create_offer(
        listing_id, payload, headers=make_buyer_agent_headers(buyer_agent_id))
    return get_success_data(resp)


def current_listing_version(listing_id, listing_agent_id):
    resp = api_client.get_listing(
        listing_id, headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)["version"]


def accept_offer(offer_id, listing_id, listing_agent_id, expected_version=None):
    if expected_version is None:
        expected_version = current_listing_version(listing_id, listing_agent_id)
    resp = api_client.accept_offer(
        offer_id, f.accept_payload(expected_version),
        headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def setup_active_listing_with_open_offer(initial_price_cents=49_000_000,
                                         requested_contingencies=None,
                                         **active_overrides):
    """Active listing with one OPEN offer (current_party == SELLER).

    Returns the setup_active_listing dict plus 'offer'.
    """
    s = setup_active_listing(**active_overrides)
    offer = submit_offer(
        s["listing"]["id"], s["buyer"]["id"], s["buyer_agent"]["id"],
        initial_price_cents=initial_price_cents,
        requested_contingencies=requested_contingencies)
    s["offer"] = offer
    return s


def setup_accepted_offer(initial_price_cents=50_000_000,
                         requested_contingencies=None, buyer_overrides=None,
                         total_pct=0.06, coop_pct=0.50):
    """Active listing whose single offer has been accepted.

    With non-empty requested_contingencies the listing is UNDER_CONTRACT and
    contingencies are PENDING; with empty/None it bubbles straight to PENDING.

    Returns setup dict plus 'offer' (post-accept) and 'contingencies' (list,
    fetched from the offer).
    """
    s = setup_active_listing(list_price_cents=initial_price_cents,
                             total_pct=total_pct, coop_pct=coop_pct,
                             buyer_overrides=buyer_overrides)
    offer = submit_offer(
        s["listing"]["id"], s["buyer"]["id"], s["buyer_agent"]["id"],
        initial_price_cents=initial_price_cents,
        requested_contingencies=requested_contingencies or [])
    accepted = accept_offer(offer["id"], s["listing"]["id"],
                            s["listing_agent"]["id"])
    s["offer"] = accepted
    s["contingencies"] = list_contingencies(offer["id"], s["buyer_agent"]["id"])
    return s


def list_contingencies(offer_id, buyer_agent_id):
    resp = api_client.list_offer_contingencies(
        offer_id, headers=make_buyer_agent_headers(buyer_agent_id))
    # List endpoints return the array directly under data.
    return get_success_data(resp)


def contingency_by_kind(contingencies, kind):
    for c in contingencies:
        if c["kind"] == kind:
            return c
    return None


# ---------------------------------------------------------------------------
# PENDING / CLOSED progression
# ---------------------------------------------------------------------------

def setup_pending_listing(sale_price_cents=50_000_000, total_pct=0.06,
                          coop_pct=0.50):
    """Listing in PENDING via a no-contingency accepted offer, ready to close.

    Returns setup dict plus 'offer' (accepted) — listing object is post-accept.
    """
    return setup_accepted_offer(initial_price_cents=sale_price_cents,
                                requested_contingencies=[],
                                total_pct=total_pct, coop_pct=coop_pct)


def close_listing(listing_id, listing_agent_id, expected_version=None):
    if expected_version is None:
        expected_version = current_listing_version(listing_id, listing_agent_id)
    resp = api_client.close_listing(
        listing_id, f.close_payload(expected_version),
        headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def setup_closed_listing(sale_price_cents=50_000_000, total_pct=0.06,
                         coop_pct=0.50):
    """Drive a listing all the way to CLOSED. Returns setup dict plus
    'closed_listing' and 'ledger' (first ledger row)."""
    s = setup_pending_listing(sale_price_cents=sale_price_cents,
                              total_pct=total_pct, coop_pct=coop_pct)
    closed = close_listing(s["listing"]["id"], s["listing_agent"]["id"])
    s["closed_listing"] = closed
    s["ledger"] = get_first_ledger(s["listing"]["id"], s["listing_agent"]["id"])
    return s


def get_first_ledger(listing_id, listing_agent_id):
    resp = api_client.get_commission_ledger(
        listing_id, headers=make_listing_agent_headers(listing_agent_id))
    rows = get_success_data(resp)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Showings
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers=anon_headers())
    return get_success_data(resp)


def request_showing(lockbox_id, buyer_agent_id, buyer_id, start_at, end_at):
    resp = api_client.create_showing(
        lockbox_id,
        f.create_showing_payload(buyer_agent_id, buyer_id, start_at, end_at),
        headers=make_buyer_agent_headers(buyer_agent_id))
    return get_success_data(resp)


def confirm_showing(showing_id, listing_agent_id):
    resp = api_client.confirm_showing(
        showing_id, headers=make_listing_agent_headers(listing_agent_id))
    return get_success_data(resp)


def setup_confirmed_showing(start_at="2026-07-01T15:00:00Z",
                            end_at="2026-07-01T15:30:00Z",
                            turnaround_minutes=30):
    """Active listing with one CONFIRMED showing on its lockbox.

    Returns setup dict plus 'showing' (CONFIRMED).
    """
    s = setup_active_listing(turnaround_minutes=turnaround_minutes)
    showing = request_showing(s["lockbox"]["id"], s["buyer_agent"]["id"],
                              s["buyer"]["id"], start_at, end_at)
    showing = confirm_showing(showing["id"], s["listing_agent"]["id"])
    s["showing"] = showing
    return s
