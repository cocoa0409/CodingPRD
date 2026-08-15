"""Composite setup helpers — multi-step preconditions built only from
PRD-declared endpoints. All helpers use the lenient get_success_data()
validator so setup failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_project_payload, create_safety_plan_payload, create_worker_payload,
    create_certificate_payload, create_subcontractor_payload,
    create_huddle_payload, create_jha_payload, create_inspection_payload,
    create_deficiency_payload, create_incident_payload, create_permit_payload,
    create_drug_test_payload, determination_payload,
)
from .test_users import (
    INSPECTOR_ONE_ID, SAFETY_MANAGER_ID,
    make_safety_manager_headers, make_site_superintendent_headers,
    make_safety_inspector_headers, make_subcontractor_rep_headers,
)

# Header shortcuts used throughout fixtures (opaque roles, PRD §2.1).
SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()


def inspector_headers(user_id: str = INSPECTOR_ONE_ID) -> dict:
    return make_safety_inspector_headers(user_id)


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Advance the logical clock and run the sweep (PRD §2.5)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, SM)
    return get_success_data(resp)


# ─── Projects & safety plans (PRD §3.1) ──────────────────────────────────────

def create_project(name="Test Project", location="Seattle",
                   annual_hours_worked=100000) -> dict:
    payload = create_project_payload(
        name=name, location=location, annual_hours_worked=annual_hours_worked
    )
    return get_success_data(api_client.create_project(payload, SM))


def create_plan(project_id: str, effective_date: str = "2026-08-01",
                revision_notes: str = None) -> dict:
    overrides = {}
    if revision_notes is not None:
        overrides["revision_notes"] = revision_notes
    payload = create_safety_plan_payload(
        project_id, effective_date=effective_date, **overrides
    )
    return get_success_data(api_client.create_safety_plan(payload, SM))


def activate_plan(plan_id: str, expected_project_version: int) -> dict:
    payload = {"expected_project_version": expected_project_version}
    return get_success_data(api_client.activate_safety_plan(plan_id, payload, SM))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, SM))


def create_project_with_active_plan(name="Test Project", location="Seattle",
                                    annual_hours_worked=100000,
                                    effective_date="2026-08-01"):
    """Project + one plan revision activated. Returns (project, plan)."""
    project = create_project(name, location, annual_hours_worked)
    plan = create_plan(project["id"], effective_date)
    plan = activate_plan(plan["id"], project["version"])
    project = get_project(project["id"])
    return project, plan


# ─── Workers & certificates (PRD §3.2) ───────────────────────────────────────

def create_worker(project_id: str, full_name="Test Worker", employer_type="DIRECT",
                  subcontractor_id=None, is_supervisor=None) -> dict:
    overrides = {"full_name": full_name, "employer_type": employer_type}
    if employer_type == "SUBCONTRACTOR":
        overrides["subcontractor_id"] = subcontractor_id
    if is_supervisor is not None:
        overrides["is_supervisor"] = is_supervisor
    payload = create_worker_payload(project_id, **overrides)
    return get_success_data(api_client.create_worker(payload, SS))


def create_certificate(worker_id: str, cert_type="OSHA_10",
                       issued_date="2026-07-01", expires_date="2027-07-01") -> dict:
    payload = create_certificate_payload(
        worker_id, cert_type=cert_type,
        issued_date=issued_date, expires_date=expires_date,
    )
    return get_success_data(api_client.create_certificate(payload, SS))


def verify_certificate(certificate_id: str, inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    return get_success_data(
        api_client.verify_certificate(certificate_id, {}, inspector_headers(inspector_id))
    )


def create_verified_certificate(worker_id: str, cert_type="OSHA_10",
                                issued_date="2026-07-01",
                                expires_date="2027-07-01",
                                inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    cert = create_certificate(worker_id, cert_type, issued_date, expires_date)
    return verify_certificate(cert["id"], inspector_id)


def complete_orientation(worker_id: str) -> dict:
    return get_success_data(api_client.complete_orientation(worker_id, {}, SS))


def clear_worker(worker_id: str) -> dict:
    return get_success_data(api_client.clear_worker(worker_id, {}, SS))


def get_worker(worker_id: str) -> dict:
    return get_success_data(api_client.get_worker(worker_id, SM))


def create_oriented_worker(project_id: str, full_name="Test Worker",
                           employer_type="DIRECT", subcontractor_id=None,
                           is_supervisor=None) -> dict:
    """Worker badged + orientation completed. Requires an ACTIVE plan (PRD §3.2)."""
    worker = create_worker(
        project_id, full_name, employer_type, subcontractor_id, is_supervisor
    )
    return complete_orientation(worker["id"])


def create_cleared_worker(project_id: str, full_name="Test Worker",
                          employer_type="DIRECT", subcontractor_id=None,
                          is_supervisor=False,
                          cert_type=None,
                          inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    """Worker badged + VERIFIED certificate + orientation + clearance (PRD §3.2)."""
    if cert_type is None:
        cert_type = "OSHA_30" if is_supervisor else "OSHA_10"
    worker = create_worker(
        project_id, full_name, employer_type, subcontractor_id, is_supervisor
    )
    create_verified_certificate(worker["id"], cert_type, inspector_id=inspector_id)
    complete_orientation(worker["id"])
    return clear_worker(worker["id"])


# ─── Subcontractors (PRD §3.7) ───────────────────────────────────────────────

def create_subcontractor(project_id: str, company_name="Test Sub LLC",
                         trade="general") -> dict:
    payload = create_subcontractor_payload(
        project_id, company_name=company_name, trade=trade
    )
    return get_success_data(api_client.create_subcontractor(payload, SM))


def get_subcontractor(subcontractor_id: str) -> dict:
    return get_success_data(api_client.get_subcontractor(subcontractor_id, SM))


def probation_review(subcontractor_id: str, action: str) -> dict:
    return get_success_data(
        api_client.probation_review(subcontractor_id, {"action": action}, SM)
    )


# ─── Huddles & JHAs (PRD §3.3) ───────────────────────────────────────────────

def create_huddle(project_id: str, huddle_date="2026-08-01", topics="daily plan") -> dict:
    payload = create_huddle_payload(
        project_id, huddle_date=huddle_date, topics=topics
    )
    return get_success_data(api_client.create_huddle(payload, SS))


def conduct_huddle(huddle_id: str, attendee_worker_ids=None) -> dict:
    payload = {"attendee_worker_ids": list(attendee_worker_ids or [])}
    return get_success_data(api_client.conduct_huddle(huddle_id, payload, SS))


def create_conducted_huddle(project_id: str, huddle_date="2026-08-01",
                            topics="daily plan", attendee_worker_ids=None) -> dict:
    huddle = create_huddle(project_id, huddle_date, topics)
    return conduct_huddle(huddle["id"], attendee_worker_ids)


def get_huddle(huddle_id: str) -> dict:
    return get_success_data(api_client.get_huddle(huddle_id, SM))


def create_jha(project_id: str, huddle_id: str, task_description="task under analysis",
               hazards="identified hazards", controls="planned controls") -> dict:
    payload = create_jha_payload(
        project_id, huddle_id, task_description=task_description,
        hazards=hazards, controls=controls,
    )
    return get_success_data(api_client.create_jha(payload, SS))


def approve_jha(jha_id: str) -> dict:
    return get_success_data(api_client.approve_jha(jha_id, {}, SM))


def create_approved_jha(project_id: str, huddle_id: str, **kwargs) -> dict:
    jha = create_jha(project_id, huddle_id, **kwargs)
    return approve_jha(jha["id"])


def get_jha(jha_id: str) -> dict:
    return get_success_data(api_client.get_jha(jha_id, SM))


# ─── Inspections & deficiencies (PRD §3.5) ───────────────────────────────────

def create_inspection(project_id: str, inspection_type="WEEKLY",
                      due_date="2026-08-10T17:00:00Z") -> dict:
    payload = create_inspection_payload(
        project_id, inspection_type=inspection_type, due_date=due_date
    )
    return get_success_data(api_client.create_inspection(payload, inspector_headers()))


def complete_inspection(inspection_id: str, findings_summary="findings recorded",
                        inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    payload = {"findings_summary": findings_summary}
    return get_success_data(
        api_client.complete_inspection(inspection_id, payload, inspector_headers(inspector_id))
    )


def create_completed_inspection(project_id: str, inspection_type="WEEKLY",
                                due_date="2026-08-10T17:00:00Z",
                                findings_summary="findings recorded",
                                inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    inspection = create_inspection(project_id, inspection_type, due_date)
    return complete_inspection(inspection["id"], findings_summary, inspector_id)


def create_deficiency(inspection_id: str, description="deficiency observed",
                      severity="MINOR", assigned_subcontractor_id=None,
                      creator_id: str = INSPECTOR_ONE_ID) -> dict:
    overrides = {"description": description, "severity": severity}
    if assigned_subcontractor_id is not None:
        overrides["assigned_subcontractor_id"] = assigned_subcontractor_id
    payload = create_deficiency_payload(inspection_id, **overrides)
    return get_success_data(
        api_client.create_deficiency(payload, inspector_headers(creator_id))
    )


def submit_correction(deficiency_id: str, correction_notes="corrected",
                      actor_headers=None, subcontractor_id=None) -> dict:
    """Submit a correction. Pass subcontractor_id to act as that firm's rep."""
    if actor_headers is None:
        actor_headers = (
            make_subcontractor_rep_headers(subcontractor_id)
            if subcontractor_id is not None else SS
        )
    payload = {"correction_notes": correction_notes}
    return get_success_data(
        api_client.submit_correction(deficiency_id, payload, actor_headers)
    )


