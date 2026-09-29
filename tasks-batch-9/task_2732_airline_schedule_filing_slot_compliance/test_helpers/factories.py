"""Payload factories — one per entity, client-supplied input fields only.

Monetary values are always integer counts of cents.
"""

from .constants import (
    SEASON_CODE,
    SEASON_END_DATE,
    SEASON_FILING_CHANGE_WINDOW_CLOSE_UTC,
    SEASON_SLOT_RETURN_DEADLINE_UTC,
    SEASON_START_DATE,
)


def create_carrier_payload(**overrides) -> dict:
    payload = {
        "iata_code": "HX",
        "icao_code": "HXA",
        "country_code": "DE",
        "is_home_carrier": True,
    }
    payload.update(overrides)
    return payload


def create_partner_carrier_payload(**overrides) -> dict:
    payload = {
        "iata_code": "TP",
        "icao_code": "TAP",
        "country_code": "PT",
        "is_home_carrier": False,
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    payload = {
        "iata_code": "FRA",
        "country_code": "DE",
        "coordination_level": "LEVEL_3_COORDINATED",
        "utc_offset_minutes": 120,
        "gate_count": 2,
    }
    payload.update(overrides)
    return payload


def create_season_payload(**overrides) -> dict:
    payload = {
        "season_code": SEASON_CODE,
        "start_date": SEASON_START_DATE,
        "end_date": SEASON_END_DATE,
        "slot_return_deadline_utc": SEASON_SLOT_RETURN_DEADLINE_UTC,
        "filing_change_window_close_utc": SEASON_FILING_CHANGE_WINDOW_CLOSE_UTC,
    }
    payload.update(overrides)
    return payload


def create_aircraft_payload(carrier_id: str, base_station_id: str, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "base_station_id": base_station_id,
        "registration": "D-AHXA",
        "fleet_type_code": "B738",
        "seats": 189,
        "min_turn_minutes": 45,
        "max_daily_block_minutes": 600,
        "required_check_minutes": 240,
    }
    payload.update(overrides)
    return payload


def create_schedule_version_payload(carrier_id: str, season_id: str, **overrides) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "season_id": season_id,
        "version_label": "W26-R1",
    }
    payload.update(overrides)
    return payload


def create_flight_leg_payload(
    schedule_version_id: str,
    origin_station_id: str,
    dest_station_id: str,
    dep_utc: str,
    arr_utc: str,
    **overrides,
) -> dict:
    payload = {
        "schedule_version_id": schedule_version_id,
        "flight_number": "HX101",
        "origin_station_id": origin_station_id,
        "dest_station_id": dest_station_id,
        "dep_utc": dep_utc,
        "arr_utc": arr_utc,
        "fleet_type_code": "B738",
    }
    payload.update(overrides)
    return payload


def create_slot_holding_payload(
    station_id: str, season_id: str, carrier_id: str, **overrides
) -> dict:
    payload = {
        "station_id": station_id,
        "season_id": season_id,
        "carrier_id": carrier_id,
        "movement_type": "DEPARTURE",
        "slot_time_utc": "2026-11-02T08:00:00.000Z",
        "days_of_week": "1",
        "series_weeks": 5,
    }
    payload.update(overrides)
    return payload


def create_slot_utilization_record_payload(
    slot_holding_id: str, operation_date: str, outcome: str = "OPERATED", **overrides
) -> dict:
    payload = {
        "slot_holding_id": slot_holding_id,
        "operation_date": operation_date,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def create_slot_transaction_payload(
    counterparty_carrier_id: str,
    offered_slot_holding_id: str,
    expected_slot_holding_version: int,
    **overrides,
) -> dict:
    payload = {
        "kind": "TRANSFER",
        "counterparty_carrier_id": counterparty_carrier_id,
        "offered_slot_holding_id": offered_slot_holding_id,
        "expected_slot_holding_version": expected_slot_holding_version,
        "response_deadline_utc": "2026-09-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_filing_submission_payload(schedule_version_id: str, **overrides) -> dict:
    payload = {
        "schedule_version_id": schedule_version_id,
        "distribution_system": "IATA_SSIM",
        "change_window": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_route_authority_payload(
    carrier_id: str,
    origin_country_code: str,
    dest_country_code: str,
    **overrides,
) -> dict:
    payload = {
        "carrier_id": carrier_id,
        "origin_country_code": origin_country_code,
        "dest_country_code": dest_country_code,
        "freedom_type": "THIRD_FOURTH",
        "weekly_frequency_cap": 14,
        "granted_from_utc": "2026-01-01T00:00:00.000Z",
        "granted_until_utc": "2027-12-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_notification_obligation_payload(
    flight_leg_id: str,
    trigger_kind: str = "RETIME",
    change_magnitude_minutes: int = 45,
    **overrides,
) -> dict:
    payload = {
        "flight_leg_id": flight_leg_id,
        "trigger_kind": trigger_kind,
        "change_magnitude_minutes": change_magnitude_minutes,
    }
    payload.update(overrides)
    return payload


def booking_snapshot_payload(
    booked_first: int = 0, booked_business: int = 0, booked_economy: int = 0
) -> dict:
    return {
        "booked_first": booked_first,
        "booked_business": booked_business,
        "booked_economy": booked_economy,
    }
