"""Closures, cascades, and refund reconciliation.

Covers the weather-CLOSED depth-3 cascade (park -> lane -> ticket -> refund),
the block-sweep depth-2 no-show cascade (no refund), the confirm/refund
conserved-count invariant, and the weather-log derived posture computed read.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_guest_patron_headers,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Difficulty/transitive_cascade/weather_closed_cascades_lane_close_ticket_expire_refund_depth3
# ===========================================================================

def test_weather_closed_cascades_park_lane_ticket_states(api):
    """PRD §3.6: "every lane currently `OPEN` or `GROOMING` is forced to `CLOSED` with
    `closure_reason` `WEATHER`; and for each lane so closed, every `CONFIRMED` session
    ticket committed to that lane in the active block is forced to `EXPIRED".
    PRD §2.6: "if the reading's `snow_depth_cm` is strictly less than the park's
    `min_snow_depth_cm`, the implied posture is `CLOSED`."

    Design: Difficulty/transitive_cascade/weather_closed_cascades_lane_close_ticket_expire_refund_depth3
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-08T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-08T10:00:00Z", block_ends="2026-03-08T12:00:00Z",
        park_overrides={"min_snow_depth_cm": 15, "max_safe_wind_kph": 50},
    )
    park_id, lane_id, ticket_id = state["park"]["id"], state["lane"]["id"], state["ticket"]["id"]
    fx.create_weather_log(park_id, observed_at="2026-03-08T10:35:00Z", snow_depth_cm=5, wind_kph=10)
    park = validate_success(api.get_park(park_id, fx.OPERATOR), 200)
    assert park["operational_posture"] == "CLOSED"
    lane = validate_success(api.get_lane(lane_id, fx.OPERATOR), 200)
    assert lane["status"] == "CLOSED"
    assert lane["closure_reason"] == "WEATHER"
    ticket = validate_success(api.get_ticket(ticket_id, fx.OPERATOR), 200)
    assert ticket["lifecycle_state"] == "EXPIRED"


def test_weather_closed_writes_weather_closure_refund(api):
    """PRD §3.6: "each such weather-expiry writes a `RefundEntry` whose `reason` is `WEATHER_CLOSURE`
    and whose `amount_cents` equals that ticket's `base_price_cents`."

    Design: Difficulty/transitive_cascade/weather_closed_cascades_lane_close_ticket_expire_refund_depth3
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-08T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-08T10:00:00Z", block_ends="2026-03-08T12:00:00Z",
        rider_age_years=30,  # adult walkup non-resident -> base 3500
        park_overrides={"min_snow_depth_cm": 15, "max_safe_wind_kph": 50},
    )
    park_id, ticket_id = state["park"]["id"], state["ticket"]["id"]
    assert state["ticket"]["base_price_cents"] == 3500
    fx.create_weather_log(park_id, observed_at="2026-03-08T10:35:00Z", snow_depth_cm=5, wind_kph=10)
    refunds = validate_success(api.list_refund_entries(fx.OPERATOR, params={"ticket_id": ticket_id}), 200)
    assert len(refunds) == 1, f"expected exactly one refund entry, got {len(refunds)}"
    assert refunds[0]["reason"] == "WEATHER_CLOSURE"
    assert refunds[0]["amount_cents"] == 3500


# ===========================================================================
# Difficulty/transitive_cascade/timeblock_sweep_expires_noshow_ticket_depth2
# ===========================================================================

def test_sweep_expires_noshow_and_decrements_committed_count(api):
    """PRD §3.6: "every `CONFIRMED` ticket in that block that is still `NOT_CHECKED_IN` is treated as
    a no-show and forced to `EXPIRED` with **no** refund (a no-show forfeits), and that
    expiry releases its committed slot: `committed_rider_count` is decremented and park
    aggregates recomputed."

    Design: Difficulty/transitive_cascade/timeblock_sweep_expires_noshow_ticket_depth2
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-09T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-09T10:00:00Z", block_ends="2026-03-09T12:00:00Z",
    )
    block_id, ticket_id = state["block"]["id"], state["ticket"]["id"]
    validate_success(api.sweep_time_block(block_id, fx.OPERATOR), 200)
    ticket = validate_success(api.get_ticket(ticket_id, fx.OPERATOR), 200)
    assert ticket["lifecycle_state"] == "EXPIRED"
    block = validate_success(api.get_time_block(block_id, fx.OPERATOR), 200)
    assert block["committed_rider_count"] == 0


def test_sweep_noshow_writes_no_refund(api):
    """PRD §3.6: "every `CONFIRMED` ticket in that block that is still `NOT_CHECKED_IN` is treated as
    a no-show and forced to `EXPIRED` with **no** refund (a no-show forfeits)".

    Design: Difficulty/transitive_cascade/timeblock_sweep_expires_noshow_ticket_depth2
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-09T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-09T10:00:00Z", block_ends="2026-03-09T12:00:00Z",
    )
    block_id, ticket_id = state["block"]["id"], state["ticket"]["id"]
    validate_success(api.sweep_time_block(block_id, fx.OPERATOR), 200)
    refunds = validate_success(api.list_refund_entries(fx.OPERATOR, params={"ticket_id": ticket_id}), 200)
    assert refunds == [], f"no-show sweep must write no refund, got {refunds}"


# ===========================================================================
# Difficulty/compensating_invariant/confirm_then_refund_conserves_committed_rider_count
# ===========================================================================

def test_confirm_then_refund_conserves_committed_rider_count(api):
    """PRD §3.4: "A refund sets `lifecycle_state` to `REFUNDED`, decrements the block's
    `committed_rider_count` by one, recomputes the park's `total_capacity_remaining".
    PRD §3.4: "the block's `committed_rider_count` rises by one".

    Design: Difficulty/compensating_invariant/confirm_then_refund_conserves_committed_rider_count
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-18T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-18T10:00:00Z", block_ends="2026-03-18T12:00:00Z",
    )
    block_id, ticket_id, patron = state["block"]["id"], state["ticket"]["id"], state["patron"]
    refunded = validate_success(api.refund_ticket(ticket_id, make_guest_patron_headers(patron["id"])), 200)
    assert refunded["lifecycle_state"] == "REFUNDED"
    block = validate_success(api.get_time_block(block_id, fx.OPERATOR), 200)
    assert block["committed_rider_count"] == 0, \
        f"committed_rider_count must return to pre-confirm 0, got {block['committed_rider_count']}"


