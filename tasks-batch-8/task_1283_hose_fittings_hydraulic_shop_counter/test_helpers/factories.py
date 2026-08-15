"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "HOSE_SKU": "PARK-387-8",
    "HOSE_DIAMETER_IN": 0.5,
    "WORKING_PRESSURE_PSI": 3000,
    "PRICE_PER_METER_CENTS": 800,
    "INITIAL_LENGTH_MM": 50000,
    "COUPLING_SKU": "1CA43-8-8",
    "COUPLING_SIZE_IN": 0.5,
    "COUPLING_UNIT_PRICE_CENTS": 1200,
    "COUPLING_INITIAL_ON_HAND": 10,
    "ASSET_TAG": "EX-100",
    "MACHINE_TYPE": "excavator",
    "CUT_LENGTH_MM": 1000,
    "REQUIRED_WP_PSI": 2000,
    "CRIMP_SPEC_MM": 25.0,
    "ESTIMATED_LABOR_MINUTES": 10,
    "VAN_ID": "VAN-1",
    "WINDOW_START": "2026-08-02T09:00:00Z",
    "WINDOW_END": "2026-08-02T10:00:00Z",
    "INSPECTION_WINDOW_START": "2026-08-10T00:00:00Z",
    "INSPECTION_WINDOW_END": "2026-08-11T00:00:00Z",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["CUSTOMER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_equipment_asset_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "machine_type": DEFAULTS["MACHINE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_reel_payload(**overrides) -> dict:
    defaults = {
        "hose_sku": DEFAULTS["HOSE_SKU"],
        "hose_diameter_in": DEFAULTS["HOSE_DIAMETER_IN"],
        "working_pressure_psi": DEFAULTS["WORKING_PRESSURE_PSI"],
        "price_per_meter_cents": DEFAULTS["PRICE_PER_METER_CENTS"],
        "initial_length_mm": DEFAULTS["INITIAL_LENGTH_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_coupling_payload(**overrides) -> dict:
    defaults = {
        "coupling_sku": DEFAULTS["COUPLING_SKU"],
        "size_in": DEFAULTS["COUPLING_SIZE_IN"],
        "unit_price_cents": DEFAULTS["COUPLING_UNIT_PRICE_CENTS"],
        "initial_on_hand_qty": DEFAULTS["COUPLING_INITIAL_ON_HAND"],
    }
    defaults.update(overrides)
    return defaults


def create_assembly_order_payload(customer_id: str, reel_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "reel_id": reel_id,
        "cut_length_mm": DEFAULTS["CUT_LENGTH_MM"],
        "required_working_pressure_psi": DEFAULTS["REQUIRED_WP_PSI"],
        "crimp_diameter_spec_mm": DEFAULTS["CRIMP_SPEC_MM"],
        "estimated_labor_minutes": DEFAULTS["ESTIMATED_LABOR_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(expected_equipment_asset_version, window_start=None,
                              window_end=None, **overrides) -> dict:
    defaults = {
        "expected_equipment_asset_version": expected_equipment_asset_version,
        "scheduled_window_start": window_start or DEFAULTS["INSPECTION_WINDOW_START"],
        "scheduled_window_end": window_end or DEFAULTS["INSPECTION_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_service_dispatch_payload(customer_id: str, van_id: str = None,
                                    **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "van_id": van_id or DEFAULTS["VAN_ID"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults
