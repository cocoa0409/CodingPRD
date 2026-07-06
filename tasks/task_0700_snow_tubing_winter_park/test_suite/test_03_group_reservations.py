"""Group reservations: hold/revise revision cycle, exclusive-lane occupation,
and the conserved open-lane-count invariant across a hold/revise round-trip.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_group_host_headers,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty/non_linear_state_machine/group_reservation_held_to_draft_revision_cycle
# ===========================================================================

def test_held_to_draft_to_held_revision_cycle_recomputes_deposit(api):
    """PRD §3.7: "A held reservation can be revised for re-quote — `HELD → DRAFT` — forming a
    draft-to-held-to-draft loop".
    PRD §3.7: "a party of 5 or fewer bills at 3000 cents per head".
    PRD §3.7: "For an exclusive-lane party the deposit is the seats subtotal plus a
    flat 20000 cents exclusive-lane charge."

    Design: Difficulty/non_linear_state_machine/group_reservation_held_to_draft_revision_cycle
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-07T10:00:00Z", block_ends="2026-03-07T12:00:00Z",
                            clock="2026-03-07T09:00:00Z")
    host_id = g["host"]["id"]
    lane1 = g["lanes"][0]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    validate_success(api.revise_group_reservation(res["id"], make_group_host_headers(host_id)), 200)
    # Second hold re-runs the deposit calc and re-closes the lane.
    held2 = fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    assert held2["state"] == "HELD"
    # 3000 * 4 + 20000 = 32000
    assert held2["deposit_cents"] == 32000, f"expected 32000 deposit, got {held2['deposit_cents']}"
    lane = validate_success(api.get_lane(lane1["id"], fx.OPERATOR), 200)
    assert lane["status"] == "CLOSED"
    assert lane["closure_reason"] == "GROUP_RENTAL"


