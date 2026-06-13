"""Lane half-open and bay closed-interval-plus-buffer temporal conflict rules.

Covers Difficulty queue: resource_temporal_overlap (lane half-open adjacency,
bay buffer gap).
"""

from test_helpers import (
    validate_success,
    validate_error,
    create_rate_card_payload,
    create_lane_payload,
    create_bay_payload,
    create_customer_payload,
    create_reservation_payload,
    CM, FD,
)


def test_lane_back_to_back_allowed_but_overlap_rejected(api):
    """PRD §2.9: "For a lane, booking windows are treated as half-open intervals
    `[start_at, end_at)`: a new window conflicts with an existing blocking
    reservation on the same lane when the two intervals overlap, but two bookings
    that touch exactly — one ending at the precise instant the next begins — are
    permitted back-to-back. A lane conflict is rejected with
    `ERR_LANE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lane_half_open_back_to_back_allowed_overlap_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="T1", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    r1 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-11T18:00:00.000Z", end_at="2026-08-11T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(r1["id"], FD), 200)

    r2 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-11T19:00:00.000Z", end_at="2026-08-11T20:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    r3 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-11T18:30:00.000Z", end_at="2026-08-11T19:30:00.000Z",
        bowler_count=2, game_count=1), FD), 201)

    held2 = validate_success(api.hold_reservation(r2["id"], FD), 200)
    assert held2["status"] == "HELD"  # back-to-back adjacency allowed

    resp = api.hold_reservation(r3["id"], FD)
    validate_error(resp, "ERR_LANE_TIME_CONFLICT", expected_status=409)


def test_bay_back_to_back_rejected_inside_cleanup_buffer(api):
    """PRD §2.9: "Each bay carries a `cleanup_buffer_minutes` gap that must
    separate consecutive bookings. A new bay window is in conflict when it starts
    before a prior booking's end plus the buffer, or when it ends after a
    following booking's start minus the buffer, on the same bay. A bay conflict is
    rejected with `ERR_BAY_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_closed_interval_buffer_gap_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="T2", per_game_cents=0, per_hour_cents=2000, deposit_pct_bps=2000), CM), 201)
    bay = validate_success(api.create_bay(create_bay_payload(
        capacity=8, cleanup_buffer_minutes=15), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    r1 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="BAY", bay_id=bay["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-12T18:00:00.000Z", end_at="2026-08-12T19:00:00.000Z",
        bowler_count=4), FD), 201)
    validate_success(api.hold_reservation(r1["id"], FD), 200)

    # R2 starts exactly at prior end (19:00), inside the 15-min cleanup buffer.
    r2 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="BAY", bay_id=bay["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-12T19:00:00.000Z", end_at="2026-08-12T20:00:00.000Z",
        bowler_count=4), FD), 201)
    resp = api.hold_reservation(r2["id"], FD)
    validate_error(resp, "ERR_BAY_TIME_CONFLICT", expected_status=409)


# =============================================================================
# Difficulty — second tests (distinct PRD-derivable facet per instance)
# =============================================================================
def test_lane_reverse_touch_adjacency_allowed(api):
    """PRD §2.9: "two bookings that touch exactly — one ending at the precise
    instant the next begins — are permitted back-to-back."

    The adjacency rule holds from the other side too: a window ending exactly when
    an existing blocking window begins is permitted.

    Design: Difficulty/resource_temporal_overlap/lane_half_open_back_to_back_allowed_overlap_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="T1b", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    later = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-11T19:00:00.000Z", end_at="2026-08-11T20:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(later["id"], FD), 200)

    earlier = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-11T18:00:00.000Z", end_at="2026-08-11T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    held = validate_success(api.hold_reservation(earlier["id"], FD), 200)
    assert held["status"] == "HELD"  # ends exactly when the later window begins


def test_bay_booking_after_buffer_gap_allowed(api):
    """PRD §2.9: "Each bay carries a `cleanup_buffer_minutes` gap that must
    separate consecutive bookings. A new bay window is in conflict when it starts
    before a prior booking's end plus the buffer".

    A bay window that starts at exactly prior_end + buffer (not before it) clears
    the cleanup gap and is accepted.

    Design: Difficulty/resource_temporal_overlap/bay_closed_interval_buffer_gap_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="T2b", per_game_cents=0, per_hour_cents=2000, deposit_pct_bps=2000), CM), 201)
    bay = validate_success(api.create_bay(create_bay_payload(
        capacity=8, cleanup_buffer_minutes=15), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    r1 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="BAY", bay_id=bay["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-12T18:00:00.000Z", end_at="2026-08-12T19:00:00.000Z",
        bowler_count=4), FD), 201)
    validate_success(api.hold_reservation(r1["id"], FD), 200)

    # R2 starts at 19:15 == prior_end (19:00) + 15-min buffer -> not before -> allowed
    r2 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="BAY", bay_id=bay["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-12T19:15:00.000Z", end_at="2026-08-12T20:15:00.000Z",
        bowler_count=4), FD), 201)
    held2 = validate_success(api.hold_reservation(r2["id"], FD), 200)
    assert held2["status"] == "HELD"
