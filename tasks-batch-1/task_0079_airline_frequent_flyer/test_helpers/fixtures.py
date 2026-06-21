"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server with an empty DB before every test). Setup calls
use get_success_data() (lenient) so a setup failure surfaces clearly.

All helpers take the api client and the relevant role headers. ProgramAdmin owns
member/cert/status-match creation, clock advance, and the test-seeding injectors;
OperationsAgent owns segments, pools, and the clearing run; the acting Member owns
awards, gifts, and upgrade requests (ownership-gated — headers built per member id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers
from .factories import (
    create_member_payload,
    create_flight_segment_payload,
    create_award_booking_payload,
    create_flight_pool_payload,
    create_upgrade_request_payload,
    create_companion_certificate_payload,
    create_points_gift_payload,
    create_status_match_payload,
)

ADMIN = TEST_USERS["admin_headers"]
AGENT = TEST_USERS["agent_headers"]


def set_clock(api, current_utc):
    """Advance the logical clock (also runs deferred sweeps). ProgramAdmin-only."""
    return get_success_data(api.advance_clock(current_utc, ADMIN))


def create_member(api, **overrides):
    """Register a member. Returns the member resource."""
    return get_success_data(api.create_member(create_member_payload(**overrides), ADMIN))


def member_headers_for(member):
    """Owner headers for an entity_backed Member."""
    return make_member_headers(member["id"])


def inject_points(api, member_id, amount):
    """Seed a member's points_balance directly (ACCRUAL lot). Returns member."""
    return get_success_data(api.inject_points(member_id, amount, ADMIN))


def inject_qualifying_segments(api, member_id, count):
    """Set a member's qualifying_segments_ytd directly and recompute tier."""
    return get_success_data(api.inject_qualifying_segments(member_id, count, ADMIN))


def grant_status_match(api, member_id, rival_tier="GOLD", valid_until="2026-12-31T23:59:59.000Z"):
    """Grant a status match (ProgramAdmin). Returns the StatusMatch resource."""
    return get_success_data(
        api.create_status_match(create_status_match_payload(member_id, rival_tier, valid_until), ADMIN)
    )


def create_companion_certificate(api, member_id, **overrides):
    """Issue a companion certificate (ProgramAdmin). Returns the certificate."""
    return get_success_data(
        api.create_companion_certificate(create_companion_certificate_payload(member_id, **overrides), ADMIN)
    )


# --- Flight segment lifecycle ---

def create_booked_segment(api, member_id, **overrides):
    """Book a segment (OperationsAgent). Returns the segment at BOOKED."""
    return get_success_data(api.create_flight_segment(create_flight_segment_payload(member_id, **overrides), AGENT))


def create_flown_segment(api, member_id, clock_utc, **overrides):
    """Set clock, book a segment, and fly it. Returns the segment at FLOWN.

    The segment's scheduled_departure defaults to before clock_utc so the fly is
    permitted; override scheduled_departure to control it.
    """
    set_clock(api, clock_utc)
    seg = create_booked_segment(api, member_id, **overrides)
    get_success_data(api.fly_flight_segment(seg["id"], AGENT))
    return seg


def accrue_segment(api, segment_id):
    """Accrue a flown segment. Returns the accrued segment resource."""
    return get_success_data(api.accrue_flight_segment(segment_id, AGENT))


# --- Award booking lifecycle ---

def quote_award(api, member, **overrides):
    """Member quotes an award. Returns the AwardBooking at QUOTED."""
    hdrs = member_headers_for(member)
    return get_success_data(api.create_award_booking(create_award_booking_payload(member["id"], **overrides), hdrs))


def quote_and_issue_award(api, member, **overrides):
    """Quote then issue an award for a member with enough points. Returns ISSUED award."""
    hdrs = member_headers_for(member)
    award = quote_award(api, member, **overrides)
    get_success_data(api.issue_award_booking(award["id"], hdrs))
    return award


# --- Flight pool / waitlist ---

def create_pool(api, **overrides):
    """Create a flight pool (OperationsAgent). Returns the pool resource."""
    return get_success_data(api.create_flight_pool(create_flight_pool_payload(**overrides), AGENT))


def join_waitlist(api, member, pool, expected_version, **overrides):
    """Member joins a pool's waitlist with an OCC version. Returns UpgradeRequest."""
    hdrs = member_headers_for(member)
    payload = create_upgrade_request_payload(member["id"], pool["id"], expected_version, **overrides)
    return get_success_data(api.create_upgrade_request(payload, hdrs))


def current_pool_version(api, pool_id):
    """Read the pool's current version (for the next OCC join)."""
    return get_success_data(api.get_flight_pool(pool_id, AGENT))["version"]


# --- Points gift ---

def create_pending_gift(api, sender, recipient_id, amount=1000):
    """Sender creates a pending gift. Returns the PointsGift at PENDING."""
    hdrs = member_headers_for(sender)
    return get_success_data(
        api.create_points_gift(create_points_gift_payload(sender["id"], recipient_id, amount), hdrs)
    )


def member_version(api, member_id):
    """Read a member's current version (for the gift-settle OCC field)."""
    return get_success_data(api.get_member(member_id, ADMIN))["version"]
