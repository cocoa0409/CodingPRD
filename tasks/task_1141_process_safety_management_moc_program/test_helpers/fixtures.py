"""Composite setup helpers for the PSM/MOC domain (PRD §3 workflows).

Every helper builds its preconditions from scratch through PRD-declared
endpoints (each test starts against an empty database) and uses the lenient
get_success_data() validator so setup failures surface as clear errors.

Identity threading: after creating a Personnel-backed actor, every
ownership-gated call uses that actor's per-instance headers
(make_*_headers(person["id"])) — never the shared fallback constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    classify_payload,
    clock_payload,
    create_action_item_payload,
    create_audit_payload,
    create_evidence_payload,
    create_extension_request_payload,
    create_incident_payload,
    create_moc_payload,
    create_personnel_payload,
    create_pha_study_payload,
    create_procedure_update_payload,
    create_pssr_payload,
    create_training_assignment_payload,
    create_unit_payload,
    verdict_payload,
)
from .test_users import (
    TEST_USERS,
    make_approver_headers,
    make_auditor_headers,
    make_investigator_headers,
    make_pssr_lead_headers,
    make_requester_headers,
    make_reviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creators and readers
# ---------------------------------------------------------------------------

def new_unit(**overrides):
    """Create a PlantUnit. Returns the unit dict."""
    return get_success_data(api_client.create_unit(create_unit_payload(**overrides), ADMIN))


def new_personnel(full_name, employee_ref, qualifications=None, active=None):
    """Create a Personnel record. Returns the personnel dict."""
    payload = create_personnel_payload(full_name=full_name, employee_ref=employee_ref)
    if qualifications is not None:
        payload["qualifications"] = qualifications
    if active is not None:
        payload["active"] = active
    return get_success_data(api_client.create_personnel(payload, ADMIN))


def set_clock(to_iso8601):
    """Advance the logical clock (PsmAdmin)."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def get_unit(unit_id):
    return get_success_data(api_client.get_unit(unit_id, MANAGER))


def get_moc(moc_id):
    return get_success_data(api_client.get_moc(moc_id, MANAGER))


def get_pssr(pssr_id):
    return get_success_data(api_client.get_pssr(pssr_id, MANAGER))


def get_pha_study(study_id):
    return get_success_data(api_client.get_pha_study(study_id, MANAGER))


def get_action_item(item_id):
    return get_success_data(api_client.get_action_item(item_id, MANAGER))


def get_audit(audit_id):
    return get_success_data(api_client.get_audit(audit_id, MANAGER))


def get_incident(incident_id):
    return get_success_data(api_client.get_incident(incident_id, MANAGER))


def moc_version(moc_id):
    """Freshly read MocRequest.version (for expected_moc_version OCC fields)."""
    return get_moc(moc_id)["version"]


def list_unit_action_items(unit_id, params=None):
    return get_success_data(api_client.list_unit_action_items(unit_id, MANAGER, params=params))


def list_moc_reviews(moc_id):
    return get_success_data(api_client.list_moc_reviews(moc_id, MANAGER))


def open_review_round(moc_id):
    """The latest (highest-round) TechnicalReview of a MOC — the OPEN one mid-cycle."""
    reviews = list_moc_reviews(moc_id)
    assert reviews, f"Expected at least one review round for MOC {moc_id}"
    return reviews[-1]


def list_moc_pssrs(moc_id):
    return get_success_data(api_client.list_moc_pssrs(moc_id, MANAGER))


def list_audit_findings(audit_id):
    return get_success_data(api_client.list_audit_findings(audit_id, MANAGER))


