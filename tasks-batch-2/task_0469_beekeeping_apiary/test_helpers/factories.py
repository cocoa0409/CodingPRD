"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD: fields the PRD declares optional or
with a default (brood_frames, source_hive_id, honey_frames_observed,
frames_drawn) are omitted from defaults unless the caller supplies them.
"""

DEFAULTS = {
    "APIARY_NAME": "CA Yard",
    "STATE_CODE": "CA",
    "LATITUDE": 38.5,
    "LONGITUDE": -121.5,
    "MAX_YARD_COLONIES": 50,
    "HIVE_TAG": "H1",
    "REGISTRATION_NUMBER": "CA-001",
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRY_DATE": "2026-12-31T00:00:00Z",
    "INSPECTED_AT": "2026-01-06T00:00:00Z",
    "LOT_CODE": "L1",
    "FLORAL_SOURCE": "WILDFLOWER",
    "GROWER_NAME": "Almond Co",
    "ORCHARD_STATE_CODE": "CA",
    "BLOOM_START": "2026-02-04T00:00:00Z",
    "BLOOM_END": "2026-03-06T00:00:00Z",
    "BASE_RATE_CENTS": 20000,
}


def create_apiary_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["APIARY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "latitude": DEFAULTS["LATITUDE"],
        "longitude": DEFAULTS["LONGITUDE"],
        "max_yard_colonies": DEFAULTS["MAX_YARD_COLONIES"],
    }
    payload.update(overrides)
    return payload


def create_registration_payload(**overrides) -> dict:
    payload = {
        "registration_number": DEFAULTS["REGISTRATION_NUMBER"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_hive_payload(apiary_id, **overrides) -> dict:
    # Required: apiary_id, tag. Optional: brood_frames (default 0), source_hive_id.
    payload = {
        "apiary_id": apiary_id,
        "tag": DEFAULTS["HIVE_TAG"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides) -> dict:
    # Required: inspected_at, mites_per_100_bees, brood_frames_observed, queen_seen.
    # Optional: honey_frames_observed (default 0).
    payload = {
        "inspected_at": DEFAULTS["INSPECTED_AT"],
        "mites_per_100_bees": 1.0,
        "brood_frames_observed": 5,
        "honey_frames_observed": 3,
        "queen_seen": True,
    }
    payload.update(overrides)
    return payload


def create_treatment_payload(**overrides) -> dict:
    payload = {
        "product": "APIVAR",
        "applied_at": "2026-02-10T00:00:00Z",
        "duration_days": 42,
    }
    payload.update(overrides)
    return payload


def create_honey_lot_payload(apiary_id, **overrides) -> dict:
    payload = {
        "apiary_id": apiary_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "floral_source": DEFAULTS["FLORAL_SOURCE"],
    }
    payload.update(overrides)
    return payload


def create_harvest_payload(hive_id, **overrides) -> dict:
    payload = {
        "hive_id": hive_id,
        "frames_pulled": 4,
        "weight_kg": 12.0,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(**overrides) -> dict:
    payload = {
        "grower_name": DEFAULTS["GROWER_NAME"],
        "orchard_state_code": DEFAULTS["ORCHARD_STATE_CODE"],
        "bloom_start": DEFAULTS["BLOOM_START"],
        "bloom_end": DEFAULTS["BLOOM_END"],
        "required_strong_hives": 1,
        "max_hives_on_site": 4,
        "base_rate_cents": DEFAULTS["BASE_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_placement_payload(hive_id, **overrides) -> dict:
    payload = {
        "hive_id": hive_id,
        "placement_start": DEFAULTS["BLOOM_START"],
        "removal_due": DEFAULTS["BLOOM_END"],
    }
    payload.update(overrides)
    return payload


def confirm_placement_payload(expected_contract_version, **overrides) -> dict:
    payload = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def create_sale_payload(source_hive_id, **overrides) -> dict:
    # Required: source_hive_id, product_type, price_cents.
    # Optional: frames_drawn (default 0).
    payload = {
        "source_hive_id": source_hive_id,
        "product_type": "NUC",
        "frames_drawn": 3,
        "price_cents": 18000,
    }
    payload.update(overrides)
    return payload


def create_feeding_payload(**overrides) -> dict:
    payload = {
        "fed_at": "2026-01-06T00:00:00Z",
        "feed_type": "SYRUP_1_1",
        "quantity_kg": 2.0,
    }
    payload.update(overrides)
    return payload


def create_requeen_schedule_payload(**overrides) -> dict:
    payload = {
        "due_date": "2026-04-01T00:00:00Z",
        "reason": "QUEENLESS",
    }
    payload.update(overrides)
    return payload


def sell_payload(**overrides) -> dict:
    payload = {"price_per_kg_cents": 4000}
    payload.update(overrides)
    return payload
