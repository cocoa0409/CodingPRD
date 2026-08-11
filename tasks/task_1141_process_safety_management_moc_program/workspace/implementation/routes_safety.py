"""IncidentInvestigation, Audit, and AuditFinding endpoints."""
from datetime import timedelta

from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_INCIDENT_INVALID_STATE, ERR_AUDIT_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_FIELDWORK_WINDOW_NOT_ACTIVE,
    ERR_AUDIT_OPEN_FINDINGS, ERR_AUDIT_WINDOW_CONFLICT, ERR_INVALID_REQUEST,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_enum, f_day, f_list, f_int,
)
from services import (
    HIGH_SEVERITY, new_entity, touch, get_unit, get_person, get_incident,
    get_audit, study_of_unit, compute_study_dues, recompute_unit,
    spawn_action_item, ser_incident, ser_audit, ser_finding, sorted_rows,
    require_active_person,
)

bp = Blueprint("safety", __name__)

SEVERITY_CLASSES = ["MINOR", "SERIOUS", "HIGH", "CATASTROPHIC"]
FINDING_SEVERITIES = ["OBSERVATION", "MINOR_NC", "MAJOR_NC"]
SEVERITY_TO_PRIORITY = {"MAJOR_NC": "P1", "MINOR_NC": "P2", "OBSERVATION": "P3"}


# ---------------------------------------------------------------------------
# IncidentInvestigation
# ---------------------------------------------------------------------------

@bp.post("/psm/units/<unit_id>/incident-investigations")
@require_roles("PsmManager")
def create_incident(unit_id):
    unit = get_unit(unit_id)
    b = body_json()
    title = f_str(b, "title")
    severity_class = f_enum(b, "severity_class", SEVERITY_CLASSES)
    occurred_at = f_day(b, "occurred_at")
    investigator_id = f_str(b, "investigator_id")
    get_person(investigator_id)  # unknown referenced Personnel -> 404
    i = new_entity()
    i.update({
        "unit_id": unit["id"],
        "title": title,
        "severity_class": severity_class,
        "occurred_at": occurred_at,
        "investigator_id": investigator_id,
        "status": "OPEN",
        "feeds_pha": False,
    })
    store.incidents[i["id"]] = i
    recompute_unit(unit)
    return ok(ser_incident(i), 201)