def list_extension_requests(moc_id):
    return get_success_data(api_client.list_extension_requests(moc_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1: state progression on MocRequest
# ---------------------------------------------------------------------------

def new_draft_moc(unit_id, requester_id, discipline="CHEMICAL", title="M", description="d"):
    """Create a MOC in DRAFT; requester_id stamped from the caller (PRD §3.2)."""
    payload = create_moc_payload(title=title, description=description, discipline=discipline)
    return get_success_data(api_client.create_moc(unit_id, payload, make_requester_headers(requester_id)))


def classify(moc_id, change_class="PERMANENT", severity=2, likelihood=2,
             temporary_start_date=None, temporary_duration_days=None,
             requires_pssr_override=None):
    """Classify a DRAFT MOC (PsmManager). Returns classified MOC."""
    payload = classify_payload(change_class=change_class,
                               screening_severity=severity,
                               screening_likelihood=likelihood)
    if temporary_start_date is not None:
        payload["temporary_start_date"] = temporary_start_date
    if temporary_duration_days is not None:
        payload["temporary_duration_days"] = temporary_duration_days
    if requires_pssr_override is not None:
        payload["requires_pssr_override"] = requires_pssr_override
    return get_success_data(api_client.classify_moc(moc_id, payload, MANAGER))


def submit(moc_id, requester_id):
    """Submit a CLASSIFIED MOC as its requester."""
    return get_success_data(api_client.submit_moc(moc_id, make_requester_headers(requester_id)))


def resubmit(moc_id, requester_id):
    return get_success_data(api_client.resubmit_moc(moc_id, make_requester_headers(requester_id)))


def submit_verdict_on_open_review(moc_id, reviewer_id, severity=2, likelihood=2,
                                  detection=1, verdict="ACCEPT", checklist_ok=True):
    """File a verdict on the MOC's latest OPEN review round. Returns the review."""
    review = open_review_round(moc_id)
    payload = verdict_payload(severity_score=severity, likelihood_score=likelihood,
                              detection_score=detection, verdict=verdict)
    if not checklist_ok:
        payload["design_basis_ok"] = False
    return get_success_data(api_client.submit_verdict(review["id"], payload, make_reviewer_headers(reviewer_id)))


def approve(moc_id, approver_id, conditions=None):
    """Approve an APPROVAL_PENDING MOC as OpsApprover (not the requester)."""
    payload = {}
    if conditions is not None:
        payload["conditions"] = conditions
    return get_success_data(api_client.approve_moc(moc_id, payload, make_approver_headers(approver_id)))


def mark_implemented(moc_id, requester_id):
    return get_success_data(api_client.mark_implemented(moc_id, make_requester_headers(requester_id)))


def authorize_startup(moc_id):
    return get_success_data(api_client.authorize_startup(moc_id, MANAGER))


def activate(moc_id, approver_id):
    return get_success_data(api_client.activate_moc(moc_id, make_approver_headers(approver_id)))


def close_moc(moc_id):
    return get_success_data(api_client.close_moc(moc_id, MANAGER))


def withdraw(moc_id, requester_id):
    return get_success_data(api_client.withdraw_moc(moc_id, make_requester_headers(requester_id)))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — units, studies, actors
# ---------------------------------------------------------------------------

def new_study(unit_id, method="HAZOP", initial_validated_at="2026-04-01"):
    """Create the unit's PHA study (PsmManager). Returns the study dict."""
    payload = create_pha_study_payload(method=method, initial_validated_at=initial_validated_at)
    return get_success_data(api_client.create_pha_study(unit_id, payload, MANAGER))


_actors_seq = itertools.count(1)


def create_standard_actors():
    """The four actors of the standard MOC lifecycle.

    Returns dict of Personnel dicts: req (requester), rev (CHEMICAL reviewer),
    app (OpsApprover), lead (PSSR_CERTIFIED lead).

    PRD §3.1: employee_ref is "unique across all personnel" — a test invoking
    this twice within one server lifetime would collide on fixed refs, so the
    refs are minted unique per call.
    """
    n = next(_actors_seq)
    return {
        "req": new_personnel("Req One", f"E-REQ-{n}"),
        "rev": new_personnel("Rev Two", f"E-REV-{n}", qualifications=["CHEMICAL"]),
        "app": new_personnel("App Three", f"E-APP-{n}"),
        "lead": new_personnel("Lead Four", f"E-LEAD-{n}", qualifications=["PSSR_CERTIFIED"]),
    }


def setup_unit_with_study(validated_at="2026-04-01", method="HAZOP", **unit_overrides):
    """Unit + CURRENT PHA study. Returns (unit, study)."""
    unit_overrides.setdefault("pha_cycle_months", 12)
    unit = new_unit(**unit_overrides)
    study = new_study(unit["id"], method=method, initial_validated_at=validated_at)
    return unit, study


# ---------------------------------------------------------------------------
# Tier 3: full MOC lifecycle shortcuts
# ---------------------------------------------------------------------------

def drive_moc_to_technical_review(unit_id, requester_id, reviewer_id,
                                  change_class="PERMANENT", severity=2, likelihood=2,
                                  temporary_start_date=None, temporary_duration_days=None):
    """create → classify → submit. Returns the MOC in TECHNICAL_REVIEW
    (or APPROVAL_PENDING for REPLACEMENT_IN_KIND, which bypasses review)."""
    moc = new_draft_moc(unit_id, requester_id)
    classify(moc["id"], change_class=change_class, severity=severity, likelihood=likelihood,
             temporary_start_date=temporary_start_date,
             temporary_duration_days=temporary_duration_days)
    return submit(moc["id"], requester_id)


def drive_moc_to_approval_pending(unit_id, requester_id, reviewer_id, **classify_kwargs):
    """Full path to APPROVAL_PENDING (review ACCEPT for non-RIK classes)."""
    moc = drive_moc_to_technical_review(unit_id, requester_id, reviewer_id, **classify_kwargs)
    if moc["status"] == "TECHNICAL_REVIEW":
        submit_verdict_on_open_review(moc["id"], reviewer_id)
        moc = get_moc(moc["id"])
    return moc


def drive_moc_to_approved(unit_id, requester_id, reviewer_id, approver_id,
                          conditions=None, **classify_kwargs):
    """Full path to APPROVED_IMPLEMENTATION. Returns the MOC."""
    moc = drive_moc_to_approval_pending(unit_id, requester_id, reviewer_id, **classify_kwargs)
    return approve(moc["id"], approver_id, conditions=conditions)


def publish_update_with_assignments(moc_id, trainee_ids, document_ref="SOP-1"):
    """Create → assign → publish a ProcedureUpdate (TrainingCoordinator).

    Returns (update_dict, {personnel_id: assignment_id})."""
    update = get_success_data(
        api_client.create_procedure_update(moc_id, create_procedure_update_payload(document_ref=document_ref), COORD))
    assignments = {}
    for trainee_id in trainee_ids:
        assignment = get_success_data(
            api_client.create_training_assignment(update["id"],
                                                  create_training_assignment_payload(trainee_id), COORD))
        assignments[trainee_id] = assignment["id"]
    update = get_success_data(api_client.publish_procedure_update(update["id"], COORD))
    return update, assignments


def complete_assignments(assignments, trainee_ids):
    """Complete the given assignments; each trainee completes their own."""
    for trainee_id in trainee_ids:
        get_success_data(api_client.complete_training_assignment(
            assignments[trainee_id], make_requester_headers(trainee_id)))


def drive_moc_to_implemented(unit_id, requester_id, reviewer_id, approver_id,
                             conditions=None, document_ref="SOP-1", **classify_kwargs):
    """Full path to IMPLEMENTED_PSSR_PENDING with 100% training coverage:
    approved + one PUBLISHED update whose sole assignment (the requester) is
    completed + mark-implemented. Returns the MOC."""
    moc = drive_moc_to_approved(unit_id, requester_id, reviewer_id, approver_id,
                                conditions=conditions, **classify_kwargs)
    _, assignments = publish_update_with_assignments(moc["id"], [requester_id], document_ref=document_ref)
    complete_assignments(assignments, [requester_id])
    return mark_implemented(moc["id"], requester_id)


def create_pssr_for_moc(moc_id, lead_id, window_start="2026-05-01", window_end="2026-05-05"):
    """Create a PSSR (PssrLead); reads the current MOC version for the OCC field."""
    version = moc_version(moc_id)
    payload = create_pssr_payload(version, field_window_start=window_start, field_window_end=window_end)
    return get_success_data(api_client.create_pssr(moc_id, payload, make_pssr_lead_headers(lead_id)))


def begin_pssr_fieldwork(pssr_id, lead_id):
    return get_success_data(api_client.begin_pssr_fieldwork(pssr_id, make_pssr_lead_headers(lead_id)))


def approve_pssr(pssr_id, lead_id):
    return get_success_data(api_client.approve_pssr(pssr_id, make_pssr_lead_headers(lead_id)))


def drive_moc_to_in_service(unit_id, requester_id, reviewer_id, approver_id, lead_id,
                            pssr_window=("2026-05-01", "2026-05-05"),
                            conditions=None, **classify_kwargs):
    """Full lifecycle to IN_SERVICE: implemented → PSSR (when required) approved
    → authorize-startup → activate. Returns the MOC."""
    moc = drive_moc_to_implemented(unit_id, requester_id, reviewer_id, approver_id,
                                   conditions=conditions, **classify_kwargs)
    if moc.get("requires_pssr"):
        pssr = create_pssr_for_moc(moc["id"], lead_id,
                                   window_start=pssr_window[0], window_end=pssr_window[1])
        begin_pssr_fieldwork(pssr["id"], lead_id)
        approve_pssr(pssr["id"], lead_id)
    moc = authorize_startup(moc["id"])
    return activate(moc["id"], approver_id)


def drive_moc_to_closed(unit_id, requester_id, reviewer_id, approver_id, lead_id,
                        **classify_kwargs):
    """Full lifecycle to CLOSED (PERMANENT/RIK close path). Returns the MOC."""
    moc = drive_moc_to_in_service(unit_id, requester_id, reviewer_id, approver_id, lead_id,
                                  **classify_kwargs)
    return close_moc(moc["id"])


def setup_implemented_scenario(change_class="PERMANENT", **classify_kwargs):
    """(unit, study, actors, moc) with the MOC at IMPLEMENTED_PSSR_PENDING."""
    unit, study = setup_unit_with_study()
    actors = create_standard_actors()
    moc = drive_moc_to_implemented(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                   actors["app"]["id"], change_class=change_class, **classify_kwargs)
    return unit, study, actors, moc


def setup_in_service_scenario(change_class="PERMANENT", conditions=None, **classify_kwargs):
    """(unit, study, actors, moc) with the MOC at IN_SERVICE."""
    unit, study = setup_unit_with_study()
    actors = create_standard_actors()
    moc = drive_moc_to_in_service(unit["id"], actors["req"]["id"], actors["rev"]["id"],
                                  actors["app"]["id"], actors["lead"]["id"],
                                  change_class=change_class, conditions=conditions, **classify_kwargs)
    return unit, study, actors, moc


# ---------------------------------------------------------------------------
# Tier 3b: action items and evidence
# ---------------------------------------------------------------------------

def new_manual_item(unit_id, assignee_id, priority="P1", due_in_days=None, title="a"):
    """Manual ActionItem (PsmManager). Returns the item dict (OPEN)."""
    payload = create_action_item_payload(assignee_id, title=title, priority=priority)
    if due_in_days is not None:
        payload["due_in_days"] = due_in_days
    return get_success_data(api_client.create_action_item(unit_id, payload, MANAGER))


def attach_evidence(item_id, uploader_id, file_ref="s3://ev/e.pdf", description="evidence"):
    """Attach one evidence item as the assignee. Returns the EvidenceItem."""
    return get_success_data(api_client.add_evidence(
        item_id, create_evidence_payload(file_ref=file_ref, description=description),
        make_requester_headers(uploader_id)))


def work_item_to_submitted(item_id, assignee_id, file_ref="s3://ev/e.pdf"):
    """OPEN → IN_PROGRESS → (evidence) → SUBMITTED_FOR_VERIFICATION. Returns item."""
    get_success_data(api_client.start_action_item(item_id, make_requester_headers(assignee_id)))
    attach_evidence(item_id, assignee_id, file_ref=file_ref)
    return get_success_data(api_client.submit_verification(item_id, make_requester_headers(assignee_id)))


def verify_item(item_id):
    return get_success_data(api_client.verify_action_item(item_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 3c: incidents and audits
# ---------------------------------------------------------------------------

def new_incident(unit_id, investigator_id, severity_class="HIGH",
                 occurred_at="2026-04-20", title="i"):
    payload = create_incident_payload(investigator_id, title=title,
                                      severity_class=severity_class, occurred_at=occurred_at)
    return get_success_data(api_client.create_incident(unit_id, payload, MANAGER))


def drive_incident_to_findings_submitted(incident, findings=None):
    """OPEN → ROOT_CAUSE_ANALYSIS → FINDINGS_SUBMITTED as the investigator."""
    investigator_id = incident["investigator_id"]
    get_success_data(api_client.begin_rca(incident["id"], make_investigator_headers(investigator_id)))
    return get_success_data(api_client.submit_findings(
        incident["id"], {"findings": findings or []}, make_investigator_headers(investigator_id)))


def new_audit(unit_id, lead_auditor_id, window_start="2026-05-01", window_end="2026-05-10", title="au"):
    payload = create_audit_payload(lead_auditor_id, title=title,
                                   field_window_start=window_start, field_window_end=window_end)
    return get_success_data(api_client.create_audit(unit_id, payload, MANAGER))


def drive_audit_to_reported(audit, findings):
    """SCHEDULED → FIELDWORK → REPORTED as the lead auditor. Returns the audit."""
    lead_id = audit["lead_auditor_id"]
    get_success_data(api_client.begin_audit_fieldwork(audit["id"], make_auditor_headers(lead_id)))
    return get_success_data(api_client.report_audit(audit["id"], {"findings": findings},
                                                    make_auditor_headers(lead_id)))


# ---------------------------------------------------------------------------
# Tier 4: accumulation / posture targeting
# ---------------------------------------------------------------------------

def drive_unit_to_frozen_via_overdue_and_study(unit_id, assignee_id, clock_iso="2027-01-11"):
    """Push a unit to index 70 (FROZEN): three P1 items with due_in_days 1
    (45 once overdue) plus the study OVERDUE (+25) after the clock crosses its
    effective due date. Returns the refreshed unit."""
    for i in range(3):
        new_manual_item(unit_id, assignee_id, priority="P1", due_in_days=1, title=f"a{i + 1}")
    set_clock(clock_iso)
    return get_unit(unit_id)


def setup_moc_with_split_training_coverage():
    """The pinned per-update-rounding scenario (PRD §3.4): an approved PERMANENT
    MOC with two PUBLISHED updates — completions 2/3 and 3/4 — so coverage is
    round2((66.67 + 75.00) / 2) == 70.84, below the 100.00 default threshold.

    Returns (unit, actors, moc)."""
    unit, _ = setup_unit_with_study()
    req = new_personnel("Req", "E-REQ")
    rev = new_personnel("Rev", "E-REV", qualifications=["CHEMICAL"])
    app = new_personnel("App", "E-APP")
    trainees = [new_personnel(f"T{i}", f"E-T{i}") for i in range(1, 5)]
    moc = drive_moc_to_approved(unit["id"], req["id"], rev["id"], app["id"])

    # Update 1: three assignments, first two completed → 66.67.
    _, a1 = publish_update_with_assignments(moc["id"], [t["id"] for t in trainees[:3]],
                                            document_ref="SOP-101")
    complete_assignments(a1, [trainees[0]["id"], trainees[1]["id"]])

    # Update 2: four assignments, first three completed → 75.00.
    _, a2 = publish_update_with_assignments(moc["id"], [t["id"] for t in trainees],
                                            document_ref="SOP-102")
    complete_assignments(a2, [trainees[0]["id"], trainees[1]["id"], trainees[2]["id"]])

    return unit, {"req": req, "rev": rev, "app": app, "trainees": trainees}, get_moc(moc["id"])


# ---------------------------------------------------------------------------
# Tier 5: terminal / expiry states
# ---------------------------------------------------------------------------

def new_extension(moc_id, requester_id, requested_days):
    """Create an ExtensionRequest as the requester (reads fresh MOC version)."""
    version = moc_version(moc_id)
    payload = create_extension_request_payload(version, requested_days=requested_days)
    return api_client.create_extension_request(moc_id, payload, make_requester_headers(requester_id))


def expire_temporary_moc(clock_iso):
    """Advance the clock past a temporary MOC's end date; runs the expiry sweep."""
    return set_clock(clock_iso)
