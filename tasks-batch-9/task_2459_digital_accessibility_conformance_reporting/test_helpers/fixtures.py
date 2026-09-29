"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database with the logical
clock at its fixed starting instant of 2026-08-01T00:00:00Z. Setup calls use the
lenient success reader so a broken precondition surfaces as a setup failure
rather than as a confusing assertion inside the test body.

Writes that are optimistically locked on a parent always re-read that parent
first, because the client's last observed `version` is what the server compares
against (PRD §2.5).
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    LEAD_USER_ID,
    LIAISON_USER_ID,
    REVIEWER_USER_ID,
    SECOND_REVIEWER_USER_ID,
    SECOND_TESTER_USER_ID,
    TESTER_USER_ID,
    make_lead_headers,
    make_liaison_headers,
    make_product_owner_headers,
    make_reviewer_headers,
    make_tester_headers,
)

LEAD = make_lead_headers()
TESTER = make_tester_headers()
SECOND_TESTER = make_tester_headers(SECOND_TESTER_USER_ID)
REVIEWER = make_reviewer_headers()
SECOND_REVIEWER = make_reviewer_headers(SECOND_REVIEWER_USER_ID)
LIAISON = make_liaison_headers()


# ===========================================================================
# Clock and reads
# ===========================================================================

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock. Moving it performs no writes of its own."""
    return get_success_data(api_client.set_clock(to_iso8601, LEAD))


def read_product(product_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_product(product_id, LEAD))


def read_component(component_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_component(component_id, LEAD))


def read_environment(environment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_environment(environment_id, LEAD))


def read_run(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_run(run_id, LEAD))


def read_assessment(assessment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_assessment(assessment_id, LEAD))


def read_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_report(report_id, LEAD))


def read_release_train(train_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_release_train(train_id, LEAD))


def read_known_issue(issue_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_known_issue(issue_id, LEAD))


def read_questionnaire(questionnaire_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_questionnaire(questionnaire_id, LEAD))


def read_complaint(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_complaint(complaint_id, LEAD))


# ===========================================================================
# Configuration primitives
# ===========================================================================

def create_standard(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_standard(f.standard_payload(**overrides), LEAD))


def create_criterion(
    standard_id: str,
    criterion_number: str = "1.4.3",
    level: str = "AA",
    disability_categories: Optional[List[str]] = None,
    applies_to_surfaces: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = f.criterion_payload(
        criterion_number=criterion_number,
        level=level,
        disability_categories=disability_categories,
        applies_to_surfaces=applies_to_surfaces,
        **overrides,
    )
    return get_success_data(api_client.create_criterion(standard_id, payload, LEAD))


def create_product(standard_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_product(f.product_payload(standard_id, **overrides), LEAD)
    )


def create_component(product_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_component(product_id, f.component_payload(**overrides), LEAD)
    )


def record_design_review(
    component_id: str,
    review_decision: str = "PASS",
    review_note: str = "Acceptance criteria signed off.",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.design_review(
            component_id, f.design_review_payload(review_decision, review_note), REVIEWER
        )
    )


def create_environment(
    name: str = "NVDA Bench 1",
    at_profile: str = "SCREEN_READER",
    reconfiguration_buffer_minutes: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = f.environment_payload(
        name=name,
        at_profile=at_profile,
        reconfiguration_buffer_minutes=reconfiguration_buffer_minutes,
        **overrides,
    )
    return get_success_data(api_client.create_environment(payload, LEAD))


def recompute_posture(product_id: str, reason: str = "Logical clock moved forward.") -> Dict[str, Any]:
    return get_success_data(
        api_client.recompute_posture(product_id, f.recompute_payload(reason), LEAD)
    )


# ===========================================================================
# Run primitives
# ===========================================================================

def schedule_run(
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
    payload = f.run_payload(
        component_id,
        environment_id,
        method=method,
        at_profile=at_profile,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        criteria_exercised=criteria_exercised,
        disability_categories_validated=disability_categories_validated,
        **overrides,
    )
    return get_success_data(api_client.create_run(payload, TESTER))


def complete_run(run_id: str, defects_found: Optional[int] = 0) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_run(run_id, f.complete_run_payload(defects_found), TESTER)
    )


def void_run(run_id: str, void_reason: str = "Bench misconfiguration invalidated the evidence.") -> Dict[str, Any]:
    return get_success_data(api_client.void_run(run_id, f.void_run_payload(void_reason), TESTER))


def schedule_and_complete_run(
    component_id: str,
    environment_id: str,
    method: str = "MANUAL",
    at_profile: str = "SCREEN_READER",
    criteria_exercised: int = 40,
    disability_categories_validated: Optional[List[str]] = None,
    scheduled_start: str = "2026-08-01T09:00:00Z",
    scheduled_end: str = "2026-08-01T12:00:00Z",
    defects_found: Optional[int] = 0,
) -> Dict[str, Any]:
    """Book a bench and close the run out, so its evidence is credited."""
    run = schedule_run(
        component_id,
        environment_id,
        method=method,
        at_profile=at_profile,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        criteria_exercised=criteria_exercised,
        disability_categories_validated=disability_categories_validated,
    )
    return complete_run(run["id"], defects_found)


# ===========================================================================
# Criterion assessment primitives
# ===========================================================================

def author_assessment(
    component_id: str,
    criterion_id: str,
    support_level: str = "SUPPORTS",
    evidence_run_id: Optional[str] = None,
    remarks: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_component_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Author a row, re-reading the component's current `version` first."""
    if expected_component_version is None:
        expected_component_version = read_component(component_id)["version"]
    payload = f.assessment_payload(
        component_id,
        criterion_id,
        expected_component_version,
        support_level=support_level,
        evidence_run_id=evidence_run_id,
        remarks=remarks,
    )
    return get_success_data(api_client.create_assessment(payload, headers or TESTER))