def verify_deficiency_closed(deficiency_id: str, disposition="CONFIRMED",
                             inspector_id: str = "insp-2") -> dict:
    payload = {"outcome": "CLOSED", "disposition": disposition}
    return get_success_data(
        api_client.verify_deficiency(deficiency_id, payload, inspector_headers(inspector_id))
    )


def get_deficiency(deficiency_id: str) -> dict:
    return get_success_data(api_client.get_deficiency(deficiency_id, SM))


# ─── Incidents (PRD §3.6) ────────────────────────────────────────────────────

def create_incident(project_id: str, worker_id=None, incident_type="INJURY",
                    severity="SERIOUS", occurred_at="2026-08-02T08:00:00Z",
                    work_related=True, description="incident reported") -> dict:
    overrides = {
        "incident_type": incident_type, "severity": severity,
        "occurred_at": occurred_at, "work_related": work_related,
        "description": description,
    }
    if worker_id is not None:
        overrides["worker_id"] = worker_id
    payload = create_incident_payload(project_id, **overrides)
    return get_success_data(api_client.create_incident(payload, SS))


def investigate_incident(incident_id: str, investigation_notes="investigation opened",
                         inspector_id: str = INSPECTOR_ONE_ID) -> dict:
    payload = {"investigation_notes": investigation_notes}
    return get_success_data(
        api_client.investigate_incident(incident_id, payload, inspector_headers(inspector_id))
    )