@bp.get("/psm/units/<uid>/incident-investigations")
@require_roles(*ALL_ROLES)
def list_unit_incidents(uid):
    unit = get_unit(uid)
    limit, offset = pagination_params()
    rows = [ser_incident(i) for i in sorted_rows(store.incidents.values())
            if i["unit_id"] == unit["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/incident-investigations/<iid>")
@require_roles(*ALL_ROLES)
def get_one_incident(iid):
    return ok(ser_incident(get_incident(iid)), 200)


@bp.get("/psm/personnel/<pid>/incident-investigations")
@require_roles(*ALL_ROLES)
def list_personnel_incidents(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_incident(i) for i in sorted_rows(store.incidents.values())
            if i["investigator_id"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.post("/psm/incident-investigations/<iid>/begin-rca")
@require_roles("Investigator")
def begin_rca(iid):
    i = get_incident(iid)
    if i["status"] != "OPEN":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, "Only an OPEN investigation can begin RCA", 409)
    if i["investigator_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the designated investigator may begin RCA", 403)
    i["status"] = "ROOT_CAUSE_ANALYSIS"
    touch(i)
    return ok(ser_incident(i), 200)


@bp.post("/psm/incident-investigations/<iid>/submit-findings")
@require_roles("Investigator")
def submit_incident_findings(iid):
    i = get_incident(iid)
    if i["status"] != "ROOT_CAUSE_ANALYSIS":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, "Findings require ROOT_CAUSE_ANALYSIS", 409)
    if i["investigator_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the designated investigator may submit findings", 403)
    b = body_json()
    findings = f_list(b, "findings")
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each finding must be an object", 400)
        title = f_str(f, "title")
        priority = f_enum(f, "priority", ["P1", "P2", "P3"])
        assignee_id = f_str(f, "assignee_id")
        require_active_person(assignee_id, "Assignee")
        parsed.append((title, priority, assignee_id))
    i["status"] = "FINDINGS_SUBMITTED"
    touch(i)
    for title, priority, assignee_id in parsed:
        spawn_action_item(i["unit_id"], "INCIDENT", i["id"], title, priority, assignee_id)
    recompute_unit(store.units[i["unit_id"]])
    return ok(ser_incident(i), 200)


@bp.post("/psm/incident-investigations/<iid>/close")
@require_roles("PsmManager")
def close_incident(iid):
    i = get_incident(iid)
    if i["status"] != "FINDINGS_SUBMITTED":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, "Only FINDINGS_SUBMITTED investigations can be closed", 409)
    i["feeds_pha"] = i["severity_class"] in HIGH_SEVERITY
    i["status"] = "CLOSED"
    touch(i)
    unit = store.units[i["unit_id"]]
    study = study_of_unit(unit["id"])
    if study is not None:
        if i["feeds_pha"] and study["status"] in ("CURRENT", "DUE_SOON", "OVERDUE"):
            # Forced-revalidation cascade: PHA_REVALIDATION item sourced to the study.
            study["status"] = "REVALIDATION_REQUIRED"
            touch(study)
            spawn_action_item(unit["id"], "PHA_REVALIDATION", study["id"],
                              f"Forced PHA revalidation: {study['method']} study",
                              "P1", i["investigator_id"], due_in_days=30)
        # Risk-accelerated dues absorb the newly CLOSED severe incident.
        before = (study["nominal_next_due"], study["risk_accelerated_due"], study["effective_next_due"])
        compute_study_dues(study, unit)
        after = (study["nominal_next_due"], study["risk_accelerated_due"], study["effective_next_due"])
        if after != before:
            touch(study)
    recompute_unit(unit)
    return ok(ser_incident(i), 200)


# ---------------------------------------------------------------------------
# Audit / AuditFinding
# ---------------------------------------------------------------------------

@bp.post("/psm/units/<unit_id>/audits")
@require_roles("PsmManager")
def create_audit(unit_id):
    unit = get_unit(unit_id)
    b = body_json()
    title = f_str(b, "title")
    lead_auditor_id = f_str(b, "lead_auditor_id")
    start = f_day(b, "field_window_start")
    end = f_day(b, "field_window_end")
    get_person(lead_auditor_id)  # unknown referenced Personnel -> 404
    if end < start:
        raise ApiError(ERR_INVALID_REQUEST, "field_window_end must be on or after field_window_start", 400)
    # 14-day buffered separation vs live audits of the same unit (either side).
    # PRD §3.8: the new window "must stand at least fourteen days clear" of a
    # neighbor. With closed windows, a neighbor ending Aug 5 and a new window
    # starting Aug 19 leaves only thirteen clear days (Aug 6..18) — conflict —
    # while a start of Aug 20 leaves fourteen. So a separation of exactly 14
    # days between end and start is INSUFFICIENT; reject when the raw day
    # difference is <= 14, i.e. when start < end + 15 days (and symmetrically).
    buffer = timedelta(days=15)
    for a in store.audits.values():
        if a["unit_id"] != unit["id"] or a["status"] not in ("SCHEDULED", "FIELDWORK", "REPORTED"):
            continue
        if start < a["field_window_end"] + buffer and a["field_window_start"] < end + buffer:
            raise ApiError(ERR_AUDIT_WINDOW_CONFLICT,
                           "Audit window within 14 days of another live audit on the unit", 409)
    a = new_entity()
    a.update({
        "unit_id": unit["id"],
        "title": title,
        "lead_auditor_id": lead_auditor_id,
        "field_window_start": start,
        "field_window_end": end,
        "status": "SCHEDULED",
    })
    store.audits[a["id"]] = a
    return ok(ser_audit(a), 201)