def test_revise_releases_exclusive_lane_back_to_open(api):
    """PRD §3.7: "revising requires the reservation to be `HELD`, and for an exclusive-lane party it
    releases the held lane back to `OPEN` with `closure_reason` cleared to null and
    bubbles up the park recompute."

    Design: Difficulty/non_linear_state_machine/group_reservation_held_to_draft_revision_cycle
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-07T10:00:00Z", block_ends="2026-03-07T12:00:00Z",
                            clock="2026-03-07T09:00:00Z")
    host_id = g["host"]["id"]
    lane1 = g["lanes"][0]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    revised = validate_success(api.revise_group_reservation(res["id"], make_group_host_headers(host_id)), 200)
    assert revised["state"] == "DRAFT"
    lane = validate_success(api.get_lane(lane1["id"], fx.OPERATOR), 200)
    assert lane["status"] == "OPEN"
    assert lane["closure_reason"] is None


# ===========================================================================
# Difficulty/resource_temporal_overlap/exclusive_lane_whole_block_occupation_conflict
# ===========================================================================

def test_second_exclusive_hold_on_occupied_lane_rejected(api):
    """PRD §3.7: "For an exclusive-lane party, the target lane must be `OPEN` and not already held by
    another reservation in the same block; a lane already closed or held for another
    group in that block is rejected with `ERR_LANE_UNAVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/exclusive_lane_whole_block_occupation_conflict
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-17T10:00:00Z", block_ends="2026-03-17T12:00:00Z",
                            clock="2026-03-17T09:00:00Z")
    lane1 = g["lanes"][0]
    h1 = fx.create_patron()
    h2 = fx.create_patron()
    res1 = fx.create_group_reservation(g["park"]["id"], h1["id"], g["block"]["id"],
                                       rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    res2 = fx.create_group_reservation(g["park"]["id"], h2["id"], g["block"]["id"],
                                       rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res1["id"], h1["id"], g["block"]["id"])
    # Second hold on the now-CLOSED/GROUP_RENTAL lane in the same block -> rejected.
    v = fx.block_version(g["block"]["id"], h2["id"])
    resp = api.hold_group_reservation(res2["id"], v, make_group_host_headers(h2["id"]))
    validate_error(resp, ApiErrorId.ERR_LANE_UNAVAILABLE.value)
    res2_fetched = validate_success(api.get_group_reservation(res2["id"], make_group_host_headers(h2["id"])), 200)
    assert res2_fetched["state"] == "DRAFT"


def test_first_exclusive_hold_closes_lane_for_group_rental(api):
    """PRD §3.7: "for an exclusive-lane party the reserved lane is taken to `CLOSED` with
    `closure_reason` `GROUP_RENTAL`, bubbling up a recompute of the park's
    `open_lane_count` and `total_capacity_remaining`."

    Design: Difficulty/resource_temporal_overlap/exclusive_lane_whole_block_occupation_conflict
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-17T10:00:00Z", block_ends="2026-03-17T12:00:00Z",
                            clock="2026-03-17T09:00:00Z")
    lane1 = g["lanes"][0]
    h1 = fx.create_patron()
    res1 = fx.create_group_reservation(g["park"]["id"], h1["id"], g["block"]["id"],
                                       rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res1["id"], h1["id"], g["block"]["id"])
    lane = validate_success(api.get_lane(lane1["id"], fx.OPERATOR), 200)
    assert lane["status"] == "CLOSED"
    assert lane["closure_reason"] == "GROUP_RENTAL"


# ===========================================================================
# Difficulty/compensating_invariant/exclusive_hold_then_revise_conserves_open_lane_count
# ===========================================================================

def test_exclusive_hold_then_revise_conserves_open_lane_count(api):
    """PRD §3.7: "for an exclusive-lane party the reserved lane is taken to `CLOSED` with
    `closure_reason` `GROUP_RENTAL`, bubbling up a recompute of the park's
    `open_lane_count` and `total_capacity_remaining`."
    PRD §3.7: "for an exclusive-lane party it releases the held lane back to `OPEN` with
    `closure_reason` cleared to null and bubbles up the park recompute."

    Design: Difficulty/compensating_invariant/exclusive_hold_then_revise_conserves_open_lane_count
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-19T10:00:00Z", block_ends="2026-03-19T12:00:00Z",
                            clock="2026-03-19T09:00:00Z")
    host_id = g["host"]["id"]
    lane1 = g["lanes"][0]
    park_before = validate_success(api.get_park(g["park"]["id"], fx.OPERATOR), 200)
    assert park_before["open_lane_count"] == 2
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    revised = validate_success(api.revise_group_reservation(res["id"], make_group_host_headers(host_id)), 200)
    assert revised["state"] == "DRAFT"
    park_after = validate_success(api.get_park(g["park"]["id"], fx.OPERATOR), 200)
    assert park_after["open_lane_count"] == 2, \
        f"open_lane_count must return to 2 after hold+revise, got {park_after['open_lane_count']}"
    lane = validate_success(api.get_lane(lane1["id"], fx.OPERATOR), 200)
    assert lane["status"] == "OPEN"
    assert lane["closure_reason"] is None


def test_exclusive_hold_then_revise_leaves_reservation_draft(api):
    """PRD §3.7: "A held reservation can be revised for re-quote — `HELD → DRAFT".

    Design: Difficulty/compensating_invariant/exclusive_hold_then_revise_conserves_open_lane_count
    """
    g = fx.setup_group_park(num_lanes=2, lane_capacity=8,
                            block_starts="2026-03-19T10:00:00Z", block_ends="2026-03-19T12:00:00Z",
                            clock="2026-03-19T09:00:00Z")
    host_id = g["host"]["id"]
    lane1 = g["lanes"][0]
    res = fx.create_group_reservation(g["park"]["id"], host_id, g["block"]["id"],
                                      rental_type="EXCLUSIVE_LANE", party_size=4, lane_id=lane1["id"])
    fx.hold_group_reservation(res["id"], host_id, g["block"]["id"])
    revised = validate_success(api.revise_group_reservation(res["id"], make_group_host_headers(host_id)), 200)
    assert revised["state"] == "DRAFT"
