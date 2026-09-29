"""Payload factories - input fields only, one per resource."""
import copy

# --- Warehouses -----------------------------------------------------------

def warehouse_payload(**overrides) -> dict:
    payload = {
        "code": "TX-DAL",
        "state_code": "TX",
        "hazmat_endorsement": True,
        "storm_reserve_pct": 0.0,
        "dock_capacity_kg_per_window": 100000.0,
    }
    payload.update(overrides)
    return payload


# --- Carriers -------------------------------------------------------------

ALL_CLASSES = [
    "NON_REGULATED",
    "UN2800_EXCEPTED",
    "UN2795",
    "UN2800",
    "UN2794",
    "UN3480_SECTION_II",
    "UN3480_SECTION_IA",
]


def carrier_payload(**overrides) -> dict:
    payload = {
        "code": "HAZEX",
        "name": "Hazex Freight",
        "accepts_hazmat_classes": list(ALL_CLASSES),
        "max_lithium_watt_hours_per_package": 5000.0,
        "ground_only": True,
    }
    payload.update(overrides)
    return payload


# --- Accounts -------------------------------------------------------------

def account_payload(**overrides) -> dict:
    payload = {
        "name": "Delta Fleet",
        "account_tier": "STANDARD",
        "state_code": "TX",
        "credit_limit_cents": 100000000,
        "storm_priority_rank": 5,
    }
    payload.update(overrides)
    return payload


# --- Battery models -------------------------------------------------------

MODEL_PRESETS = {
    "IB-31-FLD": {
        "sku": "IB-31-FLD",
        "chemistry": "FLOODED_LEAD_ACID",
        "nominal_voltage": 12,
        "amp_hour_capacity": 100,
        "peukert_exponent": 1.25,
        "unit_weight_kg": 26.0,
        "lead_content_kg": 12.5,
        "core_deposit_cents": 2200,
        "list_price_cents": 18500,
        "warranty_free_replacement_months": 12,
        "warranty_prorata_months": 24,
        "shelf_life_days": 540,
        "self_discharge_pct_per_month": 6.0,
    },
    "IB-AGM-95": {
        "sku": "IB-AGM-95",
        "chemistry": "AGM",
        "nominal_voltage": 12,
        "amp_hour_capacity": 95,
        "peukert_exponent": 1.10,
        "unit_weight_kg": 28.0,
        "lead_content_kg": 13.0,
        "core_deposit_cents": 2500,
        "list_price_cents": 26000,
        "warranty_free_replacement_months": 24,
        "warranty_prorata_months": 36,
        "shelf_life_days": 730,
        "self_discharge_pct_per_month": 3.0,
    },
    "IB-IND-2V": {
        "sku": "IB-IND-2V",
        "chemistry": "FLOODED_LEAD_ACID",
        "nominal_voltage": 2,
        "amp_hour_capacity": 500,
        "peukert_exponent": 1.25,
        "unit_weight_kg": 30.0,
        "lead_content_kg": 20.0,
        "core_deposit_cents": 50000,
        "list_price_cents": 30000,
        "warranty_free_replacement_months": 12,
        "warranty_prorata_months": 24,
        "shelf_life_days": 540,
        "self_discharge_pct_per_month": 3.0,
    },
    "IB-MICRO-6": {
        "sku": "IB-MICRO-6",
        "chemistry": "AGM",
        "nominal_voltage": 6,
        "amp_hour_capacity": 7,
        "peukert_exponent": 1.10,
        "unit_weight_kg": 2.5,
        "lead_content_kg": 1.2,
        "core_deposit_cents": 500,
        "list_price_cents": 6001,
        "warranty_free_replacement_months": 12,
        "warranty_prorata_months": 12,
        "shelf_life_days": 730,
        "self_discharge_pct_per_month": 3.0,
    },
    "IB-SLF-5": {
        "sku": "IB-SLF-5",
        "chemistry": "AGM",
        "nominal_voltage": 12,
        "amp_hour_capacity": 100,
        "peukert_exponent": 1.10,
        "unit_weight_kg": 20.0,
        "lead_content_kg": 10.0,
        "core_deposit_cents": 2000,
        "list_price_cents": 20000,
        "warranty_free_replacement_months": 24,
        "warranty_prorata_months": 36,
        "shelf_life_days": 540,
        "self_discharge_pct_per_month": 5.0,
    },
    "IB-LFP-100": {
        "sku": "IB-LFP-100",
        "chemistry": "LITHIUM_IRON_PHOSPHATE",
        "nominal_voltage": 12,
        "amp_hour_capacity": 100,
        "peukert_exponent": 1.02,
        "unit_weight_kg": 13.0,
        "lead_content_kg": 0.0,
        "core_deposit_cents": 0,
        "list_price_cents": 89000,
        "warranty_free_replacement_months": 36,
        "warranty_prorata_months": 24,
        "shelf_life_days": 1095,
        "self_discharge_pct_per_month": 1.5,
    },
    "IB-PWR-2500": {
        "sku": "IB-PWR-2500",
        "chemistry": "FLOODED_LEAD_ACID",
        "nominal_voltage": 12,
        "amp_hour_capacity": 100,
        "peukert_exponent": 1.25,
        "unit_weight_kg": 26.0,
        "lead_content_kg": 12.5,
        "core_deposit_cents": 2200,
        "list_price_cents": 252273,
        "warranty_free_replacement_months": 12,
        "warranty_prorata_months": 24,
        "shelf_life_days": 540,
        "self_discharge_pct_per_month": 6.0,
    },
}


