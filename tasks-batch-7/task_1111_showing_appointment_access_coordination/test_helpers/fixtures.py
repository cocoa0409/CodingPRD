"""Composite setup helpers.

Multi-step preconditions (verified agents, seller+listing pairs, confirmed
showings, completed showings with feedback in flight, strike accumulation) are
encapsulated here so tests stay focused on assertions.

Every fixture builds its state from scratch through the public API — the test
runner restarts the server before every test, so nothing carries over.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_agent_payload,
    create_blackout_window_payload,
    create_feedback_payload,
    create_listing_payload,
    create_showing_request_payload,
    create_seller_payload,
    create_verification_case_payload,
)
from .test_users import (
    make_admin_headers,
    make_anonymous_headers,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    make_seller_headers,
)


# ---------------------------------------------------------------------------
# Primitive step wrappers (all lenient; callers assert on the payload they need)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers())
    return get_success_data(resp)


def run_sweep():
    resp = api_client.run_expiration_sweep(make_admin_headers())
    return get_success_data(resp)


def register_agent(name="Agent", license_number=None, brokerage_name="Brokerage"):
    payload = create_agent_payload(full_name=name, brokerage_name=brokerage_name)
    if license_number is not None:
        payload["license_number"] = license_number
    resp = api_client.create_agent(payload, make_anonymous_headers())
    return get_success_data(resp)


def verify_agent(agent_id: str, license_document_ref: str = "doc-verify"):
    """File a verification case for the agent and have PlatformAdmin APPROVE it.

    Returns the approved case. After this call the agent's verification_status
    is VERIFIED.
    """
    resp = api_client.create_verification_case(
        agent_id,
        create_verification_case_payload(license_document_ref=license_document_ref),
        make_buyer_agent_headers(agent_id),
    )
    case = get_success_data(resp)
    resp = api_client.review_verification_case(
        case["id"], {"decision": "APPROVE"}, make_admin_headers()
    )
    return get_success_data(resp)


def register_and_verify_agent(name="Buyer", license_number=None):
    """Register an agent and walk them to VERIFIED. Returns the agent id."""
    agent = register_agent(name=name, license_number=license_number)
    verify_agent(agent["id"])
    return agent


def create_seller(name="Seller", email=None, auto_approve=None, approval_timeout_minutes=None):
    overrides = {}
    if email is not None:
        overrides["contact_email"] = email
    if auto_approve is not None:
        overrides["auto_approve"] = auto_approve
    if approval_timeout_minutes is not None:
        overrides["approval_timeout_minutes"] = approval_timeout_minutes
    resp = api_client.create_seller(
        create_seller_payload(**overrides), make_admin_headers()
    )
    return get_success_data(resp)


def create_listing(seller_id: str, listing_agent_id: str, occupancy_type: str = "VACANT", **policy):
    resp = api_client.create_listing(
        create_listing_payload(seller_id, occupancy_type=occupancy_type, **policy),
        make_listing_agent_headers(listing_agent_id),
    )
    return get_success_data(resp)


def create_showing_request(listing_id: str, buyer_agent_id: str, start_at: str, end_at: str, **extra):
    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, start_at, end_at, **extra),
        make_buyer_agent_headers(buyer_agent_id),
    )
    return get_success_data(resp)


def approve_request(request_id: str, seller_id: str):
    resp = api_client.approve_showing_request(request_id, make_seller_headers(seller_id))
    return get_success_data(resp)


def decline_request(request_id: str, seller_id: str, reason: str = "not convenient"):
    resp = api_client.decline_showing_request(
        request_id, make_seller_headers(seller_id), payload={"reason": reason}
    )
    return get_success_data(resp)


def confirm_request(request_id: str, buyer_agent_id: str):
    resp = api_client.confirm_showing_request(request_id, make_buyer_agent_headers(buyer_agent_id))
    return get_success_data(resp)


def cancel_request(request_id: str, buyer_agent_id: str, reason: str = "plans changed"):
    resp = api_client.cancel_showing_request(
        request_id, make_buyer_agent_headers(buyer_agent_id), payload={"reason": reason}
    )
    return get_success_data(resp)


def issue_credential(request_id: str, listing_agent_id: str, credential_type: str = "LOCKBOX_CODE"):
    resp = api_client.issue_access_credential(
        request_id, {"credential_type": credential_type}, make_listing_agent_headers(listing_agent_id)
    )
    return get_success_data(resp)


def redeem_credential(credential_id: str, buyer_agent_id: str):
    resp = api_client.redeem_access_credential(credential_id, make_buyer_agent_headers(buyer_agent_id))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_pending_request(listing_id: str, buyer_agent_id: str, start_at: str, end_at: str, **extra):
    """A request that lands in PENDING_APPROVAL (manual seller / OCCUPIED listing)."""
    return create_showing_request(listing_id, buyer_agent_id, start_at, end_at, **extra)


def create_approved_request(listing_id: str, buyer_agent_id: str, seller_id: str,
                            start_at: str, end_at: str, **extra):
    """Create + seller-approve (or auto-approve) a request. Returns the APPROVED request."""
    req = create_showing_request(listing_id, buyer_agent_id, start_at, end_at, **extra)
    if req["status"] == "PENDING_APPROVAL":
        req = approve_request(req["id"], seller_id)
    return req


def create_confirmed_request(listing_id: str, buyer_agent_id: str, seller_id: str,
                             start_at: str, end_at: str, **extra):
    """Create -> approve -> confirm. Returns the CONFIRMED request."""
    req = create_approved_request(listing_id, buyer_agent_id, seller_id, start_at, end_at, **extra)
    return confirm_request(req["id"], buyer_agent_id)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — the standard seller+listing+agents world
# ---------------------------------------------------------------------------

def setup_basic_world(occupancy_type="VACANT", auto_approve=True, listing_policy=None,
                      seller_kwargs=None):
    """Clock reset + listing agent + VERIFIED buyer agent + seller + listing.

    Returns a dict with ids and headers for the four actors and the listing.
    """
    set_clock(CLOCK_START_ISO)
    la = register_agent(name="Listing Agent")
    ba = register_and_verify_agent(name="Buyer Agent")
    seller_kwargs = dict(seller_kwargs or {})
    if auto_approve is not None:
        seller_kwargs["auto_approve"] = auto_approve
    seller = create_seller(**seller_kwargs)
    listing = create_listing(seller["id"], la["id"], occupancy_type=occupancy_type,
                             **(listing_policy or {}))
    return {
        "listing_agent": la,
        "buyer_agent": ba,
        "seller": seller,
        "listing": listing,
        "la_headers": make_listing_agent_headers(la["id"]),
        "ba_headers": make_buyer_agent_headers(ba["id"]),
        "seller_headers": make_seller_headers(seller["id"]),
        "admin_headers": make_admin_headers(),
    }


def setup_vacant_auto_world(**listing_policy):
    """The most common world: VACANT listing whose seller auto-approves."""
    return setup_basic_world(occupancy_type="VACANT", auto_approve=True,
                             listing_policy=listing_policy or None)


def setup_occupied_manual_world(**listing_policy):
    """OCCUPIED listing of a manual seller: requests start PENDING_APPROVAL."""
    return setup_basic_world(occupancy_type="OCCUPIED", auto_approve=False,
                             listing_policy=listing_policy or None)


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_confirmed_with_credential(world, start_at, end_at, credential_type="LOCKBOX_CODE"):
    """CONFIRMED showing + one ISSUED credential. Returns (request, credential)."""
    req = create_confirmed_request(
        world["listing"]["id"], world["buyer_agent"]["id"], world["seller"]["id"],
        start_at, end_at,
    )
    cred = issue_credential(req["id"], world["listing_agent"]["id"], credential_type)
    return req, cred


def setup_completed_showing(world, start_at="2026-05-01T10:00:00Z", end_at="2026-05-01T10:30:00Z",
                            redeem_at="2026-05-01T10:05:00Z", sweep_at="2026-05-01T10:45:00Z",
                            credential_type="LOCKBOX_CODE"):
    """Drive one confirmed showing all the way to COMPLETED via the sweep.

    Returns (completed_request, credential). After this fixture runs:
      - request.status == COMPLETED
      - its feedback request is SENT (sent_at == sweep_at, due_at == sweep_at + 72h)
    """
    req, cred = create_confirmed_with_credential(world, start_at, end_at, credential_type)
    set_clock(redeem_at)
    redeem_credential(cred["id"], world["buyer_agent"]["id"])
    set_clock(sweep_at)
    run_sweep()
    return req, cred


def get_feedback_request_id(world, request_id):
    resp = api_client.get_feedback_request_of_showing(request_id, world["ba_headers"])
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) >= 1, "expected a feedback request to exist"
    return data[0]["id"]


def get_agent_strikes(agent_id):
    resp = api_client.list_agent_strikes(agent_id, make_admin_headers())
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def issue_late_cancel_strike(world, start_at="2026-05-01T10:00:00Z", end_at="2026-05-01T10:30:00Z"):
    """Create + confirm + cancel (within 24h of start) -> one ACTIVE LATE_CANCEL
    strike (weight 10) against the world's buyer agent. Returns the request."""
    req = create_confirmed_request(
        world["listing"]["id"], world["buyer_agent"]["id"], world["seller"]["id"],
        start_at, end_at,
    )
    cancel_request(req["id"], world["buyer_agent"]["id"])
    return req


