"""Payload factories — one per creatable entity, input fields only (PRD §3).

Computed/system fields (status, derived tonnages, *_at stamps,
*_by_user_id, settled_* lines, ...) are never sent by the client; only
client-supplied fields appear in these payloads. Optional flags
(`irrigated`, `moisture_controlled`) are omitted unless explicitly passed,
so default-handling tests exercise true omission.
"""
import itertools

from .constants import (
    REGION_CA_NORTH,
    REGION_OR,
    STD_DELIVERY_BY,
    STD_HARVEST_DATE,
    STD_INDEX_PRICE_CENTS,
    STD_LANE_MILES,
    STD_LANE_MIN_CENTS,
    STD_LANE_RATE_CENTS,
    STD_SHIP_DATE,
    STD_WINDOW_END,
    STD_WINDOW_START,
)

# Unique-suffix counter so repeated fixture calls inside one test never
# collide on human-readable names.
_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- Grower (PRD §3.1) ---

def create_grower_payload(**overrides) -> dict:
    n = _n()
    defaults = {"name": f"Grower {n}", "region_code": REGION_OR}
    defaults.update(overrides)
    return defaults


# --- Field (PRD §3.1) ---

def create_field_payload(grower_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "grower_id": grower_id,
        "name": f"Field {n}",
        "acres": 40.0,
        "forage_type": "ALFALFA",
    }
    if "irrigated" in overrides:
        defaults["irrigated"] = overrides.pop("irrigated")
    defaults.update(overrides)
    return defaults


# --- Cutting (PRD §3.1) ---

def create_cutting_payload(field_id, **overrides) -> dict:
    defaults = {
        "field_id": field_id,
        "cutting_number": 1,
        "season_year": 2026,
        "planned_window_start": STD_WINDOW_START,
        "planned_window_end": STD_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


# --- WeatherReport (PRD §3.1) ---

def create_weather_report_payload(report_date, **overrides) -> dict:
    defaults = {
        "region_code": REGION_OR,
        "report_date": report_date,
        "precipitation_mm": 0.0,
        "drying_index": 70,
    }
    defaults.update(overrides)
    return defaults


# --- StorageSite (PRD §3.2) ---

def create_storage_site_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Barn {n}",
        "region_code": REGION_OR,
        "capacity_tons": 500.0,
    }
    if "moisture_controlled" in overrides:
        defaults["moisture_controlled"] = overrides.pop("moisture_controlled")
    defaults.update(overrides)
    return defaults


# --- BaleLot (PRD §3.2) ---

def create_bale_lot_payload(cutting_id, storage_site_id, **overrides) -> dict:
    defaults = {
        "cutting_id": cutting_id,
        "storage_site_id": storage_site_id,
        "bale_type": "LARGE_SQUARE",
        "bale_count": 20,
        "harvested_tonnage": 10.0,
        "harvested_date": STD_HARVEST_DATE,
    }
    defaults.update(overrides)
    return defaults


# --- SpoilageEvent (PRD §3.2) ---

def create_spoilage_event_payload(bale_lot_id, **overrides) -> dict:
    defaults = {
        "bale_lot_id": bale_lot_id,
        "event_date": STD_HARVEST_DATE,
        "tons_lost": 1.0,
        "reason": "MOLD",
    }
    defaults.update(overrides)
    return defaults


# --- ForageTest (PRD §3.4) ---

def create_forage_test_payload(bale_lot_id, **overrides) -> dict:
    defaults = {
        "bale_lot_id": bale_lot_id,
        "sample_date": STD_HARVEST_DATE,
    }
    defaults.update(overrides)
    return defaults


def submit_forage_test_payload(**overrides) -> dict:
    n = _n()
    defaults = {"lab_reference": f"LAB-{n}"}
    defaults.update(overrides)
    return defaults


def record_result_payload(**overrides) -> dict:
    defaults = {"rfv": 155.0, "protein_pct": 18.0, "moisture_pct": 14.0}
    defaults.update(overrides)
    return defaults


# --- MarketIndex (PRD §3.3) ---

def create_market_index_payload(**overrides) -> dict:
    defaults = {
        "region_code": REGION_OR,
        "forage_type": "ALFALFA",
        "effective_date": "2026-05-01",
        "price_per_ton_cents": STD_INDEX_PRICE_CENTS,
    }
    defaults.update(overrides)
    return defaults


# --- Buyer (PRD §3.5) ---

def create_buyer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Buyer {n}",
        "region_code": REGION_CA_NORTH,
        "credit_limit_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


# --- FreightLane (PRD §3.3) ---

def create_freight_lane_payload(**overrides) -> dict:
    defaults = {
        "origin_region_code": REGION_OR,
        "dest_region_code": REGION_CA_NORTH,
        "distance_miles": STD_LANE_MILES,
        "rate_per_mile_cents": STD_LANE_RATE_CENTS,
        "min_charge_cents": STD_LANE_MIN_CENTS,
    }
    defaults.update(overrides)
    return defaults


# --- Quote (PRD §3.5) ---

def create_quote_payload(buyer_id, **overrides) -> dict:
    defaults = {
        "buyer_id": buyer_id,
        "forage_type": "ALFALFA",
        "quality_tier": "GOOD",
        "tons": 5.0,
        "origin_region_code": REGION_OR,
        "dest_region_code": REGION_CA_NORTH,
        "requested_delivery_by": STD_DELIVERY_BY,
    }
    defaults.update(overrides)
    return defaults


# --- DeliveryLoad (PRD §3.7) ---

def create_delivery_load_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "carrier_name": f"CARRIER-{n}",
        "capacity_tons": 25.0,
        "planned_ship_date": STD_SHIP_DATE,
    }
    defaults.update(overrides)
    return defaults


# --- LoadAllocation (PRD §3.7) ---

def create_load_allocation_payload(delivery_load_id, contract_id, bale_lot_id,
                                   expected_delivery_load_version, **overrides) -> dict:
    defaults = {
        "delivery_load_id": delivery_load_id,
        "contract_id": contract_id,
        "bale_lot_id": bale_lot_id,
        "tons": 5.0,
        "expected_delivery_load_version": expected_delivery_load_version,
    }
    defaults.update(overrides)
    return defaults


# --- BalingServiceOrder (PRD §3.9) ---

def create_baling_service_order_payload(grower_id, cutting_id, **overrides) -> dict:
    defaults = {"grower_id": grower_id, "cutting_id": cutting_id}
    defaults.update(overrides)
    return defaults


def schedule_baling_payload(**overrides) -> dict:
    defaults = {"scheduled_date": "2026-08-03", "equipment_unit": "BALER-1"}
    defaults.update(overrides)
    return defaults


def complete_baling_payload(**overrides) -> dict:
    defaults = {"actual_bale_count": 300, "baled_moisture_pct": 15.0}
    defaults.update(overrides)
    return defaults