def test_refund_writes_patron_cancel_entry(api):
    """PRD §3.4: "writes a `RefundEntry` whose `reason` is `PATRON_CANCEL` and whose `amount_cents`
    equals the ticket's `base_price_cents`."

    Design: Difficulty/compensating_invariant/confirm_then_refund_conserves_committed_rider_count
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-18T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-18T10:00:00Z", block_ends="2026-03-18T12:00:00Z",
        rider_age_years=30,  # base 3500
    )
    ticket_id, patron = state["ticket"]["id"], state["patron"]
    assert state["ticket"]["base_price_cents"] == 3500
    validate_success(api.refund_ticket(ticket_id, make_guest_patron_headers(patron["id"])), 200)
    refunds = validate_success(api.list_refund_entries(fx.OPERATOR, params={"ticket_id": ticket_id}), 200)
    assert len(refunds) == 1
    assert refunds[0]["reason"] == "PATRON_CANCEL"
    assert refunds[0]["amount_cents"] == 3500


# ===========================================================================
# Corner/endpoints/weather_log_derived_posture_computed_read
# ===========================================================================

def test_weather_log_derived_posture_restricted(api):
    """PRD §2.6: "if the reading's `wind_kph` is greater than or equal to the park's
    `max_safe_wind_kph` and its `snow_depth_cm` is greater than or equal to
    `min_snow_depth_cm`, the implied posture is `RESTRICTED`."

    Design: Corner/endpoints/weather_log_derived_posture_computed_read
    """
    fx.set_clock("2026-04-04T09:00:00Z")
    park = fx.create_park(name="WxPark", resident_zip_prefixes=[],
                          min_snow_depth_cm=15, max_safe_wind_kph=50)
    log = validate_success(
        api.create_weather_log(park["id"],
                               {"observed_at": "2026-04-04T09:05:00Z", "snow_depth_cm": 40, "wind_kph": 60},
                               fx.OPERATOR),
        201,
    )
    assert log["derived_posture"] == "RESTRICTED"
    park_after = validate_success(api.get_park(park["id"], fx.OPERATOR), 200)
    assert park_after["operational_posture"] == "RESTRICTED"
