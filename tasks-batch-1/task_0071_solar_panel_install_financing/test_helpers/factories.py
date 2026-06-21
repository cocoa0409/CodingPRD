"""Payload factories — one per entity, input fields only."""


def create_homeowner_payload(**overrides) -> dict:
    defaults = {
        "email": "homeowner@example.com",
        "full_name": "Test Homeowner",
        "state_code": "CA",
        "annual_kwh_usage": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_installer_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test SunCo",
        "licensed_states": ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_utility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Utility",
        "state_code": "CA",
        "feeder_headroom_kw": 1000.0,
        "net_metering_rate_cents_per_kwh": 15.0,
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "firm_name": "Test Broker",
        "broker_fee_pct": 0.04,
        "operating_states": ["CA"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "roof_area_sqft": 700,
    }
    defaults.update(overrides)
    return defaults


def assess_payload(**overrides) -> dict:
    defaults = {
        "shading_factor": 0.10,
        "peak_sun_hours": 5.0,
    }
    defaults.update(overrides)
    return defaults


def design_payload(**overrides) -> dict:
    defaults = {
        "gross_system_cost_cents": 3000000,
    }
    defaults.update(overrides)
    return defaults


def create_financing_plan_payload(model="LEASE", **overrides) -> dict:
    defaults = {"model": model, "term_years": 20}
    if model == "LEASE":
        defaults["lease_monthly_cents"] = 8500
    elif model == "LOAN":
        defaults["term_years"] = 10
        defaults["loan_principal_cents"] = 2500000
        defaults["loan_apr"] = 0.06
    elif model == "PPA":
        defaults["ppa_rate_cents_per_kwh"] = 12.5
        defaults["ppa_escalator_pct"] = 0.029
    defaults.update(overrides)
    return defaults


def create_interconnection_application_payload(**overrides) -> dict:
    defaults = {
        "requested_export_kw": 7.0,
    }
    defaults.update(overrides)
    return defaults


def create_net_meter_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-01-01T00:00:00.000Z",
        "period_end": "2026-02-01T00:00:00.000Z",
        "kwh_produced": 900,
        "kwh_consumed": 600,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(claim_type="EQUIPMENT_DEFECT", **overrides) -> dict:
    defaults = {"claim_type": claim_type}
    if claim_type == "PRODUCTION_SHORTFALL":
        defaults["claimed_window_start"] = "2026-01-01T00:00:00.000Z"
        defaults["claimed_window_end"] = "2026-02-01T00:00:00.000Z"
    defaults.update(overrides)
    return defaults
