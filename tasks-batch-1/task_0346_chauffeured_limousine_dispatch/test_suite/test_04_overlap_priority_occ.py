"""Resource temporal overlaps (chauffeur rest buffer, vehicle turnaround),
validation priority ordering, and optimistic concurrency on fulfillment writes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_account,
    create_vehicle_class,
    create_chauffeur,
    create_vehicle,
    create_affiliate,
    create_reservation,
    create_confirmed_reservation,
    assign_in_house,
    api_client,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_assignment_payload,
    create_farm_out_order_payload,
    create_reservation_payload,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/temporal_chauffeur_rest_buffer_one_sided_overlap
# ---------------------------------------------------------------------------
def test_chauffeur_rest_buffer_collision_rejected():
    """PRD §3.3: "an ACTIVE assignment already held by that chauffeur conflicts
    with the new one when the new window starts before the existing window's end
    extended by the chauffeur's rest_buffer_minutes, and at the same time the
    existing window starts before the new window's end extended by the same
    rest_buffer_minutes."

    Design: Difficulty/resource_temporal_overlap/temporal_chauffeur_rest_buffer_one_sided_overlap
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO", rest_buffer_minutes=20)
    veh1 = create_vehicle(vclass["id"], plate="BLK-6")
    veh2 = create_vehicle(vclass["id"], plate="BLK-7")
    confA = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-15T12:00:00Z",
                                         planned_drop_at="2026-07-15T13:00:00Z", estimated_miles=10)
    assign_in_house(confA["id"], drv["id"], veh1["id"], confA["version"])
    # Second trip pickup 13:19 < 13:00+20=13:20 => collides.
    confB = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-15T13:19:00Z",
                                         planned_drop_at="2026-07-15T14:00:00Z", estimated_miles=8)
    resp = api_client.create_assignment(
        create_assignment_payload(confB["id"], drv["id"], veh2["id"], confB["version"]), DISPATCHER
    )
    validate_error(resp, "ERR_CHAUFFEUR_DOUBLE_BOOKED")


def test_chauffeur_rest_buffer_adjacency_at_buffer_allowed():
    """PRD §3.3: "Windows are half-open, so adjacency exactly at an existing
    window's end plus the buffer is allowed and is not a conflict."

    Design: Difficulty/resource_temporal_overlap/temporal_chauffeur_rest_buffer_one_sided_overlap
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO", rest_buffer_minutes=20)
    veh1 = create_vehicle(vclass["id"], plate="BLK-6A")
    veh2 = create_vehicle(vclass["id"], plate="BLK-7A")
    confA = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-15T12:00:00Z",
                                         planned_drop_at="2026-07-15T13:00:00Z", estimated_miles=10)
    assign_in_house(confA["id"], drv["id"], veh1["id"], confA["version"])
    # Pickup exactly 13:20 == 13:00 + 20 buffer => allowed.
    confB = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-15T13:20:00Z",
                                         planned_drop_at="2026-07-15T14:00:00Z", estimated_miles=8)
    asg = assign_in_house(confB["id"], drv["id"], veh2["id"], confB["version"])
    assert asg["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/temporal_vehicle_turnaround_gap_overlap
# ---------------------------------------------------------------------------
def test_vehicle_turnaround_gap_too_small_rejected():
    """PRD §3.3: "A gap strictly smaller than the vehicle's turnaround_minutes is
    a conflict; a gap exactly equal to turnaround_minutes is allowed. A vehicle
    conflict is rejected with ERR_VEHICLE_TURNAROUND_VIOLATION."

    Design: Difficulty/resource_temporal_overlap/temporal_vehicle_turnaround_gap_overlap
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv1 = create_chauffeur(full_name="Dana", home_market_code="SFO", rest_buffer_minutes=5)
    drv2 = create_chauffeur(full_name="Eli", home_market_code="SFO", rest_buffer_minutes=5)
    veh = create_vehicle(vclass["id"], plate="BLK-8", turnaround_minutes=30)
    confA = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-16T12:00:00Z",
                                         planned_drop_at="2026-07-16T13:00:00Z", estimated_miles=10)
    assign_in_house(confA["id"], drv1["id"], veh["id"], confA["version"])
    # Second trip pickup 13:29 => gap 29 < 30 => violation (different chauffeur, same vehicle).
    confB = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-16T13:29:00Z",
                                         planned_drop_at="2026-07-16T14:00:00Z", estimated_miles=8)
    resp = api_client.create_assignment(
        create_assignment_payload(confB["id"], drv2["id"], veh["id"], confB["version"]), DISPATCHER
    )
    validate_error(resp, "ERR_VEHICLE_TURNAROUND_VIOLATION")


def test_vehicle_turnaround_gap_exactly_equal_allowed():
    """PRD §3.3: "a gap exactly equal to turnaround_minutes is allowed."

    Design: Difficulty/resource_temporal_overlap/temporal_vehicle_turnaround_gap_overlap
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv1 = create_chauffeur(full_name="Dana", home_market_code="SFO", rest_buffer_minutes=5)
    drv2 = create_chauffeur(full_name="Eli", home_market_code="SFO", rest_buffer_minutes=5)
    veh = create_vehicle(vclass["id"], plate="BLK-8A", turnaround_minutes=30)
    confA = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-16T12:00:00Z",
                                         planned_drop_at="2026-07-16T13:00:00Z", estimated_miles=10)
    assign_in_house(confA["id"], drv1["id"], veh["id"], confA["version"])
    # Second trip pickup 13:30 => gap 30 == turnaround 30 => allowed.
    confB = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                         pickup_at="2026-07-16T13:30:00Z",
                                         planned_drop_at="2026-07-16T14:00:00Z", estimated_miles=8)
    asg = assign_in_house(confB["id"], drv2["id"], veh["id"], confB["version"])
    assert asg["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/priority_existence_beats_temporal_on_reservation_create
# ---------------------------------------------------------------------------
def test_existence_check_beats_time_window_on_reservation_create():
    """PRD §2.6: "Existence of every referenced resource (ERR_NOT_FOUND) is third.
    Request-body well-formedness — required fields present with correct types and
    valid enum values (ERR_INVALID_REQUEST) — is fourth."
    PRD §2.5: "body-borne references (for example, a reservation's
    corporate_account_id and vehicle_class_id, or an assignment's chauffeur_id
    and vehicle_id) are likewise checked for existence, and any unresolved
    reference yields ERR_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_temporal_on_reservation_create
    """
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    # Non-existent account FK AND inverted window: existence (gate 3) precedes the
    # business temporal check, so ERR_NOT_FOUND wins.
    payload = create_reservation_payload(
        NON_EXISTENT_UUID, vclass["id"], trip_type="POINT_TO_POINT",
        pickup_at="2026-07-10T13:00:00Z", planned_drop_at="2026-07-10T12:00:00Z", estimated_miles=10,
    )
    resp = api_client.create_reservation(payload, DISPATCHER)
    validate_error(resp, "ERR_NOT_FOUND")


def test_inverted_window_alone_yields_time_window_error():
    """PRD §3.2: "The planned_drop_at must be strictly after pickup_at; otherwise
    the request is rejected with ERR_INVALID_TIME_WINDOW."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_temporal_on_reservation_create
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    # All FKs valid; only the window is inverted => the temporal check fires.
    payload = create_reservation_payload(
        account["id"], vclass["id"], trip_type="POINT_TO_POINT",
        pickup_at="2026-07-10T13:00:00Z", planned_drop_at="2026-07-10T12:00:00Z", estimated_miles=10,
    )
    resp = api_client.create_reservation(payload, DISPATCHER)
    validate_error(resp, "ERR_INVALID_TIME_WINDOW")


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_farmout_stale_reservation_version_rejected
# ---------------------------------------------------------------------------
def test_farmout_with_stale_reservation_version_rejected():
    """PRD §2.8: "If an in-house assignment has advanced the reservation to ASSIGNED
    and bumped its version since the client's last read, the farm-out create is
    rejected with ERR_STALE_VERSION at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_farmout_stale_reservation_version_rejected
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    affiliate = create_affiliate(name="Bay Black Car", market_code="SFO", payout_share_pct=70)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-OCC")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-21T12:00:00Z",
                                             planned_drop_at="2026-08-21T13:00:00Z", estimated_miles=10)
    stale_v = confirmed["version"]
    # An in-house assignment bumps the reservation version past stale_v.
    assign_in_house(confirmed["id"], drv["id"], veh["id"], stale_v)
    resp = api_client.create_farm_out_order(
        create_farm_out_order_payload(confirmed["id"], affiliate["id"], stale_v), DISPATCHER
    )
    validate_error(resp, "ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_version_increments_on_assignment_create
# ---------------------------------------------------------------------------
def test_assignment_create_increments_reservation_version_by_one():
    """PRD §3.3: "As the first hop of a cross-entity cascade, the reservation moves
    to ASSIGNED and its version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_assignment_create
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-OCC2")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-22T12:00:00Z",
                                             planned_drop_at="2026-08-22T13:00:00Z", estimated_miles=10)
    v = confirmed["version"]
    assign_in_house(confirmed["id"], drv["id"], veh["id"], v)
    res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    assert res["trip_status"] == "ASSIGNED"
    assert res["version"] == v + 1, f"version should bump by exactly 1: expected {v + 1}, got {res['version']}"


# ---------------------------------------------------------------------------
# Corner/consistency_model/consistency_immediate_assignment_visible_in_response
# ---------------------------------------------------------------------------
def test_assignment_effect_visible_immediately_on_reservation():
    """PRD §2.9: "Many operations in this system mutate more than one entity at
    once, and every such cascade is part of the operation's contract — never an
    incidental side effect. When a reservation is assigned, the chauffeur's duty
    status changes"

    Design: Corner/consistency_model/consistency_immediate_assignment_visible_in_response
    """
    account = create_account()
    vclass = create_vehicle_class(code="SEDAN", base_fare_cents=5000, per_mile_cents=250,
                                  hourly_rate_cents=12000, wait_per_minute_cents=200)
    drv = create_chauffeur(full_name="Dana", home_market_code="SFO")
    veh = create_vehicle(vclass["id"], plate="BLK-IM1")
    confirmed = create_confirmed_reservation(account["id"], vclass["id"], trip_type="POINT_TO_POINT",
                                             pickup_at="2026-08-23T12:00:00Z",
                                             planned_drop_at="2026-08-23T13:00:00Z", estimated_miles=10)
    assign_in_house(confirmed["id"], drv["id"], veh["id"], confirmed["version"])
    res = validate_success(api_client.get_reservation(confirmed["id"], DISPATCHER), 200)
    assert res["trip_status"] == "ASSIGNED", "assignment effect must be immediately visible"
