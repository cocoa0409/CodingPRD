"""Payload builders for every write endpoint.

Each builder emits the PRD's required fields with sane domain-flavoured values
and lets a test override any of them, so a test only ever states the fields the
rule under examination actually cares about.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ACQUIRER_NAME,
    APPROVED_BUDGET,
    ASSESSMENT_YEAR,
    CLIENT_LEGAL_NAME,
    FACILITY_DC_EAST,
    FIELDWORK_END,
    FIELDWORK_START,
    LEAD_CERT_EXPIRES,
    VENDOR_APPROVAL_EXPIRES,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------
def assessor_payload(
    full_name: str = "Dana Reyes",
    email: str = "dana.reyes@qsa.example",
    certification_expires_at: str = LEAD_CERT_EXPIRES,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "email": email,
            "certification_expires_at": certification_expires_at,
        },
        overrides,
    )


def asv_vendor_payload(
    name: str = "Northstar ASV",
    approval_expires_at: str = VENDOR_APPROVAL_EXPIRES,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"name": name, "approval_expires_at": approval_expires_at}, overrides
    )


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------
def engagement_payload(
    lead_assessor_id: str,
    qa_reviewer_id: Optional[str] = None,
    client_legal_name: str = CLIENT_LEGAL_NAME,
    merchant_level: str = "L1",
    assessment_year: int = ASSESSMENT_YEAR,
    acquirer_name: str = ACQUIRER_NAME,
    fieldwork_start_date: str = FIELDWORK_START,
    fieldwork_end_date: str = FIELDWORK_END,
    approved_budget_amount: float = APPROVED_BUDGET,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_legal_name": client_legal_name,
        "merchant_level": merchant_level,
        "assessment_year": assessment_year,
        "acquirer_name": acquirer_name,
        "fieldwork_start_date": fieldwork_start_date,
        "fieldwork_end_date": fieldwork_end_date,
        "approved_budget_amount": approved_budget_amount,
        "lead_assessor_id": lead_assessor_id,
    }
    if qa_reviewer_id is not None:
        payload["qa_reviewer_id"] = qa_reviewer_id
    return _merge(payload, overrides)


def reassessment_plan_payload(
    target_year: int, planned_start_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"target_year": target_year, "planned_start_date": planned_start_date},
        overrides,
    )


# ---------------------------------------------------------------------------
# Segments and components
# ---------------------------------------------------------------------------
def network_segment_payload(
    name: str = "CDE-CORE",
    segment_class: str = "CDE",
    parent_segment_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "segment_class": segment_class}
    if parent_segment_id is not None:
        payload["parent_segment_id"] = parent_segment_id
    return _merge(payload, overrides)


def segmentation_test_plan_payload(
    test_method: str = "PEN_TEST", planned_date: str = "2026-08-05", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"test_method": test_method, "planned_date": planned_date}, overrides
    )


def validation_result_payload(
    outcome: str = "PASS", note: str = "Segmentation verified.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "note": note}, overrides)


def remediation_revalidation_payload(
    test_method: str = "PEN_TEST", planned_date: str = "2026-08-14", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"test_method": test_method, "planned_date": planned_date}, overrides
    )


def withdraw_segment_payload(
    reason: str = "The client removed the zone from the network before fieldwork began.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def system_component_payload(
    segment_id: str,
    hostname: str = "app-01",
    component_type: str = "SERVER",
    function_class: str = "SECURITY_SERVICE",
    stores_chd: bool = False,
    facility_name: str = FACILITY_DC_EAST,
    facility_type: str = "DATA_CENTER",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "hostname": hostname,
            "component_type": component_type,
            "function_class": function_class,
            "stores_chd": stores_chd,
            "facility_name": facility_name,
            "facility_type": facility_type,
            "segment_id": segment_id,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------
def sampling_plan_payload(
    expected_engagement_version: int,
    plan_variant: str = "FINAL",
    justification_text: str = "Full coverage of the in-scope inventory.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "plan_variant": plan_variant,
            "justification_text": justification_text,
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Requirements and evidence
# ---------------------------------------------------------------------------
def requirement_payload(
    requirement_ref: str = "1.2.1",
    requirement_family: str = "R1",
    testing_procedure_count: int = 3,
    applicability: str = "APPLICABLE",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "requirement_ref": requirement_ref,
            "requirement_family": requirement_family,
            "testing_procedure_count": testing_procedure_count,
            "applicability": applicability,
        },
        overrides,
    )


def evidence_payload(
    evidence_type: str = "DOCUMENT_REVIEW",
    procedure_ref: str = "1.2.1.a",
    sufficiency: str = "SUFFICIENT",
    component_id: Optional[str] = None,
    interviewee_name: Optional[str] = None,
    interviewee_title: Optional[str] = None,
    note: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "procedure_ref": procedure_ref,
        "sufficiency": sufficiency,
    }
    if component_id is not None:
        payload["component_id"] = component_id
    if interviewee_name is not None:
        payload["interviewee_name"] = interviewee_name
    if interviewee_title is not None:
        payload["interviewee_title"] = interviewee_title
    if note is not None:
        payload["note"] = note
    return _merge(payload, overrides)


def document_evidence(procedure_ref: str, **overrides: Any) -> Dict[str, Any]:
    return evidence_payload(
        evidence_type="DOCUMENT_REVIEW",
        procedure_ref=procedure_ref,
        note="Standard reviewed against the requirement.",
        **overrides
    )


def interview_evidence(
    procedure_ref: str,
    interviewee_name: str = "Priya Raman",
    interviewee_title: str = "Network Engineering Manager",
    **overrides: Any
) -> Dict[str, Any]:
    return evidence_payload(
        evidence_type="INTERVIEW",
        procedure_ref=procedure_ref,
        interviewee_name=interviewee_name,
        interviewee_title=interviewee_title,
        **overrides
    )


def observation_evidence(
    procedure_ref: str, component_id: str, **overrides: Any
) -> Dict[str, Any]:
    return evidence_payload(
        evidence_type="OBSERVATION",
        procedure_ref=procedure_ref,
        component_id=component_id,
        **overrides
    )


def conclusion_payload(
    conclusion: str = "IN_PLACE",
    conclusion_rationale: str = "Ruleset restricts inbound traffic to documented services.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"conclusion": conclusion, "conclusion_rationale": conclusion_rationale},
        overrides,
    )


def reopen_payload(
    reason: str = "The client changed the ruleset after the conclusion was recorded.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Compensating control worksheets
# ---------------------------------------------------------------------------
def ccw_payload(
    expected_requirement_assessment_version: int,
    control_refs: Optional[List[str]] = None,
    monitoring_interval_days: int = 7,
    constraint_text: str = "The legacy terminal fleet cannot accept the stated control.",
    objective_text: str = "Prevent unauthorised access to stored cardholder data.",
    identified_risk_text: str = "An attacker could reach the data store unimpeded.",
    validation_text: str = "The compensating controls were validated during fieldwork.",
    maintenance_text: str = "The client reviews the controls on the stated interval.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "constraint_text": constraint_text,
            "objective_text": objective_text,
            "identified_risk_text": identified_risk_text,
            "control_refs": list(control_refs or ["A-1", "A-2", "A-3", "A-4"]),
            "monitoring_interval_days": monitoring_interval_days,
            "validation_text": validation_text,
            "maintenance_text": maintenance_text,
            "expected_requirement_assessment_version": expected_requirement_assessment_version,
        },
        overrides,
    )


def ccw_decision_payload(
    decision: str = "ACCEPT",
    reviewer_note: str = "The compensating controls meet the original objective.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": decision, "reviewer_note": reviewer_note}, overrides)


# ---------------------------------------------------------------------------
# Remediation items
# ---------------------------------------------------------------------------
def assign_payload(
    owner_reference: str = "Client Network Team",
    due_date: str = "2026-08-20",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"owner_reference": owner_reference, "due_date": due_date}, overrides
    )


def retest_payload(
    outcome: str = "PASS", note: str = "The control was verified on retest.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "note": note}, overrides)


# ---------------------------------------------------------------------------
# Reports on compliance
# ---------------------------------------------------------------------------
def roc_payload(roc_version_label: str = "v1.0", **overrides: Any) -> Dict[str, Any]:
    return _merge({"roc_version_label": roc_version_label}, overrides)


def qa_review_payload(
    decision: str = "APPROVE",
    qa_decision_note: str = "The report is supported by the evidence on file.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"decision": decision, "qa_decision_note": qa_decision_note}, overrides
    )


def revise_payload(
    revision_note: str = "Expanded the sampling rationale and re-cited the evidence.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"revision_note": revision_note}, overrides)


def attest_payload(
    attestation_signature_name: str = "Dana Reyes", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"attestation_signature_name": attestation_signature_name}, overrides)


def submission_payload(
    submitted_to: str = "ACQUIRER",
    submission_reference: str = "FCB-2026-00841",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"submitted_to": submitted_to, "submission_reference": submission_reference},
        overrides,
    )


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def scan_cycle_payload(
    asv_vendor_id: str,
    quarter_label: str = "2026-Q3",
    window_start: str = "2026-07-01T00:00:00Z",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "quarter_label": quarter_label,
            "asv_vendor_id": asv_vendor_id,
            "window_start": window_start,
        },
        overrides,
    )


def scan_finding_payload(
    component_id: str,
    plugin_reference: str = "PLG-40912",
    cvss_score: float = 7.5,
    **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "plugin_reference": plugin_reference,
            "cvss_score": cvss_score,
            "component_id": component_id,
        },
        overrides,
    )


def dispute_payload(
    dispute_rationale: str = "The plugin fires on a banner string the host does not serve.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"dispute_rationale": dispute_rationale}, overrides)


def dispute_decision_payload(
    decision: str = "ACCEPT",
    decision_note: str = "The vendor confirmed the plugin misfired.",
    **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": decision, "decision_note": decision_note}, overrides)


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------
def change_log_payload(
    change_type: str = "COMPONENT_ADDED_TO_CDE",
    description: str = "A reporting server was joined to the cardholder network.",
    affects_scope: bool = True,
    component_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "change_type": change_type,
        "description": description,
        "affects_scope": affects_scope,
    }
    if component_id is not None:
        payload["component_id"] = component_id
    return _merge(payload, overrides)
