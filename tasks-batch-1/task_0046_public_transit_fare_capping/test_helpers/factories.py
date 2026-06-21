"""Payload factories — one per entity, input fields only.

Optional fields (those with PRD defaults) are omitted from the base payload unless
overridden, so each factory exercises the default-application path by default.
"""

DEFAULTS = {
    "ZONE": "ZONEX",
    "BASE_FARE": 300,
    "DAILY_CAP": 500,
    "WEEKLY_CAP": 2500,
}


def create_fare_product_payload(**overrides) -> dict:
    """Required: zone_code, base_fare_cents, daily_cap_cents, weekly_cap_cents.
    Optional (PRD defaults): transfer_window_minutes, transfer_discount_pct, reduced_fare_pct."""
    payload = {
        "zone_code": DEFAULTS["ZONE"],
        "base_fare_cents": DEFAULTS["BASE_FARE"],
        "daily_cap_cents": DEFAULTS["DAILY_CAP"],
        "weekly_cap_cents": DEFAULTS["WEEKLY_CAP"],
    }
    payload.update(overrides)
    return payload


def create_rider_payload(**overrides) -> dict:
    """Required: email, full_name, home_zone_code.
    Optional (PRD defaults): income_tier, low_income_discount_pct."""
    payload = {
        "email": "rider@example.com",
        "full_name": "Test Rider",
        "home_zone_code": DEFAULTS["ZONE"],
    }
    payload.update(overrides)
    return payload


def create_funding_source_payload(rider_id: str, **overrides) -> dict:
    """Required: rider_id, source_type. Optional: is_default."""
    payload = {
        "rider_id": rider_id,
        "source_type": "APPLE_PAY",
    }
    payload.update(overrides)
    return payload


def create_reduced_fare_card_payload(rider_id: str, **overrides) -> dict:
    """Required: rider_id, program_code, expires_on."""
    payload = {
        "rider_id": rider_id,
        "program_code": "SENIOR",
        "expires_on": "2027-01-01",
    }
    payload.update(overrides)
    return payload


def create_benefit_allocation_payload(rider_id: str, expected_rider_version: int,
                                      **overrides) -> dict:
    """Required: rider_id, employer_ref, period_month, allocated_cents, expected_rider_version."""
    payload = {
        "rider_id": rider_id,
        "employer_ref": "EMP1",
        "period_month": "2026-06",
        "allocated_cents": 1000,
        "expected_rider_version": expected_rider_version,
    }
    payload.update(overrides)
    return payload


def create_fare_week_payload(rider_id: str, **overrides) -> dict:
    """Required: rider_id, week_start_date (a Monday), zone_code."""
    payload = {
        "rider_id": rider_id,
        "week_start_date": "2026-06-01",
        "zone_code": DEFAULTS["ZONE"],
    }
    payload.update(overrides)
    return payload


def create_tap_payload(rider_id: str, fare_week_id: str, funding_source_id: str,
                       tapped_at: str, **overrides) -> dict:
    """Required: rider_id, fare_week_id, funding_source_id, tapped_at."""
    payload = {
        "rider_id": rider_id,
        "fare_week_id": fare_week_id,
        "funding_source_id": funding_source_id,
        "tapped_at": tapped_at,
    }
    payload.update(overrides)
    return payload


def load_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def verify_payload(verification_token: str) -> dict:
    return {"verification_token": verification_token}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
