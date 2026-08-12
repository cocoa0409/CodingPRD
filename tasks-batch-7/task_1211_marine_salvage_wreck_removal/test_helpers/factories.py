"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "VESSEL_NAME": "MV Test",
    "CASUALTY_TYPE": "GROUNDING",
    "DECLARED_SALVED_VALUE_CENTS": 200_000_000,
    "POSITION": "10S 140W",
    "POLLUTION_RISK_TIER": "TIER_1",
    "ESTIMATED_COST_CENTS": 1_000_000,
    "METHOD": "REFLOAT",
    "EQUIPMENT_CLASSES": ["TUG"],
    "FORM": "NO_CURE_NO_PAY",
    "LODGED_AMOUNT_CENTS": 30_000_000,
    "AGENCY_TYPE": "COAST_GUARD",
    "VALID_FROM": "2026-05-01T00:00:00Z",
    "VALID_TO": "2026-06-30T00:00:00Z",
    "ASSET_CLASS": "TUG",
    "DAY_RATE_CENTS": 2_000_000,
    "MAX_HS_METERS": 2.50,
    "CHARTER_WINDOW_START": "2026-05-10T00:00:00Z",
    "CHARTER_WINDOW_END": "2026-05-24T00:00:00Z",
    "WEATHER_WINDOW_START": "2026-05-08T00:00:00Z",
    "WEATHER_WINDOW_END": "2026-05-26T00:00:00Z",
    "FORECAST_HS_METERS": 2.00,
    "PHASE_TYPE": "REFLOAT",
    "PLANNED_DURATION_HOURS": 96,
    "POLLUTANT_CLASS": "DEBRIS",
    "EVENT_TIER": "TIER_1",
    "EST_VOLUME_M3": 2,
    "PROPERTY_TYPE": "CARGO",
    "QUANTITY_TONNES": 50,
    "DECLARED_VALUE_CENTS": 9_000_000,
    "SITE_NAME": "Yard A",
    "CAPACITY_TONNES": 1000,
    "ENTRY_TYPE": "DAILY_LOG",
    "ENTRY_DATE": "2026-05-11T00:00:00Z",
    "SUMMARY": "log entry",
}


def create_casualty_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": DEFAULTS["VESSEL_NAME"],
        "casualty_type": DEFAULTS["CASUALTY_TYPE"],
        "declared_salved_value_cents": DEFAULTS["DECLARED_SALVED_VALUE_CENTS"],
        "position": DEFAULTS["POSITION"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(casualty_id, expected_casualty_version, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "expected_casualty_version": expected_casualty_version,
        "pollution_risk_tier": DEFAULTS["POLLUTION_RISK_TIER"],
        "wreck_removal_required": False,
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(casualty_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "method": DEFAULTS["METHOD"],
        "required_equipment_classes": list(DEFAULTS["EQUIPMENT_CLASSES"]),
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(casualty_id, plan_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "plan_id": plan_id,
        "form": DEFAULTS["FORM"],
        "scopic_clause_included": False,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(expected_contract_version, **overrides) -> dict:
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults


def create_security_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "lodged_amount_cents": DEFAULTS["LODGED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_disburse_payload(mode, amount_cents) -> dict:
    return {"mode": mode, "amount_cents": amount_cents}


def create_permit_payload(casualty_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "agency_type": DEFAULTS["AGENCY_TYPE"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_to": DEFAULTS["VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "day_rate_cents": DEFAULTS["DAY_RATE_CENTS"],
        "max_hs_meters": DEFAULTS["MAX_HS_METERS"],
    }
    defaults.update(overrides)
    return defaults


def create_charter_payload(casualty_id, equipment_asset_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "equipment_asset_id": equipment_asset_id,
        "window_start": DEFAULTS["CHARTER_WINDOW_START"],
        "window_end": DEFAULTS["CHARTER_WINDOW_END"],
        "purpose": DEFAULTS.get("PURPOSE", "SALVAGE"),
    }
    defaults.update(overrides)
    return defaults


def create_weather_window_payload(casualty_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "window_start": DEFAULTS["WEATHER_WINDOW_START"],
        "window_end": DEFAULTS["WEATHER_WINDOW_END"],
        "forecast_hs_meters": DEFAULTS["FORECAST_HS_METERS"],
    }
    defaults.update(overrides)
    return defaults


def create_phase_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "phase_type": DEFAULTS["PHASE_TYPE"],
        "planned_duration_hours": DEFAULTS["PLANNED_DURATION_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_phase_activation_payload(weather_window_id, charter_ids) -> dict:
    return {"weather_window_id": weather_window_id, "charter_ids": charter_ids}


def create_pollution_event_payload(casualty_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "pollutant_class": DEFAULTS["POLLUTANT_CLASS"],
        "tier": DEFAULTS["EVENT_TIER"],
        "est_volume_m3": DEFAULTS["EST_VOLUME_M3"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(casualty_id, **overrides) -> dict:
    defaults = {
        "casualty_id": casualty_id,
        "property_type": DEFAULTS["PROPERTY_TYPE"],
        "quantity_tonnes": DEFAULTS["QUANTITY_TONNES"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "capacity_tonnes": DEFAULTS["CAPACITY_TONNES"],
    }
    defaults.update(overrides)
    return defaults


def create_doc_pack_payload(contract_id) -> dict:
    return {"contract_id": contract_id}


def create_doc_entry_payload(ref_id, **overrides) -> dict:
    defaults = {
        "entry_type": DEFAULTS["ENTRY_TYPE"],
        "ref_id": ref_id,
        "entry_date": DEFAULTS["ENTRY_DATE"],
        "summary": DEFAULTS["SUMMARY"],
    }
    defaults.update(overrides)
    return defaults
