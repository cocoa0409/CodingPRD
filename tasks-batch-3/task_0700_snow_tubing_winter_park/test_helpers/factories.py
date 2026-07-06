"""Payload factories — one per entity, input fields only.

Each factory builds a default valid payload and accepts **overrides for the
fields a test needs to control.
"""


def create_park_payload(**overrides) -> dict:
    """Input fields for POST /parks. name is required; thresholds optional."""
    defaults = {
        "name": "Test Park",
        "resident_zip_prefixes": [],
    }
    defaults.update(overrides)
    return defaults


def create_patron_payload(**overrides) -> dict:
    """Input fields for POST /patrons."""
    defaults = {
        "full_name": "Test Patron",
        "zip_code": "00000",
        "birthdate": "1990-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/lanes."""
    defaults = {
        "label": "Lane A",
        "rider_capacity_per_block": 5,
        "conveyor_cycle_seconds": 30,
    }
    defaults.update(overrides)
    return defaults


def create_time_block_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/time-blocks."""
    defaults = {
        "starts_at": "2026-03-01T10:00:00Z",
        "ends_at": "2026-03-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_weather_log_payload(**overrides) -> dict:
    """Input fields for POST /parks/{id}/weather-logs."""
    defaults = {
        "observed_at": "2026-03-01T10:00:00Z",
        "snow_depth_cm": 40,
        "wind_kph": 10,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    """Input fields for POST /waivers. guardian_name optional."""
    defaults = {
        "signed_at": "2026-03-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_season_pass_payload(**overrides) -> dict:
    """Input fields for POST /season-passes."""
    defaults = {
        "tier": "SILVER",
        "valid_from": "2026-03-01T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    """Input fields for POST /tickets. season_pass_id, upgraded_from_ticket_id optional."""
    defaults = {
        "rider_height_cm": 175,
        "rider_age_years": 30,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_rental_payload(**overrides) -> dict:
    """Input fields for POST /equipment-rentals. tube_size optional."""
    defaults = {
        "equipment_type": "TUBE",
        "tube_size": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_board_payload(**overrides) -> dict:
    """Input fields for POST /tickets/{id}/board."""
    defaults = {
        "boarded_at": "2026-03-01T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_group_reservation_payload(**overrides) -> dict:
    """Input fields for POST /group-reservations. lane_id optional (EXCLUSIVE_LANE only)."""
    defaults = {
        "rental_type": "SHARED_SEATS",
        "party_size": 4,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(**overrides) -> dict:
    """Input fields for POST /add-ons."""
    defaults = {
        "category": "FOOD",
        "unit_price_cents": 500,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults
