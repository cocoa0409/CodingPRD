"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_case_payload(**overrides) -> dict:
    defaults = {
        "title": "Case",
        "allegation_category": "FRAUD",
        "severity": "HIGH",
        "department": "Finance",
        "lead_investigator_id": TEST_DEFAULTS["LEAD_INVESTIGATOR_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_allegation_payload(**overrides) -> dict:
    defaults = {
        "reporter_channel": "HOTLINE",
        "is_anonymous": False,
        "reporter_ref": "rep-1",
        "narrative": "allegation narrative",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "scope_statement": "scope",
        "planned_start": "2026-05-02T00:00:00Z",
        "planned_end": "2026-05-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subject_payload(**overrides) -> dict:
    defaults = {
        "employee_ref": TEST_DEFAULTS["EMPLOYEE_REF"],
        "role_in_case": "PRIMARY",
    }
    defaults.update(overrides)
    return defaults


def create_preservation_notice_payload(**overrides) -> dict:
    defaults = {
        "custodian_ref": TEST_DEFAULTS["EMPLOYEE_REF"],
        "scope": "ALL_DATA",
        "is_regulator_ordered": False,
    }
    defaults.update(overrides)
    return defaults


def create_collection_scope_payload(**overrides) -> dict:
    defaults = {
        "custodian_ref": TEST_DEFAULTS["EMPLOYEE_REF"],
        "data_source": "EMAIL",
        "planned_start": "2026-05-05T00:00:00Z",
        "planned_end": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(**overrides) -> dict:
    defaults = {
        "custodian_ref": TEST_DEFAULTS["EMPLOYEE_REF"],
        "hash_value": "h1",
        "size_bytes": 1_000_000,
        "captured_at": "2026-05-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "witness_ref": "W-1",
        "interviewer_id": TEST_DEFAULTS["INTERVIEWER_ID"],
        "scheduled_start": "2026-05-08T14:00:00Z",
        "scheduled_end": "2026-05-08T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_privilege_designation_payload(**overrides) -> dict:
    defaults = {
        "target_type": "EVIDENCE_ITEM",
        "target_id": "PLACEHOLDER",
        "privilege_type": "ACP",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_calibrate_payload(**overrides) -> dict:
    defaults = {
        "to_status": "CALIBRATED",
        "consistency_level": "MEDIUM",
        "subject_admission": False,
        "finding_type": "INCONCLUSIVE",
    }
    defaults.update(overrides)
    return defaults


def create_recommendation_payload(**overrides) -> dict:
    defaults = {
        "mitigation_count": 0,
        "aggravation_count": 0,
        "recommended_action": "WARNING",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "title": "Report",
        "distribution_tier": "RESTRICTED",
        "distribution_list": ["gc-1"],
        "report_privilege_type": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {
        "regulator": "SEC",
        "decision_deadline": "2026-05-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_remediation_payload(**overrides) -> dict:
    defaults = {
        "action_type": "TRAINING",
        "owner_ref": TEST_DEFAULTS["OWNER_REF"],
        "due_date": "2026-06-01T00:00:00Z",
        "description": "remediation description",
    }
    defaults.update(overrides)
    return defaults
