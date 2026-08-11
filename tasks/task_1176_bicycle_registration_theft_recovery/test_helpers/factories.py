"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "OWNER_EMAIL": "owner@example.com",
    "OWNER_PASSWORD": "pw",
    "OWNER_FULL_NAME": "Test Owner",
    "ORG_NAME": "City PD",
    "ORG_TYPE": "LAW_ENFORCEMENT",
    "JURISDICTION_CODE": "CPD-1",
    "CONTACT_EMAIL": "pd@example.gov",
    "SERIAL_NUMBER": "ABC123",
    "MANUFACTURER": "Trek",
    "MODEL": "FX3",
    "PRIMARY_COLOR": "Black",
    "DECLARED_VALUE_CENTS": 40000,
    "PHOTO_URL": "https://example.com/photo.jpg",
    "SALE_PRICE_CENTS": 30000,
    "THEFT_LOCATION": "Downtown rack",
    "FOUND_LOCATION": "Impound lot",
    "APPRAISED_VALUE_CENTS": 100000,
    "PROOF_TEXT": "receipt and frame mark",
    "EVENT_TITLE": "Campus Registration Drive",
    "EVENT_VENUE": "Quad",
}


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["OWNER_EMAIL"],
        "password": DEFAULTS["OWNER_PASSWORD"],
        "full_name": DEFAULTS["OWNER_FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_partner_org_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_bicycle_payload(**overrides) -> dict:
    defaults = {
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "model": DEFAULTS["MODEL"],
        "primary_color": DEFAULTS["PRIMARY_COLOR"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
        "photo_url": DEFAULTS["PHOTO_URL"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(bicycle_id, to_owner_email, **overrides) -> dict:
    defaults = {
        "bicycle_id": bicycle_id,
        "to_owner_email": to_owner_email,
        "sale_price_cents": DEFAULTS["SALE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_theft_report_payload(bicycle_id, **overrides) -> dict:
    defaults = {
        "bicycle_id": bicycle_id,
        "occurred_at": "2026-05-03T00:00:00Z",
        "theft_location": DEFAULTS["THEFT_LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_recovery_intake_payload(**overrides) -> dict:
    defaults = {
        "serial_number_raw": DEFAULTS["SERIAL_NUMBER"],
        "primary_color": DEFAULTS["PRIMARY_COLOR"],
        "found_at": "2026-05-10T00:00:00Z",
        "found_location": DEFAULTS["FOUND_LOCATION"],
        "appraised_value_cents": DEFAULTS["APPRAISED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(recovery_intake_id, match_id, **overrides) -> dict:
    defaults = {
        "recovery_intake_id": recovery_intake_id,
        "match_id": match_id,
        "proof_text": DEFAULTS["PROOF_TEXT"],
    }
    defaults.update(overrides)
    return defaults


def create_auction_payload(recovery_intake_id, **overrides) -> dict:
    defaults = {
        "recovery_intake_id": recovery_intake_id,
        "starts_at": "2026-06-05T00:00:00Z",
        "ends_at": "2026-06-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(amount_cents, expected_auction_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_auction_version": expected_auction_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(host_org_id, **overrides) -> dict:
    defaults = {
        "host_org_id": host_org_id,
        "title": DEFAULTS["EVENT_TITLE"],
        "venue": DEFAULTS["EVENT_VENUE"],
        "starts_at": "2026-06-01T09:00:00Z",
        "ends_at": "2026-06-01T12:00:00Z",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_duplicate_flag_payload(bicycle_a_id, bicycle_b_id, **overrides) -> dict:
    defaults = {
        "bicycle_a_id": bicycle_a_id,
        "bicycle_b_id": bicycle_b_id,
    }
    defaults.update(overrides)
    return defaults
