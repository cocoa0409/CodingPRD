"""Composite setup helpers.

Every fixture builds preconditions from scratch using PRD-declared endpoints.
The harness restarts the server before each test, so each fixture runs against
an empty database.

Conventions:
- ``_d`` unwraps an API response into its data payload with a clear Setup-failed
  message on error.
- Every fixture returns a dict of named ids/resources so tests can pick what
  they assert against.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_case_payload,
    create_allegation_payload,
    create_plan_payload,
    create_subject_payload,
    create_preservation_notice_payload,
    create_collection_scope_payload,
    create_evidence_item_payload,
    create_interview_payload,
    create_privilege_designation_payload,
    create_calibrate_payload,
    create_recommendation_payload,
    create_report_payload,
    create_disclosure_payload,
    create_remediation_payload,
)
from .test_users import (
    TEST_USERS,
    make_investigator_headers,
    make_manager_headers,
    make_hr_headers,
    make_gc_headers,
    make_clo_headers,
    make_auditor_headers,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
CLO = TEST_USERS["clo_headers"]
AUD = TEST_USERS["auditor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _d(resp, step: str):
    """Unwrap a response's data or raise a clear setup error."""
    if resp.status_code >= 400:
        raise AssertionError(
            f"Setup failed at {step}: HTTP {resp.status_code} body={resp.text}"
        )
    return get_success_data(resp)


def reset_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    _d(api_client.set_clock(to_iso8601, ADMIN), "set_clock")


# ---------------------------------------------------------------------------
# Tier 1: case creation + triage
# ---------------------------------------------------------------------------

def create_case(**overrides):
    """Create a bare case in INTAKE. Returns the case dict."""
    resp = api_client.create_case(create_case_payload(**overrides), IC)
    return _d(resp, "create_case")


def create_triaged_case(**overrides):
    """Case INTAKE -> TRIAGED. Returns the case dict after triage."""
    case = create_case(**overrides)
    payload = {
        "to_status": "TRIAGED",
        "severity": overrides.get("severity", "HIGH"),
        "department": overrides.get("department", "Finance"),
    }
    resp = api_client.transition_case(case["id"], payload, IC)
    _d(resp, "triage_case")
    return _d(api_client.get_case(case["id"], IC), "get_triaged_case")


# ---------------------------------------------------------------------------
# Tier 2: case + plan in FIELDWORK
# ---------------------------------------------------------------------------

def create_case_in_fieldwork(drafter_id: str = None, **case_overrides):
    """Case INTAKE -> TRIAGED -> PLANNING -> FIELDWORK via an APPROVED plan.

    Returns dict(case=..., plan=...).
    """
    drafter_id = drafter_id or TEST_DEFAULTS["DRAFTER_ID"]
    case = create_triaged_case(**case_overrides)
    inv_h = make_investigator_headers(drafter_id)
    plan_payload = create_plan_payload(expected_case_version=case["version"])
    plan = _d(api_client.create_plan(case["id"], plan_payload, inv_h), "create_plan")
    _d(api_client.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, inv_h), "submit_plan")
    approver = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    plan = _d(
        api_client.transition_plan(plan["id"], {"to_status": "APPROVED"}, approver),
        "approve_plan",
    )
    case = _d(api_client.get_case(case["id"], IC), "get_case_fieldwork")
    return {"case": case, "plan": plan}


# ---------------------------------------------------------------------------
# Tier 3: notices + scopes + evidence inside FIELDWORK
# ---------------------------------------------------------------------------

def add_acknowledged_notice(case_id: str, custodian_ref: str = None, scope: str = "ALL_DATA"):
    payload = create_preservation_notice_payload(
        custodian_ref=custodian_ref or TEST_DEFAULTS["EMPLOYEE_REF"],
        scope=scope,
        is_regulator_ordered=False,
    )
    notice = _d(api_client.create_preservation_notice(case_id, payload, GC), "create_notice")
    notice = _d(
        api_client.transition_preservation_notice(notice["id"], {"to_status": "ACKNOWLEDGED"}, GC),
        "ack_notice",
    )
    return notice


def add_collected_scope_with_admitted_evidence(
    case_id: str,
    custodian_ref: str = None,
    data_source: str = "EMAIL",
    evidence_size_bytes: int = 1_000_000,
):
    """Build: notice (ACK) + scope PROPOSED->APPROVED->IN_PROGRESS->COLLECTED with
    one ADMITTED evidence item. Returns dict(notice, scope, evidence)."""
    custodian_ref = custodian_ref or TEST_DEFAULTS["EMPLOYEE_REF"]
    notice = add_acknowledged_notice(case_id, custodian_ref=custodian_ref)
    scope_payload = create_collection_scope_payload(
        custodian_ref=custodian_ref,
        data_source=data_source,
        preservation_notice_id=notice["id"],
    )
    scope = _d(api_client.create_collection_scope(case_id, scope_payload, INV), "create_scope")
    approver = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    scope = _d(
        api_client.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, approver),
        "approve_scope",
    )
    scope = _d(
        api_client.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1),
        "begin_scope",
    )
    ev_payload = create_evidence_item_payload(
        custodian_ref=custodian_ref, size_bytes=evidence_size_bytes
    )
    ev = _d(api_client.create_evidence_item(scope["id"], ev_payload, INV), "create_evidence")
    _d(api_client.transition_evidence_item(ev["id"], {"to_status": "UNDER_REVIEW"}, inv1), "ev_under_review")
    ev = _d(api_client.transition_evidence_item(ev["id"], {"to_status": "ADMITTED"}, inv1), "ev_admit")
    scope = _d(
        api_client.transition_collection_scope(scope["id"], {"to_status": "COLLECTED"}, inv1),
        "collect_scope",
    )
    return {"notice": notice, "scope": scope, "evidence": ev}