def record_determination(incident_id: str, manager_id: str = SAFETY_MANAGER_ID,
                         **flags) -> dict:
    payload = determination_payload(**flags)
    return get_success_data(
        api_client.record_determination(
            incident_id, payload, make_safety_manager_headers(manager_id)
        )
    )


def close_incident(incident_id: str, manager_id: str = SAFETY_MANAGER_ID) -> dict:
    return get_success_data(
        api_client.close_incident(incident_id, {}, make_safety_manager_headers(manager_id))
    )


def get_incident(incident_id: str) -> dict:
    return get_success_data(api_client.get_incident(incident_id, SM))


# ─── Permits (PRD §3.4) ──────────────────────────────────────────────────────

def create_permit(project_id: str, jha_id: str, permit_type="FALL_PROTECTION",
                  work_start="2026-08-02T08:00:00Z", work_end="2026-08-02T16:00:00Z",
                  authorized_worker_ids=None) -> dict:
    """Request a permit; expects success (201)."""
    payload = create_permit_payload(
        project_id, jha_id, permit_type=permit_type,
        work_start=work_start, work_end=work_end,
        authorized_worker_ids=list(authorized_worker_ids or []),
    )
    return get_success_data(api_client.create_permit(payload, SS))


def issue_permit(permit_id: str) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, {}, SM))


