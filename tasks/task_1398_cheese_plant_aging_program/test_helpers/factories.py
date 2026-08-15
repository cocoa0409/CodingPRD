"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "PLANT_NAME": "Test Plant",
    "LICENSE_NUMBER": "WI-500",
    "VAT_CODE": "VAT-1",
    "VAT_CAPACITY_LITERS": 20000,
    "HAULER_TICKET": "HT-1",
    "RECEIVED_AT": "2026-08-01T01:00:00Z",
    "VOLUME_LITERS": 5000.0,
    "FAT_PCT": 3.7,
    "PROTEIN_PCT": 3.0,
    "SCC": 100000,
    "CULTURE_LOT_NO": "CUL-1",
    "COAGULANT_LOT_NO": "COA-1",
    "LOT_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "CULTURE_QTY": 100.0,
    "COAGULANT_QTY": 5000.0,
    "MAKE_START": "2026-08-01T02:00:00Z",
    "MAKE_END": "2026-08-01T06:00:00Z",
    "LITERS_COMMITTED": 5000.0,
    "CULTURE_UNITS": 5.0,
    "COAGULANT_ML": 250.0,
    "GREEN_WEIGHT_KG": 500.0,
    "WHEELS_PRODUCED": 4,
    "ROOM_CODE": "RM-1",
    "ROOM_CAPACITY": 100,
    "ROOM_TEMP_C": 10.0,
    "ROOM_HUMIDITY": 85.0,
    "CUSTOMER_NAME": "Customer",
    "DESTINATION_COUNTRY": "DE",
    "CONSIGNEE": "Foreign Buyer",
}


def create_plant_payload(**overrides):
    defaults = {
        "name": DEFAULTS["PLANT_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_milk_intake_payload(**overrides):
    defaults = {
        "hauler_ticket": DEFAULTS["HAULER_TICKET"],
        "received_at": DEFAULTS["RECEIVED_AT"],
        "volume_liters": DEFAULTS["VOLUME_LITERS"],
        "fat_pct": DEFAULTS["FAT_PCT"],
        "protein_pct": DEFAULTS["PROTEIN_PCT"],
        "somatic_cell_count": DEFAULTS["SCC"],
    }
    defaults.update(overrides)
    return defaults


def create_vat_payload(**overrides):
    defaults = {
        "code": DEFAULTS["VAT_CODE"],
        "capacity_liters": DEFAULTS["VAT_CAPACITY_LITERS"],
    }
    defaults.update(overrides)
    return defaults


def create_additive_lot_payload(**overrides):
    defaults = {
        "kind": "CULTURE",
        "supplier_lot_no": DEFAULTS["CULTURE_LOT_NO"],
        "expires_at": DEFAULTS["LOT_EXPIRES_AT"],
        "quantity_initial": DEFAULTS["CULTURE_QTY"],
    }
    defaults.update(overrides)
    return defaults


def create_make_sheet_payload(**overrides):
    defaults = {
        "variety": "MUENSTER",
        "scheduled_start": DEFAULTS["MAKE_START"],
        "scheduled_end": DEFAULTS["MAKE_END"],
        "liters_committed": DEFAULTS["LITERS_COMMITTED"],
        "culture_units_planned": DEFAULTS["CULTURE_UNITS"],
        "coagulant_ml_planned": DEFAULTS["COAGULANT_ML"],
    }
    defaults.update(overrides)
    return defaults


def complete_make_payload(**overrides):
    defaults = {
        "green_weight_kg": DEFAULTS["GREEN_WEIGHT_KG"],
        "wheels_produced": DEFAULTS["WHEELS_PRODUCED"],
    }
    defaults.update(overrides)
    return defaults


def create_aging_room_payload(**overrides):
    defaults = {
        "code": DEFAULTS["ROOM_CODE"],
        "capacity_wheels": DEFAULTS["ROOM_CAPACITY"],
        "temp_c": DEFAULTS["ROOM_TEMP_C"],
        "humidity_pct": DEFAULTS["ROOM_HUMIDITY"],
    }
    defaults.update(overrides)
    return defaults


def create_aging_unit_payload(**overrides):
    defaults = {
        "wheel_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_grading_event_payload(**overrides):
    defaults = {
        "moisture_pct": 40.0,
        "fat_dry_basis_pct": 50.0,
        "body_score": 9,
        "flavor_score": 9,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_order_payload(**overrides):
    defaults = {
        "channel": "PRIVATE_LABEL",
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "wheels_requested": 1,
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cut_wrap_run_payload(**overrides):
    defaults = {
        "wheels_in": 1,
        "finished_case_weight_kg": 2.7,
        "trim_waste_kg": 0.25,
    }
    defaults.update(overrides)
    return defaults


def create_export_certificate_payload(**overrides):
    defaults = {
        "destination_country": DEFAULTS["DESTINATION_COUNTRY"],
        "consignee": DEFAULTS["CONSIGNEE"],
    }
    defaults.update(overrides)
    return defaults
