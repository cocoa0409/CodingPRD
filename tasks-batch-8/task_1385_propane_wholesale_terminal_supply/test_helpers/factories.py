"""Payload factories — one per entity, input fields only.

Defaults follow the PRD's named constants and the shared base scenario:
400000 gallons stocked, zone Z1 (120 one-way minutes, 8000 mc/gal, 150000
cents minimum), FIXED 90000 mc contracts, MT_BELVIEU index 95000 mc.
"""
from .constants import INDEX_BASIS, TEST_DEFAULTS as D


def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "name": "T-1",
        "region_code": "NE",
        "storage_capacity_gal": D["TERMINAL_STORAGE_GAL"],
        "reserve_floor_gal": D["RESERVE_FLOOR_GAL"],
        "winter_reserve_floor_gal": D["WINTER_RESERVE_FLOOR_GAL"],
        "rack_bay_count": D["RACK_BAY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_contract_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "supplier_name": "Upstream Supply Co",
        "contracted_volume_gal": D["SUPPLY_CONTRACTED_GAL"],
        "receipt_window_start": D["RECEIPT_WINDOW_START"],
        "receipt_window_end": D["RECEIPT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_rail_shipment_payload(supply_contract_id, **overrides) -> dict:
    defaults = {
        "supply_contract_id": supply_contract_id,
        "volume_gal": D["STOCK_GAL"],
        "railcar_count": 20,
        "scheduled_arrival_date": D["SHIPMENT_ARRIVAL_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Dealer Co",
        "credit_limit_cents": D["DEALER_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_contract_payload(dealer_id, terminal_id, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "terminal_id": terminal_id,
        "pricing_mode": "FIXED",
        "fixed_price_mc_per_gal": D["FIXED_PRICE_MC_PER_GAL"],
        "volume_committed_gal": D["CONTRACT_COMMITTED_GAL"],
        "window_start": D["CONTRACT_WINDOW_START"],
        "window_end": D["CONTRACT_WINDOW_END"],
    }
    defaults.update(overrides)
    if defaults.get("pricing_mode") == "INDEX":
        # fixed price is required iff pricing_mode == FIXED; absent on INDEX.
        defaults.pop("fixed_price_mc_per_gal", None)
    return defaults


def create_price_index_publication_payload(**overrides) -> dict:
    defaults = {
        "index_name": INDEX_BASIS,
        "effective_date": D["BASE_INDEX_EFFECTIVE_DATE"],
        "price_mc_per_gal": D["BASE_INDEX_MC_PER_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_freight_zone_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "zone_code": "Z1",
        "one_way_drive_minutes": D["ZONE_ONE_WAY_MINUTES"],
        "freight_mc_per_gal": D["ZONE_FREIGHT_MC_PER_GAL"],
        "min_freight_cents": D["ZONE_MIN_FREIGHT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "unit_number": "U-01",
        "capacity_gal": D["TRUCK_CAPACITY_GAL"],
        "weekly_hours_limit_minutes": D["TRUCK_WEEKLY_LIMIT_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_order_payload(terminal_id, freight_zone_id, requested_gal,
                                  dealer_contract_id=None, **overrides) -> dict:
    payload = {
        "terminal_id": terminal_id,
        "freight_zone_id": freight_zone_id,
        "requested_gal": requested_gal,
    }
    if dealer_contract_id is not None:
        payload["dealer_contract_id"] = dealer_contract_id
    payload.update(overrides)
    return payload


def create_cold_snap_event_payload(terminal_id, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "severity": "WARNING",
        "start_date": "2026-08-01",
        "end_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def create_allocation_run_payload(terminal_id, expected_terminal_version,
                                  **overrides) -> dict:
    payload = {
        "terminal_id": terminal_id,
        "expected_terminal_version": expected_terminal_version,
    }
    payload.update(overrides)
    return payload


def create_dealer_payment_payload(dealer_id, amount_cents, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "amount_cents": amount_cents,
        "method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def schedule_order_payload(truck_id, planned_load_start, planned_load_end,
                           **overrides) -> dict:
    payload = {
        "truck_id": truck_id,
        "planned_load_start": planned_load_start,
        "planned_load_end": planned_load_end,
    }
    payload.update(overrides)
    return payload
