"""Payload factories — one per entity, input fields only (PRD sections 3-4).

Defaults are chosen so a default-built chain satisfies every PRD rule:
permits expire strictly after the startup clock reading, flight windows lie
inside the default campaign window, and the static face omits loop fields.
"""
from .constants import RATE_CARD_STATIC, TEST_DEFAULTS


def set_clock_payload(to_iso8601, **overrides):
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = dict(RATE_CARD_STATIC)
    defaults.update(overrides)
    return defaults


def create_face_payload(**overrides) -> dict:
    defaults = {
        "face_code": "F-NYC-001",
        "structure_code": "ST-001",
        "market_code": "NYC",
        "display_type": "STATIC",
        "illuminated": True,
        "daily_traffic_count": 300_000,
        "width_inches": TEST_DEFAULTS["FACE_WIDTH"],
        "height_inches": TEST_DEFAULTS["FACE_HEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(face_id, **overrides) -> dict:
    defaults = {
        "face_id": face_id,
        "permit_number": "P-001",
        "jurisdiction": TEST_DEFAULTS["JURISDICTION"],
        "issued_on": TEST_DEFAULTS["PERMIT_ISSUED"],
        "expires_on": TEST_DEFAULTS["PERMIT_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(face_id, **overrides) -> dict:
    defaults = {
        "face_id": face_id,
        "order_type": "STRUCTURAL_REPAIR",
        "description": "panel refit",
    }
    defaults.update(overrides)
    return defaults


def create_advertiser_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["ADVERTISER_NAME"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(advertiser_id, **overrides) -> dict:
    defaults = {
        "advertiser_id": advertiser_id,
        "name": "C1",
        "start_date": TEST_DEFAULTS["CAMPAIGN_START"],
        "end_date": TEST_DEFAULTS["CAMPAIGN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(campaign_id, face_id, rate_card_id, expected_face_version,
                          **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "face_id": face_id,
        "rate_card_id": rate_card_id,
        "start_date": TEST_DEFAULTS["FLIGHT_START"],
        "end_date": TEST_DEFAULTS["FLIGHT_END"],
        "expected_face_version": expected_face_version,
    }
    defaults.update(overrides)
    return defaults


def confirm_flight_payload(expected_campaign_version, **overrides) -> dict:
    defaults = {"expected_campaign_version": expected_campaign_version}
    defaults.update(overrides)
    return defaults


def create_artwork_order_payload(flight_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "creative_code": "CR-1",
        "material": "VINYL",
        "width_inches": TEST_DEFAULTS["FACE_WIDTH"],
        "height_inches": TEST_DEFAULTS["FACE_HEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_posting_record_payload(flight_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "posted_on": TEST_DEFAULTS["FLIGHT_START"],
        "photo_proof_url": "https://proof.example/1.jpg",
    }
    defaults.update(overrides)
    return defaults


def create_impression_entry_payload(**overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["FLIGHT_START"],
        "period_end": "2026-08-16",
        "source": "TRAFFIC_ESTIMATE",
        "impressions": 2_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_make_good_payload(flight_id, **overrides) -> dict:
    defaults = {
        "flight_id": flight_id,
        "reason": "UNDER_DELIVERY",
    }
    defaults.update(overrides)
    return defaults
