"""Payload factories — one per entity, input fields only (PRD §3).

Each factory returns a dict with sensible defaults for all required input
fields and accepts **overrides to control individual values.
"""


# ── RentalLocation ───────────────────────────────────────────────────────
def create_location_payload(**overrides) -> dict:
    """Required: name, state_code, lot_capacity. Optional: accepts_one_way_dropoff, status."""
    defaults = {
        "name": "Test Location",
        "state_code": "CA",
        "lot_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


# ── EquipmentClass ───────────────────────────────────────────────────────
def create_equipment_class_payload(**overrides) -> dict:
    """Required: code, category, daily_rate_cents, mileage_rate_cents,
    one_way_flat_cents, fuel_capacity_gallons. Optional: requires_coverage."""
    defaults = {
        "code": "TRUCK_15",
        "category": "TRUCK",
        "daily_rate_cents": 4000,
        "mileage_rate_cents": 100,
        "one_way_flat_cents": 9900,
        "fuel_capacity_gallons": 40,
        "requires_coverage": False,
    }
    defaults.update(overrides)
    return defaults


# ── CoveragePlan ─────────────────────────────────────────────────────────
def create_coverage_plan_payload(**overrides) -> dict:
    """Required: code, daily_fee_cents, damage_deductible_cents. Optional: active."""
    defaults = {
        "code": "SAFEMOVE",
        "daily_fee_cents": 1500,
        "damage_deductible_cents": 15000,
    }
    defaults.update(overrides)
    return defaults


# ── MovingSupply ─────────────────────────────────────────────────────────
def create_supply_payload(**overrides) -> dict:
    """Required: sku, unit_price_cents, stock_qty. Optional: returnable."""
    defaults = {
        "sku": "BOX_MEDIUM",
        "unit_price_cents": 250,
        "stock_qty": 100,
    }
    defaults.update(overrides)
    return defaults


# ── Customer ─────────────────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    """Required: email, full_name. Optional: license_verified, loyalty_tier."""
    defaults = {
        "email": "test@example.com",
        "full_name": "Test Customer",
        "license_verified": True,
        "loyalty_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


# ── Equipment ────────────────────────────────────────────────────────────
def create_equipment_payload(equipment_class_id: str, home_location_id: str, **overrides) -> dict:
    """Required: equipment_class_id, home_location_id. Optional: odometer_miles, fuel_level_eighths."""
    defaults = {
        "equipment_class_id": equipment_class_id,
        "home_location_id": home_location_id,
    }
    defaults.update(overrides)
    return defaults


# ── Reservation ──────────────────────────────────────────────────────────
def create_reservation_payload(
    customer_id: str,
    equipment_class_id: str,
    pickup_location_id: str,
    dropoff_location_id: str,
    scheduled_pickup_at: str = "2026-07-01T09:00:00Z",
    scheduled_return_at: str = "2026-07-02T09:00:00Z",
    coverage_choice: str = "DECLINED",
    **overrides,
) -> dict:
    """Required: customer_id, equipment_class_id, pickup_location_id,
    dropoff_location_id, scheduled_pickup_at, scheduled_return_at.
    Optional: coverage_plan_id, coverage_choice."""
    payload = {
        "customer_id": customer_id,
        "equipment_class_id": equipment_class_id,
        "pickup_location_id": pickup_location_id,
        "dropoff_location_id": dropoff_location_id,
        "scheduled_pickup_at": scheduled_pickup_at,
        "scheduled_return_at": scheduled_return_at,
        "coverage_choice": coverage_choice,
    }
    payload.update(overrides)
    return payload


# ── SupplyLineItem ───────────────────────────────────────────────────────
def create_supply_line_payload(supply_id: str, quantity: int = 1, **overrides) -> dict:
    """Required: supply_id, quantity."""
    defaults = {"supply_id": supply_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


# ── EquipmentAddOn ───────────────────────────────────────────────────────
def create_addon_payload(addon_type: str = "UTILITY_DOLLY", quantity: int = 1, **overrides) -> dict:
    """Required: addon_type, quantity."""
    defaults = {"addon_type": addon_type, "quantity": quantity}
    defaults.update(overrides)
    return defaults


# ── DamageReport ─────────────────────────────────────────────────────────
def create_damage_report_payload(assessed_cost_cents: int = 50000,
                                 description: str = "Assessed damage", **overrides) -> dict:
    """Required: assessed_cost_cents, description."""
    defaults = {"assessed_cost_cents": assessed_cost_cents, "description": description}
    defaults.update(overrides)
    return defaults


# ── DropOffTransfer ──────────────────────────────────────────────────────
def create_transfer_payload(equipment_id: str, to_location_id: str,
                            reason: str = "FLEET_REBALANCE", **overrides) -> dict:
    """Required: equipment_id, to_location_id, reason."""
    defaults = {
        "equipment_id": equipment_id,
        "to_location_id": to_location_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


# ── Contract return / settle / dispatch ──────────────────────────────────
def return_payload(return_odometer_miles: int, return_fuel_eighths: int,
                   actual_return_at: str, **overrides) -> dict:
    """Required: return_odometer_miles, return_fuel_eighths, actual_return_at."""
    defaults = {
        "return_odometer_miles": return_odometer_miles,
        "return_fuel_eighths": return_fuel_eighths,
        "actual_return_at": actual_return_at,
    }
    defaults.update(overrides)
    return defaults


def dispatch_payload(expected_reservation_version: int, **overrides) -> dict:
    """Required: expected_reservation_version (OCC field, §2.10)."""
    defaults = {"expected_reservation_version": expected_reservation_version}
    defaults.update(overrides)
    return defaults


def settle_payload(expected_contract_version: int, **overrides) -> dict:
    """Required: expected_contract_version (OCC field, §2.10)."""
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults
