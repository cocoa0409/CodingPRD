"""Payload factories — one per entity, input fields only."""
from .constants import SEASON_DEFAULTS


def _zeroed_counts(**counts):
    """Build a six-class count object, zero-filled for unspecified classes."""
    full = {
        "H_4_5": 0, "H_5_6": 0, "H_6_7": 0,
        "H_7_8": 0, "H_8_9": 0, "H_9_PLUS": 0,
    }
    full.update(counts)
    return full


def create_season_payload(**overrides) -> dict:
    defaults = dict(SEASON_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_block_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "block_code": "B-1",
        "acreage": 12.5,
    }
    defaults.update(overrides)
    return defaults


def create_crop_lot_payload(block_id, **overrides) -> dict:
    defaults = {
        "block_id": block_id,
        "species": "NOBLE_FIR",
        "planted_year": 2019,
        "initial_counts": _zeroed_counts(H_6_7=300),
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(crop_lot_id, **overrides) -> dict:
    defaults = {
        "crop_lot_id": crop_lot_id,
        "surveyed_counts": _zeroed_counts(H_6_7=250),
    }
    defaults.update(overrides)
    return defaults


def create_buyer_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Wholesale",
        "credit_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(season_id, buyer_account_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "buyer_account_id": buyer_account_id,
        "species": "NOBLE_FIR",
        "height_class": "H_6_7",
        "quantity": 10,
        "unit_price_cents": 400,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "crew_code": "C-1",
        "size": 5,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(crew_id, block_id, lines, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "block_id": block_id,
        "work_date": "2026-11-05",
        "hours_worked": 8,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "carrier_name": "Carrier A",
        "capacity_units": 100,
        "pickup_window_start": "2026-11-20T09:00:00Z",
        "pickup_window_end": "2026-11-20T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(season_id, bucket_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "bucket_id": bucket_id,
        "lot_name": "Lot 9 Partners",
        "quantity": 10,
        "unit_price_cents": 2995,
        "max_return_pct": 0.45,
    }
    defaults.update(overrides)
    return defaults


def create_ucut_tag_payload(block_id, bucket_id, **overrides) -> dict:
    defaults = {
        "block_id": block_id,
        "bucket_id": bucket_id,
        "customer_name": "Patron A",
        "price_cents": 6500,
    }
    defaults.update(overrides)
    return defaults


def create_cull_record_payload(bucket_id, **overrides) -> dict:
    defaults = {
        "bucket_id": bucket_id,
        "count": 1,
        "reason": "DISEASE",
    }
    defaults.update(overrides)
    return defaults


def create_replant_plan_payload(block_id, **overrides) -> dict:
    defaults = {
        "block_id": block_id,
        "species": "DOUGLAS_FIR",
        "planned_count": 400,
    }
    defaults.update(overrides)
    return defaults
