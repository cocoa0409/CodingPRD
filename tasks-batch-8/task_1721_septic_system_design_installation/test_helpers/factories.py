"""Payload factories — one per creatable resource, input fields only."""

from .constants import TEST_DEFAULTS as D


def create_installer_company_payload(**overrides) -> dict:
    defaults = {
        "legal_name": D["LEGAL_NAME"],
        "license_number": D["COMPANY_LICENSE"],
        "county_codes": list(D["COUNTY_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_soil_scientist_payload(**overrides) -> dict:
    defaults = {"full_name": D["SCIENTIST_NAME"], "license_number": D["SCIENTIST_LICENSE"]}
    defaults.update(overrides)
    return defaults


def create_system_designer_payload(**overrides) -> dict:
    defaults = {"full_name": D["DESIGNER_NAME"], "license_number": D["DESIGNER_LICENSE"]}
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {"full_name": D["INSPECTOR_NAME"], "license_number": D["INSPECTOR_LICENSE"]}
    defaults.update(overrides)
    return defaults


def create_health_officer_payload(**overrides) -> dict:
    defaults = {"full_name": D["OFFICER_NAME"], "badge_number": D["OFFICER_BADGE"]}
    defaults.update(overrides)
    return defaults


def create_project_manager_payload(**overrides) -> dict:
    defaults = {"full_name": D["MANAGER_NAME"], "employee_number": D["MANAGER_EMPLOYEE"]}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": D["CUSTOMER_NAME"],
        "email": D["CUSTOMER_EMAIL"],
        "phone": D["CUSTOMER_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "parcel_id": D["PARCEL_ID"],
        "address_line": D["ADDRESS_LINE"],
        "county_code": D["COUNTY_CODE"],
        "high_water_table": False,
    }
    defaults.update(overrides)
    return defaults


def advance_clock_payload(by_periods=1, **overrides) -> dict:
    defaults = {"by_periods": by_periods}
    defaults.update(overrides)
    return defaults


def freeze_site_payload(freeze_until_period=3, **overrides) -> dict:
    defaults = {"freeze_until_period": freeze_until_period}
    defaults.update(overrides)
    return defaults


def create_soil_evaluation_payload(evaluator_id, **overrides) -> dict:
    defaults = {
        "evaluator_id": evaluator_id,
        "soil_class": "LOAM",
        "limiting_layer_inches": 36,
    }
    defaults.update(overrides)
    return defaults


def create_percolation_test_payload(evaluator_id, **overrides) -> dict:
    defaults = {
        "evaluator_id": evaluator_id,
        "minutes_per_inch": 12.0,
        "test_pit_count": 4,
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(designer_id, soil_evaluation_id, percolation_test_id, **overrides) -> dict:
    defaults = {
        "designer_id": designer_id,
        "soil_evaluation_id": soil_evaluation_id,
        "percolation_test_id": percolation_test_id,
        "bedroom_count": 3,
        "system_type": "GRAVITY",
    }
    defaults.update(overrides)
    return defaults


def decide_design_payload(officer_id, decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision, "officer_id": officer_id}
    defaults.update(overrides)
    return defaults


def revise_design_payload(expected_design_version, **overrides) -> dict:
    defaults = {"expected_design_version": expected_design_version}
    defaults.update(overrides)
    return defaults


def create_permit_payload(design_id, officer_id, **overrides) -> dict:
    defaults = {"design_id": design_id, "officer_id": officer_id}
    defaults.update(overrides)
    return defaults


def reinstate_permit_payload(expected_permit_version, **overrides) -> dict:
    defaults = {"expected_permit_version": expected_permit_version}
    defaults.update(overrides)
    return defaults


def revoke_permit_payload(revoke_note="Falsified staking plan discovered", **overrides) -> dict:
    defaults = {"revoke_note": revoke_note}
    defaults.update(overrides)
    return defaults


def create_installation_payload(permit_id, **overrides) -> dict:
    defaults = {"permit_id": permit_id, "crew_lead": D["CREW_LEAD"]}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(inspector_id, hold_point="TANK_SET", scheduled_period=0, **overrides) -> dict:
    defaults = {
        "hold_point": hold_point,
        "inspector_id": inspector_id,
        "scheduled_period": scheduled_period,
    }
    defaults.update(overrides)
    return defaults


def decide_inspection_payload(decision="PASS", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_material_payload(material_kind="TANK", quantity=1, unit_cost_cents=150000, **overrides) -> dict:
    defaults = {
        "material_kind": material_kind,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_variance_request_payload(design_id, relief_kind="AREA_REDUCTION", **overrides) -> dict:
    defaults = {
        "design_id": design_id,
        "relief_kind": relief_kind,
        "justification": "Low-flow fixtures reduce design flow",
    }
    defaults.update(overrides)
    return defaults


def decide_variance_payload(officer_id, decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision, "officer_id": officer_id}
    defaults.update(overrides)
    return defaults


def create_maintenance_contract_payload(installation_id, start_period=0, end_period=3,
                                        annual_fee_cents=120000, **overrides) -> dict:
    defaults = {
        "installation_id": installation_id,
        "start_period": start_period,
        "end_period": end_period,
        "annual_fee_cents": annual_fee_cents,
    }
    defaults.update(overrides)
    return defaults


def renew_contract_payload(new_end_period, expected_contract_version, **overrides) -> dict:
    defaults = {
        "new_end_period": new_end_period,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def record_visit_payload(visit_period=0, **overrides) -> dict:
    defaults = {
        "visit_period": visit_period,
        "findings": "All components operating within normal parameters",
        "alarm_condition": False,
        "technician_name": "Tech A",
    }
    defaults.update(overrides)
    return defaults


def deliver_education_payload(site_id, delivery_period=0, **overrides) -> dict:
    defaults = {"site_id": site_id, "delivery_period": delivery_period}
    defaults.update(overrides)
    return defaults


def create_repair_case_payload(failed_installation_id, failure_kind="HYDRAULIC_OVERLOAD", **overrides) -> dict:
    defaults = {
        "failed_installation_id": failed_installation_id,
        "failure_kind": failure_kind,
        "diagnosis_note": "Field saturated after two wet seasons",
    }
    defaults.update(overrides)
    return defaults


def triage_repair_case_payload(remedy="REPLACEMENT", replacement_design_id=None, **overrides) -> dict:
    defaults = {"remedy": remedy}
    if replacement_design_id is not None:
        defaults["replacement_design_id"] = replacement_design_id
    defaults.update(overrides)
    return defaults


def resolve_repair_case_payload(resolution_note="Replaced crushed lateral and retested", **overrides) -> dict:
    defaults = {"resolution_note": resolution_note}
    defaults.update(overrides)
    return defaults
