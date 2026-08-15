"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .constants import TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_code": _uniq("AG").upper(),
        "agency_name": "Test Regulator Agency",
        "jurisdiction": "FEDERAL",
        "escalation_threshold_days": TEST_DEFAULTS["ESCALATION_THRESHOLD_DAYS"],
        "repeat_finding_multiplier_bp": TEST_DEFAULTS["REPEAT_MULTIPLIER_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_officer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Officer",
        "email": f"{_uniq('officer')}@bank.test",
        "officer_role_title": "CRO",
    }
    defaults.update(overrides)
    return defaults


def create_reviewer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Reviewer",
        "email": f"{_uniq('reviewer')}@bank.test",
        "certification_level": "L3",
    }
    defaults.update(overrides)
    return defaults


def create_examination_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "exam_cycle_code": _uniq("CYCLE").upper(),
        "exam_type": "IT",
        "scheduled_start_date": TEST_DEFAULTS["EXAM_START"],
        "scheduled_end_date": TEST_DEFAULTS["EXAM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_first_day_item_payload(**overrides) -> dict:
    defaults = {
        "request_ref": _uniq("FDL").upper(),
        "description": "Requested documents",
        "due_date": TEST_DEFAULTS["ITEM_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_document_manifest(**overrides) -> list:
    manifest = [
        {"doc_id": _uniq("doc"), "title": "Document", "page_count": 10,
         "sha256": uuid.uuid4().hex}
    ]
    if overrides:
        manifest = overrides.get("document_manifest", manifest)
    return manifest


def create_document_submission_payload(**overrides) -> dict:
    defaults = {"document_manifest": create_document_manifest()}
    defaults.update(overrides)
    return defaults


def create_examiner_meeting_payload(examination_id: str, **overrides) -> dict:
    defaults = {
        "examination_id": examination_id,
        "meeting_date": TEST_DEFAULTS["MEETING_DATE"],
        "attendees": ["Examiner A", "Bank Officer B"],
        "minutes_summary": "Meeting minutes",
    }
    defaults.update(overrides)
    return defaults


def create_informal_finding_payload(**overrides) -> dict:
    defaults = {
        "finding_text": "Informal finding narrative",
        "severity_hint": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_issue_payload(expected_examination_version: int, **overrides) -> dict:
    defaults = {
        "issue_ref": _uniq("MRA").upper(),
        "classification": "MRA",
        "severity": "LOW",
        "due_date": TEST_DEFAULTS["ISSUE_DUE"],
        "expected_examination_version": expected_examination_version,
    }
    defaults.update(overrides)
    return defaults


def create_remediation_plan_payload(owner_user_id: str, **overrides) -> dict:
    defaults = {
        "owner_user_id": owner_user_id,
        "root_cause_narrative": "Root cause analysis",
        "corrective_action_summary": "Corrective actions",
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(expected_plan_version: int, **overrides) -> dict:
    defaults = {
        "milestone_name": _uniq("MS"),
        "due_date": TEST_DEFAULTS["MILESTONE_DUE"],
        "expected_plan_version": expected_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_validation_evidence_payload(submitted_by_user_id: str, **overrides) -> dict:
    defaults = {
        "evidence_type": "TEST_RESULTS",
        "artifact_manifest": [
            {"artifact_id": _uniq("art"), "name": "artifact",
             "sha256": uuid.uuid4().hex}
        ],
        "submitted_by_user_id": submitted_by_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_submit_validation_payload(validation_evidence_id: str, **overrides) -> dict:
    defaults = {
        "validation_evidence_id": validation_evidence_id,
        "closure_narrative": "Issue remediated",
    }
    defaults.update(overrides)
    return defaults


def create_closure_approve_payload(expected_issue_version: int, **overrides) -> dict:
    defaults = {"expected_issue_version": expected_issue_version}
    defaults.update(overrides)
    return defaults


def create_board_report_payload(examination_id: str, **overrides) -> dict:
    defaults = {
        "examination_id": examination_id,
        "reporting_period_start": "2026-07-01T00:00:00Z",
        "reporting_period_end": "2026-07-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(committed_by_user_id: str, **overrides) -> dict:
    defaults = {
        "commitment_text": "Will remediate by Q4",
        "committed_by_user_id": committed_by_user_id,
        "due_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
