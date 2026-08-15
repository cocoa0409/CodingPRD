"""Truck logistics: inclusive capacity boundaries with weight-before-volume
ordering, the two-hour buffered vehicle window, and load instrument gating."""
from test_helpers import (
    ApiErrorId,
    create_charter,
    create_instrument,
    create_open_program,
    create_truck_charter_payload,
    truck_load_payload,
    validate_error,
    validate_success,
)


# --- Difficulty: truck_weight_inclusive_capacity_boundary -------------------------

def test_weight_capacity_inclusive_then_one_pound_over(api, equipment_headers,
                                                       reader_headers):
    """PRD §3.9: "Capacity is checked on every add, weight before volume: the prospective `loaded_weight_lb` — the existing sum plus the new load's `weight_lb` — must not exceed `capacity_weight_lb`, with exact equality allowed, else `ERR_TRUCK_OVERWEIGHT` (HTTP 422); only if weight passes is volume checked, with the prospective `loaded_volume_cuft` likewise bounded by `capacity_volume_cuft` with equality allowed, else `ERR_TRUCK_OVERVOLUME` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/truck_weight_inclusive_capacity_boundary
    """
    program = create_open_program(season_name="TW")
    charter = create_charter(program["id"], vehicle_label="TRUCK-2",
                             capacity_weight_lb=1000, capacity_volume_cuft=1000,
                             window_start="2026-09-01T04:00:00Z",
                             window_end="2026-09-01T23:00:00Z")

    validate_success(api.add_truck_load(
        charter["id"], truck_load_payload("trunks", 600, 100),
        equipment_headers), 201)
    accepted = validate_success(api.add_truck_load(
        charter["id"], truck_load_payload("drums", 400, 100),
        equipment_headers), 201)
    assert validate_success(api.get_truck_charter(charter["id"],
                                                  reader_headers))[
        "loaded_weight_lb"] == 1000, "600 + 400 == capacity: equality allowed"

    over = api.add_truck_load(charter["id"], truck_load_payload("one pound", 1, 1),
                              equipment_headers)
    validate_error(over, ApiErrorId.ERR_TRUCK_OVERWEIGHT)
    charter = validate_success(api.get_truck_charter(charter["id"],
                                                     reader_headers))
    assert charter["loaded_weight_lb"] == 1000, "the rejected load leaves no trace"
    _ = accepted


def test_volume_capacity_inclusive_and_weight_checked_before_volume(
        api, equipment_headers, reader_headers):
    """PRD §3.9: "Capacity is checked on every add, weight before volume: the prospective `loaded_weight_lb` — the existing sum plus the new load's `weight_lb` — must not exceed `capacity_weight_lb`, with exact equality allowed, else `ERR_TRUCK_OVERWEIGHT` (HTTP 422); only if weight passes is volume checked, with the prospective `loaded_volume_cuft` likewise bounded by `capacity_volume_cuft` with equality allowed, else `ERR_TRUCK_OVERVOLUME` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/truck_weight_inclusive_capacity_boundary
    """
    program = create_open_program(season_name="TV")
    charter = create_charter(program["id"], vehicle_label="TRUCK-V",
                             capacity_weight_lb=10000, capacity_volume_cuft=100,
                             window_start="2026-09-01T04:00:00Z",
                             window_end="2026-09-01T23:00:00Z")

    validate_success(api.add_truck_load(
        charter["id"], truck_load_payload("fifty cubes", 50, 100),
        equipment_headers), 201)
    charter = validate_success(api.get_truck_charter(charter["id"],
                                                     reader_headers))
    assert charter["loaded_volume_cuft"] == 100, "volume equality allowed"

    over_volume = api.add_truck_load(
        charter["id"], truck_load_payload("one more cube", 1, 1),
        equipment_headers)
    validate_error(over_volume, ApiErrorId.ERR_TRUCK_OVERVOLUME)

    both_fail = api.add_truck_load(
        charter["id"], truck_load_payload("too heavy and bulky", 20000, 500),
        equipment_headers)
    validate_error(both_fail, ApiErrorId.ERR_TRUCK_OVERWEIGHT, 422)

    charter = validate_success(api.get_truck_charter(charter["id"],
                                                     reader_headers))
    assert charter["loaded_weight_lb"] == 50
    assert charter["loaded_volume_cuft"] == 100


# --- Difficulty: vehicle_buffered_window_adjacency_rejected ------------------------

