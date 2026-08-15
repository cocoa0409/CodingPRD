"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_terminal_payload(code=None, name=None, dock_doors=None, **overrides) -> dict:
    defaults = {
        "code": code or TEST_DEFAULTS["TERMINAL_CODE"],
        "name": name or TEST_DEFAULTS["TERMINAL_NAME"],
        "dock_doors": dock_doors if dock_doors is not None else TEST_DEFAULTS["DOCK_DOORS"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(origin_terminal_id, destination_terminal_id, **overrides) -> dict:
    defaults = {
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "nmfc_class": "CLASS_60",
        "actual_weight_lbs": 500,
        "length_in": 48,
        "width_in": 40,
        "height_in": 48,
        "service_standard": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_pickup_route_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "route_date": TEST_DEFAULTS["ROUTE_DATE"],
        "driver_id": TEST_DEFAULTS["DRIVER_ID"],
        "shift_start_minute": TEST_DEFAULTS["SHIFT_START_MINUTE"],
        "shift_end_minute": TEST_DEFAULTS["SHIFT_END_MINUTE"],
    }
    defaults.update(overrides)
    return defaults


def create_pickup_stop_payload(route_id, shipment_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "shipment_id": shipment_id,
        "stop_sequence": 1,
        "planned_arrival_minute": 540,
    }
    defaults.update(overrides)
    return defaults


def create_dock_door_payload(terminal_id, door_number, door_kind="OUTBOUND", **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "door_number": door_number,
        "door_kind": door_kind,
    }
    defaults.update(overrides)
    return defaults


def create_sortation_batch_payload(terminal_id, inbound_door_id, destination_terminal_id,
                                   **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "inbound_door_id": inbound_door_id,
        "destination_terminal_id": destination_terminal_id,
    }
    defaults.update(overrides)
    return defaults


def create_trailer_payload(terminal_id, destination_terminal_id, outbound_door_id,
                           **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "outbound_door_id": outbound_door_id,
        "max_weight_lbs": TEST_DEFAULTS["TRAILER_MAX_WEIGHT_LBS"],
        "max_cube_cuft": TEST_DEFAULTS["TRAILER_MAX_CUBE_CUFT"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_entry_payload(shipment_id, expected_trailer_version,
                                  load_position=1, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "load_position": load_position,
        "expected_trailer_version": expected_trailer_version,
    }
    defaults.update(overrides)
    return defaults


def create_seal_payload(expected_trailer_version, **overrides) -> dict:
    defaults = {"expected_trailer_version": expected_trailer_version}
    defaults.update(overrides)
    return defaults


def create_linehaul_leg_payload(origin_terminal_id, destination_terminal_id, trailer_id,
                                planned_departure_utc, planned_arrival_utc,
                                relay_sequence=1, **overrides) -> dict:
    defaults = {
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "trailer_id": trailer_id,
        "planned_departure_utc": planned_departure_utc,
        "planned_arrival_utc": planned_arrival_utc,
        "relay_sequence": relay_sequence,
    }
    defaults.update(overrides)
    return defaults


def create_dimensioner_scan_payload(shipment_id, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "measured_length_in": 60,
        "measured_width_in": 48,
        "measured_height_in": 50,
        "measured_weight_lbs": 430,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(shipment_id, scan_id, claimed_nmfc_class, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "scan_id": scan_id,
        "claimed_nmfc_class": claimed_nmfc_class,
    }
    defaults.update(overrides)
    return defaults


def create_osd_case_payload(shipment_id, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "case_kind": "DAMAGE",
        "claimed_amount_cents": 1000,
        "item_amounts_cents": [1000],
    }
    defaults.update(overrides)
    return defaults


def create_service_standard_report_payload(report_date, **overrides) -> dict:
    defaults = {"report_date": report_date}
    defaults.update(overrides)
    return defaults
