"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TRIP_DATE": "2026-06-15T09:00:00Z",
    "END_TIME": "2026-06-15T15:00:00Z",
    "BASE_RATE_CENTS": 12000,
    "MAX_CAPACITY": 12,
    "GUIDE_RATIO_MAX": 6,
    "SAFE_FLOW_MIN": 800,
    "SAFE_FLOW_MAX": 3000,
    "MARGINAL_FLOW_MAX": 4000,
}


def create_trip_payload(**overrides) -> dict:
    defaults = {
        "river_name": "Test River",
        "difficulty_class": "CLASS_III",
        "trip_date": DEFAULTS["TRIP_DATE"],
        "end_time": DEFAULTS["END_TIME"],
        "put_in_location": "Put In",
        "take_out_location": "Take Out",
        "max_capacity": DEFAULTS["MAX_CAPACITY"],
        "guide_ratio_max": DEFAULTS["GUIDE_RATIO_MAX"],
        "base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
        "min_age": 0,
        "safe_flow_min": DEFAULTS["SAFE_FLOW_MIN"],
        "safe_flow_max": DEFAULTS["SAFE_FLOW_MAX"],
        "marginal_flow_max": DEFAULTS["MARGINAL_FLOW_MAX"],
    }
    defaults.update(overrides)
    return defaults


def create_guide_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Guide", "max_class": "CLASS_III"}
    defaults.update(overrides)
    return defaults


def create_guide_assignment_payload(trip_id, guide_id, role="LEAD", **overrides) -> dict:
    defaults = {"trip_id": trip_id, "guide_id": guide_id, "role": role}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(trip_id, expected_trip_version, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "booking_type": "GROUP",
        "party_size": 1,
        "deposit_cents": 3000,
        "expected_trip_version": expected_trip_version,
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(reservation_id, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "full_name": "Test Guest",
        "age": 30,
        "weight_lbs": 175,
    }
    defaults.update(overrides)
    return defaults


def create_gear_item_payload(**overrides) -> dict:
    defaults = {
        "gear_type": "PFD",
        "size_label": "L",
        "min_weight_lbs": 100,
        "max_weight_lbs": 250,
    }
    defaults.update(overrides)
    return defaults


def create_gear_assignment_payload(gear_item_id, guest_id, trip_id, **overrides) -> dict:
    defaults = {"gear_item_id": gear_item_id, "guest_id": guest_id, "trip_id": trip_id}
    defaults.update(overrides)
    return defaults


def create_shuttle_vehicle_payload(**overrides) -> dict:
    defaults = {"name": "Test Van", "seat_capacity": 14}
    defaults.update(overrides)
    return defaults


def create_shuttle_run_payload(trip_id, shuttle_vehicle_id, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "shuttle_vehicle_id": shuttle_vehicle_id,
        "direction": "TO_PUT_IN",
        "depart_time": "2026-06-15T07:00:00Z",
        "arrive_time": "2026-06-15T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_condition_reading_payload(trip_id, flow_cfs, **overrides) -> dict:
    defaults = {
        "trip_id": trip_id,
        "flow_cfs": flow_cfs,
        "reading_time": "2026-06-15T07:00:00Z",
    }
    defaults.update(overrides)
    return defaults
