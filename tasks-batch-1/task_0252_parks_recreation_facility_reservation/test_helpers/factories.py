"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "HOURLY_RATE_CENTS": 10000,
    "RESIDENT_DISCOUNT_PCT": 0.0,
    "PRIME_MULTIPLIER": 1.5,
    "PRIME_START_HOUR": 18,
    "PRIME_END_HOUR": 22,
}


def create_facility_payload(**overrides) -> dict:
    """Input fields for POST /facilities. Optional fields (buffer_minutes,
    deposit_cents, requires_coi, min_coi_coverage_cents) are omitted unless
    overridden, letting the server apply its declared defaults."""
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "facility_type": "FIELD",
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "resident_discount_pct": DEFAULTS["RESIDENT_DISCOUNT_PCT"],
        "prime_multiplier": DEFAULTS["PRIME_MULTIPLIER"],
        "prime_start_hour": DEFAULTS["PRIME_START_HOUR"],
        "prime_end_hour": DEFAULTS["PRIME_END_HOUR"],
    }
    defaults.update(overrides)
    return defaults


_PATRON_EMAIL_SEQ = [0]


def _unique_email(prefix="patron"):
    _PATRON_EMAIL_SEQ[0] += 1
    return f"{prefix}{_PATRON_EMAIL_SEQ[0]}@example.com"


def create_patron_payload(**overrides) -> dict:
    """Input fields for POST /patrons. Email is auto-unique unless overridden."""
    defaults = {
        "full_name": "Test Patron",
        "email": _unique_email(),
        "residency": "NON_RESIDENT",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(patron_id, **overrides) -> dict:
    """Input fields for POST /insurance-certificates."""
    defaults = {
        "patron_id": patron_id,
        "coverage_amount_cents": 100000,
        "effective_date": "2026-07-01T00:00:00Z",
        "expiry_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(patron_id, start_at, end_at, **overrides) -> dict:
    """Input fields for POST /facilities/{id}/permits."""
    defaults = {
        "patron_id": patron_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(fee_component_cents, deposit_component_cents, **overrides) -> dict:
    """Input fields for POST /permits/{id}/payments."""
    defaults = {
        "fee_component_cents": fee_component_cents,
        "deposit_component_cents": deposit_component_cents,
    }
    defaults.update(overrides)
    return defaults


def create_league_payload(facility_id, patron_id, **overrides) -> dict:
    """Input fields for POST /leagues."""
    defaults = {
        "facility_id": facility_id,
        "patron_id": patron_id,
        "weekday": 1,
        "start_hour": 10,
        "duration_minutes": 120,
        "first_date": "2026-08-04T00:00:00Z",
        "occurrences": 1,
    }
    defaults.update(overrides)
    return defaults


def create_lottery_round_payload(facility_id, **overrides) -> dict:
    """Input fields for POST /lottery-rounds."""
    defaults = {
        "facility_id": facility_id,
        "slot_start_at": "2026-08-03T18:00:00Z",
        "slot_end_at": "2026-08-03T20:00:00Z",
        "opens_at": "2026-07-01T00:00:00Z",
        "closes_at": "2026-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lottery_entry_payload(patron_id, **overrides) -> dict:
    """Input fields for POST /lottery-rounds/{id}/entries."""
    defaults = {"patron_id": patron_id}
    defaults.update(overrides)
    return defaults
