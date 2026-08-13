"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TRACK_NAME": "Test Track",
    "NOISE_LIMIT_DB": 90,
    "RUN_GROUP_CAPACITY": 10,
    "GARAGE_BAY_COUNT": 3,
    "PADDOCK_STALL_COUNT": 8,
    "COACH_NAME": "Coach One",
    "CERT_LEVEL": "INTERMEDIATE",
    "TRACK_DAY_DATE": "2026-09-01",
    "BLOCK_INDEX": 0,
    "START_MINUTE": 480,
    "END_MINUTE": 540,
    "MAX_GROUP_SIZE": 5,
    "ORGANIZER": "org-1",
    "GROUP_NAME": "Test Group",
    "RUN_GROUP_CLASS": "ADVANCED",
    "DRIVER_COUNT": 1,
    "INSURANCE_REF": "POL-0001",
    "DRIVER_NAME": "Driver One",
    "LICENSE_CLASS": "CLUB",
    "SIGNATURE_HASH": "sig-hash-0001",
    "INSPECTOR": "safety-1",
    "SEVERITY": "LOW",
    "REPORTER": "ops-1",
    "CLEARER": "safety-1",
    "DB_LEVEL": 91,
    "BAY_NUMBER": 1,
    "POWER_HOOKUPS": 1,
    "STALL_NUMBER": 1,
}


def create_track_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TRACK_NAME"],
        "noise_limit_db": DEFAULTS["NOISE_LIMIT_DB"],
        "run_group_capacity": DEFAULTS["RUN_GROUP_CAPACITY"],
        "garage_bay_count": DEFAULTS["GARAGE_BAY_COUNT"],
        "paddock_stall_count": DEFAULTS["PADDOCK_STALL_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["COACH_NAME"],
        "cert_level": DEFAULTS["CERT_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_track_day_payload(**overrides) -> dict:
    defaults = {"date": DEFAULTS["TRACK_DAY_DATE"]}
    defaults.update(overrides)
    return defaults


def create_rental_block_payload(**overrides) -> dict:
    defaults = {
        "block_index": DEFAULTS["BLOCK_INDEX"],
        "start_minute": DEFAULTS["START_MINUTE"],
        "end_minute": DEFAULTS["END_MINUTE"],
        "max_group_size": DEFAULTS["MAX_GROUP_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "organizer_user_id": DEFAULTS["ORGANIZER"],
        "group_name": DEFAULTS["GROUP_NAME"],
        "run_group_class": DEFAULTS["RUN_GROUP_CLASS"],
        "driver_count": DEFAULTS["DRIVER_COUNT"],
        "insurance_policy_ref": DEFAULTS["INSURANCE_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["DRIVER_NAME"],
        "license_class": DEFAULTS["LICENSE_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(**overrides) -> dict:
    defaults = {
        "signed_at_utc": "2026-08-01T08:00:00Z",
        "signature_payload_hash": DEFAULTS["SIGNATURE_HASH"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspector_user_id": DEFAULTS["INSPECTOR"],
        "helmet_ok": True,
        "harness_ok": True,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {"run_group_class": DEFAULTS["RUN_GROUP_CLASS"]}
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "severity": DEFAULTS["SEVERITY"],
        "reported_by_user_id": DEFAULTS["REPORTER"],
    }
    defaults.update(overrides)
    return defaults


def create_noise_reading_payload(**overrides) -> dict:
    defaults = {
        "db_level": DEFAULTS["DB_LEVEL"],
        "recorded_at_utc": "2026-09-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_garage_assignment_payload(**overrides) -> dict:
    defaults = {
        "bay_number": DEFAULTS["BAY_NUMBER"],
        "power_hookups": DEFAULTS["POWER_HOOKUPS"],
        "water_hookup": False,
    }
    defaults.update(overrides)
    return defaults


def create_paddock_assignment_payload(**overrides) -> dict:
    defaults = {"stall_number": DEFAULTS["STALL_NUMBER"]}
    defaults.update(overrides)
    return defaults