def add_completed_interview(case_id: str, witness_ref: str = "W-1", interviewer_id: str = None,
                            scheduled_start: str = "2026-05-08T14:00:00Z",
                            scheduled_end: str = "2026-05-08T15:00:00Z"):
    """Schedule + UPJOHN_DELIVERED + COMPLETED. Returns interview dict."""
    interviewer_id = interviewer_id or TEST_DEFAULTS["INTERVIEWER_ID"]
    payload = create_interview_payload(
        witness_ref=witness_ref,
        interviewer_id=interviewer_id,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    interview = _d(api_client.create_interview(case_id, payload, INV), "create_interview")
    interview = _d(
        api_client.transition_interview(interview["id"], {"to_status": "UPJOHN_DELIVERED"}, inv1),
        "upjohn",
    )
    interview = _d(
        api_client.transition_interview(
            interview["id"],
            {"to_status": "COMPLETED", "completion_note": "memo"},
            inv1,
        ),
        "complete",
    )
    return interview


def add_allegation_linked(case_id: str, **overrides):
    """Allegation filed (SUBMITTED) and transitioned to LINKED. Returns dict."""
    alg = _d(
        api_client.create_allegation(case_id, create_allegation_payload(**overrides), IC),
        "create_allegation",
    )
    return alg


def add_subject(case_id: str, **overrides):
    return _d(
        api_client.create_subject(case_id, create_subject_payload(**overrides), INV),
        "create_subject",
    )


# ---------------------------------------------------------------------------
# Tier 4: FINDINGS with FINAL SUBSTANTIATED finding
# ---------------------------------------------------------------------------

def setup_findings_case(with_evidence: bool = True, with_interview: bool = True,
                        severity: str = "HIGH", category: str = "FRAUD",
                        department: str = "Finance", subject_emp: str = None):
    """Walk a case to FINDINGS with allegation LINKED + subject attached.

    Returns dict(case, allegation, subject, plan, evidence, interview).
    Note: allegation remains TRIAGED unless explicitly transitioned to LINKED
    by the caller before the case leaves TRIAGED/PLANNING/FIELDWORK/FINDINGS.
    """
    subject_emp = subject_emp or TEST_DEFAULTS["EMPLOYEE_REF"]
    bundle = create_case_in_fieldwork(severity=severity, allegation_category=category,
                                      department=department)
    case = bundle["case"]
    # Allegation must be filed and LINKED while the case is in
    # TRIAGED/PLANNING/FIELDWORK/FINDINGS. File it before triage, link it
    # after triage cascade moves it to TRIAGED.
    # The case is now in FIELDWORK; create allegation now, then triage cascade
    # won't move it. Create allegation then link it now (case is FIELDWORK,
    # which permits TRIAGED->LINKED).
    alg = add_allegation_linked(case["id"])
    # Allegation created while case is in FIELDWORK starts in SUBMITTED.
    # Move SUBMITTED->TRIAGED->LINKED.
    _d(api_client.transition_allegation(alg["id"], {"to_status": "TRIAGED"}, IC),
       "allegation_triage")
    alg = _d(api_client.transition_allegation(alg["id"], {"to_status": "LINKED"}, IC),
             "allegation_link")
    subj = add_subject(case["id"], employee_ref=subject_emp)
    ev = None
    interview = None
    if with_evidence:
        ev = add_collected_scope_with_admitted_evidence(case["id"],
                                                        custodian_ref=subject_emp)["evidence"]
    if with_interview:
        interview = add_completed_interview(case["id"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    case = _d(
        api_client.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1),
        "case_to_findings",
    )
    return {
        "case": case,
        "allegation": alg,
        "subject": subj,
        "plan": bundle["plan"],
        "evidence": ev,
        "interview": interview,
    }


def setup_final_substantiated_finding(severity: str = "HIGH", subject_emp: str = None):
    """Case in FINDINGS with one FINAL SUBSTANTIATED finding (score 0.70).

    Score: 1 ADMITTED evidence (0.25) + 1 COMPLETED interview (0.15) +
    HIGH consistency (0.30) = 0.70.
    """
    bundle = setup_findings_case(with_evidence=True, with_interview=True,
                                 severity=severity, subject_emp=subject_emp)
    case = bundle["case"]
    finding_payload = {
        "allegation_id": bundle["allegation"]["id"],
        "subject_id": bundle["subject"]["id"],
        "evidence_item_ids": [bundle["evidence"]["id"]],
    }
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    finding = _d(api_client.create_finding(case["id"], finding_payload, inv1), "create_finding")
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    cal_payload = create_calibrate_payload(consistency_level="HIGH", finding_type="SUBSTANTIATED")
    finding = _d(api_client.transition_finding(finding["id"], cal_payload, hr1), "calibrate_finding")
    fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
    finding = _d(api_client.transition_finding(finding["id"], {"to_status": "FINAL"}, fin),
                 "finalize_finding")
    bundle["finding"] = finding
    bundle["case"] = _d(api_client.get_case(case["id"], IC), "reread_case")
    return bundle


def setup_disposition_case(severity: str = "HIGH", subject_emp: str = None,
                           finding_type: str = "SUBSTANTIATED"):
    """Case progressed to DISPOSITION with one FINAL finding (no open recs)."""
    if finding_type == "SUBSTANTIATED":
        bundle = setup_final_substantiated_finding(severity=severity, subject_emp=subject_emp)
    else:
        # INCONCLUSIVE finding path: no evidence/interview needed
        bundle = setup_findings_case(with_evidence=False, with_interview=False,
                                     severity=severity, subject_emp=subject_emp)
        case = bundle["case"]
        finding_payload = {
            "allegation_id": bundle["allegation"]["id"],
            "subject_id": bundle["subject"]["id"],
        }
        inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
        finding = _d(api_client.create_finding(case["id"], finding_payload, inv1), "create_finding")
        hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
        cal_payload = create_calibrate_payload(consistency_level="MEDIUM",
                                               finding_type=finding_type)
        finding = _d(api_client.transition_finding(finding["id"], cal_payload, hr1),
                     "calibrate_finding")
        fin = make_manager_headers(TEST_DEFAULTS["FINALIZER_ID"])
        finding = _d(api_client.transition_finding(finding["id"], {"to_status": "FINAL"}, fin),
                     "finalize_finding")
        bundle["finding"] = finding
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    case = bundle["case"]
    case = _d(api_client.transition_case(case["id"], {"to_status": "DISPOSITION"}, mgr),
              "case_to_disposition")
    bundle["case"] = case
    return bundle


# ---------------------------------------------------------------------------
# Tier 5: full lifecycle (CLOSED case) and other composites
# ---------------------------------------------------------------------------

def setup_closed_case():
    """Case progressed to CLOSED with: one FINAL SUBSTANTIATED finding,
    one APPROVED disciplinary recommendation, one DISTRIBUTED RESTRICTED report,
    one VERIFIED remediation action. Returns dict with all artifacts."""
    bundle = setup_disposition_case(severity="HIGH", finding_type="SUBSTANTIATED")
    case = bundle["case"]
    finding = bundle["finding"]
    hr1 = make_hr_headers(TEST_DEFAULTS["HR_ID"])
    rec = _d(
        api_client.create_disciplinary_recommendation(
            finding["id"], create_recommendation_payload(), hr1
        ),
        "create_rec",
    )
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    rec = _d(
        api_client.transition_disciplinary_recommendation(rec["id"], {"to_status": "APPROVED"}, mgr),
        "approve_rec",
    )
    # DISPOSITION -> REMEDIATION
    case = _d(api_client.transition_case(case["id"], {"to_status": "REMEDIATION"}, mgr),
              "case_to_remediation")
    # Create DISTRIBUTED report while in REMEDIATION (allowed per PRD)
    case_fresh = _d(api_client.get_case(case["id"], IC), "reread_case")
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    report_payload = create_report_payload(
        title="Final Report",
        distribution_tier="RESTRICTED",
        report_privilege_type="WORK_PRODUCT",
        expected_case_version=case_fresh["version"],
    )
    report = _d(api_client.create_report(case["id"], report_payload, inv1), "create_report")
    report = _d(api_client.transition_report(report["id"], {"to_status": "LEGAL_REVIEW"}, inv1),
                "report_legal_review")
    report = _d(
        api_client.transition_report(report["id"], {"to_status": "DISTRIBUTION_APPROVED"}, GC),
        "report_approved",
    )
    report = _d(
        api_client.transition_report(report["id"], {"to_status": "DISTRIBUTED"}, GC),
        "report_distributed",
    )
    # Remediation action -> VERIFIED
    rem = _d(
        api_client.create_remediation_action(case["id"], create_remediation_payload(), hr1),
        "create_rem",
    )
    _d(api_client.transition_remediation_action(rem["id"], {"to_status": "IN_PROGRESS"}, hr1),
       "rem_in_progress")
    _d(api_client.transition_remediation_action(rem["id"], {"to_status": "AWAITING_VERIFICATION"}, hr1),
       "rem_awaiting")
    aud = make_auditor_headers(TEST_DEFAULTS["AUDITOR_ID"])
    rem = _d(
        api_client.transition_remediation_action(rem["id"], {"to_status": "VERIFIED"}, aud),
        "rem_verify",
    )
    case = _d(api_client.transition_case(case["id"], {"to_status": "CLOSED"}, mgr), "case_close")
    bundle.update({
        "case": case,
        "recommendation": rec,
        "report": report,
        "remediation": rem,
    })
    return bundle


def setup_disclosure_pending(case_severity: str = "CRITICAL"):
    """Case in FINDINGS with a PENDING SelfDisclosureDecision. Returns dict."""
    bundle = create_case_in_fieldwork(severity=case_severity, allegation_category="BRIBERY",
                                      department="Sales")
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    case = _d(api_client.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1),
              "case_to_findings")
    case_fresh = _d(api_client.get_case(case["id"], GC), "reread_case")
    payload = create_disclosure_payload(expected_case_version=case_fresh["version"])
    decision = _d(api_client.create_self_disclosure_decision(case["id"], payload, GC),
                  "create_disclosure")
    bundle["case"] = _d(api_client.get_case(case["id"], IC), "reread_case_2")
    bundle["disclosure"] = decision
    return bundle
