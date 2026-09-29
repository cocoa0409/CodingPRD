"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "PROJECT_NAME": "Test Commissioning Engagement",
    "BUILDING_NAME": "Test Building",
    "CONTRACT_VALUE_CENTS": TEST_DEFAULTS["PROJECT_CONTRACT_VALUE_CENTS"],
    "METRIC_KEY": "SUPPLY_AIRFLOW_CFM",
    "TARGET_VALUE": TEST_DEFAULTS["REQUIREMENT_TARGET_VALUE"],
    "TOLERANCE_PCT": TEST_DEFAULTS["REQUIREMENT_TOLERANCE_PCT"],
    "PLAN_TITLE": "Test Commissioning Plan",
    "SUBMITTAL_TITLE": "Test Submittal",
    "EQUIPMENT_TAG": "AHU-1",
    "EQUIPMENT_CONTRACT_VALUE_CENTS": TEST_DEFAULTS["EQUIPMENT_CONTRACT_VALUE_CENTS"],
    "EQUIPMENT_WEIGHT_UNITS": TEST_DEFAULTS["EQUIPMENT_WEIGHT_UNITS"],
    "TEMPLATE_CODE": "PFC-AHU-STD",
    "ITEM_CODE": "PFC-01",
    "ITEM_DESCRIPTION": "Filters installed and clean",
    "SCRIPT_CODE": "FPT-AHU-01",
    "ISSUE_DESCRIPTION": "Deficiency observed on site",
    "DELIVERABLE_TITLE": "Test Closeout Deliverable",
    "CREDIT_CODE": "EA-CX-FUNDAMENTAL",
    "MEASURE_CODE": "RCX-SAT-RESET",
}


def create_cx_project_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "building_name": DEFAULTS["BUILDING_NAME"],
        "project_type": "NEW_CONSTRUCTION",
        "contract_value_cents": DEFAULTS["CONTRACT_VALUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_owner_requirement_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "metric_key": DEFAULTS["METRIC_KEY"],
        "target_value": DEFAULTS["TARGET_VALUE"],
        "tolerance_pct": DEFAULTS["TOLERANCE_PCT"],
        "criticality": "CRITICAL",
    }
    payload.update(overrides)
    return payload


def revise_owner_requirement_payload(**overrides) -> dict:
    payload = {
        "target_value": 11_000,
        "tolerance_pct": 4,
        "criticality": "CRITICAL",
    }
    payload.update(overrides)
    return payload


def create_cx_plan_payload(project_id, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "title": DEFAULTS["PLAN_TITLE"],
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_submittal_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "title": DEFAULTS["SUBMITTAL_TITLE"],
        "submittal_kind": "DESIGN_DOCUMENT",
    }
    payload.update(overrides)
    return payload


def review_submittal_payload(decision, **overrides) -> dict:
    payload = {"decision": decision, "comment": "Design review comment"}
    payload.update(overrides)
    return payload


def create_equipment_unit_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "tag": DEFAULTS["EQUIPMENT_TAG"],
        "system_type": "AHU",
        "criticality": "STANDARD",
        "contract_value_cents": DEFAULTS["EQUIPMENT_CONTRACT_VALUE_CENTS"],
        "weight_units": DEFAULTS["EQUIPMENT_WEIGHT_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_prefunctional_checklist_payload(equipment_id, **overrides) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "template_code": DEFAULTS["TEMPLATE_CODE"],
    }
    payload.update(overrides)
    return payload


def add_checklist_item_payload(**overrides) -> dict:
    payload = {
        "item_code": DEFAULTS["ITEM_CODE"],
        "description": DEFAULTS["ITEM_DESCRIPTION"],
        "is_safety_critical": False,
    }
    payload.update(overrides)
    return payload


def record_checklist_item_payload(**overrides) -> dict:
    payload = {"item_code": DEFAULTS["ITEM_CODE"], "result": "PASS"}
    payload.update(overrides)
    return payload


def create_functional_test_payload(
    equipment_id, requirement_id, scheduled_start, scheduled_end, **overrides
) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "requirement_id": requirement_id,
        "script_code": DEFAULTS["SCRIPT_CODE"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_issue_payload(project_id, severity, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "origin": "DESIGN_REVIEW",
        "severity": severity,
        "description": DEFAULTS["ISSUE_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_deferred_test_payload(
    equipment_id, requirement_id, window_start, window_end, **overrides
) -> dict:
    payload = {
        "equipment_id": equipment_id,
        "requirement_id": requirement_id,
        "season": "COOLING",
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_closeout_deliverable_payload(project_id, deliverable_kind, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "deliverable_kind": deliverable_kind,
        "title": DEFAULTS["DELIVERABLE_TITLE"],
    }
    payload.update(overrides)
    return payload


def deliver_closeout_deliverable_payload(**overrides) -> dict:
    payload = {"attendee_count": 0, "duration_minutes": 0}
    payload.update(overrides)
    return payload


def create_certification_credit_payload(
    project_id, required_evidence_count, max_points, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "credit_code": DEFAULTS["CREDIT_CODE"],
        "required_evidence_count": required_evidence_count,
        "max_points": max_points,
    }
    payload.update(overrides)
    return payload


def attach_credit_evidence_payload(evidence_type, evidence_ref_id, **overrides) -> dict:
    payload = {"evidence_type": evidence_type, "evidence_ref_id": evidence_ref_id}
    payload.update(overrides)
    return payload


def create_energy_baseline_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "measure_code": DEFAULTS["MEASURE_CODE"],
        "baseline_kwh": 480_000,
        "baseline_hdd": 3_200,
        "stipulated_kwh_per_hour": 12.5,
        "operating_hours": 4_380,
    }
    payload.update(overrides)
    return payload


def record_post_period_payload(**overrides) -> dict:
    payload = {"post_kwh": 410_000, "post_hdd": 2_880}
    payload.update(overrides)
    return payload
