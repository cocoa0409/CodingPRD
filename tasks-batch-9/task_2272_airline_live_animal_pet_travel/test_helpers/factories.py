"""Request-payload builders.

Each builder returns the minimal valid body for a create or update endpoint and
accepts ``**overrides`` so a scenario can vary exactly the field it is probing.
Defaults are chosen to be unremarkable: a medium dog on a CHECKED booking in a
container that satisfies every §3.4 compliance threshold.
"""

from __future__ import annotations

from typing import Any, Dict

from .constants import (
    CONTAINER_INTERIOR_HEIGHT_CM,
    CONTAINER_INTERIOR_LENGTH_CM,
    CONTAINER_INTERIOR_WIDTH_CM,
    CONTAINER_MODEL_CODE,
    CONTAINER_TARE_WEIGHT_KG,
    CONTAINER_VENTILATED_SIDE_COUNT,
    CONTAINER_VENTILATION_AREA_PCT,
    COUNTRY_HONG_KONG,
    COUNTRY_UNITED_STATES,
    DESTINATION_MAX_AGE_DAYS_AT_ARRIVAL,
    DOCUMENT_EXPIRES_AT_UTC,
    DOCUMENT_ISSUED_AT_UTC,
    LEG_AN101_ARRIVAL_UTC,
    LEG_AN101_DEPARTURE_UTC,
    SPECIES_CODE_DOG,
    SPECIES_COMMON_NAME_DOG,
    SPECIES_MAX_CABIN_WEIGHT_KG,
    SPECIES_MIN_AGE_WEEKS,
    STATION_HKG,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is ``None``."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None and key in merged:
            merged.pop(key)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Species acceptance catalogue (PRD §3.1)
# ---------------------------------------------------------------------------


def species_profile_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "species_code": SPECIES_CODE_DOG,
            "common_name": SPECIES_COMMON_NAME_DOG,
            "acceptance_class": "ACCEPTED_ALL_ROUTINGS",
            "max_cabin_weight_kg": SPECIES_MAX_CABIN_WEIGHT_KG,
            "min_age_weeks": SPECIES_MIN_AGE_WEEKS,
        },
        overrides,
    )


def breed_restriction_payload(species_profile_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "species_profile_id": species_profile_id,
            "breed_name": "Bulldog",
            "restriction_type": "SNUB_NOSED",
        },
        overrides,
    )


def destination_requirement_payload(
    species_profile_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "species_profile_id": species_profile_id,
            "destination_country_code": COUNTRY_UNITED_STATES,
            "document_type": "HEALTH_CERTIFICATE",
            "max_age_days_at_arrival": DESTINATION_MAX_AGE_DAYS_AT_ARRIVAL,
            "mandatory": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Containers and stations (PRD §3.2)
# ---------------------------------------------------------------------------


def container_model_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "model_code": CONTAINER_MODEL_CODE,
            "interior_length_cm": CONTAINER_INTERIOR_LENGTH_CM,
            "interior_width_cm": CONTAINER_INTERIOR_WIDTH_CM,
            "interior_height_cm": CONTAINER_INTERIOR_HEIGHT_CM,
            "tare_weight_kg": CONTAINER_TARE_WEIGHT_KG,
            "ventilation_area_pct": CONTAINER_VENTILATION_AREA_PCT,
            "ventilated_side_count": CONTAINER_VENTILATED_SIDE_COUNT,
            "wheels_removable": True,
            "cabin_eligible": False,
        },
        overrides,
    )


def station_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "iata_code": STATION_HKG,
            "country_code": COUNTRY_HONG_KONG,
            "kennel_bay_count": 4,
        },
        overrides,
    )


