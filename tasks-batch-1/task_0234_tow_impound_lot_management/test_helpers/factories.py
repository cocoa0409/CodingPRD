"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "LOT_NAME": "Test Impound Lot",
    "JURISDICTION_CODE": "CA",
    "DAILY_STORAGE_RATE_CENTS": 5000,
    "ADMIN_FEE_CENTS": 7500,
    "LIEN_PROCESSING_FEE_CENTS": 3000,
    "STATUTORY_HOLD_DAYS": 30,
    "NOTICE_GRACE_DAYS": 10,
}

# Monotonic license-number generator so each provider's license_number is unique.
_license_seq = [0]


def _next_license() -> str:
    _license_seq[0] += 1
    return f"LIC-{_license_seq[0]:06d}"


def create_impound_lot_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LOT_NAME"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "daily_storage_rate_cents": DEFAULTS["DAILY_STORAGE_RATE_CENTS"],
        "admin_fee_cents": DEFAULTS["ADMIN_FEE_CENTS"],
        "lien_processing_fee_cents": DEFAULTS["LIEN_PROCESSING_FEE_CENTS"],
        "statutory_hold_days": DEFAULTS["STATUTORY_HOLD_DAYS"],
        "notice_grace_days": DEFAULTS["NOTICE_GRACE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_tow_provider_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test Tow Co",
        "license_number": _next_license(),
        "rotation_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_lienholder_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Bank",
        "mailing_address": "1 Bank St",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_tow_order_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "tow_type": "POLICE",
        "vin": "VINTEST",
        "plate": "PLATE1",
        "owner_name": "Test Owner",
        "owner_address": "123 Owner Ave",
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(**overrides) -> dict:
    defaults = {
        "recipient_type": "OWNER",
        "method": "CERTIFIED_MAIL",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "category": "EXTERIOR_PHOTO",
        "description": "front photo",
        "photo_ref": "ref-1",
    }
    defaults.update(overrides)
    return defaults


def create_fee_waiver_payload(**overrides) -> dict:
    defaults = {
        "reason": "BILLING_DISPUTE",
        "requested_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_release_record_payload(**overrides) -> dict:
    defaults = {
        "amount_paid_cents": 0,
        "released_to_name": "Test Owner",
    }
    defaults.update(overrides)
    return defaults


def create_auction_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "window_start": "2030-01-01T00:00:00Z",
        "window_end": "2030-01-01T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults
