"""Composite setup helpers — multi-step state builders.

These walk the API through the PRD-mandated lifecycle (intake -> scoped ->
investigating -> confirmed -> contained -> closed) so individual tests can
target a specific mid-lifecycle state without re-implementing the preamble.
Every fixture returns domain dicts (parsed JSON `data` payloads), never raw
responses.

The logical clock starts at 2026-05-01T00:00:00Z (PRD §3.13); fixtures assume
that startup default unless they explicitly advance the clock.
"""
from typing import List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_affected_subject_payload,
    create_credit_monitoring_offer_payload,
    create_evidence_item_payload,
    create_forensic_scope_payload,
    create_incident_payload,
    create_jurisdiction_evaluation_payload,
    create_mailing_batch_payload,
    create_notice_payload,
    create_call_center_staffing_plan_payload,
    create_custody_log_payload,
)
from .test_users import (
    TEST_USERS,
    make_affected_subject_headers,
)


# Re-export for convenience
IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]
PC = TEST_USERS["privacy_counsel_headers"]
GC = TEST_USERS["general_counsel_headers"]
DA = TEST_USERS["data_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1 — State progression (incident)
# ---------------------------------------------------------------------------

def create_incident(**overrides) -> dict:
    """Create an INTAKE incident (PRD §3.1). Returns the incident dict."""
    resp = api_client.create_incident(create_incident_payload(**overrides), IC)
    return get_success_data(resp)


def create_incident_in_scoped_state(**overrides) -> Tuple[dict, dict]:
    """Incident + first ForensicScope created (INTAKE -> SCOPED).
    Returns (incident, scope).
    """
    inc = create_incident(**overrides)
    scope_resp = api_client.create_forensic_scope(
        inc["id"], create_forensic_scope_payload(), FL
    )
    scope = get_success_data(scope_resp)
    inc = get_success_data(api_client.get_incident(inc["id"], IC))
    return inc, scope


def create_incident_in_investigating_state(
    subject_count: int = 1,
    verify_subjects: bool = True,
    add_sealed_evidence: bool = True,
    scope_elements: Optional[List[str]] = None,
    exfiltration_likelihood_pct: int = 100,
    subject_state_code: str = "CA",
    subject_record_count: int = 1,
    **incident_overrides,
) -> dict:
    """Walk incident INTAKE -> SCOPED -> INVESTIGATING with optional evidence
    and subjects. Returns a dict of the full context.

    Keys: incident, scope, evidence (optional), subjects (list).
    """
    scope_elements = scope_elements or ["SSN"]
    inc = create_incident(**incident_overrides)
    scope_resp = api_client.create_forensic_scope(
        inc["id"],
        create_forensic_scope_payload(
            data_elements_at_risk=scope_elements,
            exfiltration_likelihood_pct=exfiltration_likelihood_pct,
        ),
        FL,
    )
    scope = get_success_data(scope_resp)
    baseline_resp = api_client.baseline_forensic_scope(inc["id"], scope["id"], FL)
    scope = get_success_data(baseline_resp)

    evidence = None
    if add_sealed_evidence:
        ev_resp = api_client.create_evidence_item(
            inc["id"], create_evidence_item_payload(), FL
        )
        ev = get_success_data(ev_resp)
        seal_resp = api_client.seal_evidence_item(inc["id"], ev["id"], FL)
        evidence = get_success_data(seal_resp)

    subjects: List[dict] = []
    for i in range(subject_count):
        subj_resp = api_client.create_affected_subject(
            inc["id"],
            create_affected_subject_payload(
                external_subject_ref=f"S{i+1}",
                full_name=f"Subject {i+1}",
                residence_state_code=subject_state_code,
                data_elements_exposed=list(scope_elements),
                record_count=subject_record_count,
            ),
            DA,
        )
        subj = get_success_data(subj_resp)
        if verify_subjects:
            v_resp = api_client.verify_affected_subject(inc["id"], subj["id"], DA)
            subj = get_success_data(v_resp)
        subjects.append(subj)

    inc = get_success_data(api_client.get_incident(inc["id"], IC))
    return {
        "incident": inc,
        "scope": scope,
        "evidence": evidence,
        "subjects": subjects,
    }


def create_incident_confirmed(
    subject_count: int = 1,
    jurisdiction_payloads: Optional[List[dict]] = None,
    **kwargs,
) -> dict:
    """Walk incident through CONFIRMED. Registers one or more
    JurisdictionEvaluation rows (defaults to a single CA row threshold=1,
    deadline 30 CALENDAR_DAYS) BEFORE the confirm call so they trigger.

    Returns dict with keys: incident, scope, evidence, subjects,
    jurisdiction_evaluations.
    """
    ctx = create_incident_in_investigating_state(subject_count=subject_count, **kwargs)
    inc = ctx["incident"]

    jes = []
    if jurisdiction_payloads is None:
        jurisdiction_payloads = [create_jurisdiction_evaluation_payload()]
    for jp in jurisdiction_payloads:
        je_resp = api_client.create_jurisdiction_evaluation(inc["id"], jp, PC)
        jes.append(get_success_data(je_resp))

    confirm_resp = api_client.confirm_incident(inc["id"], IC)
    inc = get_success_data(confirm_resp)

    # Refresh JEs (status flipped to TRIGGERED, deadline_at computed)
    refreshed = []
    for je in jes:
        refreshed.append(
            get_success_data(
                api_client.get_jurisdiction_evaluation(inc["id"], je["id"], PC)
            )
        )
    ctx["incident"] = inc
    ctx["jurisdiction_evaluations"] = refreshed
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — Notice lifecycle
# ---------------------------------------------------------------------------

def create_draft_notice(
    incident: dict,
    jurisdiction_evaluation: dict,
    creator_headers=None,
    body_text: Optional[str] = None,
) -> dict:
    """Create a Notice in DRAFT (uses current incident.version)."""
    headers = creator_headers or PC
    inc_now = get_success_data(api_client.get_incident(incident["id"], IC))
    overrides = {}
    if body_text is not None:
        overrides["body_text"] = body_text
    resp = api_client.create_notice(
        incident["id"],
        create_notice_payload(
            jurisdiction_evaluation_id=jurisdiction_evaluation["id"],
            expected_incident_version=inc_now["version"],
            **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def create_notice_in_legal_review(
    incident: dict,
    jurisdiction_evaluation: dict,
    creator_headers=None,
) -> dict:
    """Notice DRAFT -> LEGAL_REVIEW."""
    headers = creator_headers or PC
    notice = create_draft_notice(
        incident, jurisdiction_evaluation, creator_headers=headers
    )
    resp = api_client.submit_notice_for_review(incident["id"], notice["id"], headers)
    return get_success_data(resp)


def create_approved_notice(
    incident: dict,
    jurisdiction_evaluation: dict,
    creator_headers=None,
    approver_headers=None,
) -> dict:
    """Notice DRAFT -> LEGAL_REVIEW -> APPROVED."""
    notice = create_notice_in_legal_review(
        incident, jurisdiction_evaluation, creator_headers=creator_headers
    )
    approve_headers = approver_headers or GC
    resp = api_client.approve_notice(incident["id"], notice["id"], approve_headers)
    return get_success_data(resp)


def create_locked_notice(
    incident: dict,
    jurisdiction_evaluation: dict,
    creator_headers=None,
    approver_headers=None,
) -> dict:
    """Notice DRAFT -> LEGAL_REVIEW -> APPROVED -> LOCKED_FOR_MAIL."""
    notice = create_approved_notice(
        incident,
        jurisdiction_evaluation,
        creator_headers=creator_headers,
        approver_headers=approver_headers,
    )
    resp = api_client.lock_notice_for_mail(incident["id"], notice["id"], PC)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3 — Mailing batch lifecycle
# ---------------------------------------------------------------------------

def create_mailing_batch_for_notice(incident: dict, notice: dict, **overrides) -> dict:
    """Create a MailingBatch in QUEUED. Bumps incident notification_status
    APPROVED -> DISPATCHING when this is the first batch (PRD §3.8)."""
    inc_now = get_success_data(api_client.get_incident(incident["id"], IC))
    resp = api_client.create_mailing_batch(
        incident["id"],
        create_mailing_batch_payload(
            notice_id=notice["id"],
            expected_incident_version=inc_now["version"],
            **overrides,
        ),
        PC,
    )
    return get_success_data(resp)


def create_batch_in_production(incident: dict, notice: dict, **overrides) -> dict:
    """QUEUED -> IN_PRODUCTION. Subjects in VERIFIED flip to NOTICE_QUEUED."""
    batch = create_mailing_batch_for_notice(incident, notice, **overrides)
    resp = api_client.start_production_mailing_batch(
        incident["id"], batch["id"], PC
    )
    return get_success_data(resp)


def setup_dispatching_incident_with_queued_batch(
    subject_count: int = 1,
) -> dict:
    """Incident CONFIRMED + notice LOCKED_FOR_MAIL + MailingBatch QUEUED.
    Subjects are still VERIFIED (no production started yet).
    Returns dict with keys: incident, scope, evidence, subjects,
    jurisdiction_evaluations, notice, batch.
    """
    ctx = create_incident_confirmed(subject_count=subject_count)
    inc = ctx["incident"]
    je = ctx["jurisdiction_evaluations"][0]
    notice = create_locked_notice(inc, je)
    batch = create_mailing_batch_for_notice(inc, notice)
    inc = get_success_data(api_client.get_incident(inc["id"], IC))
    ctx["incident"] = inc
    ctx["notice"] = notice
    ctx["batch"] = batch
    return ctx


def setup_incident_after_mark_shipped(subject_count: int = 1) -> dict:
    """Full path through DISPATCHING with batch marked SHIPPED.
    All verified subjects transition to NOTIFIED."""
    ctx = setup_dispatching_incident_with_queued_batch(subject_count=subject_count)
    inc = ctx["incident"]
    batch = ctx["batch"]
    resp = api_client.start_production_mailing_batch(inc["id"], batch["id"], PC)
    batch = get_success_data(resp)
    resp = api_client.mark_shipped_mailing_batch(inc["id"], batch["id"], PC)
    batch = get_success_data(resp)
    inc = get_success_data(api_client.get_incident(inc["id"], IC))
    ctx["incident"] = inc
    ctx["batch"] = batch
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — Credit monitoring offers
# ---------------------------------------------------------------------------

def create_issued_offer(incident: dict, subject: dict, **overrides) -> dict:
    """Create an ISSUED CreditMonitoringOffer. Subject flips to OFFERED_PENDING."""
    resp = api_client.create_credit_monitoring_offer(
        incident["id"],
        create_credit_monitoring_offer_payload(subject["id"], **overrides),
        PC,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5 — Custody / staffing / regulator / remediation helpers
# ---------------------------------------------------------------------------

def create_custody_log(incident: dict, evidence_item_id: str, **overrides) -> dict:
    resp = api_client.create_custody_log(
        incident["id"],
        create_custody_log_payload(evidence_item_id, **overrides),
        FL,
    )
    return get_success_data(resp)


def create_staffing_plan(incident: dict, **overrides) -> dict:
    resp = api_client.create_call_center_staffing_plan(
        incident["id"], create_call_center_staffing_plan_payload(**overrides), IC
    )
    return get_success_data(resp)


__all__ = [
    "IC", "FL", "PC", "GC", "DA", "AUD",
    "create_incident",
    "create_incident_in_scoped_state",
    "create_incident_in_investigating_state",
    "create_incident_confirmed",
    "create_draft_notice",
    "create_notice_in_legal_review",
    "create_approved_notice",
    "create_locked_notice",
    "create_mailing_batch_for_notice",
    "create_batch_in_production",
    "setup_dispatching_incident_with_queued_batch",
    "setup_incident_after_mark_shipped",
    "create_issued_offer",
    "create_custody_log",
    "create_staffing_plan",
    "make_affected_subject_headers",
]