def test_buffered_window_forbids_adjacency(api, equipment_headers):
    """PRD §3.9: "Reservation windows for the same vehicle may not even touch: the overlap check is buffered, applying a two-hour loading buffer to both ends of every existing reservation, so a new window conflicts whenever the other charter belongs to the same program, carries the same `vehicle_label`, sits in `RESERVED`, `LOADED`, or `DEPARTED` status, and the new `window_start` falls strictly before the other's `window_end` plus two hours while the other's `window_start` minus two hours falls strictly before the new `window_end`. A conflicting reservation is rejected with `ERR_VEHICLE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_window_adjacency_rejected
    """
    program = create_open_program(season_name="VB")
    create_charter(program["id"], vehicle_label="TRUCK-1",
                   capacity_weight_lb=4000, capacity_volume_cuft=400,
                   window_start="2026-09-01T08:00:00Z",
                   window_end="2026-09-01T12:00:00Z")

    adjacent = api.create_truck_charter(
        create_truck_charter_payload(
            program["id"], vehicle_label="TRUCK-1",
            window_start="2026-09-01T12:00:00Z",
            window_end="2026-09-01T16:00:00Z"), equipment_headers)
    validate_error(adjacent, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT)

    # window_start == other's window_end + 2h is the inclusive acceptance edge
    accepted = validate_success(api.create_truck_charter(
        create_truck_charter_payload(
            program["id"], vehicle_label="TRUCK-1",
            window_start="2026-09-01T14:00:00Z",
            window_end="2026-09-01T16:00:00Z"), equipment_headers), 201)
    assert accepted["status"] == "RESERVED"


def test_buffer_applies_to_the_leading_edge_and_scopes_per_vehicle(
        api, equipment_headers):
    """PRD §3.9: "Reservation windows for the same vehicle may not even touch: the overlap check is buffered, applying a two-hour loading buffer to both ends of every existing reservation, so a new window conflicts whenever the other charter belongs to the same program, carries the same `vehicle_label`, sits in `RESERVED`, `LOADED`, or `DEPARTED` status, and the new `window_start` falls strictly before the other's `window_end` plus two hours while the other's `window_start` minus two hours falls strictly before the new `window_end`. A conflicting reservation is rejected with `ERR_VEHICLE_WINDOW_CONFLICT` (HTTP 409)." PRD §3.9: "Back-to-back scheduling without the buffer is deliberately impossible for vehicles, in contrast to the half-open adjacency permitted for facilities."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_window_adjacency_rejected
    """
    program = create_open_program(season_name="VB2")
    create_charter(program["id"], vehicle_label="TRUCK-1",
                   capacity_weight_lb=4000, capacity_volume_cuft=400,
                   window_start="2026-09-01T08:00:00Z",
                   window_end="2026-09-01T12:00:00Z")

    # Same window, different vehicle label: no conflict (per-vehicle scoping).
    other_vehicle = validate_success(api.create_truck_charter(
        create_truck_charter_payload(
            program["id"], vehicle_label="TRUCK-2",
            window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z"), equipment_headers), 201)
    assert other_vehicle["vehicle_label"] == "TRUCK-2"

    # Leading edge: new end == other's window_start - 2h is allowed; one minute
    # later collides with the buffer.
    leading_ok = validate_success(api.create_truck_charter(
        create_truck_charter_payload(
            program["id"], vehicle_label="TRUCK-1",
            window_start="2026-09-01T04:00:00Z",
            window_end="2026-09-01T06:00:00Z"), equipment_headers), 201)
    assert leading_ok["status"] == "RESERVED"

    leading_conflict = api.create_truck_charter(
        create_truck_charter_payload(
            program["id"], vehicle_label="TRUCK-1",
            window_start="2026-09-01T04:00:00Z",
            window_end="2026-09-01T06:01:00Z"), equipment_headers)
    validate_error(leading_conflict, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT)


# --- Corner: load instrument gating -----------------------------------------------

def test_load_of_retired_instrument_rejected(api, equipment_headers,
                                             reader_headers):
    """PRD §3.9: "The `EquipmentManager` adds loads to a charter by supplying a `description` such as "12 equipment trunks", a positive `weight_lb`, and a positive `volume_cuft`; a load may optionally name an `instrument_id`, in which case that instrument must not be `RETIRED` or `IN_MAINTENANCE`, else `ERR_LOAD_INSTRUMENT_INVALID`."

    Design: Corner/errors/load_retired_instrument_rejected
    """
    program = create_open_program(season_name="LI")
    instrument = create_instrument(program["id"], serial_number="SN-LI-1",
                                   instrument_type="HORN",
                                   replacement_value_cents=50000)
    validate_success(api.retire_instrument(instrument["id"], equipment_headers))
    charter = create_charter(program["id"], vehicle_label="TRUCK-7",
                             capacity_weight_lb=2000, capacity_volume_cuft=200,
                             window_start="2026-09-01T04:00:00Z",
                             window_end="2026-09-01T23:00:00Z")

    resp = api.add_truck_load(
        charter["id"],
        truck_load_payload("retired horn", 30, 5,
                           instrument_id=instrument["id"]),
        equipment_headers)
    validate_error(resp, ApiErrorId.ERR_LOAD_INSTRUMENT_INVALID)
    charter = validate_success(api.get_truck_charter(charter["id"],
                                                     reader_headers))
    assert charter["loaded_weight_lb"] == 0
    assert charter["status"] == "RESERVED"
