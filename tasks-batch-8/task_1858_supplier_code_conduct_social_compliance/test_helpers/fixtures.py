"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: Auditor calls are entity-backed by Auditor and
SupplierContact calls are entity-backed by Supplier. Every ownership-gated
call in these helpers builds its headers from the real entity id via
make_auditor_headers / make_supplier_contact_headers; the shared constants
are used only for the four opaque roles.
"""
from math import isqrt

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUDIT_END,
    AUDIT_START,
    EXTERNAL_AUDIT_DATE_FRESH,
)
from .factories import (
    cap_action,
    create_audit_payload,
    create_auditor_payload,
    create_cap_payload,
    create_claim_payload,
    create_code_acknowledgment_payload,
    create_code_version_payload,
    create_facility_payload,
    create_fee_review_payload,
    create_finding_payload,
    create_grievance_payload,
    create_interview_record_payload,
    create_reimbursement_payload,
    create_supplier_payload,
    fee_item,
)
from .test_users import (
    TEST_USERS,
    make_auditor_headers,
    make_supplier_contact_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORDINATOR = TEST_USERS["audit_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
HOTLINE = TEST_USERS["worker_hotline_headers"]


def ceil_sqrt(n: int) -> int:
    """Ceiling of the square root: the worker interview minimum sample."""
    root = isqrt(n)
    return root if root * root == n else root + 1


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple reads
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the program logical clock. Returns the clock echo payload."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_code_version(version_label="CoC v1.0",
                        effective_from="2026-01-01T00:00:00Z",
                        zero_tolerance_categories=("FORCED_LABOR",),
                        publish=True):
    """Create a code version (starts DRAFT) and optionally publish it."""
    payload = create_code_version_payload(
        version_label=version_label,
        effective_from=effective_from,
        zero_tolerance_categories=list(zero_tolerance_categories),
    )
    cv = get_success_data(api_client.create_code_version(payload, ADMIN))
    if publish:
        cv = get_success_data(
            api_client.transition_code_version(
                cv["id"], {"to_status": "PUBLISHED"}, ADMIN
            )
        )
    return cv


def create_supplier(legal_name="Test Supplier Ltd", country_code="US",
                    sector="FOOD"):
    """Register a supplier (starts ONBOARDING, both scores 100)."""
    payload = create_supplier_payload(
        legal_name=legal_name, country_code=country_code, sector=sector
    )
    return get_success_data(api_client.create_supplier(payload, ADMIN))


def get_supplier(supplier_id):
    return get_success_data(api_client.get_supplier(supplier_id, OFFICER))


def get_scorecard(supplier_id):
    return get_success_data(api_client.get_supplier_scorecard(supplier_id, OFFICER))


def get_scoping(facility_id):
    return get_success_data(api_client.get_facility_scoping(facility_id, OFFICER))


def get_audit(audit_id):
    return get_success_data(api_client.get_audit(audit_id, OFFICER))


def get_finding(finding_id):
    return get_success_data(api_client.get_finding(finding_id, OFFICER))


def get_cap(cap_id):
    return get_success_data(api_client.get_corrective_action_plan(cap_id, OFFICER))


def get_review(review_id):
    return get_success_data(api_client.get_recruitment_fee_review(review_id, OFFICER))


def get_claim(claim_id):
    return get_success_data(
        api_client.get_mutual_recognition_claim(claim_id, OFFICER)
    )


def acknowledge_code(supplier, code_version_id, signer_name="A Signatory",
                     signer_title="CEO"):
    """Acknowledge a published code version on the supplier's behalf.

    OCC: re-reads the supplier first so expected_supplier_version always
    matches the current version. Returns the acknowledgment.
    """
    fresh = get_supplier(supplier["id"])
    payload = create_code_acknowledgment_payload(
        supplier_id=fresh["id"],
        code_version_id=code_version_id,
        expected_supplier_version=fresh["version"],
        signer_name=signer_name,
        signer_title=signer_title,
    )
    return get_success_data(
        api_client.create_code_acknowledgment(
            payload, make_supplier_contact_headers(fresh["id"])
        )
    )


def create_facility(supplier_id, name="Test Facility", country_code="US",
                    worker_count=10, processes=("packing",)):
    """Register a facility (baseline risk computed at creation)."""
    payload = create_facility_payload(
        supplier_id,
        name=name,
        country_code=country_code,
        worker_count=worker_count,
        processes=list(processes),
    )
    return get_success_data(api_client.create_facility(payload, ADMIN))


def create_auditor(full_name="Lead Auditor", firm_name="AuditCo",
                   certifications=("SA8000",), country_codes_covered=("US",)):
    """Register an auditor (starts ACTIVE)."""
    payload = create_auditor_payload(
        full_name=full_name,
        firm_name=firm_name,
        certifications=list(certifications),
        country_codes_covered=list(country_codes_covered),
    )
    return get_success_data(api_client.create_auditor(payload, COORDINATOR))


def schedule_audit(facility_id, auditor_id, audit_type="INITIAL",
                   announcement="ANNOUNCED", scheduled_start=AUDIT_START,
                   scheduled_end=AUDIT_END):
    """Schedule an audit (starts SCHEDULED, tallies zeroed)."""
    payload = create_audit_payload(
        facility_id,
        auditor_id,
        audit_type=audit_type,
        announcement=announcement,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    return get_success_data(api_client.create_audit(payload, COORDINATOR))


def begin_audit(audit):
    """Advance the clock to the audit's scheduled_start and start it as the
    assigned lead auditor. Returns the IN_PROGRESS audit."""
    set_clock(audit["scheduled_start"])
    return get_success_data(
        api_client.start_audit(
            audit["id"], make_auditor_headers(audit["auditor_id"])
        )
    )


def record_finding(audit_id, auditor_id, classification="MAJOR", category="WAGES",
                   description="Finding recorded during fieldwork"):
    payload = create_finding_payload(
        classification=classification, category=category, description=description
    )
    return get_success_data(
        api_client.create_finding(
            audit_id, payload, make_auditor_headers(auditor_id)
        )
    )


def record_interviews(audit_id, auditor_id, interview_count=4,
                      forced_labor_indicators=False,
                      recruitment_fee_indicators=False, notes=None):
    payload = create_interview_record_payload(
        interview_count=interview_count,
        forced_labor_indicators=forced_labor_indicators,
        recruitment_fee_indicators=recruitment_fee_indicators,
    )
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(
        api_client.create_worker_interview_record(
            audit_id, payload, make_auditor_headers(auditor_id)
        )
    )


def submit_report(audit_id, auditor_id):
    return get_success_data(
        api_client.submit_audit_report(
            audit_id, make_auditor_headers(auditor_id)
        )
    )


def decide_audit(audit_id, decision, correction_note=None):
    payload = {"decision": decision}
    if correction_note is not None:
        payload["correction_note"] = correction_note
    return get_success_data(api_client.decide_audit(audit_id, payload, OFFICER))


def cancel_audit(audit_id, reason="Rescoped"):
    return get_success_data(
        api_client.cancel_audit(audit_id, {"reason": reason}, COORDINATOR)
    )


# ---------------------------------------------------------------------------
# Tier 2: the program workspace (published code + ACTIVE supplier + facility)
# ---------------------------------------------------------------------------

def setup_active_supplier(sector="FOOD", supplier_country="US",
                          zero_tolerance_categories=("FORCED_LABOR",),
                          legal_name="Test Supplier Ltd",
                          version_label="CoC v1.0"):
    """Published code version + supplier acknowledged into ACTIVE.

    Returns {"code_version", "supplier", "acknowledgment"} with the supplier
    re-read after acknowledgment (status ACTIVE, current code version set).
    """
    cv = create_code_version(
        version_label=version_label,
        zero_tolerance_categories=zero_tolerance_categories,
    )
    supplier = create_supplier(legal_name=legal_name,
                               country_code=supplier_country, sector=sector)
    ack = acknowledge_code(supplier, cv["id"])
    supplier = get_supplier(supplier["id"])
    return {"code_version": cv, "supplier": supplier, "acknowledgment": ack}


# ---------------------------------------------------------------------------
# Tier 3: audit lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_in_progress_audit(sector="FOOD", supplier_country="US",
                            facility_country="US", worker_count=10,
                            zt_categories=("FORCED_LABOR",),
                            audit_type="INITIAL", announcement="ANNOUNCED",
                            scheduled_start=AUDIT_START,
                            scheduled_end=AUDIT_END,
                            auditor_countries=None, with_verifier=True,
                            supplier_name="Test Supplier Ltd",
                            facility_name="Test Facility",
                            facility_processes=("packing",)):
    """ACTIVE supplier + facility + lead auditor + audit IN_PROGRESS.

    The clock is advanced to the audit's scheduled_start. Returns a context
    dict: code_version, supplier, facility, auditor, verifier (optional),
    audit.
    """
    if auditor_countries is None:
        auditor_countries = sorted({facility_country, "US"})
    ctx = setup_active_supplier(
        sector=sector,
        supplier_country=supplier_country,
        zero_tolerance_categories=zt_categories,
        legal_name=supplier_name,
    )
    facility = create_facility(
        ctx["supplier"]["id"],
        name=facility_name,
        country_code=facility_country,
        worker_count=worker_count,
        processes=facility_processes,
    )
    auditor = create_auditor(country_codes_covered=auditor_countries)
    ctx["facility"] = facility
    ctx["auditor"] = auditor
    if with_verifier:
        ctx["verifier"] = create_auditor(
            full_name="Verification Auditor",
            firm_name="VerifyCo",
            certifications=("SMETA",),
            country_codes_covered=auditor_countries,
        )
    audit = schedule_audit(
        facility["id"], auditor["id"],
        audit_type=audit_type, announcement=announcement,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    ctx["audit"] = begin_audit(audit)
    return ctx


def setup_report_submitted_audit(interview_count=None, **kwargs):
    """IN_PROGRESS audit + interview record + report submitted."""
    ctx = setup_in_progress_audit(**kwargs)
    if interview_count is None:
        interview_count = ceil_sqrt(ctx["facility"]["worker_count"])
    ctx["interview_record"] = record_interviews(
        ctx["audit"]["id"], ctx["auditor"]["id"], interview_count=interview_count
    )
    ctx["audit"] = submit_report(ctx["audit"]["id"], ctx["auditor"]["id"])
    return ctx


def setup_completed_audit(**kwargs):
    """Full happy path: audit REPORT_SUBMITTED -> COMPLETED (no findings, no
    grievances)."""
    ctx = setup_report_submitted_audit(**kwargs)
    ctx["audit"] = decide_audit(ctx["audit"]["id"], "COMPLETE")
    return ctx


def setup_failed_zt_audit(zt_category="FORCED_LABOR", **kwargs):
    """IN_PROGRESS audit plus one ZERO_TOLERANCE finding: the audit auto-fails
    to FAILED_ZT and the supplier drops to PROBATION. Returns the context with
    ctx["zt_finding"] and a refreshed ctx["audit"]."""
    kwargs.setdefault("zt_categories", ("FORCED_LABOR", "CHILD_LABOR"))
    ctx = setup_in_progress_audit(**kwargs)
    ctx["zt_finding"] = record_finding(
        ctx["audit"]["id"], ctx["auditor"]["id"],
        classification="ZERO_TOLERANCE", category=zt_category,
        description="Zero-tolerance finding",
    )
    ctx["audit"] = get_audit(ctx["audit"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: corrective action plan lifecycle
# ---------------------------------------------------------------------------

def create_cap(finding_id, supplier_id, actions=None):
    payload = create_cap_payload(finding_id, actions=actions)
    return get_success_data(
        api_client.create_corrective_action_plan(
            payload, make_supplier_contact_headers(supplier_id)
        )
    )


def review_cap(cap_id, decision="APPROVE", rejection_reason=None):
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return get_success_data(
        api_client.review_corrective_action_plan(cap_id, payload, OFFICER)
    )


def resubmit_cap(cap_id, supplier_id, actions=None):
    payload = {"actions": actions if actions is not None else [cap_action()]}
    return get_success_data(
        api_client.resubmit_corrective_action_plan(
            cap_id, payload, make_supplier_contact_headers(supplier_id)
        )
    )


def request_cap_verification(cap_id, supplier_id):
    return get_success_data(
        api_client.request_cap_verification(
            cap_id, make_supplier_contact_headers(supplier_id)
        )
    )


def verify_cap(cap_id, verifier_id, outcome="PASS",
               verification_note="Verified on site"):
    payload = {"outcome": outcome, "verification_note": verification_note}
    return get_success_data(
        api_client.verify_corrective_action_plan(
            cap_id, payload, make_auditor_headers(verifier_id)
        )
    )


def cap_full_pass_cycle(finding_id, supplier_id, verifier_id, actions=None):
    """Create -> approve -> request-verification -> verify PASS (independent
    auditor). Returns the VERIFIED_PASSED plan."""
    cap = create_cap(finding_id, supplier_id, actions=actions)
    cap = review_cap(cap["id"], "APPROVE")
    cap = request_cap_verification(cap["id"], supplier_id)
    return verify_cap(cap["id"], verifier_id, "PASS", "Verified on site")


# ---------------------------------------------------------------------------
# Tier 3: grievances
# ---------------------------------------------------------------------------

def file_grievance(facility_id, channel="HOTLINE", category="WAGES",
                   severity="CRITICAL", description="Worker grievance narrative"):
    payload = create_grievance_payload(
        facility_id, channel=channel, category=category,
        severity=severity, description=description,
    )
    return get_success_data(api_client.create_grievance(payload, HOTLINE))


def triage_grievance(grievance_id, action, resolution_note=None):
    payload = {"action": action}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return get_success_data(
        api_client.triage_grievance(grievance_id, payload, OFFICER)
    )


def resolve_grievance(grievance_id, resolution_note="Investigated and remedied"):
    """START_REVIEW then RESOLVE. Returns the RESOLVED grievance."""
    triage_grievance(grievance_id, "START_REVIEW")
    return triage_grievance(grievance_id, "RESOLVE", resolution_note)


# ---------------------------------------------------------------------------
# Tier 3: recruitment fee reviews and the reimbursement ledger
# ---------------------------------------------------------------------------

def create_fee_review(audit_id, auditor_id, workers_assessed=1, fee_items=None,
                      linked_grievance_id=None):
    payload = create_fee_review_payload(
        workers_assessed=workers_assessed,
        fee_items=fee_items if fee_items is not None else [],
    )
    if linked_grievance_id is not None:
        payload["linked_grievance_id"] = linked_grievance_id
    return get_success_data(
        api_client.create_recruitment_fee_review(
            audit_id, payload, make_auditor_headers(auditor_id)
        )
    )


def confirm_violation(review_id):
    return get_success_data(api_client.confirm_fee_violation(review_id, OFFICER))


def record_reimbursement(review_id, amount_cents, worker_ref=None):
    payload = create_reimbursement_payload(amount_cents)
    if worker_ref is not None:
        payload["worker_ref"] = worker_ref
    return get_success_data(
        api_client.create_reimbursement(review_id, payload, OFFICER)
    )


def setup_confirmed_review(num_items=1, amount_minor_units=300, currency="BDT",
                           **kwargs):
    """IN_PROGRESS audit + fee review + confirm-violation.

    Returns the audit context extended with ctx["review"] (status
    VIOLATION_CONFIRMED).
    """
    ctx = setup_in_progress_audit(**kwargs)
    items = [
        fee_item(worker_ref=f"W{i + 1}", amount_minor_units=amount_minor_units,
                 currency=currency)
        for i in range(num_items)
    ]
    review = create_fee_review(
        ctx["audit"]["id"], ctx["auditor"]["id"],
        workers_assessed=num_items, fee_items=items,
    )
    ctx["review"] = confirm_violation(review["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: mutual recognition claims
# ---------------------------------------------------------------------------

def create_claim(facility_id, supplier_id, program_name="SMETA",
                 external_audit_ref="EXT-2026-001",
                 external_audit_date=EXTERNAL_AUDIT_DATE_FRESH,
                 external_score=80):
    payload = create_claim_payload(
        facility_id,
        program_name=program_name,
        external_audit_ref=external_audit_ref,
        external_audit_date=external_audit_date,
        external_score=external_score,
    )
    return get_success_data(
        api_client.create_mutual_recognition_claim(
            payload, make_supplier_contact_headers(supplier_id)
        )
    )


def decide_claim(claim_id, decision, decision_reason=None):
    payload = {"decision": decision}
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return get_success_data(
        api_client.decide_mutual_recognition_claim(claim_id, payload, OFFICER)
    )


# ---------------------------------------------------------------------------
# Tier 4/5: composite scenario used by the dual-variant risk tests
# ---------------------------------------------------------------------------

def completed_audit_with_findings(findings=(), **kwargs):
    """IN_PROGRESS audit -> interview sample -> findings -> submit -> COMPLETE.

    `findings` is a list of (classification, category) tuples recorded while
    the audit is IN_PROGRESS (a ZERO_TOLERANCE entry auto-fails the audit and
    must come last; FAILED_ZT is terminal so no submit/decide follows).
    Returns the context with ctx["findings"] and the refreshed audit.
    """
    worker_count = kwargs.get("worker_count", 10)
    ctx = setup_in_progress_audit(**kwargs)
    ctx["interview_record"] = record_interviews(
        ctx["audit"]["id"], ctx["auditor"]["id"],
        interview_count=ceil_sqrt(worker_count),
    )
    ctx["findings"] = [
        record_finding(
            ctx["audit"]["id"], ctx["auditor"]["id"],
            classification=classification, category=category,
            description=f"{classification} {category} finding",
        )
        for classification, category in findings
    ]
    if any(c == "ZERO_TOLERANCE" for c, _ in findings):
        ctx["audit"] = get_audit(ctx["audit"]["id"])  # FAILED_ZT, terminal
    else:
        ctx["audit"] = submit_report(ctx["audit"]["id"], ctx["auditor"]["id"])
        ctx["audit"] = decide_audit(ctx["audit"]["id"], "COMPLETE")
    return ctx