def temperature_embargo_rule_payload(station_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "station_id": station_id,
            "direction": "ORIGIN",
            "season_start_month_day": "06-01",
            "season_end_month_day": "09-30",
            "forecast_high_limit_c": 29.5,
            "forecast_low_limit_c": -5.0,
            "applies_to_routings": ["CHECKED", "CARGO"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Flight legs (PRD §3.3)
# ---------------------------------------------------------------------------


def flight_leg_payload(
    origin_station_id: str, destination_station_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "flight_number": "AN101",
            "origin_station_id": origin_station_id,
            "destination_station_id": destination_station_id,
            "scheduled_departure_utc": LEG_AN101_DEPARTURE_UTC,
            "scheduled_arrival_utc": LEG_AN101_ARRIVAL_UTC,
            "cabin_animal_limit": 2,
            "checked_animal_limit": 2,
            "cargo_animal_limit": 4,
            "forecast_high_c": 25,
            "forecast_low_c": 15,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Reservations and animals (PRD §3.4)
# ---------------------------------------------------------------------------


def reservation_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "passenger_name": "Wu",
            "contact_email": "wu@example.com",
            "routing_type": "CHECKED",
        },
        overrides,
    )


def animal_record_payload(
    reservation_id: str,
    species_profile_id: str,
    container_model_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "reservation_id": reservation_id,
            "species_profile_id": species_profile_id,
            "container_model_id": container_model_id,
            "animal_name": "Mochi",
            "breed_name": "Labrador",
            "declared_weight_kg": 20,
            "height_at_shoulder_cm": 35,
            "length_nose_to_tail_cm": 50,
            "age_weeks": 52,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Segment assignments (PRD §3.5)
# ---------------------------------------------------------------------------


def segment_assignment_payload(
    animal_record_id: str,
    flight_leg_id: str,
    expected_flight_leg_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "animal_record_id": animal_record_id,
            "flight_leg_id": flight_leg_id,
            "routing_type": "CHECKED",
            "sequence_index": 1,
            "expected_flight_leg_version": expected_flight_leg_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Health documents (PRD §3.6)
# ---------------------------------------------------------------------------


def health_document_payload(animal_record_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "animal_record_id": animal_record_id,
            "document_type": "HEALTH_CERTIFICATE",
            "issuing_country_code": COUNTRY_HONG_KONG,
            "issued_at": DOCUMENT_ISSUED_AT_UTC,
            "expires_at": DOCUMENT_EXPIRES_AT_UTC,
        },
        overrides,
    )


def health_document_resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "issued_at": DOCUMENT_ISSUED_AT_UTC,
            "expires_at": DOCUMENT_EXPIRES_AT_UTC,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Kennel allocations and welfare checks (PRD §3.7)
# ---------------------------------------------------------------------------


def kennel_allocation_payload(
    station_id: str,
    animal_record_id: str,
    expected_station_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "station_id": station_id,
            "animal_record_id": animal_record_id,
            "bay_count": 1,
            "occupancy_start_utc": "2026-08-05T06:00:00Z",
            "occupancy_end_utc": "2026-08-05T09:00:00Z",
            "feeding_interval_minutes": 240,
            "expected_station_version": expected_station_version,
        },
        overrides,
    )


def welfare_check_payload(segment_assignment_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "segment_assignment_id": segment_assignment_id,
            "check_type": "WATER",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Incidents and sweeps (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------


def irops_care_sweep_payload(flight_leg_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"flight_leg_id": flight_leg_id}, overrides)


def animal_incident_payload(animal_record_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "animal_record_id": animal_record_id,
            "incident_type": "INJURY",
            "discovered_at_utc": "2026-08-01T00:00:00Z",
        },
        overrides,
    )


__all__ = [
    "species_profile_payload",
    "breed_restriction_payload",
    "destination_requirement_payload",
    "container_model_payload",
    "station_payload",
    "temperature_embargo_rule_payload",
    "flight_leg_payload",
    "reservation_payload",
    "animal_record_payload",
    "segment_assignment_payload",
    "health_document_payload",
    "health_document_resubmit_payload",
    "kennel_allocation_payload",
    "welfare_check_payload",
    "irops_care_sweep_payload",
    "animal_incident_payload",
]
