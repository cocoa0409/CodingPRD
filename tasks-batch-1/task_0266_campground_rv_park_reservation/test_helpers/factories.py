"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PARK_NAME": "Pinewood",
    "DEPOSIT_PCT": 0.30,
    "TAX_RATE": 0.08,
    "LONG_STAY_NIGHTS_THRESHOLD": 28,
    "RV_NIGHTLY": 5000,
    "RV_WEEKLY": 30000,
    "RV_MONTHLY": 100000,
    "GUEST_EMAIL": "g1@x.com",
    "GUEST_NAME": "Guest One",
}


def create_park_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PARK_NAME"],
        "deposit_pct": DEFAULTS["DEPOSIT_PCT"],
        "tax_rate": DEFAULTS["TAX_RATE"],
        "long_stay_nights_threshold": DEFAULTS["LONG_STAY_NIGHTS_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_plan_payload(**overrides) -> dict:
    defaults = {
        "site_type": "RV",
        "nightly_rate_cents": DEFAULTS["RV_NIGHTLY"],
        "weekly_rate_cents": DEFAULTS["RV_WEEKLY"],
        "monthly_rate_cents": DEFAULTS["RV_MONTHLY"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "PEAK",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "surcharge_pct": 12.5,
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_policy_payload(**overrides) -> dict:
    defaults = {
        "full_refund_min_days": 14,
        "half_refund_min_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(rate_plan_id, **overrides) -> dict:
    defaults = {
        "rate_plan_id": rate_plan_id,
        "label": "A-1",
        "site_type": "RV",
        "hookup_level": "FULL",
        "max_length_of_stay_nights": 30,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_hold_payload(start_date, end_date, expected_site_version, **overrides) -> dict:
    defaults = {
        "start_date": start_date,
        "end_date": end_date,
        "reason": "maintenance",
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["GUEST_EMAIL"],
        "full_name": DEFAULTS["GUEST_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(guest_id, check_in_date, check_out_date,
                               expected_site_version, **overrides) -> dict:
    defaults = {
        "guest_id": guest_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(kind, amount_cents, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(payment_type, amount_cents, **overrides) -> dict:
    defaults = {
        "type": payment_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
