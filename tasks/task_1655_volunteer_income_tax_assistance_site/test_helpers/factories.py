"""Payload factories — one per creatable entity, input fields only (PRD §3-§4)."""

# Sensible defaults shared by factories. Season bounds and the daily window
# contain every appointment used by the suite; the startup logical clock
# (2026-08-01T00:00:00Z, PRD §2.5) precedes every default appointment start.
DEFAULTS = {
    "SITE_NAME": "Library VITA",
    "SPONSOR_ORG": "UnitedWay",
    "STATION_CAPACITY": 4,
    "SEASON_START": "2026-07-01T00:00:00Z",
    "SEASON_END": "2026-12-31T23:59:59Z",
    "DAILY_OPEN_HOUR": 9,
    "DAILY_CLOSE_HOUR": 17,
    "GOAL_RETURNS": 50,
    "TAX_SEASON": 2026,
    "TAX_YEAR": 2025,
    "APPT_START": "2026-08-03T10:00:00Z",
    "APPT_END": "2026-08-03T11:00:00Z",
    "ROUTING_NUMBER": "021000021",
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-08-31T23:59:59Z",
}


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "sponsor_org": DEFAULTS["SPONSOR_ORG"],
        "station_capacity": DEFAULTS["STATION_CAPACITY"],
        "season_start": DEFAULTS["SEASON_START"],
        "season_end": DEFAULTS["SEASON_END"],
        "daily_open_hour": DEFAULTS["DAILY_OPEN_HOUR"],
        "daily_close_hour": DEFAULTS["DAILY_CLOSE_HOUR"],
        "goal_returns": DEFAULTS["GOAL_RETURNS"],
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "full_name": "Volunteer",
        "email": "volunteer@x.org",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(expected_volunteer_version, **overrides) -> dict:
    defaults = {
        "test_type": "ETHICS",
        "score": 90,
        "tax_season": DEFAULTS["TAX_SEASON"],
        "expected_volunteer_version": expected_volunteer_version,
    }
    defaults.update(overrides)
    return defaults


def create_taxpayer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Taxpayer",
        "ssn_token": "SSN-0001",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(site_id, taxpayer_id, volunteer_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "taxpayer_id": taxpayer_id,
        "volunteer_id": volunteer_id,
        "purpose": "PREPARATION",
        "start_at": DEFAULTS["APPT_START"],
        "end_at": DEFAULTS["APPT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_return_payload(appointment_id, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "tax_year": DEFAULTS["TAX_YEAR"],
        "filing_status": "SINGLE",
    }
    defaults.update(overrides)
    return defaults


def patch_tax_return_payload(expected_return_version, **overrides) -> dict:
    """OCC-guarded edit payload (PRD §2.7): always carries the version."""
    defaults = {"expected_return_version": expected_return_version}
    defaults.update(overrides)
    return defaults


def create_refund_allocation_payload(tax_return_id, **overrides) -> dict:
    defaults = {
        "tax_return_id": tax_return_id,
        "account_type": "CHECKING",
        "routing_number": DEFAULTS["ROUTING_NUMBER"],
        "account_number_mask": "****0001",
        "amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_site_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults
