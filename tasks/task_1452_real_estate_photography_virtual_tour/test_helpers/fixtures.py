"""Composite setup helpers for the booking pipeline (PRD §3).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because each test runs against a freshly restarted server with an
empty database. Setup calls use get_success_data() so setup failures surface
as clear errors rather than assertion noise.

Identity threading: ClientAgent and Photographer are entity-backed roles, so
every ownership-gated call uses make_client_agent_headers(entity["id"]) /
make_photographer_headers(entity["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    create_market_payload,
    create_photographer_payload,
    create_client_agent_payload,
    create_booking_payload,
)
from .test_users import (
    make_client_agent_headers,
    make_photographer_headers,
    make_coordinator_headers,
    make_ops_admin_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: participants
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_EPOCH):
    """Advance the logical clock (PRD §2.10). Returns now_utc."""
    resp = api_client.set_clock(to_iso8601, make_ops_admin_headers())
    return get_success_data(resp)


def create_market(**overrides):
    resp = api_client.create_market(create_market_payload(**overrides), make_ops_admin_headers())
    return get_success_data(resp)


def create_photographer(market_id, **overrides):
    resp = api_client.create_photographer(
        create_photographer_payload(market_id, **overrides), make_ops_admin_headers())
    return get_success_data(resp)


def create_agent(home_market_id, **overrides):
    resp = api_client.create_client_agent(
        create_client_agent_payload(home_market_id, **overrides), make_ops_admin_headers())
    return get_success_data(resp)


def create_booking(agent, market_id, **overrides):
    """Create a DRAFT booking owned by the given agent entity."""
    headers = make_client_agent_headers(agent["id"])
    resp = api_client.create_booking(create_booking_payload(market_id, **overrides), headers)
    return get_success_data(resp)


def get_booking(booking_id):
    resp = api_client.get_booking(booking_id, make_coordinator_headers())
    return get_success_data(resp)


def get_photographer(photographer_id):
    resp = api_client.get_photographer(photographer_id, make_coordinator_headers())
    return get_success_data(resp)


def get_agent(agent_id):
    resp = api_client.get_client_agent(agent_id, make_ops_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression — submit + readiness + assign + confirm
# ---------------------------------------------------------------------------

def submit_and_prepare(booking, agent):
    """Submit a DRAFT booking and check every default checklist item, leaving
    the booking READY (readiness aggregate complete). Returns the READY booking."""
    headers = make_client_agent_headers(agent["id"])
    resp = api_client.submit_booking(booking["id"], headers)
    get_success_data(resp)
    resp = api_client.list_checklist_items(booking["id"], headers, params={"limit": 100})
    items = get_success_data(resp)
    assert isinstance(items, list) and len(items) == 5, (
        f"Setup failed: expected 5 default checklist items, got {items!r}")
    for item in items:
        r = api_client.patch_checklist_item(booking["id"], item["id"], True, headers)
        get_success_data(r)
    return get_booking(booking["id"])


def assign_booking(booking_id, photographer_id):
    resp = api_client.assign_booking(booking_id, photographer_id, make_coordinator_headers())
    return get_success_data(resp)


def confirm_booking(booking_id):
    resp = api_client.confirm_booking(booking_id, make_coordinator_headers())
    return get_success_data(resp)


def create_ready_booking(agent, market_id, **booking_overrides):
    """Create a booking and walk it DRAFT -> AWAITING_READINESS -> READY."""
    booking = create_booking(agent, market_id, **booking_overrides)
    return submit_and_prepare(booking, agent)


def create_confirmed_booking(agent, photographer, market_id, **booking_overrides):
    """Full scheduling pipeline: create -> submit -> checklist -> assign -> confirm.
    Only valid for bookings with NO active drone add-on."""
    booking = create_ready_booking(agent, market_id, **booking_overrides)
    assign_booking(booking["id"], photographer["id"])
    return confirm_booking(booking["id"])


# ---------------------------------------------------------------------------
# Tier 2: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_shot_booking(agent, photographer, market_id, mark_time,
                        confirm_first=True, **booking_overrides):
    """Booking walked to IN_EDIT (mark-shot flips CONFIRMED -> SHOT -> IN_EDIT)."""
    if confirm_first:
        booking = create_confirmed_booking(agent, photographer, market_id, **booking_overrides)
    else:
        booking = create_ready_booking(agent, market_id, **booking_overrides)
        assign_booking(booking["id"], photographer["id"])
    set_clock(mark_time)
    resp = api_client.mark_shot(booking["id"], make_photographer_headers(photographer["id"]))
    return get_success_data(resp)


def create_delivered_booking(agent, photographer, market_id, mark_time,
                             photo_asset_count=None, tour_asset_url=None,
                             **booking_overrides):
    """Booking walked to DELIVERED. Returns (booking, bundle)."""
    booking = create_shot_booking(agent, photographer, market_id, mark_time,
                                  **booking_overrides)
    if photo_asset_count is None:
        photo_asset_count = booking["photo_count"]
    payload = {"photo_asset_count": photo_asset_count}
    if tour_asset_url is not None:
        payload["tour_asset_url"] = tour_asset_url
    resp = api_client.deliver(booking["id"], payload, make_photographer_headers(photographer["id"]))
    bundle = get_success_data(resp)
    return get_booking(booking["id"]), bundle


def create_accepted_booking(agent, photographer, market_id, mark_time,
                            **booking_overrides):
    """Booking walked to ACCEPTED (terminal). Returns (booking, bundle)."""
    booking, bundle = create_delivered_booking(
        agent, photographer, market_id, mark_time, **booking_overrides)
    resp = api_client.accept_booking(booking["id"], make_client_agent_headers(agent["id"]))
    get_success_data(resp)
    return get_booking(booking["id"]), bundle


# ---------------------------------------------------------------------------
# Tier 3: reschedule helpers (OCC-guarded)
# ---------------------------------------------------------------------------

def live_version(booking_id):
    """Fetch the booking's live OCC version immediately before a guarded write."""
    return get_booking(booking_id)["version"]


