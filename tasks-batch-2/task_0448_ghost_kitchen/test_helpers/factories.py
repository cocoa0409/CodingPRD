"""Payload factories — one per entity, input fields only."""


def create_stall_payload(**overrides) -> dict:
    """Stall create. Required: name, timezone, open_minute_of_day, close_minute_of_day."""
    defaults = {
        "name": "Test Stall",
        "timezone": "UTC",
        "open_minute_of_day": 0,
        "close_minute_of_day": 1440,
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload(**overrides) -> dict:
    """VirtualBrand create. Required: name, owner_email, commission_rate_bps."""
    defaults = {
        "name": "Test Brand",
        "owner_email": "brand@example.com",
        "commission_rate_bps": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(stall_id: str, brand_id: str, **overrides) -> dict:
    """KitchenLease create. Required: stall_id, brand_id, monthly_fee_cents, priority_rank."""
    defaults = {
        "stall_id": stall_id,
        "brand_id": brand_id,
        "monthly_fee_cents": 100000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(stall_id: str, **overrides) -> dict:
    """Equipment create. Required: stall_id, equipment_type. Optional: turnaround_buffer_minutes."""
    defaults = {
        "stall_id": stall_id,
        "equipment_type": "FRYER",
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(equipment_id: str, start_minute: int, end_minute: int, **overrides) -> dict:
    """Maintenance-hold EquipmentBooking create. Required: equipment_id, start_minute, end_minute."""
    defaults = {
        "equipment_id": equipment_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(brand_id: str, **overrides) -> dict:
    """MenuItem create. Required: brand_id, name, price_cents, prep_minutes, required_equipment_type."""
    defaults = {
        "brand_id": brand_id,
        "name": "Wings",
        "price_cents": 1000,
        "prep_minutes": 8,
        "required_equipment_type": "FRYER",
    }
    defaults.update(overrides)
    return defaults


def create_recipe_component_payload(**overrides) -> dict:
    """RecipeComponent create. Required: ingredient_name, quantity_grams."""
    defaults = {
        "ingredient_name": "chicken",
        "quantity_grams": 100,
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_lot_payload(stall_id: str, **overrides) -> dict:
    """IngredientLot create. Required: stall_id, ingredient_name, received_at,
    unit_cost_cents_per_gram, grams_received."""
    defaults = {
        "stall_id": stall_id,
        "ingredient_name": "chicken",
        "received_at": "2026-01-01T00:00:00Z",
        "unit_cost_cents_per_gram": 4,
        "grams_received": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(brand_id: str, line_items: list, **overrides) -> dict:
    """AggregatorOrder ingest. Required: brand_id, aggregator, external_ref, line_items.
    line_items is a list of {menu_item_id, qty} dicts."""
    defaults = {
        "brand_id": brand_id,
        "aggregator": "DOORDASH",
        "external_ref": "DD-1",
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults
