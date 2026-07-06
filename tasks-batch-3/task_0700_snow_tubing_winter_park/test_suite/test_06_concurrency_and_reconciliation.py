"""Concurrency, optimistic locking, and derived-field reconciliation.

Covers the conveyor-turn interval-overlap rejection, the optimistic-concurrency
stale-version rejection on confirm, derived total_capacity_remaining
reconciliation, and immediate (lag-free) committed-count visibility.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_guest_patron_headers,
    create_board_payload,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty/resource_temporal_overlap/conveyor_turn_overlap_rejected_half_open_on_lane
# ===========================================================================

def _setup_two_geared_up_on_one_lane(clock_day):
    base = fx.setup_park_with_lane_and_block(
        clock=f"{clock_day}T10:30:00Z", lane_capacity=5, num_lanes=1, conveyor_cycle_seconds=30,
        block_starts=f"{clock_day}T10:00:00Z", block_ends=f"{clock_day}T12:00:00Z",
    )
    park_id, block_id, lane_id = base["park"]["id"], base["block"]["id"], base["lane"]["id"]
    p1, _ = fx.setup_waivered_patron(park_id)
    p2, _ = fx.setup_waivered_patron(park_id)
    t1 = fx.create_ticket(park_id, block_id, p1["id"])
    t2 = fx.create_ticket(park_id, block_id, p2["id"])
    fx.confirm_ticket(t1["id"], p1["id"], block_id)
    fx.confirm_ticket(t2["id"], p2["id"], block_id)
    fx.dispatch_tube(t1["id"])
    fx.dispatch_tube(t2["id"])
    fx.gear_up(t1["id"])
    fx.gear_up(t2["id"])
    return park_id, block_id, lane_id, t1, t2


def test_conveyor_turn_overlap_rejected(api):
    """PRD §3.5: "A lane admits only one turn at a time: a new turn's half-open interval from
    `boarded_at` (inclusive) to `cleared_at` (exclusive) must not overlap any existing
    `BOARDED` turn on the same lane."
    PRD §3.5: "but any true overlap is rejected with `ERR_LANE_TURN_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/conveyor_turn_overlap_rejected_half_open_on_lane
    """
    park_id, block_id, lane_id, t1, t2 = _setup_two_geared_up_on_one_lane("2026-03-16")
    fx.board(t1["id"], lane_id, "2026-03-16T10:30:00Z")  # interval [10:30:00, 10:30:30)
    # Second board at 10:30:15 falls strictly inside the first interval -> overlap.
    resp = api.board_ticket(
        t2["id"], create_board_payload(lane_id=lane_id, boarded_at="2026-03-16T10:30:15Z"), fx.MARSHAL
    )
    validate_error(resp, ApiErrorId.ERR_LANE_TURN_OVERLAP.value)


def test_conveyor_turn_overlap_leaves_second_ticket_geared_up(api):
    """PRD §3.5: "any true overlap is rejected with `ERR_LANE_TURN_OVERLAP` (HTTP 409)."
    PRD §3.5: "Boarding a rider — `GEARED_UP → ON_LANE".

    Design: Difficulty/resource_temporal_overlap/conveyor_turn_overlap_rejected_half_open_on_lane
    """
    park_id, block_id, lane_id, t1, t2 = _setup_two_geared_up_on_one_lane("2026-03-16")
    fx.board(t1["id"], lane_id, "2026-03-16T10:30:00Z")
    resp = api.board_ticket(
        t2["id"], create_board_payload(lane_id=lane_id, boarded_at="2026-03-16T10:30:15Z"), fx.MARSHAL
    )
    validate_error(resp, ApiErrorId.ERR_LANE_TURN_OVERLAP.value)
    ticket = validate_success(api.get_ticket(t2["id"], fx.OPERATOR), 200)
    assert ticket["checkin_state"] == "GEARED_UP"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_time_block_version_on_confirm_returns_412
# ===========================================================================

def test_stale_block_version_on_confirm_rejected(api):
    """PRD §2.8: "If another writer has advanced the block's `version` since the client last read it —
    for example by confirming another ticket, which legitimately consumes a slot and
    bumps `committed_rider_count` — the confirm is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_time_block_version_on_confirm_returns_412
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-04-07T10:30:00Z", lane_capacity=5, num_lanes=1,
        block_starts="2026-04-07T10:00:00Z", block_ends="2026-04-07T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    pa, _ = fx.setup_waivered_patron(park_id)
    pb, _ = fx.setup_waivered_patron(park_id)
    ta = fx.create_ticket(park_id, block_id, pa["id"])
    tb = fx.create_ticket(park_id, block_id, pb["id"])
    # Both read the same version, then A confirms (bumping it).
    shared_v = fx.block_version(block_id, pb["id"])
    validate_success(api.confirm_ticket(ta["id"], shared_v, make_guest_patron_headers(pa["id"])), 200)
    # B confirms with the now-stale version.
    resp = api.confirm_ticket(tb["id"], shared_v, make_guest_patron_headers(pb["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    ticket_b = validate_success(api.get_ticket(tb["id"], fx.OPERATOR), 200)
    assert ticket_b["lifecycle_state"] == "RESERVED"


# ===========================================================================
# Corner/cross_cutting_complexity_layers/capacity_remaining_reconciled_after_confirm_and_refund
# ===========================================================================

def test_capacity_remaining_reconciles_down_then_up(api):
    """PRD §2.7: "total_capacity_remaining` is the sum, over all `OPEN` lanes, of each lane's
    `rider_capacity_per_block`, minus the riders already committed for the active block;
    it is reconciled on every event that opens or closes a lane or commits or releases a
    rider."

    Design: Corner/cross_cutting_complexity_layers/capacity_remaining_reconciled_after_confirm_and_refund
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-04-08T10:30:00Z", lane_capacity=5,
        block_starts="2026-04-08T10:00:00Z", block_ends="2026-04-08T12:00:00Z",
    )
    park_id, block_id, ticket_id, patron = (
        state["park"]["id"], state["block"]["id"], state["ticket"]["id"], state["patron"]
    )
    # After confirm: remaining is 4 (5 cap - 1 committed).
    park_mid = validate_success(api.get_park(park_id, fx.OPERATOR), 200)
    assert park_mid["total_capacity_remaining"] == 4
    # Refund releases the slot.
    validate_success(api.refund_ticket(ticket_id, make_guest_patron_headers(patron["id"])), 200)
    park_after = validate_success(api.get_park(park_id, fx.OPERATOR), 200)
    assert park_after["total_capacity_remaining"] == 5, \
        f"remaining must reconcile back to 5, got {park_after['total_capacity_remaining']}"
    block = validate_success(api.get_time_block(block_id, fx.OPERATOR), 200)
    assert block["committed_rider_count"] == 0


# ===========================================================================
# Corner/consistency_model/confirm_response_reflects_committed_count_immediately
# ===========================================================================

def test_committed_count_visible_immediately_after_confirm(api):
    """PRD §3.4: "the block's `committed_rider_count` rises by one".
    PRD §1 (Introduction): "capacity ledgers are reconciled the instant a ticket is
    confirmed or released".

    Design: Corner/consistency_model/confirm_response_reflects_committed_count_immediately
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-04-09T10:30:00Z", lane_capacity=5,
        block_starts="2026-04-09T10:00:00Z", block_ends="2026-04-09T12:00:00Z",
    )
    block = validate_success(api.get_time_block(state["block"]["id"], fx.OPERATOR), 200)
    assert block["committed_rider_count"] == 1, \
        f"committed count must be 1 immediately after confirm, got {block['committed_rider_count']}"
