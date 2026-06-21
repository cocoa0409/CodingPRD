"""Payload factories — one per create/mutation endpoint, input fields only."""

import itertools

# Monotonic counters so default natural keys are unique per server process.
_sku_seq = itertools.count(1)
_station_seq = itertools.count(1)
_route_seq = itertools.count(1)
_tag_seq = itertools.count(1)
_locker_seq = itertools.count(1)


def create_account_payload(**overrides) -> dict:
    """Account: legal_name + service_day required; shortage_grace_units optional."""
    defaults = {
        "legal_name": "Test Account",
        "service_day": "MON",
    }
    defaults.update(overrides)
    return defaults


def create_wearer_payload(**overrides) -> dict:
    """Wearer: full_name, shirt_size, pant_size, locker_label all required."""
    defaults = {
        "full_name": "Test Wearer",
        "shirt_size": "M",
        "pant_size": 32,
        "locker_label": f"LKR-{next(_locker_seq)}",
    }
    defaults.update(overrides)
    return defaults


def create_garment_type_payload(**overrides) -> dict:
    """GarmentType: sku, category, and the three cent fields all required."""
    defaults = {
        "sku": f"SKU-{next(_sku_seq)}",
        "category": "SHIRT",
        "weekly_rate_cents": 1000,
        "replacement_cost_cents": 8000,
        "emblem_setup_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_wash_station_payload(**overrides) -> dict:
    """WashStation: station_code + capacity required."""
    defaults = {
        "station_code": f"WS-{next(_station_seq)}",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_garment_payload(garment_type_id: str, **overrides) -> dict:
    """Garment: garment_type_id + tag_code required; emblem_text optional."""
    defaults = {
        "garment_type_id": garment_type_id,
        "tag_code": f"TAG-{next(_tag_seq)}",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(garment_id: str, wearer_id: str, **overrides) -> dict:
    """Assignment: garment_id + wearer_id required."""
    defaults = {
        "garment_id": garment_id,
        "wearer_id": wearer_id,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    """Route: route_code, service_day, driver_user_id required."""
    defaults = {
        "route_code": f"RT-{next(_route_seq)}",
        "service_day": "MON",
        "driver_user_id": "drv-default",
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(account_id: str, **overrides) -> dict:
    """RouteStop: account_id, stop_sequence, window_start_min, window_end_min required."""
    defaults = {
        "account_id": account_id,
        "stop_sequence": 1,
        "window_start_min": 480,
        "window_end_min": 540,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(**overrides) -> dict:
    """ServiceVisit: week_index required."""
    defaults = {
        "week_index": 0,
    }
    defaults.update(overrides)
    return defaults


def pickup_payload(actual_soil_count: int = 0, **overrides) -> dict:
    """Pickup: actual_soil_count required."""
    defaults = {"actual_soil_count": actual_soil_count}
    defaults.update(overrides)
    return defaults


def reconcile_payload(expected_service_visit_version: int, **overrides) -> dict:
    """Reconcile: expected_service_visit_version required (PRD §2.7)."""
    defaults = {"expected_service_visit_version": expected_service_visit_version}
    defaults.update(overrides)
    return defaults


def apply_emblem_payload(emblem_text: str, **overrides) -> dict:
    """apply-emblem: emblem_text required."""
    defaults = {"emblem_text": emblem_text}
    defaults.update(overrides)
    return defaults


def start_wash_payload(wash_station_id: str, slot_start_min: int = 600,
                       slot_end_min: int = 660, **overrides) -> dict:
    """start-wash: wash_station_id, slot_start_min, slot_end_min required."""
    defaults = {
        "wash_station_id": wash_station_id,
        "slot_start_min": slot_start_min,
        "slot_end_min": slot_end_min,
    }
    defaults.update(overrides)
    return defaults
