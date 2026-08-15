"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "COMMUNITY_NAME": "Riverbend",
    "BUYER_NAME": "Alice Avery",
    "BUYER_EMAIL": "alice@example.com",
    "REP_NAME": "Rita Rep",
    "REP_EMAIL": "rita@example.com",
    "LOT_NUMBER": "L-101",
    "ADDRESS": "1 Riverbend Way",
    "SALES_PRICE_CENTS": 45_000_000,
    "CLOSING_DATE": "2026-09-01T17:00:00Z",
    "APPOINTMENT_START": "2026-08-25T14:00:00Z",
    "VISIT_DURATION_MINUTES": 60,
}


def create_community_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["COMMUNITY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_homebuyer_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["BUYER_NAME"],
        "email": DEFAULTS["BUYER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_rep_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["REP_NAME"],
        "email": DEFAULTS["REP_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_home_payload(**overrides) -> dict:
    defaults = {
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "address": DEFAULTS["ADDRESS"],
        "sales_price_cents": DEFAULTS["SALES_PRICE_CENTS"],
        "closing_date": DEFAULTS["CLOSING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {"scheduled_start": DEFAULTS["APPOINTMENT_START"]}
    defaults.update(overrides)
    return defaults


def create_attendee_payload(**overrides) -> dict:
    defaults = {"attendee_type": "BUYER"}
    defaults.update(overrides)
    return defaults


def create_deficiency_item_payload(**overrides) -> dict:
    defaults = {"title": "Paint scuff"}
    defaults.update(overrides)
    return defaults


def classify_deficiency_item_payload(**overrides) -> dict:
    defaults = {
        "classification": "WARRANTABLE",
        "estimated_repair_cost_cents": 20_000,
    }
    defaults.update(overrides)
    return defaults


def decide_deficiency_item_payload(**overrides) -> dict:
    defaults = {"resolution": "COMPLETE_AFTER_CLOSING"}
    defaults.update(overrides)
    return defaults


def create_reinspection_visit_payload(**overrides) -> dict:
    defaults = {"duration_minutes": DEFAULTS["VISIT_DURATION_MINUTES"]}
    defaults.update(overrides)
    return defaults


def submit_survey_payload(**overrides) -> dict:
    defaults = {
        "overall_rating": 5,
        "systems_demo_rating": 5,
        "timeliness_rating": 5,
        "would_recommend": True,
    }
    defaults.update(overrides)
    return defaults


def respond_signature_payload(**overrides) -> dict:
    defaults = {"decision": "SIGN", "signature_payload": "sig:buyer:1"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": "2026-08-25T14:00:00Z"}
    defaults.update(overrides)
    return defaults
