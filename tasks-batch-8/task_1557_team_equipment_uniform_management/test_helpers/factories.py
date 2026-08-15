"""Payload factories — one per creatable resource, input fields only."""
from .constants import DEFAULT_SEASON


def create_player_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Player",
        "position_group": "OFFENSE",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_pool_payload(**overrides) -> dict:
    defaults = {
        "season_label": DEFAULT_SEASON,
        "garment_type": "GAME_JERSEY",
        "size_code": "M",
        "stock_on_hand": 5,
        "reorder_point": 0,
        "reorder_batch_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_supplier_contract_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "Test Vendor",
        "season_label": DEFAULT_SEASON,
        "start_on": "2026-06-01",
        "end_on": "2027-05-31",
        "allocation_caps": [{"garment_type": "GAME_JERSEY", "max_units": 50}],
        "default_lead_time_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_kit_order_payload(supplier_contract_id, **overrides) -> dict:
    defaults = {
        "supplier_contract_id": supplier_contract_id,
        "lines": [
            {
                "garment_type": "GAME_JERSEY",
                "size_code": "M",
                "quantity": 1,
                "unit_price_cents": 5000,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_kit_assignment_payload(player_id, jersey_pool_id, pants_pool_id,
                                  **overrides) -> dict:
    defaults = {
        "player_id": player_id,
        "season_label": DEFAULT_SEASON,
        "jersey_number": 1,
        "jersey_pool_id": jersey_pool_id,
        "pants_pool_id": pants_pool_id,
    }
    defaults.update(overrides)
    return defaults


def create_gear_item_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": "TAG-0001",
        "item_type": "HELMET",
        "size_spec": "HELMET-L",
        "acquired_on": "2025-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_reconditioning_job_payload(item_id, **overrides) -> dict:
    defaults = {
        "item_id": item_id,
        "provider_name": "RCOA",
        "sent_on": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_game_event_payload(**overrides) -> dict:
    defaults = {
        "season_label": DEFAULT_SEASON,
        "opponent_name": "Tigers",
        "kickoff_at": "2026-09-05T15:00:00Z",
        "designated_kit": "HOME",
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(player_id, **overrides) -> dict:
    defaults = {
        "player_id": player_id,
        "claim_type": "DAMAGED",
        "base_value_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_disposition_case_payload(**overrides) -> dict:
    defaults = {
        "season_label": DEFAULT_SEASON,
        "garment_type": "GAME_JERSEY",
        "method": "DONATE",
    }
    defaults.update(overrides)
    return defaults
