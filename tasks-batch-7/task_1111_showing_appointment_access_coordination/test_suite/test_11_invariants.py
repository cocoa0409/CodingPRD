"""Compensating invariants: INV-1 confirmed_showing_count and INV-2 strike points."""
import pytest

from test_helpers import (
    api_client,
    cancel_request,
    create_confirmed_request,
    get_agent_strikes,
    make_admin_headers,
    setup_vacant_auto_world,
    validate_success,
)


def test_inv1_confirmed_count_confirm_increments(api):
    """PRD §2.9: "a listing's `confirmed_showing_count` always equals the
    number of its showing requests currently in CONFIRMED status: confirmation
    increments it (the forward leg)."

    Design: Difficulty/compensating_invariant/inv1_confirmed_count_confirm_cancel
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    assert req["status"] == "CONFIRMED"
    listing = validate_success(api_client.get_listing(world["listing"]["id"], world["la_headers"]))
    assert listing["confirmed_showing_count"] == 1, listing


def test_inv1_confirmed_count_cancel_compensates_without_strike(api):
    """PRD §2.9: "every transition out of CONFIRMED — buyer cancellation,
    completion, no-show declaration, or system cascade — decrements it (the
    compensating legs)." PRD §3.6: "when the cancellation lands less than 24
    hours before the window's `start_at` — a LATE_CANCEL strike of `weight` 10
    is created against the buyer agent."

    Cancel 34h before start: count returns to 0 and no strike is issued.

    Design: Difficulty/compensating_invariant/inv1_confirmed_count_confirm_cancel
    """
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z")
    cancel_request(req["id"], world["buyer_agent"]["id"], reason="plans changed")

    listing = validate_success(api_client.get_listing(world["listing"]["id"], world["la_headers"]))
    assert listing["confirmed_showing_count"] == 0, listing

    agent = validate_success(api_client.get_agent(world["buyer_agent"]["id"], make_admin_headers()))
    assert agent["active_strike_points"] == 0, agent


def _setup_late_cancel_strike():
    """VACANT auto world where the buyer has one ACTIVE LATE_CANCEL strike (10)."""
    world = setup_vacant_auto_world()
    req = create_confirmed_request(world["listing"]["id"], world["buyer_agent"]["id"],
                                   world["seller"]["id"],
                                   "2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z")
    cancel_request(req["id"], world["buyer_agent"]["id"], reason="late change")
    return world


def test_inv2_late_cancel_strike_adds_ten_points(api):
    """PRD §2.9: "an agent's `active_strike_points` always equals the sum of
    the `weight` values of that agent's StrikeRecords in ACTIVE status; strike
    creation raises it." PRD §3.6: "when the cancellation lands less than 24
    hours before the window's `start_at` — a LATE_CANCEL strike of `weight` 10
    is created against the buyer agent."

    Design: Difficulty/compensating_invariant/inv2_strike_points_issue_forgive
    """
    world = _setup_late_cancel_strike()
    agent = validate_success(api_client.get_agent(world["buyer_agent"]["id"], make_admin_headers()))
    assert agent["active_strike_points"] == 10, agent

    strikes = get_agent_strikes(world["buyer_agent"]["id"])
    assert len(strikes) == 1 and strikes[0]["strike_type"] == "LATE_CANCEL", strikes
    assert strikes[0]["weight"] == 10 and strikes[0]["status"] == "ACTIVE", strikes


def test_inv2_forgive_compensates_points_and_restores_standing(api):
    """PRD §3.6: "A `PlatformAdmin` may also forgive an ACTIVE strike — an
    optional `reason` may accompany the decision — moving it to FORGIVEN and
    recomputing standing as the compensating leg of the points invariant."

    Design: Difficulty/compensating_invariant/inv2_strike_points_issue_forgive
    """
    world = _setup_late_cancel_strike()
    ba_id = world["buyer_agent"]["id"]
    strikes = get_agent_strikes(ba_id)
    strike_id = strikes[0]["id"]

    forgiven = validate_success(api_client.forgive_strike(
        strike_id, {"reason": "first offense"}, make_admin_headers()))
    assert forgiven["status"] == "FORGIVEN", forgiven

    agent = validate_success(api_client.get_agent(ba_id, make_admin_headers()))
    assert agent["active_strike_points"] == 0, agent
    assert agent["standing"] == "GOOD_STANDING", agent
