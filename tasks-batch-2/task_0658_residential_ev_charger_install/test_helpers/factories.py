"""Payload factories — one per entity, input fields only.

Default values keep the happy-path consistent across fixtures: a CA property on a
200A panel in the PGE territory, scoping a 40A-circuit charger that fits.
"""

DEFAULTS = {
    "STATE_CODE": "CA",
    "UTILITY_TERRITORY": "PGE",
    "MAIN_BREAKER_AMPS": 200,
    "FLOOR_AREA_SQFT": 1800,
    "JURISDICTION_CODE": "AHJ1",
}


def create_homeowner_payload(**overrides) -> dict:
    # `email` is intentionally NOT defaulted here: it is a unique key, and the atomic
    # creator in fixtures.py supplies a per-call unique value via setdefault. Hardcoding
    # a default would defeat that and collide whenever two homeowners are created.
    defaults = {
        "full_name": "Test Homeowner",
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(homeowner_id: str, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "address_line": "1 Test St",
        "state_code": DEFAULTS["STATE_CODE"],
        "utility_territory_code": DEFAULTS["UTILITY_TERRITORY"],
        "main_breaker_amps": DEFAULTS["MAIN_BREAKER_AMPS"],
        "floor_area_sqft": DEFAULTS["FLOOR_AREA_SQFT"],
    }
    defaults.update(overrides)
    return defaults


def create_charger_product_payload(**overrides) -> dict:
    # `sku` is intentionally NOT defaulted here: it is a unique key, and the atomic
    # creator in fixtures.py supplies a per-call unique value via setdefault. Hardcoding
    # a default would defeat that and collide whenever two products are created.
    defaults = {
        "name": "Charger 40",
        "rated_amps": 32,
        "required_circuit_amps": 40,
        "msrp_cents": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_electrician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Electrician",
        "license_state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(property_id: str, charger_product_sku: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "charger_product_sku": charger_product_sku,
    }
    defaults.update(overrides)
    return defaults


def create_site_assessment_payload(property_id: str, install_job_id: str,
                                    assessment_method: str = "LOAD_STUDY_220_87",
                                    **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "install_job_id": install_job_id,
        "assessment_method": assessment_method,
        "declared_fixed_appliance_va": 0,
        "max_measured_demand_va": 7200,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(install_job_id: str, labor_cents: int = 120000,
                         parts_line_cents=None, **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "labor_cents": labor_cents,
        "parts_line_cents": parts_line_cents if parts_line_cents is not None else [60000, 5000],
    }
    defaults.update(overrides)
    return defaults


def create_permit_application_payload(install_job_id: str, **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_interconnection_request_payload(install_job_id: str,
                                           utility_territory_code: str = "PGE",
                                           requested_load_amps: int = 32, **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "utility_territory_code": utility_territory_code,
        "requested_load_amps": requested_load_amps,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_assignment_payload(install_job_id: str, electrician_id: str,
                                       window_date: str = "2026-05-01T00:00:00Z",
                                       window_start_minute: int = 540,
                                       window_end_minute: int = 720, **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "electrician_id": electrician_id,
        "window_date": window_date,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
    }
    defaults.update(overrides)
    return defaults


def create_incentive_claim_payload(install_job_id: str, program_kind: str,
                                   eligible_cost_cents: int, **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "program_kind": program_kind,
        "eligible_cost_cents": eligible_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_ticket_payload(install_job_id: str, summary: str = "defect", **overrides) -> dict:
    defaults = {
        "install_job_id": install_job_id,
        "summary": summary,
    }
    defaults.update(overrides)
    return defaults
