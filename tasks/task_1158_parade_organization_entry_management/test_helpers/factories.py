"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from . import constants as C


def create_parade_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Parade",
        "parade_date": C.PARADE_DATE_ISO,
        "entry_deadline": C.ENTRY_DEADLINE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_route_segment_payload(**overrides) -> dict:
    defaults = {
        "order_index": 1,
        "name": "Main St",
        "length_meters": 800,
        "emergency_lane_width_m": 3.5,
        "segment_window_start": C.SEGMENT_WINDOW_START_ISO,
        "segment_window_end": C.SEGMENT_WINDOW_END_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_staging_area_payload(**overrides) -> dict:
    defaults = {
        "name": "Lot A",
        "capacity": 3,
        "open_time": C.STAGING_OPEN_ISO,
        "close_time": C.STAGING_CLOSE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_dispersal_plan_payload(**overrides) -> dict:
    defaults = {
        "emergency_lane_width_m": 3.5,
        "dispersal_corridors": ["Oak Ave"],
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(agency_type="POLICE", expected_permit_version=1, **overrides) -> dict:
    defaults = {
        "agency_type": agency_type,
        "expected_permit_version": expected_permit_version,
    }
    defaults.update(overrides)
    return defaults


def create_entry_payload(**overrides) -> dict:
    defaults = {
        "org_name": "Test Marchers",
        "requested_category": "BAND",
        "estimated_participants": 10,
    }
    defaults.update(overrides)
    return defaults


def create_float_payload(**overrides) -> dict:
    defaults = {
        "length_m": 10,
        "width_m": 3,
        "height_m": 4,
        "weight_kg": 7000,
        "vehicle_class": "SELF_PROPELLED",
        "fuel_type": "DIESEL",
    }
    defaults.update(overrides)
    return defaults


def schedule_inspection_payload(**overrides) -> dict:
    defaults = {"scheduled_at": "2026-06-25T09:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_lineup_assignment_payload(entry_id, staging_area_id, **overrides) -> dict:
    defaults = {
        "entry_id": entry_id,
        "staging_area_id": staging_area_id,
        "position_number": 1,
        "arrive_at": "2026-07-04T07:30:00Z",
        "depart_at": "2026-07-04T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_marshal_assignment_payload(route_segment_id, marshal_user_id, **overrides) -> dict:
    defaults = {
        "route_segment_id": route_segment_id,
        "marshal_user_id": marshal_user_id,
        "shift_start": "2026-07-04T08:00:00Z",
        "shift_end": "2026-07-04T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_score_sheet_payload(total=80, **overrides) -> dict:
    """Build a four-criterion sheet payload summing to `total` (each <= 25)."""
    base = total // 4
    rem = total - base * 4
    defaults = {
        "creativity": base + rem,
        "craftsmanship": base,
        "theme": base,
        "crowd_appeal": base,
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "award_category": "BEST_FLOAT",
        "eligible_entry_category": "FLOAT",
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "sponsor_name": "Acme Corp",
        "tier": "GOLD",
        "contribution_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_script_item_payload(item_type="SPONSOR_READ", **overrides) -> dict:
    defaults = {
        "item_type": item_type,
        "sequence_index": 1,
        "duration_minutes": 1.0,
    }
    defaults.update(overrides)
    return defaults
