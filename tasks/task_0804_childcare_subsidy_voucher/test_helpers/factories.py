"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STATE_CODE": "CA",
    "HOUSEHOLD_SIZE": 3,
    "GROSS_INCOME": 250_000,
    "ENTRY_LIMIT": 400_000,
    "EXIT_LIMIT": 500_000,
    "PUBLISHED_RATE": 6_000,
    "CEILING_MAX": 5_000,
    "LICENSE_EXPIRY": "2027-01-01T00:00:00Z",
    "CEILING_START": "2020-01-01T00:00:00Z",
    "CEILING_END": "2030-01-01T00:00:00Z",
    "AUTH_START": "2026-03-01T00:00:00Z",
    "AUTH_END": "2026-09-01T00:00:00Z",
    "DAYS_PER_MONTH": 22,
}


def create_family_payload(**overrides) -> dict:
    payload = {
        "applicant_name": "A Fam",
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "monthly_gross_income_cents": DEFAULTS["GROSS_INCOME"],
        "monthly_self_employment_income_cents": 0,
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_parent_activity_payload(family_id, **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "activity_type": "WORK",
        "weekly_hours": 40,
    }
    payload.update(overrides)
    return payload


def create_income_standard_payload(**overrides) -> dict:
    payload = {
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "entry_monthly_limit_cents": DEFAULTS["ENTRY_LIMIT"],
        "exit_monthly_limit_cents": DEFAULTS["EXIT_LIMIT"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_determination_payload(family_id, determination_type="INITIAL", **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "determination_type": determination_type,
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "name": "Sunny Center",
        "provider_type": "CENTER",
        "published_daily_rate_cents": DEFAULTS["PUBLISHED_RATE"],
        "license_expiry_date": DEFAULTS["LICENSE_EXPIRY"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_rate_ceiling_payload(**overrides) -> dict:
    payload = {
        "provider_type": "CENTER",
        "care_level": "TODDLER",
        "max_daily_rate_cents": DEFAULTS["CEILING_MAX"],
        "effective_start": DEFAULTS["CEILING_START"],
        "effective_end": DEFAULTS["CEILING_END"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return payload


def create_authorization_payload(family_id, provider_id, determination_id,
                                 expected_family_version, **overrides) -> dict:
    payload = {
        "family_id": family_id,
        "provider_id": provider_id,
        "determination_id": determination_id,
        "child_name": "Kid One",
        "care_level": "TODDLER",
        "start_date": DEFAULTS["AUTH_START"],
        "end_date": DEFAULTS["AUTH_END"],
        "authorized_days_per_month": DEFAULTS["DAYS_PER_MONTH"],
        "expected_family_version": expected_family_version,
    }
    payload.update(overrides)
    return payload


def create_attendance_payload(authorization_id, service_month="2026-03",
                              present_days=18, absent_days=3, **overrides) -> dict:
    payload = {
        "authorization_id": authorization_id,
        "service_month": service_month,
        "present_days": present_days,
        "absent_days": absent_days,
    }
    payload.update(overrides)
    return payload
