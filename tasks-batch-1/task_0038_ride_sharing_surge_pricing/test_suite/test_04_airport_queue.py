"""Airport FIFO queue: join eligibility, dispatch order, withdraw/offline re-sequence,
plus the snapshot window-overlap rule.

Citations trace to PRD §3.2, §3.4, §3.6, §3.10.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_zone, create_rider, create_driver, request_trip, dispatch_tick, go_online,
    setup_airport_zone, join_queue, publish_snapshot,
    TEST_USERS, make_driver_headers, make_rider_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_go_offline_queue_withdraw_resequence_depth2(api):
    """PRD §3.2: "if the driver holds a `WAITING` airport queue entry, that entry
    transitions to `WITHDRAWN`, and the remaining `WAITING` entries in that airport zone
    re-sequence their `position` ordered by `joined_at` ascending."

    Driver D1 (position 1) goes offline; their entry -> WITHDRAWN and D2 re-sequences to 1.

    Design: Difficulty/transitive_cascade/go_offline_queue_withdraw_resequence_depth2
    """
    az = setup_airport_zone(grid_code="Z9", base_fare_cents=1500)
    d1 = create_driver(az["id"], name="D1")
    d2 = create_driver(az["id"], name="D2")
    go_online(d1["id"])
    go_online(d2["id"])
    q1 = join_queue(az["id"], d1["id"])
    q2 = join_queue(az["id"], d2["id"])

    validate_success(api.go_offline(d1["id"], make_driver_headers(d1["id"])))

    fq1 = validate_success(api.get_airport_queue_entry(q1["id"], DISPATCHER))
    fq2 = validate_success(api.get_airport_queue_entry(q2["id"], DISPATCHER))
    assert fq1["status"] == "WITHDRAWN"
    assert fq2["status"] == "WAITING"
    assert fq2["position"] == 1


def test_airport_dispatch_uses_fifo_queue_order(api):
    """PRD §3.4: "For an airport pickup zone, the candidate set is the drivers holding a
    `WAITING` airport queue entry in that zone, ranked strictly first-in-first-out by the
    queue entry's `joined_at` ascending, with `created_at` ascending as a tie-break."
    PRD §3.4: "For an airport pickup, the dispatched driver's `WAITING` airport queue
    entry transitions to `DISPATCHED`"

    D2 (registered second) joins FIRST, so D2 is dispatched, not the earliest-registered D1.

    Design: Corner/state_machines/airport_dispatch_uses_fifo_queue_order
    """
    az = create_zone(grid_code="Z2", base_fare_cents=1500, is_airport=True, name="Airport")
    publish_snapshot(az["id"], observed_demand=1, observed_supply=4,
                     expected_zone_version=az["version"])
    d1 = create_driver(az["id"], name="D1")
    d2 = create_driver(az["id"], name="D2")
    go_online(d1["id"])
    go_online(d2["id"])
    q2 = join_queue(az["id"], d2["id"])  # joins first
    join_queue(az["id"], d1["id"])
    rider = create_rider(az["id"], wallet_balance_cents=0)
    trip = request_trip(rider["id"], az["id"], az["id"])

    dispatch_tick(az["id"])

    ft = validate_success(api.get_trip(trip["id"], DISPATCHER))
    fq2 = validate_success(api.get_airport_queue_entry(q2["id"], DISPATCHER))
    assert ft["driver_id"] == d2["id"]
    assert fq2["status"] == "DISPATCHED"


def test_withdraw_already_withdrawn_queue_entry_invalid_state(api):
    """PRD §3.10: "A driver may withdraw their own `WAITING` entry, moving it from
    `WAITING` to `WITHDRAWN`; this is permitted only when the entry is `WAITING`"
    PRD §2.10: "for transition endpoints, the target resource's current state is checked
    against the state machine, yielding `ERR_INVALID_STATE` when the requested transition
    is not defined from that state."

    Design: Corner/state_machines/withdraw_already_withdrawn_queue_entry_invalid_state
    """
    az = setup_airport_zone(grid_code="Z1", base_fare_cents=1500)
    driver = create_driver(az["id"])
    go_online(driver["id"])
    q = join_queue(az["id"], driver["id"])
    validate_success(api.withdraw_airport_queue_entry(q["id"], make_driver_headers(driver["id"])))
    resp = api.withdraw_airport_queue_entry(q["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_airport_queue_join_non_airport_zone_rejected(api):
    """PRD §3.10: "The target zone must be an airport zone — its `is_airport` flag must
    be true — or the join is rejected with `ERR_NOT_AIRPORT_ZONE`."

    Design: Corner/validations/airport_queue_join_non_airport_zone_rejected
    """
    z = create_zone(grid_code="N1", base_fare_cents=1000)  # not airport
    driver = create_driver(z["id"])
    go_online(driver["id"])
    resp = api.join_airport_queue(
        {"zone_id": z["id"], "driver_id": driver["id"]}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_AIRPORT_ZONE.value)


def test_airport_queue_join_offline_driver_rejected(api):
    """PRD §3.10: "The joining driver must currently be `AVAILABLE`, or the join is
    rejected with `ERR_DRIVER_NOT_AVAILABLE`."

    An OFFLINE driver targeting a valid airport zone is rejected.

    Design: Corner/validations/airport_queue_join_offline_driver_rejected
    """
    az = setup_airport_zone(grid_code="Z3", base_fare_cents=1500)
    driver = create_driver(az["id"])  # OFFLINE
    resp = api.join_airport_queue(
        {"zone_id": az["id"], "driver_id": driver["id"]}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_AVAILABLE.value)


def test_airport_queue_double_join_rejected(api):
    """PRD §3.10: "A driver may hold at most one `WAITING` queue entry across all airport
    zones at a time; a second concurrent join is rejected with `ERR_ALREADY_QUEUED`."

    Design: Corner/validations/airport_queue_double_join_rejected
    """
    az1 = setup_airport_zone(grid_code="Z4", base_fare_cents=1500)
    az2 = setup_airport_zone(grid_code="Z5", base_fare_cents=1500)
    driver = create_driver(az1["id"])
    go_online(driver["id"])
    join_queue(az1["id"], driver["id"])
    resp = api.join_airport_queue(
        {"zone_id": az2["id"], "driver_id": driver["id"]}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_QUEUED.value)


def test_surge_snapshot_window_overlap_half_open_adjacency_allowed(api):
    """PRD §3.6: "A new snapshot is rejected with `ERR_SNAPSHOT_WINDOW_OVERLAP` if its
    interval overlaps any existing snapshot's interval for the same `zone_id` — that is,
    if the new window's `effective_from` is earlier than the existing window's
    `effective_to` and the existing window's `effective_from` is earlier than the new
    window's `effective_to`."

    Existing [00:00, 01:30); new [01:00, 02:00) overlaps -> rejected.

    Design: Difficulty/resource_temporal_overlap/surge_snapshot_window_overlap_half_open_adjacency_allowed
    """
    z = create_zone(grid_code="N1", base_fare_cents=1000, name="TZ")
    publish_snapshot(z["id"], observed_demand=1, observed_supply=4,
                     expected_zone_version=z["version"],
                     effective_from="2026-06-01T00:00:00Z",
                     effective_to="2026-06-01T01:30:00Z")
    v2 = validate_success(api.get_zone(z["id"], DISPATCHER))["version"]
    resp = api.create_surge_snapshot(
        z["id"],
        {"observed_demand": 1, "observed_supply": 4, "is_rush_hour": False,
         "effective_from": "2026-06-01T01:00:00Z", "effective_to": "2026-06-01T02:00:00Z",
         "expected_zone_version": v2}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_WINDOW_OVERLAP.value)


def test_surge_snapshot_window_adjacent_boundary_allowed(api):
    """PRD §3.6: "Because the interval is half-open, two windows that merely touch at a
    boundary, where the new window's `effective_from` equals an existing window's
    `effective_to`, do not overlap and are allowed."

    Existing [00:00, 01:30); new [01:30, 02:30) touches at 01:30 -> accepted.

    Design: Difficulty/resource_temporal_overlap/surge_snapshot_window_overlap_half_open_adjacency_allowed
    """
    z = create_zone(grid_code="N2", base_fare_cents=1000, name="TZ2")
    publish_snapshot(z["id"], observed_demand=1, observed_supply=4,
                     expected_zone_version=z["version"],
                     effective_from="2026-06-01T00:00:00Z",
                     effective_to="2026-06-01T01:30:00Z")
    v2 = validate_success(api.get_zone(z["id"], DISPATCHER))["version"]
    snap = validate_success(api.create_surge_snapshot(
        z["id"],
        {"observed_demand": 1, "observed_supply": 4, "is_rush_hour": False,
         "effective_from": "2026-06-01T01:30:00Z", "effective_to": "2026-06-01T02:30:00Z",
         "expected_zone_version": v2}, DISPATCHER), 201)
    assert snap["id"]
