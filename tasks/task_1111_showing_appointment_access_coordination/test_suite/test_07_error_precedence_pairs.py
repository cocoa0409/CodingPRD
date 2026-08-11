"""Priority-pair validation conflicts (PRD §2.7 pipeline ordering)."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_confirmed_request,
    create_showing_request_payload,
    register_agent,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_state_beats_temporal_overlap_returns_listing_not_active(api):
    """PRD §2.7: "Every mutating request passes through a fixed validation
    pipeline, and the stages run in the order below. The first failing stage
    produces the response; later stages are never reached, so an earlier
    failure masks every later one." PRD §3.3: "The listing must be ACTIVE —
    intake against a PAUSED or WITHDRAWN listing fails with
    `ERR_LISTING_NOT_ACTIVE`."

    A request violating both listing-not-active (stage 7) and buffered-overlap
    (stage 11) MUST return ERR_LISTING_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_overlap
    """
    world = setup_vacant_auto_world(buffer_minutes=30)
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    create_confirmed_request(listing_id, ba_id, world["seller"]["id"],
                             "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    validate_success(api_client.pause_listing(listing_id, world["la_headers"]))

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T10:15:00Z", "2026-05-01T10:45:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)


def test_state_beats_temporal_overlap_persists_nothing(api):
    """PRD §2.7: "The first failing stage produces the response; later stages
    are never reached, so an earlier failure masks every later one."

    The rejected intake leaves the listing's request collection unchanged.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_overlap
    """
    world = setup_vacant_auto_world(buffer_minutes=30)
    listing_id = world["listing"]["id"]
    ba_id = world["buyer_agent"]["id"]

    create_confirmed_request(listing_id, ba_id, world["seller"]["id"],
                             "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    validate_success(api_client.pause_listing(listing_id, world["la_headers"]))

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T10:15:00Z", "2026-05-01T10:45:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE)

    from test_helpers import validate_paginated
    data, meta = validate_paginated(api_client.list_showing_requests(
        world["la_headers"], params={"listing_id": listing_id}))
    assert meta["total_count"] == 1, (data, meta)


def test_safety_beats_daily_capacity_returns_agent_not_verified(api):
    """PRD §2.7: "The first failing stage produces the response; later stages
    are never reached, so an earlier failure masks every later one." PRD §3.3:
    "The acting agent must be VERIFIED, else `ERR_AGENT_NOT_VERIFIED` (HTTP
    403)."

    An UNVERIFIED buyer creating on a listing whose daily cap (1) is already
    full MUST get ERR_AGENT_NOT_VERIFIED (stage 8 beats stage 14).

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_daily_capacity
    """
    world = setup_vacant_auto_world(max_showings_per_day=1)
    listing_id = world["listing"]["id"]

    # Verified buyer fills the single daily slot (APPROVED counts toward the cap).
    create_showing = create_showing_request_payload(
        listing_id, "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    resp = api_client.create_showing_request(create_showing, world["ba_headers"])
    assert validate_success(resp, expected_status=201)["status"] == "APPROVED"

    # Second, UNVERIFIED buyer attempts a non-overlapping same-day request.
    other = register_agent(name="Unverified Buyer", license_number="LIC-UNVERIFIED-1")
    from test_helpers import make_buyer_agent_headers
    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z"),
        make_buyer_agent_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGENT_NOT_VERIFIED)


def test_safety_beats_daily_capacity_error_status_is_403(api):
    """PRD §3.3: "The acting agent must be VERIFIED, else
    `ERR_AGENT_NOT_VERIFIED` (HTTP 403), and must not be SUSPENDED, else
    `ERR_AGENT_SUSPENDED` (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_daily_capacity
    """
    world = setup_vacant_auto_world(max_showings_per_day=1)
    listing_id = world["listing"]["id"]

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"),
        world["ba_headers"],
    )
    validate_success(resp, expected_status=201)

    other = register_agent(name="Unverified Buyer", license_number="LIC-UNVERIFIED-2")
    from test_helpers import make_buyer_agent_headers
    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T12:00:00Z", "2026-05-01T12:30:00Z"),
        make_buyer_agent_headers(other["id"]),
    )
    assert resp.status_code == 403, resp.text
    validate_error(resp, ApiErrorId.ERR_AGENT_NOT_VERIFIED)
