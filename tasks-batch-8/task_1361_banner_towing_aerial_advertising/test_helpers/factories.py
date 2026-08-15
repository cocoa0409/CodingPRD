"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_base_payload(**overrides) -> dict:
    defaults = {"code": "KMYB", "name": "Myrtle Beach"}
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "tail_number": "N100AA",
        "model": "CITABRIA",
        "max_tow_weight_lbs": TEST_DEFAULTS["MAX_TOW_WEIGHT_LBS"],
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pilot One",
        "certificate_number": "CERT-1",
        "tow_endorsement_level": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "code": "BEACH-N-01",
        "kind": "BEACH",
        "length_nm": TEST_DEFAULTS["ROUTE_LENGTH_NM"],
        "min_banner_length_ft": TEST_DEFAULTS["MIN_BANNER_LENGTH_FT"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {"legal_name": "Acme Advertising", "billing_email": "acme@example.com"}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {"name": "Summer Campaign"}
    defaults.update(overrides)
    return defaults


def create_banner_payload(**overrides) -> dict:
    defaults = {
        "artwork_hash": "art-hash-1",
        "text_message": "EAT AT JOES",
        "banner_length_ft": TEST_DEFAULTS["BANNER_LENGTH_FT"],
        "banner_weight_lbs": TEST_DEFAULTS["BANNER_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_banner_revision_payload(**overrides) -> dict:
    defaults = {"proposed_text": "EAT AT JOES", "proposed_artwork_hash": "art-hash-1"}
    defaults.update(overrides)
    return defaults


def create_airspace_approval_payload(**overrides) -> dict:
    defaults = {
        "date_local": "2026-08-13",
        "window_start_utc": "2026-08-13T14:00:00Z",
        "window_end_utc": "2026-08-13T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tfr_payload(**overrides) -> dict:
    defaults = {
        "starts_utc": "2026-08-13T15:00:00Z",
        "ends_utc": "2026-08-13T18:00:00Z",
        "reason": "GAME",
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_capacity_payload(**overrides) -> dict:
    defaults = {
        "month_yyyy_mm": TEST_DEFAULTS["MONTH"],
        "aircraft_hour_quota": TEST_DEFAULTS["QUOTA_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_flight_slot_payload(**overrides) -> dict:
    defaults = {
        "date_local": "2026-08-13",
        "planned_start_utc": "2026-08-13T15:00:00Z",
        "planned_duration_hours": 1,
    }
    defaults.update(overrides)
    return defaults


def create_weather_assessment_payload(**overrides) -> dict:
    defaults = {"ceiling_ft": 5000, "visibility_sm": 10.0, "wind_kts": 5}
    defaults.update(overrides)
    return defaults


def create_flight_log_payload(**overrides) -> dict:
    defaults = {
        "hobbs_out": 100.0,
        "hobbs_in": 101.0,
        "pickup_technique": "GROUND_PICKUP",
        "pickup_outcome": "CLEAN",
        "tow_field_notes": "",
    }
    defaults.update(overrides)
    return defaults


def create_proof_of_flight_payload(**overrides) -> dict:
    defaults = {
        "gps_track_digest": "a" * 64,
        "photo_hash": "b" * 64,
        "pilot_attestation": True,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {"period_yyyy_mm": TEST_DEFAULTS["MONTH"]}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = TEST_DEFAULTS["CLOCK_START"]) -> dict:
    return {"to_iso8601": to_iso8601}
