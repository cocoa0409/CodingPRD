"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid create-payload for an endpoint and merges
caller overrides. Only fields the client supplies (source: input) are included.
"""
from .constants import (
    DEFAULT_REPAIR_COST_LIMIT_CENTS,
    DEFAULT_PASSENGER_BASE_FEE_CENTS,
    DEFAULT_REINSPECTION_WINDOW_DAYS,
    DEFAULT_VIN,
)


def create_station_payload(**overrides) -> dict:
    payload = {
        "name": "Test Inspection Station",
        "state_code": "CA",
        "certificate_serial_prefix": "CA-",
        "repair_cost_limit_cents": DEFAULT_REPAIR_COST_LIMIT_CENTS,
        "analyzer_count": 1,
    }
    payload.update(overrides)
    return payload


def create_vehicle_class_profile_payload(station_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "vehicle_class": "PASSENGER",
        "base_fee_cents": DEFAULT_PASSENGER_BASE_FEE_CENTS,
        "obd_required": True,
        "checklist_item_count": 2,
        "reinspection_window_days": DEFAULT_REINSPECTION_WINDOW_DAYS,
    }
    payload.update(overrides)
    return payload


def create_lane_payload(station_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "lane_number": 1,
        "supports_obd": True,
        "turnaround_buffer_minutes": 0,
    }
    payload.update(overrides)
    return payload


def create_analyzer_reservation_payload(station_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "vehicle_vin": DEFAULT_VIN,
        "window_start": "2026-06-10T10:00:00Z",
        "window_end": "2026-06-10T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(lane_id: str, **overrides) -> dict:
    payload = {
        "lane_id": lane_id,
        "vehicle_vin": DEFAULT_VIN,
        "vehicle_class": "PASSENGER",
        "kind": "WALK_IN",
        "scheduled_start": "2026-06-10T09:00:00Z",
        "scheduled_end": "2026-06-10T09:30:00Z",
    }
    payload.update(overrides)
    return payload


def create_inspection_record_payload(appointment_id: str, **overrides) -> dict:
    payload = {"appointment_id": appointment_id}
    payload.update(overrides)
    return payload


def create_checklist_result_payload(record_id: str, item_code: str = "BRAKES",
                                    outcome: str = "PASS", **overrides) -> dict:
    payload = {
        "record_id": record_id,
        "item_code": item_code,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def create_emissions_test_payload(record_id: str, **overrides) -> dict:
    payload = {
        "record_id": record_id,
        "protocol": "OBD2_CAN",
        "dtc_count": 0,
        "readiness_monitors_incomplete": 0,
        "mil_on": False,
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(record_id: str, **overrides) -> dict:
    payload = {
        "record_id": record_id,
        "shop_name": "Test Auto Shop",
        "documented_cost_cents": 0,
        "estimated_cost_cents": 0,
        "emissions_related": True,
    }
    payload.update(overrides)
    return payload


def create_waiver_request_payload(record_id: str, **overrides) -> dict:
    payload = {
        "record_id": record_id,
        "cost_basis": "DOCUMENTED_ONLY",
    }
    payload.update(overrides)
    return payload


def create_certificate_payload(record_id: str, expected_record_version: int, **overrides) -> dict:
    payload = {
        "record_id": record_id,
        "expected_record_version": expected_record_version,
    }
    payload.update(overrides)
    return payload


def create_state_report_batch_payload(station_id: str, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "period_label": "2026-06",
    }
    payload.update(overrides)
    return payload


def attach_line_payload(record_id: str, **overrides) -> dict:
    payload = {"record_id": record_id}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
