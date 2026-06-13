"""Payload factories — one per entity, input fields only (PRD-exact names)."""
from .constants import DEFAULT_PRICING_POLICY, DEFAULT_LOCKER_BAND


def create_customer_payload(**overrides) -> dict:
    """Required: full_name, phone. Optional: loyalty_tier (defaults STANDARD)."""
    payload = {"full_name": "Test Customer", "phone": "555-0000"}
    payload.update(overrides)
    return payload


def create_cut_type_payload(**overrides) -> dict:
    """Required: code, species, base_price_cents_per_kg.
    Optional: is_grind (default false), requires_dry_age (default false)."""
    payload = {"code": "RIBEYE", "species": "BEEF", "base_price_cents_per_kg": 4000}
    payload.update(overrides)
    return payload


def create_pricing_policy_payload(**overrides) -> dict:
    """All six rate/threshold fields are required."""
    payload = dict(DEFAULT_PRICING_POLICY)
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(**overrides) -> dict:
    """Required: cut_type_id, received_weight_g.
    Optional: aging_target_days (default 0), source_share_id (default null)."""
    payload = {"received_weight_g": 5000}
    payload.update(overrides)
    return payload


def create_locker_payload(**overrides) -> dict:
    """Required: name, capacity_g, min_temp_c, max_temp_c."""
    payload = {"name": "LOCKER-A", "capacity_g": 20000}
    payload.update(DEFAULT_LOCKER_BAND)
    payload.update(overrides)
    return payload


def create_temp_reading_payload(**overrides) -> dict:
    """Required: temp_c, reading_at."""
    payload = {"temp_c": 2.0, "reading_at": "2026-06-02T00:00:00Z"}
    payload.update(overrides)
    return payload


def create_animal_share_payload(**overrides) -> dict:
    """Required: species, carcass_weight_g, deposit_cents."""
    payload = {"species": "BEEF", "carcass_weight_g": 100000, "deposit_cents": 8000}
    payload.update(overrides)
    return payload


def create_share_claim_payload(**overrides) -> dict:
    """Required: animal_share_id, customer_id, fraction."""
    payload = {"fraction": "QUARTER"}
    payload.update(overrides)
    return payload


def create_holiday_window_payload(**overrides) -> dict:
    """Required: name, pickup_date, capacity_g, cutoff_at."""
    payload = {
        "name": "THANKSGIVING_2026",
        "pickup_date": "2026-11-26T00:00:00Z",
        "capacity_g": 100000,
        "cutoff_at": "2026-11-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_custom_order_payload(**overrides) -> dict:
    """Required: customer_id, order_kind, lines.
    Optional (HOLIDAY only): holiday_window_id, pickup_date."""
    payload = {"order_kind": "STANDARD", "lines": []}
    payload.update(overrides)
    return payload


def order_line_payload(cut_type_id, ordered_weight_g) -> dict:
    """One entry in a custom order's lines array. Input fields only."""
    return {"cut_type_id": cut_type_id, "ordered_weight_g": ordered_weight_g}


def create_sausage_batch_payload(**overrides) -> dict:
    """Required: recipe_name, output_cut_type_id, planned_output_g."""
    payload = {"recipe_name": "Test Recipe", "planned_output_g": 5000}
    payload.update(overrides)
    return payload


def add_batch_input_payload(**overrides) -> dict:
    """Required: inventory_lot_id, weight_g."""
    payload = {}
    payload.update(overrides)
    return payload