def attest_assessment(
    assessment_id: str,
    headers: Optional[Dict[str, str]] = None,
    attestation_note: str = "Independently reviewed against the cited run evidence.",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.attest_assessment(
            assessment_id, f.attestation_payload(attestation_note), headers or REVIEWER
        )
    )


# ===========================================================================
# Report primitives
# ===========================================================================

def open_report(
    product_id: str,
    standard_id: str,
    report_title: str = "Atlas Portal Accessibility Conformance Report",
    expected_product_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a report, re-reading the product's current `version` first."""
    if expected_product_version is None:
        expected_product_version = read_product(product_id)["version"]
    payload = f.report_payload(
        product_id, standard_id, expected_product_version, report_title=report_title
    )
    return get_success_data(api_client.create_report(payload, LEAD))


def submit_report(report_id: str, product_id: str, submission_note: str = "Ready for reviewer sign-off.") -> Dict[str, Any]:
    """Submit as the accountable ProductOwner, whose X-User-ID is the product id."""
    return get_success_data(
        api_client.submit_report(
            report_id, f.submission_payload(submission_note), make_product_owner_headers(product_id)
        )
    )


def request_changes(
    report_id: str,
    change_request_note: str = "Coverage narrative needs the magnification detail.",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.request_changes(
            report_id, f.change_request_payload(change_request_note), headers or REVIEWER
        )
    )


def approve_report(
    report_id: str,
    headers: Optional[Dict[str, str]] = None,
    approval_note: str = "Evidence and remarks check out.",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_report(
            report_id, f.approval_payload(approval_note), headers or REVIEWER
        )
    )


def publish_report(report_id: str, publication_channel: str = "CUSTOMER_TRUST_PORTAL") -> Dict[str, Any]:
    return get_success_data(
        api_client.publish_report(report_id, f.publication_payload(publication_channel), LEAD)
    )


def withdraw_report(
    report_id: str, withdrawal_reason: str = "Certified figure no longer defensible."
) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_report(report_id, f.withdrawal_payload(withdrawal_reason), LEAD)
    )


# ===========================================================================
# Release train, budget and known issue primitives
# ===========================================================================

def create_release_train(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_release_train(f.release_train_payload(**overrides), LEAD)
    )


def allocate_budget(train_id: str, product_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.allocate_budget(train_id, f.allocate_budget_payload(product_id), LEAD)
    )


