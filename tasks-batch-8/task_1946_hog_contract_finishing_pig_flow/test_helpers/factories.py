"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import CONTRACT_TERMS, DEFAULT_BARN, DEFAULT_GROUP, TEST_DEFAULTS


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Site S",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "county": TEST_DEFAULTS["COUNTY"],
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Grower G",
        "grower_code": "G-1",
        "email": "g@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(grower_id: str, site_id: str, **overrides) -> dict:
    defaults = {"grower_id": grower_id, "site_id": site_id}
    defaults.update(CONTRACT_TERMS)
    defaults.update(overrides)
    return defaults


def create_barn_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "barn_code": "B1",
        "capacity_head": DEFAULT_BARN["capacity_head"],
        "floor_space_sqft": DEFAULT_BARN["floor_space_sqft"],
    }
    defaults.update(overrides)
    return defaults


def create_pig_group_payload(barn_id: str, contract_id: str, expected_barn_version,
                             **overrides) -> dict:
    defaults = {
        "barn_id": barn_id,
        "contract_id": contract_id,
        "placement_date": DEFAULT_GROUP["placement_date"],
        "target_market_date": DEFAULT_GROUP["target_market_date"],
        "head_placed": DEFAULT_GROUP["head_placed"],
        "avg_start_weight_lbs": DEFAULT_GROUP["avg_start_weight_lbs"],
        "expected_barn_version": expected_barn_version,
    }
    defaults.update(overrides)
    return defaults


def confirm_placement_payload(**overrides) -> dict:
    return dict(overrides)


def create_mortality_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": "2026-03-05",
        "mortality_count": 1,
        "cull_count": 0,
        "reason_code": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_feed_order_payload(group_id: str, **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "phase": "STARTER",
        "diet_code": "ST-1",
        "quantity_lbs": 10000,
        "requested_delivery_date": "2026-03-05",
    }
    defaults.update(overrides)
    return defaults


def schedule_feed_order_payload(**overrides) -> dict:
    defaults = {"scheduled_delivery_date": "2026-03-05"}
    defaults.update(overrides)
    return defaults


def deliver_feed_order_payload(delivered_lbs: int, **overrides) -> dict:
    defaults = {"delivered_lbs": delivered_lbs}
    defaults.update(overrides)
    return defaults


def create_packer_slot_payload(**overrides) -> dict:
    defaults = {
        "plant_code": TEST_DEFAULTS["PLANT_CODE"],
        "slot_date": "2026-07-13",
        "shift": "AM",
        "capacity_head": 500,
        "min_weight_lbs": 240,
        "max_weight_lbs": 320,
    }
    defaults.update(overrides)
    return defaults


def create_market_load_payload(group_id: str, slot_id: str, expected_slot_version,
                               **overrides) -> dict:
    defaults = {
        "group_id": group_id,
        "slot_id": slot_id,
        "head_count": 100,
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def dispatch_load_payload(truck_wash_id: str, **overrides) -> dict:
    defaults = {"truck_wash_id": truck_wash_id}
    defaults.update(overrides)
    return defaults


def deliver_load_payload(live_weight_lbs_total: int, **overrides) -> dict:
    defaults = {"live_weight_lbs_total": live_weight_lbs_total}
    defaults.update(overrides)
    return defaults


def create_truck_wash_payload(**overrides) -> dict:
    defaults = {
        "truck_code": "T-1",
        "washed_at": "2026-07-12T08:00:00Z",
        "wash_type": "FULL_DISINFECT",
    }
    defaults.update(overrides)
    return defaults


def create_barn_wash_payload(barn_id: str, **overrides) -> dict:
    defaults = {
        "barn_id": barn_id,
        "wash_type": "FULL_DISINFECT",
        "completed_at": "2026-07-13T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_manure_plan_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "plan_year": 2026,
        "lagoon_capacity_gal": 2000000,
        "lagoon_start_gal": 1000000,
        "n_budget_lbs": 50000,
        "p_budget_lbs": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_manure_application_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "field_code": "F-1",
        "applied_at": "2026-07-15T10:00:00Z",
        "gallons": 1000,
        "n_lbs": 40,
        "p_lbs": 30,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_ticket_payload(barn_id: str, **overrides) -> dict:
    defaults = {
        "barn_id": barn_id,
        "category": "EQUIPMENT",
        "description": "feeder repair",
    }
    defaults.update(overrides)
    return defaults


def quote_ticket_payload(**overrides) -> dict:
    defaults = {"cost_cents": 30000, "cause": "WEAR"}
    defaults.update(overrides)
    return defaults


def dispute_settlement_payload(**overrides) -> dict:
    defaults = {"reason": "settlement disputed by grower"}
    defaults.update(overrides)
    return defaults


def refinalize_settlement_payload(**overrides) -> dict:
    defaults = {"adjustment_cents": 0}
    defaults.update(overrides)
    return defaults
