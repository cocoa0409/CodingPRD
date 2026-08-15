"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_team_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "team_code": f"T{n:03d}",
        "display_name": f"Test Team {n}",
        "league_rest_policy": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = {
        "label": TEST_DEFAULTS["SEASON_LABEL"],
        "travel_budget_cents": TEST_DEFAULTS["TRAVEL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "destination_code": "LAX",
        "game_tipoff_utc": TEST_DEFAULTS["GAME_TIPOFF"],
        "return_arrival_utc": TEST_DEFAULTS["RETURN_ARRIVAL"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "member_ref": f"M{n:03d}",
        "party_role": "PLAYER",
        "travel_class": "CHARTER_FIRST",
        "per_diem_tier": "TIER_A",
    }
    defaults.update(overrides)
    return defaults


def create_charter_contract_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "vendor_code": f"V{n:03d}",
        "base_price_cents": 5000000,
        "fuel_surcharge_cap_cents": 500000,
        "seat_capacity": 30,
        "cargo_capacity_lb": 10000,
        "penalty_bands": [{"days_before": 30, "penalty_pct": 10}],
    }
    defaults.update(overrides)
    return defaults


def create_flight_leg_payload(**overrides) -> dict:
    defaults = {
        "leg_seq": 1,
        "origin_code": "PDX",
        "destination_code": "LAX",
        "scheduled_depart_utc": "2027-02-28T18:00:00Z",
        "scheduled_arrive_utc": "2027-02-28T21:00:00Z",
        "is_charter": False,
    }
    defaults.update(overrides)
    return defaults


def create_manifest_entry_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "seat_assignment": "1A",
    }
    defaults.update(overrides)
    return defaults


def create_hotel_block_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "hotel_code": f"H{n:03d}",
        "room_count": 1,
        "rate_cents_per_night": 20000,
        "check_in_date": "2027-02-28",
        "night_count": 1,
        "cutoff_date": "2027-02-20",
    }
    defaults.update(overrides)
    return defaults


def create_room_assignment_payload(member_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "member_id": member_id,
        "room_label": f"R{n:03d}",
    }
    defaults.update(overrides)
    return defaults


def create_per_diem_payload(**overrides) -> dict:
    defaults = {
        "service_date": "2027-03-01",
        "day_kind": "GAME_DAY",
        "meals_provided_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "shipment_kind": "TEAM_GEAR",
        "gross_weight_lb": 500,
        "piece_count": 5,
        "declared_value_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_contingency_payload(affected_leg_id: str, **overrides) -> dict:
    defaults = {
        "kind": "WEATHER",
        "detected_at": "2027-02-28T12:00:00Z",
        "affected_leg_id": affected_leg_id,
        "severity": "MAJOR",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "venue_code": "LAX",
        "access_level": "FIELD",
    }
    defaults.update(overrides)
    return defaults
