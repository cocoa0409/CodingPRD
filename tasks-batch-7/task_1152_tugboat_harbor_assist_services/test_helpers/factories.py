"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TUG_NAME": "Tug Atlas",
    "TUG_BOLLARD_PULL_TONS": 60.0,
    "TUG_HORSEPOWER": 5000,
    "TUG_HOURLY_RATE_CENTS": 120000,
    "TUG_INSURED_VALUE_CENTS": 20000000,
    "VESSEL_NAME": "MV Aurora",
    "VESSEL_IMO": "IMO9074729",
    "VESSEL_DWT": 40000,
    "VESSEL_LOA": 180.0,
    "PILOT_NAME": "Pilot Reyes",
    "PILOT_LICENSE": "CLASS_I",
    "CREW_FULL_NAME": "Deckhand Okafor",
    "CREW_ROLE": "DECKHAND",
    "TARIFF_CODE": "TAR-DOCK-01",
    "TARIFF_MANEUVER": "DOCKING",
    "TARIFF_BASE_FEE_CENTS": 500000,
    "TARIFF_STANDBY_BLOCK_RATE_CENTS": 25000,
    "TARIFF_FREE_STANDBY_MINUTES": 30,
    "TARIFF_STANDBY_BLOCK_MINUTES": 15,
    "TARIFF_WEATHER_SURCHARGE_PCT": 0,
    "TARIFF_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "TARIFF_EFFECTIVE_TO": "2026-12-31T23:59:59Z",
    "JOB_SCHEDULED_START": "2026-06-01T08:00:00Z",
    "JOB_SCHEDULED_END": "2026-06-01T10:00:00Z",
    "INSPECTION_ITEM": "TOW_LINE",
    "INSPECTION_OUTCOME": "PASSED",
    "INSPECTION_INSPECTED_AT": "2026-05-01T00:00:00Z",
    "INSPECTION_NEXT_DUE_AT": "2026-12-31T00:00:00Z",
    "INCIDENT_TYPE": "CONTACT_DAMAGE",
    "INCIDENT_SEVERITY": "MINOR",
    "INCIDENT_OCCURRED_AT": "2026-06-01T09:00:00Z",
    "INCIDENT_DESCRIPTION": "Minor contact",
    "WEATHER_RESTRICTION_TYPE": "WIND",
    "WEATHER_THRESHOLD_VALUE": 35.0,
    "WEATHER_PORT_AREA": "NORTH_HARBOR",
    "WEATHER_EFFECTIVE_START": "2026-06-01T09:00:00Z",
    "WEATHER_EFFECTIVE_END": "2026-06-01T11:00:00Z",
}


def create_tug_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TUG_NAME"],
        "bollard_pull_tons": DEFAULTS["TUG_BOLLARD_PULL_TONS"],
        "horsepower": DEFAULTS["TUG_HORSEPOWER"],
        "hourly_rate_cents": DEFAULTS["TUG_HOURLY_RATE_CENTS"],
        "insured_value_cents": DEFAULTS["TUG_INSURED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VESSEL_NAME"],
        "imo_number": DEFAULTS["VESSEL_IMO"],
        "deadweight_tonnage": DEFAULTS["VESSEL_DWT"],
        "loa_meters": DEFAULTS["VESSEL_LOA"],
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PILOT_NAME"],
        "license_class": DEFAULTS["PILOT_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CREW_FULL_NAME"],
        "crew_role": DEFAULTS["CREW_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_tariff_rate_payload(**overrides) -> dict:
    defaults = {
        "tariff_code": DEFAULTS["TARIFF_CODE"],
        "maneuver_type": DEFAULTS["TARIFF_MANEUVER"],
        "base_fee_cents": DEFAULTS["TARIFF_BASE_FEE_CENTS"],
        "standby_block_rate_cents": DEFAULTS["TARIFF_STANDBY_BLOCK_RATE_CENTS"],
        "effective_from": DEFAULTS["TARIFF_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["TARIFF_EFFECTIVE_TO"],
        "free_standby_minutes": DEFAULTS["TARIFF_FREE_STANDBY_MINUTES"],
        "standby_block_minutes": DEFAULTS["TARIFF_STANDBY_BLOCK_MINUTES"],
        "weather_surcharge_pct": DEFAULTS["TARIFF_WEATHER_SURCHARGE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_job_order_payload(vessel_id: str, tariff_rate_id: str, **overrides) -> dict:
    defaults = {
        "vessel_id": vessel_id,
        "tariff_rate_id": tariff_rate_id,
        "maneuver_type": DEFAULTS["TARIFF_MANEUVER"],
        "scheduled_start": DEFAULTS["JOB_SCHEDULED_START"],
        "scheduled_end": DEFAULTS["JOB_SCHEDULED_END"],
    }
    defaults.update(overrides)
    return defaults


def create_tug_assignment_payload(
    job_order_id: str, tug_id: str, expected_job_order_version: int, **overrides
) -> dict:
    defaults = {
        "job_order_id": job_order_id,
        "tug_id": tug_id,
        "window_start": DEFAULTS["JOB_SCHEDULED_START"],
        "window_end": DEFAULTS["JOB_SCHEDULED_END"],
        "expected_job_order_version": expected_job_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_pilot_booking_payload(job_order_id: str, pilot_id: str, **overrides) -> dict:
    defaults = {
        "job_order_id": job_order_id,
        "pilot_id": pilot_id,
        "window_start": DEFAULTS["JOB_SCHEDULED_START"],
        "window_end": DEFAULTS["JOB_SCHEDULED_END"],
    }
    defaults.update(overrides)
    return defaults


def create_watch_rotation_payload(
    tug_assignment_id: str, crew_member_id: str, **overrides
) -> dict:
    defaults = {
        "tug_assignment_id": tug_assignment_id,
        "crew_member_id": crew_member_id,
        "watch_start": "2026-06-01T08:00:00Z",
        "watch_end": "2026-06-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_gear_inspection_payload(tug_id: str, **overrides) -> dict:
    defaults = {
        "tug_id": tug_id,
        "inspection_item": DEFAULTS["INSPECTION_ITEM"],
        "outcome": DEFAULTS["INSPECTION_OUTCOME"],
        "inspected_at": DEFAULTS["INSPECTION_INSPECTED_AT"],
        "next_due_at": DEFAULTS["INSPECTION_NEXT_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(tug_id: str, **overrides) -> dict:
    defaults = {
        "tug_id": tug_id,
        "incident_type": DEFAULTS["INCIDENT_TYPE"],
        "severity": DEFAULTS["INCIDENT_SEVERITY"],
        "occurred_at": DEFAULTS["INCIDENT_OCCURRED_AT"],
        "description": DEFAULTS["INCIDENT_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_weather_restriction_payload(**overrides) -> dict:
    defaults = {
        "restriction_type": DEFAULTS["WEATHER_RESTRICTION_TYPE"],
        "threshold_value": DEFAULTS["WEATHER_THRESHOLD_VALUE"],
        "port_area": DEFAULTS["WEATHER_PORT_AREA"],
        "effective_start": DEFAULTS["WEATHER_EFFECTIVE_START"],
        "effective_end": DEFAULTS["WEATHER_EFFECTIVE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(
    incident_id: str, vessel_id: str, claimed_amount_cents: int, **overrides
) -> dict:
    defaults = {
        "incident_id": incident_id,
        "vessel_id": vessel_id,
        "claimed_amount_cents": claimed_amount_cents,
    }
    defaults.update(overrides)
    return defaults
