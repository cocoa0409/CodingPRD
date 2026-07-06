"""Session-ticket lifecycle and the parallel check-in dimension.

Covers the two independent state axes (lifecycle x checkin), confirm capacity
boundary precision, conveyor-turn interval adjacency, cross-entity gating on
park posture and lane status, redeem preconditions, and the tube height minimum.
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
# Difficulty/non_linear_state_machine/ticket_parallel_lifecycle_and_checkin_dimensions
# ===========================================================================

def test_gear_up_advances_checkin_axis_leaving_lifecycle_confirmed(api):
    """PRD §3.4: "A new ticket starts with `lifecycle_state` of `RESERVED` and `checkin_state` of
    `NOT_CHECKED_IN`; these two dimensions evolve independently."
    PRD §3.5: "A `SafetyMarshal` gears up a rider — `NOT_CHECKED_IN → GEARED_UP` — which requires
    the ticket's `checkin_state` to be `NOT_CHECKED_IN`, its `lifecycle_state` to be
    `CONFIRMED`, and at least one `DISPATCHED` equipment rental of `equipment_type`
    `TUBE` to exist for the ticket."

    Design: Difficulty/non_linear_state_machine/ticket_parallel_lifecycle_and_checkin_dimensions
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-06T10:30:00Z",
        block_starts="2026-03-06T10:00:00Z", block_ends="2026-03-06T12:00:00Z",
    )
    fx.dispatch_tube(state["ticket"]["id"], tube_size="MEDIUM")
    geared = validate_success(api.gear_up_ticket(state["ticket"]["id"], fx.MARSHAL), 200)
    assert geared["lifecycle_state"] == "CONFIRMED", "lifecycle axis must remain CONFIRMED after gear-up"
    assert geared["checkin_state"] == "GEARED_UP", "checkin axis must advance to GEARED_UP"


def test_confirm_advances_lifecycle_without_touching_checkin(api):
    """PRD §3.4: "On success the ticket's `lifecycle_state` becomes `CONFIRMED".
    PRD §3.4: "A new ticket starts with `lifecycle_state` of `RESERVED` and `checkin_state` of
    `NOT_CHECKED_IN`; these two dimensions evolve independently."

    Design: Difficulty/non_linear_state_machine/ticket_parallel_lifecycle_and_checkin_dimensions
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-06T10:30:00Z",
        block_starts="2026-03-06T10:00:00Z", block_ends="2026-03-06T12:00:00Z",
    )
    # setup_confirmed_ticket already confirmed it; assert the confirmed snapshot.
    assert state["ticket"]["lifecycle_state"] == "CONFIRMED"
    assert state["ticket"]["checkin_state"] == "NOT_CHECKED_IN", \
        "checkin axis must stay NOT_CHECKED_IN after a lifecycle confirm"


# ===========================================================================
# Difficulty/boundary_precision_check/capacity_exact_fill_then_one_over_on_confirm
# ===========================================================================

def test_confirm_at_exact_capacity_boundary_succeeds(api):
    """PRD §2.7: "a commit may not push a time block's `committed_rider_count` above the sum of the
    capacities (`rider_capacity_per_block`) of the park's currently `OPEN` lanes."

    Design: Difficulty/boundary_precision_check/capacity_exact_fill_then_one_over_on_confirm
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-03-12T10:30:00Z", lane_capacity=2, num_lanes=1,
        block_starts="2026-03-12T10:00:00Z", block_ends="2026-03-12T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    # Patron A then B confirm; the 2nd (committed 1->2, 2<=2) is the exact boundary.
    pa, _ = fx.setup_waivered_patron(park_id)
    pb, _ = fx.setup_waivered_patron(park_id)
    ta = fx.create_ticket(park_id, block_id, pa["id"])
    tb = fx.create_ticket(park_id, block_id, pb["id"])
    fx.confirm_ticket(ta["id"], pa["id"], block_id)
    confirmed_b = fx.confirm_ticket(tb["id"], pb["id"], block_id)
    assert confirmed_b["lifecycle_state"] == "CONFIRMED"
    block = validate_success(api.get_time_block(block_id, fx.OPERATOR), 200)
    assert block["committed_rider_count"] == 2, f"expected 2 at boundary, got {block['committed_rider_count']}"