@bp.get("/psm/units/<uid>/audits")
@require_roles(*ALL_ROLES)
def list_unit_audits(uid):
    unit = get_unit(uid)
    limit, offset = pagination_params()
    rows = [ser_audit(a) for a in sorted_rows(store.audits.values()) if a["unit_id"] == unit["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/audits/<aid>")
@require_roles(*ALL_ROLES)
def get_one_audit(aid):
    return ok(ser_audit(get_audit(aid)), 200)


@bp.get("/psm/personnel/<pid>/audits")
@require_roles(*ALL_ROLES)
def list_personnel_audits(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_audit(a) for a in sorted_rows(store.audits.values())
            if a["lead_auditor_id"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/audits/<aid>/findings")
@require_roles(*ALL_ROLES)
def list_audit_findings(aid):
    a = get_audit(aid)
    limit, offset = pagination_params()
    rows = [ser_finding(f) for f in sorted_rows(store.findings.values()) if f["audit_id"] == a["id"]]
    return ok_list(rows, limit, offset)


@bp.post("/psm/audits/<aid>/begin-fieldwork")
@require_roles("Auditor")
def begin_audit_fieldwork(aid):
    a = get_audit(aid)
    if a["status"] != "SCHEDULED":
        raise ApiError(ERR_AUDIT_INVALID_STATE, "Only a SCHEDULED audit can begin fieldwork", 409)
    if a["lead_auditor_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the lead auditor may begin fieldwork", 403)
    if not (a["field_window_start"] <= store.clock <= a["field_window_end"]):
        raise ApiError(ERR_FIELDWORK_WINDOW_NOT_ACTIVE, "Clock is outside the fieldwork window", 409)
    a["status"] = "FIELDWORK"
    touch(a)
    return ok(ser_audit(a), 200)


@bp.post("/psm/audits/<aid>/report")
@require_roles("Auditor")
def report_audit(aid):
    a = get_audit(aid)
    if a["status"] != "FIELDWORK":
        raise ApiError(ERR_AUDIT_INVALID_STATE, "Only a FIELDWORK audit can be reported", 409)
    if a["lead_auditor_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the lead auditor may report", 403)
    b = body_json()
    findings = f_list(b, "findings")
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each finding must be an object", 400)
        title = f_str(f, "title")
        severity = f_enum(f, "severity", FINDING_SEVERITIES)
        assignee_id = f_str(f, "assignee_id")
        require_active_person(assignee_id, "Assignee")
        parsed.append((title, severity, assignee_id))
    a["status"] = "REPORTED"
    touch(a)
    for title, severity, assignee_id in parsed:
        finding = new_entity()
        finding.update({
            "audit_id": a["id"],
            "title": title,
            "severity": severity,
            "status": "ACTION_ASSIGNED",  # created OPEN, assigned in the same request
            "corrective_action_id": None,
        })
        store.findings[finding["id"]] = finding
        item = spawn_action_item(a["unit_id"], "AUDIT", finding["id"], title,
                                 SEVERITY_TO_PRIORITY[severity], assignee_id)
        finding["corrective_action_id"] = item["id"]
    recompute_unit(store.units[a["unit_id"]])
    return ok(ser_audit(a), 200)


@bp.post("/psm/audits/<aid>/close")
@require_roles("PsmManager")
def close_audit(aid):
    a = get_audit(aid)
    if a["status"] != "REPORTED":
        raise ApiError(ERR_AUDIT_INVALID_STATE, "Only a REPORTED audit can be closed", 409)
    from services import open_finding_count
    if open_finding_count(a) != 0:
        raise ApiError(ERR_AUDIT_OPEN_FINDINGS, "Audit has open findings", 409)
    a["status"] = "CLOSED"
    touch(a)
    return ok(ser_audit(a), 200)
