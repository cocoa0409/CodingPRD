"""Payload factories — one per entity, input fields only.

Each factory builds the minimal valid required-field set and accepts **overrides
for any field a test needs to control. Optional fields are omitted by default so
that "default applied" tests can assert the server-side default.
"""

# Shared sensible defaults reused across factories.
DEFAULTS = {
    "BASE_NIGHTLY_RATE_CENTS": 20000,
    "CLEANING_FEE_CENTS": 5000,
    "PET_FEE_CENTS": 3000,
    "SECURITY_DEPOSIT_CENTS": 10000,
    "SEASONAL_MULTIPLIER_BPS": 10000,
}


def create_host_payload(**overrides) -> dict:
    """Required: email, display_name. Optional: payout_method."""
    payload = {
        "email": "host@example.com",
        "display_name": "Test Host",
    }
    payload.update(overrides)
    return payload


def create_guest_payload(**overrides) -> dict:
    """Required: email, full_name.
    Optional (with PRD defaults): govt_id_verified, prior_cancellations,
    chargeback_flag."""
    payload = {
        "email": "guest@example.com",
        "full_name": "Test Guest",
    }
    payload.update(overrides)
    return payload


def create_listing_payload(host_id, **overrides) -> dict:
    """Required: host_id, title, base_nightly_rate_cents, cleaning_fee_cents.
    Optional: pet_fee_cents, tax_rate_bps, min_nights, gap_nights,
    cancellation_tier, security_deposit_cents, platform_commission_bps,
    payout_delay_days."""
    payload = {
        "host_id": host_id,
        "title": "Test Listing",
        "base_nightly_rate_cents": DEFAULTS["BASE_NIGHTLY_RATE_CENTS"],
        "cleaning_fee_cents": DEFAULTS["CLEANING_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_rate_plan_payload(listing_id, **overrides) -> dict:
    """Required: listing_id, label, window_start, window_end,
    seasonal_multiplier_bps. Optional: weekend_multiplier_bps."""
    payload = {
        "listing_id": listing_id,
        "label": "STD",
        "window_start": "2026-07-01",
        "window_end": "2026-07-31",
        "seasonal_multiplier_bps": DEFAULTS["SEASONAL_MULTIPLIER_BPS"],
    }
    payload.update(overrides)
    return payload


def create_calendar_block_payload(expected_listing_calendar_version, **overrides) -> dict:
    """Required: source, start_date, end_date, expected_listing_calendar_version."""
    payload = {
        "source": "MANUAL",
        "start_date": "2026-09-01",
        "end_date": "2026-09-04",
        "expected_listing_calendar_version": expected_listing_calendar_version,
    }
    payload.update(overrides)
    return payload


def create_channel_connection_payload(listing_id, **overrides) -> dict:
    """Required: listing_id, channel."""
    payload = {
        "listing_id": listing_id,
        "channel": "AIRBNB",
    }
    payload.update(overrides)
    return payload


def create_imported_reservation_payload(**overrides) -> dict:
    """Required: external_ref, start_date, end_date."""
    payload = {
        "external_ref": "EXT-1",
        "start_date": "2026-09-01",
        "end_date": "2026-09-05",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(listing_id, guest_id, expected_listing_calendar_version, **overrides) -> dict:
    """Required: listing_id, guest_id, check_in, check_out,
    expected_listing_calendar_version. Optional: pets_count."""
    payload = {
        "listing_id": listing_id,
        "guest_id": guest_id,
        "check_in": "2026-07-10",
        "check_out": "2026-07-13",
        "expected_listing_calendar_version": expected_listing_calendar_version,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(security_deposit_id, amount_cents, **overrides) -> dict:
    """Required: security_deposit_id, amount_cents, reason."""
    payload = {
        "security_deposit_id": security_deposit_id,
        "amount_cents": amount_cents,
        "reason": "Damage",
    }
    payload.update(overrides)
    return payload