def battery_model_payload(preset: str = "IB-31-FLD", **overrides) -> dict:
    """Payload for a catalog model. `preset` names one of the known SKUs."""
    payload = copy.deepcopy(MODEL_PRESETS[preset])
    payload.update(overrides)
    return payload


# --- Inventory lots -------------------------------------------------------

def inventory_lot_payload(battery_model_id, warehouse_id, **overrides) -> dict:
    payload = {
        "battery_model_id": battery_model_id,
        "warehouse_id": warehouse_id,
        "manufactured_on": "2026-06-01",
        "quantity_on_hand": 30,
    }
    payload.update(overrides)
    return payload


# --- Orders and lines -----------------------------------------------------

def order_payload(account_id, warehouse_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "warehouse_id": warehouse_id,
        "requested_ship_date": "2026-08-10",
    }
    payload.update(overrides)
    return payload


def order_line_payload(battery_model_id, quantity=1, **overrides) -> dict:
    payload = {
        "battery_model_id": battery_model_id,
        "quantity": quantity,
        "core_expected_count": 0,
    }
    payload.update(overrides)
    return payload


# --- Shipments ------------------------------------------------------------

def shipment_payload(order_id, carrier_id, expected_order_version, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "carrier_id": carrier_id,
        "pickup_window_start": "2026-08-05T08:00:00Z",
        "pickup_window_end": "2026-08-05T18:00:00Z",
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


# --- Core returns ---------------------------------------------------------

def core_return_payload(account_id, order_id, battery_model_id, declared_core_count=1,
                        **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "order_id": order_id,
        "battery_model_id": battery_model_id,
        "declared_core_count": declared_core_count,
    }
    payload.update(overrides)
    return payload


# --- Warranty claims ------------------------------------------------------

def warranty_claim_payload(account_id, battery_model_id, serial_number,
                           installed_on="2024-08-15", failed_on="2025-08-15",
                           **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "battery_model_id": battery_model_id,
        "serial_number": serial_number,
        "installed_on": installed_on,
        "failed_on": failed_on,
    }
    payload.update(overrides)
    return payload


# --- Service contracts ----------------------------------------------------

def service_contract_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "coverage_tier": "GOLD",
        "load_watts": 2400,
        "required_runtime_minutes": 90,
        "system_voltage": 48,
        "ambient_temp_c": 10.0,
        "allowed_chemistries": ["AGM", "LITHIUM_IRON_PHOSPHATE"],
    }
    payload.update(overrides)
    return payload


# --- Storm events ---------------------------------------------------------

def storm_event_payload(**overrides) -> dict:
    payload = {
        "name": "Hurricane Ledger",
        "region_state_code": "TX",
        "severity_tier": "WARNING",
        "allocation_pool_units": 5,
    }
    payload.update(overrides)
    return payload


# --- Disposal manifests ---------------------------------------------------

def disposal_manifest_payload(warehouse_id, **overrides) -> dict:
    payload = {
        "warehouse_id": warehouse_id,
        "epa_id": "TXD988001122",
        "reporting_period": "2026-Q3",
    }
    payload.update(overrides)
    return payload
