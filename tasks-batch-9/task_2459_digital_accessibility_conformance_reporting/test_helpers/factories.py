"""Payload factories — one per write operation, request fields only.

Derived fields are never supplied by clients (PRD §2.9), so no factory emits
one.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def standard_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": TEST_DEFAULTS["STANDARD_CODE"],
        "title": TEST_DEFAULTS["STANDARD_TITLE"],
        "surface_scope": TEST_DEFAULTS["SURFACE_SCOPE"],
        "max_target_level": TEST_DEFAULTS["MAX_TARGET_LEVEL"],
    }
    payload.update(overrides)
    return payload


def criterion_payload(
    criterion_number: str = TEST_DEFAULTS["CRITERION_NUMBER"],
    level: str = "AA",
    disability_categories: Optional[List[str]] = None,
    applies_to_surfaces: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "criterion_number": criterion_number,
        "title": TEST_DEFAULTS["CRITERION_TITLE"],
        "level": level,
        "disability_categories": list(disability_categories or ["VISION"]),
        "applies_to_surfaces": list(applies_to_surfaces or ["WEB"]),
    }
    payload.update(overrides)
    return payload


def product_payload(standard_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["PRODUCT_NAME"],
        "version_label": TEST_DEFAULTS["VERSION_LABEL"],
        "standard_id": standard_id,
        "target_level": TEST_DEFAULTS["TARGET_LEVEL"],
        "surface_type": TEST_DEFAULTS["SURFACE_TYPE"],
    }
    payload.update(overrides)
    return payload


def component_payload(
    name: str = TEST_DEFAULTS["COMPONENT_NAME"],
    in_scope: bool = True,
    assessment_scope: str = "FULL",
    applicable_criteria_count: int = TEST_DEFAULTS["APPLICABLE_CRITERIA_COUNT"],
    user_reach_pct: float = TEST_DEFAULTS["USER_REACH_PCT"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "component_type": TEST_DEFAULTS["COMPONENT_TYPE"],
        "in_scope": in_scope,
        "assessment_scope": assessment_scope,
        "applicable_criteria_count": applicable_criteria_count,
        "user_reach_pct": user_reach_pct,
    }
    payload.update(overrides)
    return payload


def design_review_payload(
    review_decision: str = "PASS", review_note: str = "Acceptance criteria signed off."
) -> Dict[str, Any]:
    return {"review_decision": review_decision, "review_note": review_note}


def environment_payload(
    name: str = TEST_DEFAULTS["ENVIRONMENT_NAME"],
    at_profile: str = "SCREEN_READER",
    reconfiguration_buffer_minutes: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "at_profile": at_profile,
        "at_product_name": TEST_DEFAULTS["AT_PRODUCT_NAME"],
        "os_platform": TEST_DEFAULTS["OS_PLATFORM"],
    }
    if reconfiguration_buffer_minutes is not None:
        payload["reconfiguration_buffer_minutes"] = reconfiguration_buffer_minutes
    payload.update(overrides)
    return payload


def run_payload(
    component_id: str,
    environment_id: str,
    method: str = "MANUAL",
    at_profile: str = "SCREEN_READER",
    scheduled_start: str = "2026-08-01T09:00:00Z",
    scheduled_end: str = "2026-08-01T12:00:00Z",
    criteria_exercised: int = 40,
    disability_categories_validated: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "component_id": component_id,
        "environment_id": environment_id,
        "method": method,
        "at_profile": at_profile,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "criteria_exercised": criteria_exercised,
        "disability_categories_validated": list(disability_categories_validated or ["VISION"]),
    }
    payload.update(overrides)
    return payload


def complete_run_payload(defects_found: Optional[int] = 0) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if defects_found is not None:
        payload["defects_found"] = defects_found
    return payload


def void_run_payload(void_reason: str = "Bench misconfiguration invalidated the evidence.") -> Dict[str, Any]:
    return {"void_reason": void_reason}


def assessment_payload(
    component_id: str,
    criterion_id: str,
    expected_component_version: int,
    support_level: str = "SUPPORTS",
    evidence_run_id: Optional[str] = None,
    remarks: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "component_id": component_id,
        "criterion_id": criterion_id,
        "support_level": support_level,
        "expected_component_version": expected_component_version,
    }
    if evidence_run_id is not None:
        payload["evidence_run_id"] = evidence_run_id
    if remarks is not None:
        payload["remarks"] = remarks
    payload.update(overrides)
    return payload


def attestation_payload(
    attestation_note: str = "Independently reviewed against the cited run evidence.",
) -> Dict[str, Any]:
    return {"attestation_note": attestation_note}


def report_payload(
    product_id: str,
    standard_id: str,
    expected_product_version: int,
    report_title: str = TEST_DEFAULTS["REPORT_TITLE"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "standard_id": standard_id,
        "report_title": report_title,
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def submission_payload(submission_note: str = "Ready for reviewer sign-off.") -> Dict[str, Any]:
    return {"submission_note": submission_note}


def change_request_payload(
    change_request_note: str = "Coverage narrative needs the magnification detail.",
) -> Dict[str, Any]:
    return {"change_request_note": change_request_note}


def approval_payload(approval_note: str = "Evidence and remarks check out.") -> Dict[str, Any]:
    return {"approval_note": approval_note}


def publication_payload(publication_channel: str = "CUSTOMER_TRUST_PORTAL") -> Dict[str, Any]:
    return {"publication_channel": publication_channel}


def withdrawal_payload(
    withdrawal_reason: str = "Certified figure no longer defensible.",
) -> Dict[str, Any]:
    return {"withdrawal_reason": withdrawal_reason}


def release_train_payload(
    name: str = TEST_DEFAULTS["TRAIN_NAME"],
    window_start: str = "2026-09-01",
    window_end: str = "2026-09-30",
    effort_capacity_points: int = 100,
    remediation_budget_cents: int = 1000000,
    freeze_days: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "window_start": window_start,
        "window_end": window_end,
        "effort_capacity_points": effort_capacity_points,
        "remediation_budget_cents": remediation_budget_cents,
    }
    if freeze_days is not None:
        payload["freeze_days"] = freeze_days
    payload.update(overrides)
    return payload


def allocate_budget_payload(product_id: str) -> Dict[str, Any]:
    return {"product_id": product_id}


def deallocate_budget_payload(
    product_id: str, reason: str = "Reprioritised after the board meeting."
) -> Dict[str, Any]:
    return {"product_id": product_id, "reason": reason}


def known_issue_payload(
    product_id: str,
    component_id: str,
    criterion_id: str,
    severity: str = "SERIOUS",
    effort_points: int = 4,
    target_remediation_date: str = "2026-09-15",
    publish_intent: str = "INCLUDED",
    summary: str = TEST_DEFAULTS["ISSUE_SUMMARY"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "component_id": component_id,
        "criterion_id": criterion_id,
        "severity": severity,
        "summary": summary,
        "effort_points": effort_points,
        "target_remediation_date": target_remediation_date,
        "publish_intent": publish_intent,
    }
    payload.update(overrides)
    return payload


def triage_issue_payload(
    triage_note: str = "Confirmed and reproducible on the review step.",
    severity: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"triage_note": triage_note}
    if severity is not None:
        payload["severity"] = severity
    return payload


def board_review_payload(
    defer: bool = False, board_review_note: str = "Board accepted the prioritisation."
) -> Dict[str, Any]:
    return {"board_review_note": board_review_note, "defer": defer}


def commit_issue_payload(release_train_id: str) -> Dict[str, Any]:
    return {"release_train_id": release_train_id}


def resolve_issue_payload(
    resolution_run_id: str, resolution_note: str = "Fix verified on the component under test."
) -> Dict[str, Any]:
    return {"resolution_note": resolution_note, "resolution_run_id": resolution_run_id}


def questionnaire_payload(
    product_id: str,
    report_id: str,
    customer_name: str = TEST_DEFAULTS["CUSTOMER_NAME"],
    questionnaire_kind: str = TEST_DEFAULTS["QUESTIONNAIRE_KIND"],
    answers_summary: str = TEST_DEFAULTS["ANSWERS_SUMMARY"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "report_id": report_id,
        "customer_name": customer_name,
        "questionnaire_kind": questionnaire_kind,
        "answers_summary": answers_summary,
    }
    payload.update(overrides)
    return payload


def questionnaire_attestation_payload(
    accuracy_attestation: str = "These answers are accurate as of today.",
) -> Dict[str, Any]:
    return {"accuracy_attestation": accuracy_attestation}


def questionnaire_revision_payload(
    answers_summary: str = "Revised answers reflecting the withdrawn conformance report.",
) -> Dict[str, Any]:
    return {"answers_summary": answers_summary}


def complaint_payload(
    product_id: str,
    component_id: Optional[str] = None,
    criterion_id: Optional[str] = None,
    channel: str = TEST_DEFAULTS["COMPLAINT_CHANNEL"],
    description: str = TEST_DEFAULTS["COMPLAINT_DESCRIPTION"],
    disability_category: str = "VISION",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "channel": channel,
        "description": description,
        "disability_category": disability_category,
    }
    if component_id is not None:
        payload["component_id"] = component_id
    if criterion_id is not None:
        payload["criterion_id"] = criterion_id
    payload.update(overrides)
    return payload


def complaint_triage_payload(
    route: str = "REMEDIATION",
    requested_accommodation: Optional[str] = None,
    needed_by_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"route": route}
    if requested_accommodation is not None:
        payload["requested_accommodation"] = requested_accommodation
    if needed_by_date is not None:
        payload["needed_by_date"] = needed_by_date
    return payload


def link_issue_payload(known_issue_id: str) -> Dict[str, Any]:
    return {"known_issue_id": known_issue_id}


def close_complaint_payload(closure_outcome: str) -> Dict[str, Any]:
    return {"closure_outcome": closure_outcome}


def recompute_payload(reason: str = "Logical clock moved forward.") -> Dict[str, Any]:
    return {"reason": reason}