def accumulate_late_cancel_strikes(world, count: int, base_hour: int = 8):
    """Issue `count` LATE_CANCEL strikes against the world's buyer agent by
    confirming and late-cancelling `count` same-day requests spaced 2h apart.
    Requires the listing's daily cap to be >= count. Returns the requests."""
    requests = []
    for i in range(count):
        hour = base_hour + 2 * i
        req = create_confirmed_request(
            world["listing"]["id"], world["buyer_agent"]["id"], world["seller"]["id"],
            f"2026-05-01T{hour:02d}:00:00Z", f"2026-05-01T{hour:02d}:30:00Z",
        )
        cancel_request(req["id"], world["buyer_agent"]["id"])
        requests.append(req)
    return requests


# ---------------------------------------------------------------------------
# Tier 5: terminal-state setups
# ---------------------------------------------------------------------------

def setup_withdrawn_listing_world(occupancy_type="VACANT"):
    """A world whose listing has been withdrawn (terminal)."""
    world = setup_basic_world(occupancy_type=occupancy_type, auto_approve=True)
    resp = api_client.withdraw_listing(world["listing"]["id"], world["la_headers"])
    get_success_data(resp)
    return world


def setup_completed_showing_world():
    """VACANT auto world with one COMPLETED showing. Returns (world, request, credential)."""
    world = setup_vacant_auto_world()
    req, cred = setup_completed_showing(world)
    return world, req, cred
