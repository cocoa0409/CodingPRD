"""Payload factories — input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "ZONE_NAME": "Zone",
    "FULL_NAME": "Resident Ray",
    "EMAIL": "resident@x.com",
    "ADDRESS": "1 Main St",
    "PARTNER_NAME": "ThriftCo",
    "PARTNER_TYPE": "THRIFT",
    "ACCEPTED_GRADES": ["RESALE", "RECYCLE"],
    "CAPACITY_KG": 1000,
    "BOX_LABEL": "Box-1",
    "BOX_LOCATION": "Depot",
    "SPONSOR_NAME": "EcoCorp",
    "CHARITY_NAME": "ClothesAid",
}


def create_zone_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["ZONE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_resident_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "email": DEFAULTS["EMAIL"],
        "address": DEFAULTS["ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_bag_kit_payload(**overrides) -> dict:
    defaults = {"kit_type": "BAG"}
    defaults.update(overrides)
    return defaults


def create_pickup_payload(resident_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
        "bags_claimed": TEST_DEFAULTS["BAGS_CLAIMED"],
    }
    defaults.update(overrides)
    return defaults


def reschedule_pickup_payload(expected_pickup_version, **overrides) -> dict:
    defaults = {
        "window_start": "2026-05-11T10:00:00Z",
        "window_end": "2026-05-11T12:00:00Z",
        "expected_pickup_version": expected_pickup_version,
    }
    defaults.update(overrides)
    return defaults


def route_pickup_payload(**overrides) -> dict:
    defaults = {
        "driver_id": TEST_DEFAULTS["DRIVER_ID"],
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def mark_collected_payload(**overrides) -> dict:
    defaults = {"provisional_weight_kg": TEST_DEFAULTS["PROVISIONAL_WEIGHT_KG"]}
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PARTNER_NAME"],
        "partner_type": DEFAULTS["PARTNER_TYPE"],
        "accepted_grades": list(DEFAULTS["ACCEPTED_GRADES"]),
        "capacity_kg": DEFAULTS["CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_dropbox_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "label": DEFAULTS["BOX_LABEL"],
        "location": DEFAULTS["BOX_LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_fill_reading_payload(**overrides) -> dict:
    defaults = {"fill_pct": 20.0, "recorded_at": "2026-05-01T06:00:00Z"}
    defaults.update(overrides)
    return defaults


def certify_ticket_payload(**overrides) -> dict:
    defaults = {
        "certified_weight_kg": TEST_DEFAULTS["CERTIFIED_WEIGHT_KG"],
        "grade": TEST_DEFAULTS["GRADE"],
    }
    defaults.update(overrides)
    return defaults


def create_contamination_report_payload(**overrides) -> dict:
    defaults = {"severity": "MAJOR"}
    defaults.update(overrides)
    return defaults


def create_sponsor_fund_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "sponsor_name": DEFAULTS["SPONSOR_NAME"],
        "initial_cents": TEST_DEFAULTS["FUND_INITIAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_charity_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["CHARITY_NAME"]}
    defaults.update(overrides)
    return defaults


def create_reporting_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-05-01T00:00:00Z",
        "period_end": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def charity_split_payload(lines, expected_zone_version) -> dict:
    """lines: list of {charity_id, pct} dicts."""
    return {"charity_splits": list(lines), "expected_zone_version": expected_zone_version}


def topup_payload(amount_cents=5000) -> dict:
    return {"amount_cents": amount_cents}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
