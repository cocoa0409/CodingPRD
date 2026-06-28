"""Non-linear state-machine shapes (reservation's parallel dimensions, trail revert
cycle) and transitive cascade chains (trail close depth-3, depart depth-2). Covers
difficulty rules non_linear_state_machine and transitive_cascade."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_trail,
    setup_confirmed_reservation, setup_checked_out_reservation,
    read_reservation, read_member, read_unit, read_gear, read_departure,
    make_member_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]


# ===================================================================
# Rule non_linear_state_machine
# ===================================================================

def test_cancel_advances_both_reservation_and_settlement_dimensions(api):
    """PRD §3.4: "a reservation may be `CHECKED_OUT` on the lifecycle axis while still
    `HELD` on the billing axis, and the settlement axis advances only as a side effect
    of lifecycle transitions, never by direct request."
    PRD §3.9: "cancelling a confirmed reservation releases its unit from `RESERVED` to
    `AVAILABLE`, releases its gear from `ASSIGNED` to `AVAILABLE`, decrements the
    departure's `rider_count` by one, moves its billing state from `HELD` to `REFUNDED`
    with the full `deposit_hold_cents` refunded, and recomputes the member's total hold."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_status_vs_settlement
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Loop", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-18T09:00:00Z", "ends_at": "2026-12-18T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)
    member = bundle["member"]
    res = read_reservation(bundle["reservation"]["id"])
    assert res["reservation_status"] == "CONFIRMED"
    assert res["settlement_status"] == "HELD"

    cancelled = validate_success(
        api.cancel_reservation(bundle["reservation"]["id"], make_member_headers(member["id"])), 200)
    assert cancelled["reservation_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "REFUNDED"
    assert read_member(member["id"])["deposit_hold_cents"] == 0


def test_trail_condition_reverts_open_caution_open(api):
    """PRD §3.7: "Moving a trail among `OPEN` and `CAUTION` in either direction is
    purely advisory and cancels nothing: those transitions record a `ClosureEvent`
    whose `cancelled_departure_count` is zero, and the trail's `condition` is updated
    to the new value."

    Design: Difficulty/non_linear_state_machine/trail_condition_revert_open_caution_open_cycle
    """
    trail = create_trail(name="Cycle", required_class="TRAIL", max_riders=10)
    get_success_data(api.post_closure(trail["id"], {"new_condition": "CAUTION", "reason": "wind"}, DISPATCH))
    event = validate_success(
        api.post_closure(trail["id"], {"new_condition": "OPEN", "reason": "cleared"}, DISPATCH), 201)
    assert event["new_condition"] == "OPEN"
    assert event["cancelled_departure_count"] == 0
    trail_after = validate_success(api.get_trail(trail["id"], DISPATCH), 200)
    assert trail_after["condition"] == "OPEN"


# ===================================================================
# Rule transitive_cascade
# ===================================================================

def test_trail_close_cascades_departure_reservation_deposit_depth3(api):
    """PRD §3.7: "When a trail closes, every departure on that trail whose status is
    `SCHEDULED` or `LOCKED` is cancelled: each such departure runs the full
    departure-cancellation cascade of §3.6, which in turn unwinds that departure's
    `PENDING` and `CONFIRMED` reservations, releasing their units and gear and refunding
    any `HELD` deposits."
    PRD §3.7: "The number of departures cancelled this way is counted into the
    `ClosureEvent`'s `cancelled_departure_count`."

    Design: Difficulty/transitive_cascade/trail_close_cascades_departure_then_reservation_then_deposit_depth3
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "ClsTrail", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-20T09:00:00Z", "ends_at": "2026-12-20T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)
    trail = bundle["trail"]
    dep = bundle["departure"]
    unit = bundle["unit"]
    member = bundle["member"]
    res = bundle["reservation"]

    event = validate_success(
        api.post_closure(trail["id"], {"new_condition": "CLOSED", "reason": "avalanche risk"}, DISPATCH), 201)
    assert event["cancelled_departure_count"] == 1

    assert validate_success(api.get_trail(trail["id"], DISPATCH), 200)["condition"] == "CLOSED"
    assert read_departure(dep["id"])["status"] == "CANCELLED"
    res_after = read_reservation(res["id"])
    assert res_after["reservation_status"] == "CANCELLED"
    assert res_after["settlement_status"] == "REFUNDED"
    assert read_unit(unit["id"])["status"] == "AVAILABLE"
    assert read_member(member["id"])["deposit_hold_cents"] == 0


def test_depart_cascades_checkout_unit_out_gear_out_depth2(api):
    """PRD §3.6: "every reservation still `CONFIRMED` is checked out — moved to
    `CHECKED_OUT`, its `checked_out_at` stamped with the clock now, its unit moved from
    `RESERVED` to `OUT`, and its assigned gear moved from `ASSIGNED` to `OUT`".

    Design: Difficulty/transitive_cascade/depart_cascades_confirmed_to_checkedout_then_unit_out_depth2
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "DepTrail", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-22T09:00:00Z", "ends_at": "2026-12-22T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-22T09:15:00Z")
    assert read_departure(bundle["departure"]["id"])["status"] == "DEPARTED"
    assert read_reservation(bundle["reservation"]["id"])["reservation_status"] == "CHECKED_OUT"
    assert read_unit(bundle["unit"]["id"])["status"] == "OUT"
    assert read_gear(bundle["helmet"]["id"])["status"] == "OUT"
    assert read_gear(bundle["suit"]["id"])["status"] == "OUT"


# ===================================================================
# Second tests per instance (≥2 coverage)
# ===================================================================

def test_confirm_advances_status_to_confirmed_and_settlement_to_held(api):
    """PRD §3.4: "On success the reservation moves from `PENDING` to `CONFIRMED`; its
    `settlement_status` advances from `NONE` to `HELD`".

    Design: Difficulty/non_linear_state_machine/reservation_parallel_dimensions_status_vs_settlement
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Loop2", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-18T09:00:00Z", "ends_at": "2026-12-18T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)
    res = read_reservation(bundle["reservation"]["id"])
    # Two independent axes advanced by the single confirm side effect.
    assert res["reservation_status"] == "CONFIRMED"
    assert res["settlement_status"] == "HELD"


def test_trail_open_to_caution_records_zero_count_event(api):
    """PRD §3.7: "Moving a trail among `OPEN` and `CAUTION` in either direction is purely
    advisory and cancels nothing: those transitions record a `ClosureEvent` whose
    `cancelled_departure_count` is zero, and the trail's `condition` is updated to the
    new value."

    Design: Difficulty/non_linear_state_machine/trail_condition_revert_open_caution_open_cycle
    """
    trail = create_trail(name="Cycle2", required_class="TRAIL", max_riders=10)
    event = validate_success(
        api.post_closure(trail["id"], {"new_condition": "CAUTION", "reason": "fog"}, DISPATCH), 201)
    assert event["new_condition"] == "CAUTION"
    assert event["cancelled_departure_count"] == 0
    assert validate_success(api.get_trail(trail["id"], DISPATCH), 200)["condition"] == "CAUTION"


def test_trail_close_releases_unit_to_available(api):
    """PRD §3.7: "which in turn unwinds that departure's `PENDING` and `CONFIRMED`
    reservations, releasing their units and gear and refunding any `HELD` deposits."

    Design: Difficulty/transitive_cascade/trail_close_cascades_departure_then_reservation_then_deposit_depth3
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "ClsTrail2", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-20T09:00:00Z", "ends_at": "2026-12-20T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)
    assert read_unit(bundle["unit"]["id"])["status"] == "RESERVED"  # held by the confirm
    validate_success(
        api.post_closure(bundle["trail"]["id"], {"new_condition": "CLOSED", "reason": "storm"}, DISPATCH), 201)
    assert read_unit(bundle["unit"]["id"])["status"] == "AVAILABLE"  # released by cascade
    assert read_reservation(bundle["reservation"]["id"])["reservation_status"] == "CANCELLED"


def test_depart_stamps_checked_out_at_and_departure_departed(api):
    """PRD §3.6: "every reservation still `CONFIRMED` is checked out — moved to
    `CHECKED_OUT`, its `checked_out_at` stamped with the clock now, its unit moved from
    `RESERVED` to `OUT`, and its assigned gear moved from `ASSIGNED` to `OUT`".

    Design: Difficulty/transitive_cascade/depart_cascades_confirmed_to_checkedout_then_unit_out_depth2
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "DepTrail2", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-22T09:00:00Z", "ends_at": "2026-12-22T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-22T09:15:00Z")
    res = read_reservation(bundle["reservation"]["id"])
    assert res["reservation_status"] == "CHECKED_OUT"
    assert res["checked_out_at"] is not None
    assert read_departure(bundle["departure"]["id"])["status"] == "DEPARTED"
