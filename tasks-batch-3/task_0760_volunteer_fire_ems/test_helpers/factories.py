"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "MEMBER_NAME": "Test Member",
    "STATION_NAME": "Test Station",
    "JOIN_DATE": "2026-01-01T00:00:00Z",
}

_email_counter = [0]


def unique_email(prefix="user"):
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": unique_email("member"),
        "role_class": "EMT",
        "join_date": DEFAULTS["JOIN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "cert_type": "EMT_BASIC",
        "category": "EMS",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {
        "category": "EMS",
        "hours": 20,
        "training_date": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_point_adjustment_payload(**overrides) -> dict:
    defaults = {
        "points": 10,
        "reason": "service points",
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["STATION_NAME"]}
    defaults.update(overrides)
    return defaults


def create_apparatus_payload(**overrides) -> dict:
    defaults = {
        "unit_designation": "ENGINE-1",
        "apparatus_type": "ENGINE",
        "min_crew": 1,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Equipment",
        "is_critical": False,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-04-01T00:00:00Z",
        "end_at": "2026-04-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_duty_shift_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-06-01T06:00:00Z",
        "end_at": "2026-06-01T18:00:00Z",
        "max_crew": 4,
        "min_crew": 1,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "incident_type": "EMS",
        "alarm_at": "2026-03-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Campaign",
        "goal_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {
        "donor_name": "Test Donor",
        "amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults
