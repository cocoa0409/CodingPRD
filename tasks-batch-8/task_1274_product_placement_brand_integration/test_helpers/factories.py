"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from typing import Optional

DEFAULTS = {
    "BRAND_NAME": "FizzCo",
    "BRAND_CATEGORY": "BEVERAGE",
    "BRIEF_TITLE": "Summer fizz",
    "BRIEF_OBJECTIVE": "awareness",
    "BRIEF_BUDGET_CENTS": 1_000_000,
    "SERIES_NAME": "Night Shift",
    "SERIES_NETWORK": "NBN",
    "SERIES_POLICY": "STANDARD",
    "EPISODE_NUMBER": 1,
    "EPISODE_RUNTIME_SECONDS": 1200,
    "EPISODE_AIR_DATE": "2026-06-01T20:00:00Z",
    "SCENE_DESCRIPTION": "Kitchen",
    "SCENE_START": 0,
    "SCENE_END": 40,
    "ESTIMATED_EXPOSURE_SECONDS": 25,
    "PROPOSED_FEE_CENTS": 1_000_000,
    "GUARANTEED_SECONDS": 30,
    "GUARANTEED_VERBAL_MENTIONS": 0,
    "CROSS_PROMO_OWED": 0,
    "RATE_CENTS_PER_SECOND": 2000,
    "ITEM_DESCRIPTION": "Branded fridge",
    "QUANTITY": 1,
    "SCENE_TIMECODE_SECONDS": 12,
    "CONTINUITY_NOTE": "fridge visible left of frame",
    "DISCLOSURE_TEXT": "Paid placement by FizzCo",
    "CLOCK_AFTER_AIR": "2026-06-02T00:00:00Z",
}


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BRAND_NAME"],
        "category": DEFAULTS["BRAND_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_brief_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["BRIEF_TITLE"],
        "objective": DEFAULTS["BRIEF_OBJECTIVE"],
        "budget_cents": DEFAULTS["BRIEF_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SERIES_NAME"],
        "network_name": DEFAULTS["SERIES_NETWORK"],
    }
    defaults.update(overrides)
    return defaults


def create_episode_payload(**overrides) -> dict:
    defaults = {
        "episode_number": DEFAULTS["EPISODE_NUMBER"],
        "runtime_seconds": DEFAULTS["EPISODE_RUNTIME_SECONDS"],
        "air_date": DEFAULTS["EPISODE_AIR_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_opportunity_payload(**overrides) -> dict:
    defaults = {
        "scene_description": DEFAULTS["SCENE_DESCRIPTION"],
        "start_timecode_seconds": DEFAULTS["SCENE_START"],
        "end_timecode_seconds": DEFAULTS["SCENE_END"],
        "estimated_exposure_seconds": DEFAULTS["ESTIMATED_EXPOSURE_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(brand_id: str, expected_episode_version: int, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "expected_episode_version": expected_episode_version,
    }
    defaults.update(overrides)
    return defaults


def decide_clearance_payload(decision: str = "GRANT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_proposal_payload(brief_id: str, opportunity_id: str, **overrides) -> dict:
    defaults = {
        "brief_id": brief_id,
        "opportunity_id": opportunity_id,
        "proposed_fee_cents": DEFAULTS["PROPOSED_FEE_CENTS"],
        "guaranteed_seconds": DEFAULTS["GUARANTEED_SECONDS"],
        "guaranteed_verbal_mentions": DEFAULTS["GUARANTEED_VERBAL_MENTIONS"],
        "cross_promo_owed_count": DEFAULTS["CROSS_PROMO_OWED"],
        "rate_cents_per_second": DEFAULTS["RATE_CENTS_PER_SECOND"],
    }
    defaults.update(overrides)
    return defaults


def proposal_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_revision_payload(expected_proposal_version: int, **overrides) -> dict:
    defaults = {
        "proposed_fee_cents": 900_000,
        "guaranteed_seconds": DEFAULTS["GUARANTEED_SECONDS"],
        "guaranteed_verbal_mentions": DEFAULTS["GUARANTEED_VERBAL_MENTIONS"],
        "cross_promo_owed_count": DEFAULTS["CROSS_PROMO_OWED"],
        "rate_cents_per_second": DEFAULTS["RATE_CENTS_PER_SECOND"],
        "expected_proposal_version": expected_proposal_version,
    }
    defaults.update(overrides)
    return defaults


def amend_terms_payload(base_fee_cents: int, expected_contract_version: int, **overrides) -> dict:
    defaults = {
        "base_fee_cents": base_fee_cents,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "item_description": DEFAULTS["ITEM_DESCRIPTION"],
        "quantity": DEFAULTS["QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def advance_shipment_payload(to: str, **overrides) -> dict:
    defaults = {"to": to}
    defaults.update(overrides)
    return defaults


def create_continuity_record_payload(shipment_id: str, **overrides) -> dict:
    defaults = {
        "shipment_id": shipment_id,
        "scene_timecode_seconds": DEFAULTS["SCENE_TIMECODE_SECONDS"],
        "note": DEFAULTS["CONTINUITY_NOTE"],
    }
    defaults.update(overrides)
    return defaults


def create_airing_report_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "measured_segments_seconds": [30],
        "measured_verbal_mentions": 0,
    }
    defaults.update(overrides)
    return defaults


def remeasure_payload(**overrides) -> dict:
    defaults = {
        "measured_segments_seconds": [30],
        "measured_verbal_mentions": 0,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {"disclosure_text": DEFAULTS["DISCLOSURE_TEXT"]}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: Optional[str] = None) -> dict:
    return {"to_iso8601": to_iso8601 or DEFAULTS["CLOCK_AFTER_AIR"]}
