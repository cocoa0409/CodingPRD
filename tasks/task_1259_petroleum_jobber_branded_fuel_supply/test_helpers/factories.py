"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PRODUCT_CODE": "REGULAR_87",
    "PRODUCT_NAME": "Regular 87",
    "CATEGORY": "GASOLINE",
    "FED_EXCISE_GAS": 184,
    "FED_EXCISE_DSL": 244,
    "TEMP_COEFF_GAS": 0.00065,
    "TEMP_COEFF_DSL": 0.00040,
    "STATION_NAME": "Test Station",
    "STATE_CODE": "TX",
    "HOME_TERMINAL": "TX-NORTH",
    "STATE_EXCISE": 200,
    "CREDIT_LIMIT": 100_000_000,
    "TERM_START": "2026-01-01",
    "TERM_END": "2026-12-31",
    "COMMITTED_GALLONS": 100_000,
    "IMAGING_ALLOWANCE": 100_000,
    "MARGIN_TC": 25,
    "SHORTFALL_TC": 20,
    "BUYOUT_METHOD": "LOST_MARGIN",
    "EFFECTIVE_DATE": "2026-05-01",
    "PRICE_TC": 2000,
    "TANK_CAPACITY": 20_000,
    "OPENING_PHYSICAL": 0,
    "TRUCK_CODE": "TRK-1",
    "TRUCK_CAPACITY": 12_000,
    "PLANNED_GALLONS": 1000,
    "WINDOW_START": "2026-05-02T08:00:00Z",
    "WINDOW_END": "2026-05-02T12:00:00Z",
    "PERIOD_START": "2026-05-01",
    "PERIOD_END": "2026-05-31",
    "AUDIT_DATE": "2026-05-10",
    "AUDIT_SCORE": 80,
    "LOSS_OCCURRED_AT": "2026-05-03T09:00:00Z",
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "display_name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["CATEGORY"],
        "federal_excise_tc_per_gal": DEFAULTS["FED_EXCISE_GAS"],
        "temp_coeff": DEFAULTS["TEMP_COEFF_GAS"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_station_payload(**overrides) -> dict:
    defaults = {
        "station_name": DEFAULTS["STATION_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "home_terminal_code": DEFAULTS["HOME_TERMINAL"],
        "state_excise_tc_per_gal": DEFAULTS["STATE_EXCISE"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_agreement_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "committed_gallons": DEFAULTS["COMMITTED_GALLONS"],
        "imaging_allowance_cents": DEFAULTS["IMAGING_ALLOWANCE"],
        "margin_tc_per_gal": DEFAULTS["MARGIN_TC"],
        "shortfall_penalty_tc_per_gal": DEFAULTS["SHORTFALL_TC"],
        "buyout_method": DEFAULTS["BUYOUT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_rack_price_posting_payload(**overrides) -> dict:
    defaults = {
        "terminal_code": DEFAULTS["HOME_TERMINAL"],
        "product_id": None,
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "price_tc_per_gal": DEFAULTS["PRICE_TC"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_tank_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "product_id": None,
        "capacity_gallons": DEFAULTS["TANK_CAPACITY"],
        "opening_physical_gallons": DEFAULTS["OPENING_PHYSICAL"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {
        "truck_code": DEFAULTS["TRUCK_CODE"],
        "capacity_gallons": DEFAULTS["TRUCK_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_transport_drop_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "tank_id": None,
        "truck_id": None,
        "product_id": None,
        "planned_gallons": DEFAULTS["PLANNED_GALLONS"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(**overrides) -> dict:
    defaults = {
        "tank_id": None,
        "reading_at": "2026-05-01T08:00:00Z",
        "totalizer_gallons": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_loss_event_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "loss_type": "SPILL",
        "gallons": 100,
        "occurred_at": DEFAULTS["LOSS_OCCURRED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_inventory_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_eft_draft_payload(**overrides) -> dict:
    defaults = {
        "invoice_id": None,
        "scheduled_date": "2026-05-10",
    }
    defaults.update(overrides)
    return defaults


def create_tax_remittance_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_brand_compliance_audit_payload(**overrides) -> dict:
    defaults = {
        "station_id": None,
        "audit_date": DEFAULTS["AUDIT_DATE"],
        "score": DEFAULTS["AUDIT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_set_clock_payload(to_iso8601: str = "2026-05-01T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
