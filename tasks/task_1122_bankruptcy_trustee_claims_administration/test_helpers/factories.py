"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "CASE_NUMBER": "26-00001",
    "DEBTOR_NAME": "Test Debtor",
    "FILED_ON": "2026-01-15T00:00:00Z",
    "DISTRICT": "D.Del.",
    "TRUSTEE_USER_ID": "trust-0001",
    "BAR_DATE": "2026-06-01T00:00:00Z",
    "LEGAL_NAME": "Test Creditor",
    "CREDITOR_REF": "CR-0001",
    "CONTACT_EMAIL": "creditor@example.com",
    "RECEIVED_AT": "2026-02-01T00:00:00Z",
    "FILED_AMOUNT_CENTS": 100000,
    "PRIORITY_CLASS": "GENERAL_UNSECURED",
    "DESCRIPTION": "Test asset",
    "SCHEDULED_VALUE_CENTS": 100000,
    "BUYER_NAME": "BuyerCo",
    "GROUNDS": "AMOUNT_DISPUTED",
    "TRANSFER_DATE": "2025-12-01T00:00:00Z",
}


def create_case_payload(**overrides) -> dict:
    defaults = {
        "case_number": DEFAULTS["CASE_NUMBER"],
        "debtor_name": DEFAULTS["DEBTOR_NAME"],
        "filed_on": DEFAULTS["FILED_ON"],
        "district": DEFAULTS["DISTRICT"],
        "trustee_user_id": DEFAULTS["TRUSTEE_USER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_creditor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "creditor_ref": DEFAULTS["CREDITOR_REF"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def file_claim_payload(**overrides) -> dict:
    defaults = {
        "received_at": DEFAULTS["RECEIVED_AT"],
        "filed_amount_cents": DEFAULTS["FILED_AMOUNT_CENTS"],
        "priority_class": DEFAULTS["PRIORITY_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_objection_payload(**overrides) -> dict:
    defaults = {
        "grounds": DEFAULTS["GROUNDS"],
        "proposed_allowed_amount_cents": 0,
        "proposed_priority_class": DEFAULTS["PRIORITY_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def settle_objection_payload(**overrides) -> dict:
    defaults = {"outcome": "ALLOW"}
    defaults.update(overrides)
    return defaults


def create_asset_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["DESCRIPTION"],
        "scheduled_value_cents": DEFAULTS["SCHEDULED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    defaults = {
        "buyer_name": DEFAULTS["BUYER_NAME"],
        "hammer_price_cents": 100000,
        "sale_costs_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_avoidance_action_payload(**overrides) -> dict:
    defaults = {
        "transfer_date": DEFAULTS["TRANSFER_DATE"],
        "transfer_amount_cents": 100000,
        "action_type": "PREFERENCE_547",
        "demand_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_fee_application_payload(**overrides) -> dict:
    defaults = {
        "applicant_role": "COUNSEL",
        "requested_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults
