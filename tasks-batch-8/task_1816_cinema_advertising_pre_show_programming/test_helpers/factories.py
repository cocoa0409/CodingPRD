"""Payload factories — one per entity, input fields only."""
from . import constants


def create_theater_payload(**overrides) -> dict:
    defaults = {"name": "MetroPlex", "market_tier": "MAJOR_METRO"}
    defaults.update(overrides)
    return defaults


def create_screen_payload(**overrides) -> dict:
    defaults = {"auditorium_label": "Aud 1", "seat_count": constants.SEAT_COUNT}
    defaults.update(overrides)
    return defaults


def create_feature_payload(**overrides) -> dict:
    defaults = {
        "title": "Skyline",
        "content_rating": "PG13",
        "runtime_minutes": 120,
        "release_date": constants.FEATURE_RELEASE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_showtime_payload(feature_id, **overrides) -> dict:
    defaults = {"feature_id": feature_id, "starts_at": constants.OPENING_EVENING_START}
    defaults.update(overrides)
    return defaults


def create_advertiser_payload(**overrides) -> dict:
    defaults = {
        "name": "AutoCo",
        "advertiser_type": "NATIONAL",
        "category": "AUTOMOTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(advertiser_id, **overrides) -> dict:
    defaults = {
        "advertiser_id": advertiser_id,
        "name": "C1",
        "flight_start_date": constants.FLIGHT_START,
        "flight_end_date": constants.FLIGHT_END,
        "contracted_impressions": 10000,
        "cpm_cents": constants.CPM_CENTS,
        "budget_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(campaign_id, expected_reel_version, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "start_offset_seconds": 0,
        "duration_seconds": 60,
        "expected_reel_version": expected_reel_version,
    }
    defaults.update(overrides)
    return defaults


def create_playlog_payload(**overrides) -> dict:
    defaults = {"outcome": "VERIFIED"}
    defaults.update(overrides)
    return defaults


def acknowledge_delivery_payload(**overrides) -> dict:
    defaults = {"outcome": "DELIVERED"}
    defaults.update(overrides)
    return defaults


def lock_reel_payload(expected_reel_version) -> dict:
    return {"expected_reel_version": expected_reel_version}


def create_attendance_report_payload(**overrides) -> dict:
    defaults = {"reported_attendance": 175}
    defaults.update(overrides)
    return defaults


def review_attendance_payload(decision) -> dict:
    return {"decision": decision}


def audit_attendance_payload(**overrides) -> dict:
    defaults = {"audited_attendance": 150}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "period_start_date": constants.FLIGHT_START,
        "period_end_date": constants.FLIGHT_END,
    }
    defaults.update(overrides)
    return defaults


def review_make_good_payload(decision) -> dict:
    return {"decision": decision}


def apply_make_good_payload(expected_invoice_version) -> dict:
    return {"expected_invoice_version": expected_invoice_version}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