def close_permit(permit_id: str, completion_notes=None) -> dict:
    payload = {} if completion_notes is None else {"completion_notes": completion_notes}
    return get_success_data(api_client.close_permit(permit_id, payload, SS))


def reinstate_permit(permit_id: str) -> dict:
    return get_success_data(api_client.reinstate_permit(permit_id, {}, SM))


def get_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, SM))


def create_issued_permit(project_id: str, jha_id: str, **permit_kwargs) -> dict:
    permit = create_permit(project_id, jha_id, **permit_kwargs)
    return issue_permit(permit["id"])


def setup_jobsite_with_issued_permit(project_name="Test Site", annual_hours=100000,
                                     permit_type="FALL_PROTECTION",
                                     work_start="2026-08-02T08:00:00Z",
                                     work_end="2026-08-02T16:00:00Z",
                                     worker_name="Crew Lead",
                                     clock: str = CLOCK_START) -> dict:
    """Full jobsite chain: project + ACTIVE plan + CLEARED worker + CONDUCTED
    huddle + APPROVED JHA + ISSUED permit crewed by the worker (PRD §3.1-§3.4).
    Returns a dict with every entity produced."""
    set_clock(clock)
    project, plan = create_project_with_active_plan(project_name, annual_hours_worked=annual_hours)
    worker = create_cleared_worker(project["id"], full_name=worker_name)
    huddle = create_conducted_huddle(project["id"], attendee_worker_ids=[worker["id"]])
    jha = create_approved_jha(project["id"], huddle["id"])
    permit = create_issued_permit(
        project["id"], jha["id"], permit_type=permit_type,
        work_start=work_start, work_end=work_end,
        authorized_worker_ids=[worker["id"]],
    )
    return {
        "project": project, "plan": plan, "worker": worker,
        "huddle": huddle, "jha": jha, "permit": permit,
    }


# ─── Drug test records (PRD §3.8) ────────────────────────────────────────────

def create_drug_test(worker_id: str, test_type="RANDOM",
                     collected_at="2026-08-05T09:00:00Z", incident_id=None) -> dict:
    overrides = {"test_type": test_type, "collected_at": collected_at}
    if incident_id is not None:
        overrides["incident_id"] = incident_id
    payload = create_drug_test_payload(worker_id, **overrides)
    return get_success_data(api_client.create_drug_test(payload, SM))


def record_drug_result(drug_test_id: str, result: str) -> dict:
    return get_success_data(
        api_client.record_drug_test_result(drug_test_id, {"result": result}, SM)
    )


def create_resulted_post_incident_test(worker_id: str, incident_id: str,
                                       collected_at: str, result="NEGATIVE") -> dict:
    """POST_INCIDENT collection inside the 32-hour window + recorded result."""
    record = create_drug_test(
        worker_id, test_type="POST_INCIDENT",
        collected_at=collected_at, incident_id=incident_id,
    )
    return record_drug_result(record["id"], result)


def get_drug_test(drug_test_id: str) -> dict:
    return get_success_data(api_client.get_drug_test(drug_test_id, SM))