def test_confirm_one_over_capacity_rejected(api):
    """PRD §2.7: "A commit that would breach that ceiling is rejected with `ERR_CAPACITY_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/capacity_exact_fill_then_one_over_on_confirm
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-03-12T10:30:00Z", lane_capacity=2, num_lanes=1,
        block_starts="2026-03-12T10:00:00Z", block_ends="2026-03-12T12:00:00Z",
    )
    park_id, block_id = base["park"]["id"], base["block"]["id"]
    pa, _ = fx.setup_waivered_patron(park_id)
    pb, _ = fx.setup_waivered_patron(park_id)
    pc, _ = fx.setup_waivered_patron(park_id)
    ta = fx.create_ticket(park_id, block_id, pa["id"])
    tb = fx.create_ticket(park_id, block_id, pb["id"])
    tc = fx.create_ticket(park_id, block_id, pc["id"])
    fx.confirm_ticket(ta["id"], pa["id"], block_id)
    fx.confirm_ticket(tb["id"], pb["id"], block_id)
    # 3rd confirm: 2 + 1 = 3 > 2 -> rejected.
    v = fx.block_version(block_id, pc["id"])
    resp = api.confirm_ticket(tc["id"], v, make_guest_patron_headers(pc["id"]))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Difficulty/boundary_precision_check/conveyor_turn_adjacency_allowed_half_open_on_board
# ===========================================================================

def test_board_adjacent_turn_at_exact_clear_instant_allowed(api):
    """PRD §3.5: "Adjacency is allowed — a new turn whose `boarded_at` exactly equals an existing
    turn's `cleared_at` does not overlap, because the interval is half-open with zero
    buffer".

    Design: Difficulty/boundary_precision_check/conveyor_turn_adjacency_allowed_half_open_on_board
    """
    base = fx.setup_park_with_lane_and_block(
        clock="2026-03-13T10:30:00Z", lane_capacity=5, num_lanes=1, conveyor_cycle_seconds=30,
        block_starts="2026-03-13T10:00:00Z", block_ends="2026-03-13T12:00:00Z",
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
    fx.board(t1["id"], lane_id, "2026-03-13T10:30:00Z")  # clears at 10:30:30
    # Second board at exactly 10:30:30 == first cleared_at -> adjacency allowed.
    boarded = validate_success(
        api.board_ticket(t2["id"], create_board_payload(lane_id=lane_id, boarded_at="2026-03-13T10:30:30Z"), fx.MARSHAL),
        200,
    )
    assert boarded["checkin_state"] == "ON_LANE"
    turns = validate_success(api.list_conveyor_turns(fx.OPERATOR, params={"lane_id": lane_id}), 200)
    assert len(turns) == 2, f"expected exactly two conveyor turns, got {len(turns)}"


def test_board_creates_conveyor_turn_with_computed_clear(api):
    """PRD §3.5: "Boarding creates a `ConveyorTurn` in `state` `BOARDED` on the lane, recording the
    `lane_id`, the `time_block_id`, the rider's `ticket_id`, the `boarded_at` instant,
    and a computed `cleared_at` equal to `boarded_at` plus the lane's
    `conveyor_cycle_seconds` (added as seconds)".

    Design: Difficulty/boundary_precision_check/conveyor_turn_adjacency_allowed_half_open_on_board
    """
    state = fx.setup_geared_up_ticket(
        clock="2026-03-13T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-13T10:00:00Z", block_ends="2026-03-13T12:00:00Z",
    )
    fx.board(state["ticket"]["id"], state["lane"]["id"], "2026-03-13T10:30:00Z")
    turns = validate_success(api.list_conveyor_turns(fx.OPERATOR, params={"lane_id": state["lane"]["id"]}), 200)
    assert len(turns) == 1
    assert turns[0]["state"] == "BOARDED"
    assert turns[0]["lane_id"] == state["lane"]["id"]


# ===========================================================================
# Difficulty/cross_entity_state_dependency/ticket_confirm_blocked_by_park_restricted_posture
# ===========================================================================

def test_confirm_blocked_when_park_restricted(api):
    """PRD §2.6: "Confirming a ticket and holding a group reservation additionally require the posture
    to be exactly `OPEN` — a posture of `RESTRICTED` blocks them too".
    PRD §3.4: "the park's posture to be exactly `OPEN".

    Design: Difficulty/cross_entity_state_dependency/ticket_confirm_blocked_by_park_restricted_posture
    """
    state = fx.setup_reserved_ticket(
        clock="2026-03-14T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-14T10:00:00Z", block_ends="2026-03-14T12:00:00Z",
        park_overrides={"min_snow_depth_cm": 15, "max_safe_wind_kph": 50},
    )
    park_id, block_id, patron = state["park"]["id"], state["block"]["id"], state["patron"]
    # High wind + deep snow -> RESTRICTED.
    fx.create_weather_log(park_id, observed_at="2026-03-14T10:35:00Z", snow_depth_cm=40, wind_kph=60)
    park = validate_success(api.get_park(park_id, fx.OPERATOR), 200)
    assert park["operational_posture"] == "RESTRICTED"
    v = fx.block_version(block_id, patron["id"])
    resp = api.confirm_ticket(state["ticket"]["id"], v, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PARK_CLOSED.value)
    ticket = validate_success(api.get_ticket(state["ticket"]["id"], fx.OPERATOR), 200)
    assert ticket["lifecycle_state"] == "RESERVED"


def test_restricted_posture_keeps_ticket_reserved(api):
    """PRD §2.6: "Confirming a ticket and holding a group reservation additionally require the posture
    to be exactly `OPEN` — a posture of `RESTRICTED` blocks them too".

    Design: Difficulty/cross_entity_state_dependency/ticket_confirm_blocked_by_park_restricted_posture
    """
    state = fx.setup_reserved_ticket(
        clock="2026-03-14T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-14T10:00:00Z", block_ends="2026-03-14T12:00:00Z",
        park_overrides={"min_snow_depth_cm": 15, "max_safe_wind_kph": 50},
    )
    park_id, patron = state["park"]["id"], state["patron"]
    fx.create_weather_log(park_id, observed_at="2026-03-14T10:35:00Z", snow_depth_cm=40, wind_kph=60)
    v = fx.block_version(state["block"]["id"], patron["id"])
    resp = api.confirm_ticket(state["ticket"]["id"], v, make_guest_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_PARK_CLOSED.value)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/ticket_board_blocked_by_lane_grooming
# ===========================================================================

def test_board_blocked_when_target_lane_grooming(api):
    """PRD §3.5: "Boarding a rider — `GEARED_UP → ON_LANE` — is performed by a `SafetyMarshal` and
    carries a `lane_id` (the lane to board) and a `boarded_at` instant. It requires the
    ticket's `checkin_state` to be `GEARED_UP` and the target lane's `status` to be
    `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/ticket_board_blocked_by_lane_grooming
    """
    # Two lanes so committing on lane is unaffected; groom lane1 (the target).
    state = fx.setup_geared_up_ticket(
        clock="2026-03-15T10:30:00Z", lane_capacity=5, num_lanes=2,
        block_starts="2026-03-15T10:00:00Z", block_ends="2026-03-15T12:00:00Z",
    )
    lane1 = state["lanes"][0]
    groomed = validate_success(api.groom_lane(lane1["id"], fx.OPERATOR), 200)
    assert groomed["status"] == "GROOMING"
    resp = api.board_ticket(state["ticket"]["id"],
                            create_board_payload(lane_id=lane1["id"], boarded_at="2026-03-15T10:40:00Z"),
                            fx.MARSHAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    ticket = validate_success(api.get_ticket(state["ticket"]["id"], fx.OPERATOR), 200)
    assert ticket["checkin_state"] == "GEARED_UP"


def test_board_onto_grooming_lane_leaves_checkin_geared_up(api):
    """PRD §3.5: "requires the ticket's `checkin_state` to be `GEARED_UP` and the target lane's
    `status` to be `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/ticket_board_blocked_by_lane_grooming
    """
    state = fx.setup_geared_up_ticket(
        clock="2026-03-15T10:30:00Z", lane_capacity=5, num_lanes=2,
        block_starts="2026-03-15T10:00:00Z", block_ends="2026-03-15T12:00:00Z",
    )
    lane1 = state["lanes"][0]
    validate_success(api.groom_lane(lane1["id"], fx.OPERATOR), 200)
    resp = api.board_ticket(state["ticket"]["id"],
                            create_board_payload(lane_id=lane1["id"], boarded_at="2026-03-15T10:40:00Z"),
                            fx.MARSHAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    turns = validate_success(api.list_conveyor_turns(fx.OPERATOR, params={"lane_id": lane1["id"]}), 200)
    assert len(turns) == 0, "no conveyor turn should be created on a failed board"


# ===========================================================================
# Corner/state_machines/redeem_requires_on_lane_checkin_state
# ===========================================================================

def test_redeem_requires_on_lane_checkin(api):
    """PRD §3.5: "it requires the ticket's `lifecycle_state` to be `CONFIRMED`, its `checkin_state` to
    be `ON_LANE`, and the ticket's time block to be `ACTIVE`."

    Design: Corner/state_machines/redeem_requires_on_lane_checkin_state
    """
    state = fx.setup_confirmed_ticket(
        clock="2026-03-27T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-27T10:00:00Z", block_ends="2026-03-27T12:00:00Z",
    )
    # Ticket is CONFIRMED but checkin is still NOT_CHECKED_IN.
    resp = api.redeem_ticket(state["ticket"]["id"], fx.MARSHAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    ticket = validate_success(api.get_ticket(state["ticket"]["id"], fx.OPERATOR), 200)
    assert ticket["lifecycle_state"] == "CONFIRMED"


# ===========================================================================
# Corner/state_machines/clear_conveyor_turn_before_cycle_elapsed_returns_invalid_state
# ===========================================================================

def test_clear_turn_before_cycle_elapsed_rejected(api):
    """PRD §3.5: "a `ParkOperator` clears it — `BOARDED → CLEARED` — which requires the turn to be
    `BOARDED` and the logical clock to be at or after the turn's `cleared_at`."

    Design: Corner/state_machines/clear_conveyor_turn_before_cycle_elapsed_returns_invalid_state
    """
    # Board at 10:30:00, cycle 30s -> cleared_at 10:30:30; clock still 10:30:00.
    state = fx.setup_boarded_ticket(
        clock="2026-03-26T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-26T10:00:00Z", block_ends="2026-03-26T12:00:00Z",
        boarded_at="2026-03-26T10:30:00Z",
    )
    turn = state["turn"]
    assert turn is not None and turn["state"] == "BOARDED"
    resp = api.clear_conveyor_turn(turn["id"], fx.OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    fetched = validate_success(api.get_conveyor_turn(turn["id"], fx.OPERATOR), 200)
    assert fetched["state"] == "BOARDED"


# ===========================================================================
# Corner/validations/height_below_min_blocks_gear_up
# ===========================================================================

def test_gear_up_short_rider_below_height_min_rejected(api):
    """PRD §3.5: "Gearing up with a tube also enforces the height minimum: the rider's
    `rider_height_cm` must be at least 92 centimeters, and a shorter rider is rejected
    with `ERR_HEIGHT_BELOW_MIN` (HTTP 422)."

    Design: Corner/validations/height_below_min_blocks_gear_up
    """
    # Confirmed minor rider with guardian waiver, height 80 < 92, DISPATCHED TUBE.
    state = fx.setup_confirmed_ticket(
        clock="2026-03-31T10:30:00Z", lane_capacity=5,
        block_starts="2026-03-31T10:00:00Z", block_ends="2026-03-31T12:00:00Z",
        rider_height_cm=80, rider_age_years=7, guardian_name="Parent P",
    )
    fx.dispatch_tube(state["ticket"]["id"], tube_size="SMALL")
    resp = api.gear_up_ticket(state["ticket"]["id"], fx.MARSHAL)
    validate_error(resp, ApiErrorId.ERR_HEIGHT_BELOW_MIN.value)
    ticket = validate_success(api.get_ticket(state["ticket"]["id"], fx.OPERATOR), 200)
    assert ticket["checkin_state"] == "NOT_CHECKED_IN"