def reschedule(booking, agent, kind, new_start_utc, reason_code):
    """OCC-disciplined reschedule: reads the live version right before the call."""
    headers = make_client_agent_headers(agent["id"])
    version = live_version(booking["id"])
    resp = api_client.reschedule_booking(
        booking["id"],
        {
            "expected_booking_version": version,
            "kind": kind,
            "new_start_utc": new_start_utc,
            "reason_code": reason_code,
        },
        headers,
    )
    return get_success_data(resp)


def weather_reschedule(booking, agent, new_start_utc, reason_code="PRECIPITATION"):
    return reschedule(booking, agent, "WEATHER", new_start_utc, reason_code)


def client_reschedule(booking, agent, new_start_utc, reason_code="SELLER_DELAY"):
    return reschedule(booking, agent, "CLIENT", new_start_utc, reason_code)


# ---------------------------------------------------------------------------
# Tier 4: drone authorization helpers
# ---------------------------------------------------------------------------

def first_authorization(booking_id):
    resp = api_client.list_authorizations(booking_id, make_coordinator_headers())
    auths = get_success_data(resp)
    assert isinstance(auths, list) and len(auths) >= 1, (
        f"Setup failed: expected an authorization on booking {booking_id}, got {auths!r}")
    return auths[0]


def create_authorization_pending_booking(agent, photographer, market_id,
                                         addon_kind="DRONE_STILLS", **booking_overrides):
    """Drone booking walked to AUTHORIZATION_PENDING: create (DRAFT) -> attach drone
    add-on -> submit -> checklist -> assign (auto-routes ASSIGNED -> AUTHORIZATION_PENDING).
    Returns (booking, authorization)."""
    booking = create_booking(agent, market_id, **booking_overrides)
    headers = make_client_agent_headers(agent["id"])
    resp = api_client.create_addon(booking["id"], addon_kind, headers)
    get_success_data(resp)
    booking = submit_and_prepare(booking, agent)
    assign_booking(booking["id"], photographer["id"])
    booking = get_booking(booking["id"])
    assert booking["state"] == "AUTHORIZATION_PENDING", (
        f"Setup failed: expected AUTHORIZATION_PENDING, got {booking['state']}")
    return booking, first_authorization(booking["id"])


def create_confirmed_drone_booking(agent, photographer, market_id,
                                   addon_kind="DRONE_STILLS", **booking_overrides):
    """Drone booking walked to CONFIRMED via an approved authorization.
    Returns (booking, authorization)."""
    booking, auth = create_authorization_pending_booking(
        agent, photographer, market_id, addon_kind=addon_kind, **booking_overrides)
    resp = api_client.approve_authorization(booking["id"], auth["id"], make_ops_admin_headers())
    get_success_data(resp)
    booking = get_booking(booking["id"])
    assert booking["state"] == "CONFIRMED", (
        f"Setup failed: expected CONFIRMED, got {booking['state']}")
    return booking, auth


# ---------------------------------------------------------------------------
# Tier 5: market+participants bundle
# ---------------------------------------------------------------------------

def setup_market_participants(market_overrides=None, photographer_overrides=None,
                              drone_certified=False):
    """Create one market, one photographer, and one agent. Returns (market, photographer, agent)."""
    market = create_market(**(market_overrides or {}))
    photographer = create_photographer(
        market["id"], drone_certified=drone_certified, **(photographer_overrides or {}))
    agent = create_agent(market["id"])
    return market, photographer, agent
