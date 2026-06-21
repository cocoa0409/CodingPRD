"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD: only fields the PRD marks required (no
default) are included unconditionally; optional fields are merged via overrides.
"""

DEFAULTS = {
    "PROPERTY_NAME": "Test Property",
    "TOTAL_ROOMS": 30,
    "ROOM_TYPE_CODE": "KING",
    "ROOM_TYPE_NAME": "King Room",
    "PHYSICAL_ROOMS": 30,
    "BASE_RATE": 200.0,
    "FLOOR_RATE": 100.0,
    "CEILING_RATE": 400.0,
    "REQUESTED_RATE": 200.0,
    "GROUP_NAME": "Test Group",
    "OFFERED_RATE": 300.0,
    "COMPETITOR_NAME": "Rival Hotel",
    "SHOPPED_RATE": 199.0,
    "STAY_DATE": "2026-06-06T00:00:00Z",
    "SHOPPED_AT": "2026-06-01T08:00:00Z",
}


def create_property_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "total_rooms": DEFAULTS["TOTAL_ROOMS"],
    }
    payload.update(overrides)
    return payload


def create_room_type_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "code": DEFAULTS["ROOM_TYPE_CODE"],
        "name": DEFAULTS["ROOM_TYPE_NAME"],
        "physical_rooms": DEFAULTS["PHYSICAL_ROOMS"],
    }
    payload.update(overrides)
    return payload


def create_rate_plan_payload(room_type_id, **overrides) -> dict:
    payload = {
        "room_type_id": room_type_id,
        "rate_class": "BAR",
        "base_rate": DEFAULTS["BASE_RATE"],
        "floor_rate": DEFAULTS["FLOOR_RATE"],
        "ceiling_rate": DEFAULTS["CEILING_RATE"],
    }
    payload.update(overrides)
    return payload


def create_inventory_day_payload(room_type_id, stay_date=None, **overrides) -> dict:
    payload = {
        "room_type_id": room_type_id,
        "stay_date": stay_date or DEFAULTS["STAY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_rate_decision_payload(rate_plan_id, stay_date=None, **overrides) -> dict:
    payload = {
        "rate_plan_id": rate_plan_id,
        "stay_date": stay_date or DEFAULTS["STAY_DATE"],
        "requested_rate": DEFAULTS["REQUESTED_RATE"],
    }
    payload.update(overrides)
    return payload


def create_yield_rule_payload(
    property_id, occupancy_threshold_pct, adjustment_pct, priority, **overrides
) -> dict:
    payload = {
        "property_id": property_id,
        "name": "Test Yield Rule",
        "occupancy_threshold_pct": occupancy_threshold_pct,
        "adjustment_pct": adjustment_pct,
        "priority": priority,
    }
    payload.update(overrides)
    return payload


def create_group_block_payload(
    room_type_id, arrival_date=None, **overrides
) -> dict:
    payload = {
        "room_type_id": room_type_id,
        "group_name": DEFAULTS["GROUP_NAME"],
        "arrival_date": arrival_date or DEFAULTS["STAY_DATE"],
        "nights": 1,
        "rooms_per_night": 5,
        "offered_rate": DEFAULTS["OFFERED_RATE"],
    }
    payload.update(overrides)
    return payload


def create_channel_mapping_payload(rate_plan_id, channel, **overrides) -> dict:
    payload = {
        "rate_plan_id": rate_plan_id,
        "channel": channel,
    }
    payload.update(overrides)
    return payload


def create_competitor_rate_payload(property_id, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "competitor_name": DEFAULTS["COMPETITOR_NAME"],
        "stay_date": DEFAULTS["STAY_DATE"],
        "shopped_rate": DEFAULTS["SHOPPED_RATE"],
        "shopped_at": DEFAULTS["SHOPPED_AT"],
    }
    payload.update(overrides)
    return payload


def create_transient_reservation_payload(
    room_type_id, rate_plan_id, arrival_date=None, **overrides
) -> dict:
    payload = {
        "room_type_id": room_type_id,
        "rate_plan_id": rate_plan_id,
        "arrival_date": arrival_date or DEFAULTS["STAY_DATE"],
        "nights": 1,
        "rooms": 1,
    }
    payload.update(overrides)
    return payload
