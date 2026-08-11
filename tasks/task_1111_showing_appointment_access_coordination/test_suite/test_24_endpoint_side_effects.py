"""Endpoint side effects: confirm automation, activity trail, sweep counters, blackout delete."""
import pytest

from test_helpers import (
    api_client,
    create_blackout_window_payload,
    create_confirmed_request,
    create_showing_request,
    create_showing_request_payload,
    get_feedback_request_id,
    issue_credential,
    is_iso8601_timestamp,
    redeem_credential,
    run_sweep,
    set_clock,
    setup_completed_showing,
    setup_occupied_manual_world,
    setup_vacant_auto_world,
    validate_paginated,
    validate_success,
)


def test_confirm_creates_feedback_request_scheduled(api):
    """PRD §3.5: "Success carries real weight: the listing's
    `confirmed_showing_count` increments by one (the forward leg of the
    confirmed-count invariant), a FeedbackRequest is automatically created in
    SCHEDULED status for the request, a `CONFIRMED` event is appended, and the
    request's `version` increments."

    Design: Corner/endpoints/confirm_creates_feedback_request_scheduled
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    feedback = validate_success(api_client.get_feedback_request_of_showing(
        req["id"], world["ba_headers"]))
    assert len(feedback) == 1, feedback
    assert feedback[0]["status"] == "SCHEDULED", feedback
    assert feedback[0]["showing_request_id"] == req["id"], feedback


def test_activity_events_record_transition_trail(api):
    """PRD §2.12: "Every meaningful mutation appends an ActivityEvent to the
    affected listing's log. An event records the `listing_id` it belongs to,
    the `showing_request_id` it concerns (null for listing-level events such as
    pauses), an `event_type`, the `actor_role` responsible." PRD §2.3: "Unless
    otherwise specified, every list endpoint returns resources sorted by their
    creation timestamp in ascending order."

    create + approve + confirm appends REQUEST_CREATED, APPROVED, CONFIRMED in
    creation order.

    Design: Corner/endpoints/activity_events_record_transition_trail
    """
    world = setup_occupied_manual_world()
    listing_id = world["listing"]["id"]
    req = create_confirmed_request(listing_id, world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")

    events, meta = validate_paginated(api_client.list_listing_activity_events(
        listing_id, world["seller_headers"]))
    event_types = [e["event_type"] for e in events]
    assert event_types == ["REQUEST_CREATED", "APPROVED", "CONFIRMED"], event_types
    for e in events:
        assert e["listing_id"] == listing_id, e
        assert e["showing_request_id"] == req["id"], e


def test_sweep_completion_counts_observable(api):
    """PRD §2.11: "The response summarizes the run with six counts:
    `requests_expired_count`, `requests_completed_count`,
    `credentials_expired_count`, `feedback_sent_count`,
    `feedback_expired_count`, and `strikes_expired_count`." PRD §2.11 step 3:
    "Every showing request in CONFIRMED whose `end_at` has passed and for which
    a credential has been USED moves to COMPLETED, and its SCHEDULED feedback
    request flips to SENT in the same step." PRD §3.7: "at which point
    `sent_at` is stamped and `due_at` lands seventy-two hours later."

    Design: Corner/endpoints/sweep_completion_counts_observable
    """
    world = setup_vacant_auto_world()
    req, cred = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                         world["seller"]["id"],
                                         "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z"), None
    cred = issue_credential(req["id"], world["listing_agent"]["id"], "LOCKBOX_CODE")
    set_clock("2026-05-01T10:05:00Z")
    redeem_credential(cred["id"], world["buyer_agent"]["id"])
    set_clock("2026-05-01T10:45:00Z")

    sweep = run_sweep()
    assert sweep["requests_completed_count"] == 1, sweep
    assert sweep["feedback_sent_count"] == 1, sweep

    feedback = validate_success(api_client.get_feedback_request_of_showing(
        req["id"], world["seller_headers"]))
    assert feedback[0]["status"] == "SENT", feedback
    assert feedback[0]["sent_at"] == "2026-05-01T10:45:00Z", feedback
    assert feedback[0]["due_at"] == "2026-05-04T10:45:00Z", feedback  # +72h


def test_blackout_delete_restores_bookability(api):
    """PRD §3.2: "Blackouts can be listed by the seller and the listing agent,
    and the owning seller can delete one outright, which returns a 204 with no
    content."

    Design: Corner/endpoints/blackout_delete_restores_bookability
    """
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    window = validate_success(api_client.create_blackout_window(
        listing_id,
        create_blackout_window_payload("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
        world["seller_headers"]), expected_status=201)

    resp = api_client.delete_blackout_window(window["id"], world["seller_headers"])
    assert resp.status_code == 204, resp.text

    req = validate_success(api_client.create_showing_request(
        create_showing_request_payload(listing_id, "2026-05-02T10:30:00Z", "2026-05-02T11:00:00Z"),
        world["ba_headers"]), expected_status=201)
    assert req["status"] == "APPROVED", req