def deallocate_budget(
    train_id: str, product_id: str, reason: str = "Reprioritised after the board meeting."
) -> Dict[str, Any]:
    return get_success_data(
        api_client.deallocate_budget(
            train_id, f.deallocate_budget_payload(product_id, reason), LEAD
        )
    )


def log_issue(
    product_id: str,
    component_id: str,
    criterion_id: str,
    severity: str = "SERIOUS",
    effort_points: int = 4,
    target_remediation_date: str = "2026-09-15",
    publish_intent: str = "INCLUDED",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = f.known_issue_payload(
        product_id,
        component_id,
        criterion_id,
        severity=severity,
        effort_points=effort_points,
        target_remediation_date=target_remediation_date,
        publish_intent=publish_intent,
        **overrides,
    )
    return get_success_data(api_client.create_known_issue(payload, headers or TESTER))


def triage_issue(issue_id: str, severity: Optional[str] = None, triage_note: str = "Confirmed and reproducible on the review step.") -> Dict[str, Any]:
    return get_success_data(
        api_client.triage_issue(issue_id, f.triage_issue_payload(triage_note, severity), LEAD)
    )


def board_review_issue(issue_id: str, defer: bool = False) -> Dict[str, Any]:
    return get_success_data(
        api_client.board_review_issue(issue_id, f.board_review_payload(defer), LEAD)
    )


def commit_issue(issue_id: str, train_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.commit_issue(issue_id, f.commit_issue_payload(train_id), LEAD)
    )


def resolve_issue(issue_id: str, resolution_run_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_issue(issue_id, f.resolve_issue_payload(resolution_run_id), TESTER)
    )


# ===========================================================================
# Questionnaire and complaint primitives
# ===========================================================================

def draft_questionnaire(product_id: str, report_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_questionnaire(
            f.questionnaire_payload(product_id, report_id, **overrides), LIAISON
        )
    )


def submit_questionnaire(questionnaire_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.submit_questionnaire(questionnaire_id, {}, LIAISON))


def attest_questionnaire(questionnaire_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.attest_questionnaire(
            questionnaire_id, f.questionnaire_attestation_payload(), LEAD
        )
    )


def revise_questionnaire(questionnaire_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.revise_questionnaire(
            questionnaire_id, f.questionnaire_revision_payload(**overrides), LIAISON
        )
    )


def intake_complaint(product_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_complaint(f.complaint_payload(product_id, **overrides), LIAISON)
    )


def triage_complaint(
    complaint_id: str,
    route: str = "REMEDIATION",
    requested_accommodation: Optional[str] = None,
    needed_by_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.complaint_triage_payload(route, requested_accommodation, needed_by_date)
    return get_success_data(api_client.triage_complaint(complaint_id, payload, LEAD))


def link_complaint_issue(complaint_id: str, issue_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.link_issue(complaint_id, f.link_issue_payload(issue_id), LEAD)
    )


def fulfill_accommodation(complaint_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.fulfill_accommodation(complaint_id, {}, LIAISON))


def close_complaint(complaint_id: str, closure_outcome: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_complaint(complaint_id, f.close_complaint_payload(closure_outcome), LEAD)
    )


# ===========================================================================
# Composite scenarios
# ===========================================================================

def enrolled_product(
    criteria: Optional[Sequence[Dict[str, Any]]] = None,
    target_level: str = "AA",
    max_target_level: str = "AA",
    surface_scope: str = "BOTH",
    surface_type: str = "WEB",
    standard_code: str = "WCAG_2_1",
) -> Dict[str, Any]:
    """A standard with its criteria plus a product enrolled against it.

    `criteria` is a sequence of keyword dicts passed straight to
    create_criterion; it defaults to a single level-AA VISION criterion.
    """
    standard = create_standard(
        code=standard_code, surface_scope=surface_scope, max_target_level=max_target_level
    )
    specs = list(criteria if criteria is not None else [{}])
    created = [create_criterion(standard["id"], **spec) for spec in specs]
    product = create_product(
        standard["id"], target_level=target_level, surface_type=surface_type
    )
    return {
        "standard": standard,
        "criteria": created,
        "criterion": created[0] if created else None,
        "product": product,
    }


def screen_reader_bench(
    name: str = "NVDA Bench 1", reconfiguration_buffer_minutes: Optional[int] = None
) -> Dict[str, Any]:
    return create_environment(
        name=name,
        at_profile="SCREEN_READER",
        at_product_name="NVDA 2026.1",
        reconfiguration_buffer_minutes=reconfiguration_buffer_minutes,
    )


def keyboard_bench(name: str = "Keyboard Bench 1") -> Dict[str, Any]:
    return create_environment(
        name=name, at_profile="KEYBOARD", at_product_name="Keyboard-only harness 3.2"
    )


def magnification_bench(name: str = "ZoomText Bench 1") -> Dict[str, Any]:
    return create_environment(
        name=name, at_profile="MAGNIFICATION", at_product_name="ZoomText 2026"
    )


def complete_component(
    product_id: str,
    name: str = "Checkout Flow",
    applicable_criteria_count: int = 40,
    user_reach_pct: float = 80,
    validated_categories: Optional[List[str]] = None,
    bench_name: str = "NVDA Bench 1",
    in_scope: bool = True,
    assessment_scope: str = "FULL",
) -> Dict[str, Any]:
    """A component carried to COMPLETE by one MANUAL screen-reader run.

    A manual run exercising every applicable criterion scores the
    SCREEN_READER profile at 1, so the weighted coverage is 45.00 percent —
    exactly the attestation floor.
    """
    component = create_component(
        product_id,
        name=name,
        in_scope=in_scope,
        assessment_scope=assessment_scope,
        applicable_criteria_count=applicable_criteria_count,
        user_reach_pct=user_reach_pct,
    )
    bench = screen_reader_bench(name=bench_name)
    run = schedule_and_complete_run(
        component["id"],
        bench["id"],
        method="MANUAL",
        at_profile="SCREEN_READER",
        criteria_exercised=applicable_criteria_count,
        disability_categories_validated=list(validated_categories or ["VISION"]),
    )
    return {
        "component": read_component(component["id"]),
        "environment": bench,
        "run": run,
    }


def attested_assessment(
    component_id: str,
    criterion_id: str,
    support_level: str = "SUPPORTS",
    evidence_run_id: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """Author a row as the tester and attest it as an independent reviewer."""
    row = author_assessment(
        component_id,
        criterion_id,
        support_level=support_level,
        evidence_run_id=evidence_run_id,
        remarks=remarks,
        headers=TESTER,
    )
    return attest_assessment(row["id"], REVIEWER)


def publishable_product(
    criteria: Optional[Sequence[Dict[str, Any]]] = None,
    validated_categories: Optional[List[str]] = None,
    applicable_criteria_count: int = 40,
) -> Dict[str, Any]:
    """A product whose single in-scope component clears every publication gate.

    The component is COMPLETE, design-reviewed PASS, and carries one attested
    assessment per configured criterion.
    """
    setup = enrolled_product(criteria=criteria)
    product = setup["product"]
    built = complete_component(
        product["id"],
        applicable_criteria_count=applicable_criteria_count,
        validated_categories=validated_categories or ["VISION"],
    )
    component = built["component"]
    assessments = [
        attested_assessment(component["id"], criterion["id"], evidence_run_id=built["run"]["id"])
        for criterion in setup["criteria"]
    ]
    record_design_review(component["id"], "PASS")
    return {
        **setup,
        "component": component,
        "environment": built["environment"],
        "run": built["run"],
        "assessments": assessments,
        "assessment": assessments[0] if assessments else None,
        "product": read_product(product["id"]),
    }


def approved_report(scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Carry a publishable product's report from DRAFT to APPROVED.

    Submission is performed by the accountable ProductOwner and approval by a
    reviewer whose X-User-ID differs from the submitter's.
    """
    scenario = scenario or publishable_product()
    product = scenario["product"]
    report = open_report(product["id"], scenario["standard"]["id"])
    submit_report(report["id"], product["id"])
    approve_report(report["id"], REVIEWER)
    return {**scenario, "report": read_report(report["id"]), "product": read_product(product["id"])}


def published_report(scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Carry a publishable product's report all the way to PUBLISHED."""
    built = approved_report(scenario)
    published = publish_report(built["report"]["id"])
    return {
        **built,
        "report": published,
        "product": read_product(built["product"]["id"]),
    }
