"""Resource temporal overlap: buffered half-open showings vs closed blackouts."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_blackout_window_payload,
    create_confirmed_request,
    create_showing_request_payload,
    setup_vacant_auto_world,
    validate_error,
    validate_success,
)


def test_buffered_overlap_one_minute_inside_boundary_conflicts(api):
    """PRD §3.3: "A conflict exists exactly when the new window's start falls
    before some existing window's padded end (its `end_at` plus the buffer) and
    that window's padded start (its `start_at` minus the buffer) falls before
    the new window's end. ... A violation yields `ERR_SHOWING_OVERLAP_CONFLICT`
    (HTTP 409)."

    With buffer 30 an existing 10:00-10:30 CONFIRMED blocks [09:30, 11:00);
    10:59 start conflicts.

    Design: Difficulty/resource_temporal_overlap/buffered_halfopen_showing_overlap
    """
    world = setup_vacant_auto_world(buffer_minutes=30)
    listing_id = world["listing"]["id"]
    create_confirmed_request(listing_id, world["buyer_agent"]["id"],
                             world["seller"]["id"],
                             "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T10:59:00Z", "2026-05-01T11:29:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SHOWING_OVERLAP_CONFLICT)


def test_buffered_overlap_touching_boundary_allowed(api):
    """PRD §3.3: "Because both comparisons are strict, a new window that merely
    kisses a padded boundary is allowed."

    A start at exactly 11:00 touches the buffered end and is allowed.

    Design: Difficulty/resource_temporal_overlap/buffered_halfopen_showing_overlap
    """
    world = setup_vacant_auto_world(buffer_minutes=30)
    listing_id = world["listing"]["id"]
    create_confirmed_request(listing_id, world["buyer_agent"]["id"],
                             world["seller"]["id"],
                             "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")

    resp = api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-01T11:00:00Z", "2026-05-01T11:30:00Z"),
        world["ba_headers"],
    )
    assert validate_success(resp, expected_status=201)["status"] == "APPROVED"


def _setup_blackout_world():
    world = setup_vacant_auto_world()
    resp = api_client.create_blackout_window(
        world["listing"]["id"],
        create_blackout_window_payload("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z",
                                       reason="contractor visit"),
        world["seller_headers"],
    )
    window = validate_success(resp, expected_status=201)
    return world, window


def test_blackout_closed_interval_touching_end_conflicts(api):
    """PRD §3.3: "The blackout check is a separate, buffer-free closed-interval
    intersection against every BlackoutWindow of the listing: a conflict exists
    when the new start is at or before the blackout's `end_at` and the
    blackout's `start_at` is at or before the new end — touching counts here,
    and the rejection is `ERR_BLACKOUT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/closed_interval_blackout_overlap
    """
    world, _window = _setup_blackout_world()
    resp = api_client.create_showing_request(
        create_showing_request_payload(world["listing"]["id"],
                                       "2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
        world["ba_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_BLACKOUT_CONFLICT)


def test_blackout_closed_interval_one_minute_past_end_allowed(api):
    """PRD §2.10: "A blackout window is a closed interval — both its
    `start_at` and its `end_at` are occupied — and no buffer is applied to it,
    so touching either blackout boundary is a conflict."

    Starting one minute after the blackout's closed end clears the check.

    Design: Difficulty/resource_temporal_overlap/closed_interval_blackout_overlap
    """
    world, _window = _setup_blackout_world()
    resp = api_client.create_showing_request(
        create_showing_request_payload(world["listing"]["id"],
                                       "2026-05-02T11:01:00Z", "2026-05-02T11:31:00Z"),
        world["ba_headers"],
    )
    assert validate_success(resp, expected_status=201)["status"] == "APPROVED"
