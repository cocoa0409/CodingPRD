"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "ADDRESS": "100 Test St",
    "OWNER_NAME": "Owner of Record",
    "OCCUPANCY": "BUSINESS",
    "CONSTRUCTION": "TYPE_II",
    "FLOOR_AREA": 5000,
    "STORIES": 1,
    "PERMIT_TYPE": "CONSTRUCTION",
    "VALUATION_CENTS": 100080,
    "SCOPE_AREA": 5000,
    "LOCATION_DESC": "hydrant location",
    "MAIN_SIZE": 8,
}


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address": DEFAULTS["ADDRESS"],
        "owner_name": DEFAULTS["OWNER_NAME"],
        "occupancy_classification": DEFAULTS["OCCUPANCY"],
        "construction_type": DEFAULTS["CONSTRUCTION"],
        "total_floor_area_sqft": DEFAULTS["FLOOR_AREA"],
        "stories": DEFAULTS["STORIES"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_application_payload(property_id, applicant_user_id="app-1", **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "applicant_user_id": applicant_user_id,
        "permit_type": DEFAULTS["PERMIT_TYPE"],
        "project_valuation_cents": DEFAULTS["VALUATION_CENTS"],
        "scope_area_sqft": DEFAULTS["SCOPE_AREA"],
    }
    defaults.update(overrides)
    return defaults


def discipline_decision_payload(discipline, decision, **overrides) -> dict:
    defaults = {"discipline": discipline, "decision": decision}
    defaults.update(overrides)
    return defaults


def pay_fee_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_permit_payload(application_id, **overrides) -> dict:
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_certificate_payload(property_id, **overrides) -> dict:
    defaults = {"property_id": property_id}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(property_id, inspection_type="PERIODIC",
                              scheduled_date="2026-03-05T00:00:00Z", **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "inspection_type": inspection_type,
        "scheduled_date": scheduled_date,
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(result, findings=None, **overrides) -> dict:
    defaults = {"result": result}
    if findings is not None:
        defaults["findings"] = findings
    defaults.update(overrides)
    return defaults


def finding(code_section, severity) -> dict:
    return {"code_section": code_section, "severity": severity}


def abatement_order_payload(expected_violation_version, **overrides) -> dict:
    defaults = {"expected_violation_version": expected_violation_version}
    defaults.update(overrides)
    return defaults


def create_hydrant_payload(property_id, location_desc=None, main_size_inches=None, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "location_desc": location_desc or DEFAULTS["LOCATION_DESC"],
        "main_size_inches": main_size_inches if main_size_inches is not None else DEFAULTS["MAIN_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_flow_test_payload(hydrant_id, test_date="2026-03-01T00:00:00Z",
                             static_psi=70, residual_psi=50, measured_flow_gpm=1500, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "test_date": test_date,
        "static_psi": static_psi,
        "residual_psi": residual_psi,
        "measured_flow_gpm": measured_flow_gpm,
    }
    defaults.update(overrides)
    return defaults
