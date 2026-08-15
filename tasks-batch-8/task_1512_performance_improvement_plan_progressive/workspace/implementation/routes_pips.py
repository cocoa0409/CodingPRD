"""Routes: PIPs, PIP goals, check-ins, evidence items."""

from flask import Blueprint, request

from core import (
    db, auth, require_role, ok_object, list_response, body, require_field,
    min_len, enum_field, new_record, new_append_record, touch, public,
    parse_dt, fmt_like, days, ALL_ROLES,
    E_FORBIDDEN, E_NOT_FOUND, E_PARENT_MISMATCH, E_STALE_VERSION,
    E_INVALID_STATE, E_SOD, E_EMPLOYEE_NOT_ACTIVE, E_INVALID_REQUEST,
    E_CONCERN_NOT_ACCEPTED, E_TEMPLATE_NOT_PUBLISHED, E_ACTIVE_PIP_EXISTS,
    E_PIP_NOT_ACTIVE, E_OUTCOME_ALREADY_PROPOSED, E_CHECKIN_TOO_EARLY,
    E_CHECKIN_QUORUM, E_CHECKIN_ALREADY_HELD, E_CHECKIN_CADENCE,
    E_REFERENTIAL, err,
)
from business import (
    goals_of_pip, checkins_of_pip, evidence_of_checkin, recompute_provisional,
    goal_status_for,
)
from routes_core import resolve_ou, resolve_employee

bp = Blueprint("pip_routes", __name__)

READERS = ALL_ROLES
EVIDENCE_READERS = ["HRSystemAdmin", "HRBusinessPartner", "HRDirector",
                    "LegalCounsel", "Manager"]
EVIDENCE_SOURCES = {"MANAGER_OBSERVATION", "SYSTEM_REPORT", "PEER_FEEDBACK",
                    "SELF_REPORT"}
PIP_INFLIGHT = ("ISSUED", "ACTIVE", "EXTENDED")


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def resolve_pip(ou_id, emp_id, pip_id):
    ou, emp = resolve_employee(ou_id, emp_id)
    pip = db.pips.get(pip_id)
    if pip is None:
        err(E_NOT_FOUND, "PIP not found")
    if pip["employee_id"] != emp["id"]:
        err(E_PARENT_MISMATCH, "PIP does not belong to employee")
    return ou, emp, pip


def resolve_checkin(ou_id, emp_id, pip_id, check_in_id):
    ou, emp, pip = resolve_pip(ou_id, emp_id, pip_id)
    c = db.checkins.get(check_in_id)
    if c is None:
        err(E_NOT_FOUND, "check-in not found")
    if c["pip_id"] != pip["id"]:
        err(E_PARENT_MISMATCH, "check-in does not belong to PIP")
    return ou, emp, pip, c


def resolve_evidence(ou_id, emp_id, pip_id, check_in_id, evidence_id):
    ou, emp, pip, c = resolve_checkin(ou_id, emp_id, pip_id, check_in_id)
    ev = db.evidence.get(evidence_id)
    if ev is None:
        err(E_NOT_FOUND, "evidence item not found")
    if ev["check_in_id"] != c["id"]:
        err(E_PARENT_MISMATCH, "evidence item does not belong to check-in")
    return ou, emp, pip, c, ev


# ---------------------------------------------------------------------------
# PIPs
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips")
def create_pip(ouId, empId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp = resolve_employee(ouId, empId)
    b = body()
    concern_id = require_field(b, "concern_id")
    template_id = require_field(b, "template_id")
    start_raw = require_field(b, "start_date")
    if not isinstance(concern_id, str) or not isinstance(template_id, str):
        err(E_INVALID_REQUEST, "concern_id and template_id must be strings")
    start = parse_dt(start_raw)
    if start is None:
        err(E_INVALID_REQUEST, "start_date must be an ISO 8601 timestamp")
    concern = db.concerns.get(concern_id)
    template = db.templates.get(template_id)
    # Template-state failures surface ERR_TEMPLATE_NOT_PUBLISHED
    if template is not None and template["template_status"] != "PUBLISHED":
        err(E_TEMPLATE_NOT_PUBLISHED, "template is not PUBLISHED")
    # Referential integrity for body references
    if concern is None or concern["status"] != "ACCEPTED":
        err(E_REFERENTIAL, "concern must exist and be ACCEPTED")
    for other in db.pips.values():
        if other["concern_id"] == concern["id"] and \
                other["status"] in ("DRAFT", "ISSUED", "ACTIVE", "EXTENDED"):
            err(E_REFERENTIAL, "concern is already bound to another non-terminal PIP")
    if template is None:
        err(E_REFERENTIAL, "template does not exist")
    if emp["employment_status"] != "ACTIVE":
        err(E_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    for other in db.pips.values():
        if other["employee_id"] == emp["id"] and other["status"] in PIP_INFLIGHT:
            err(E_ACTIVE_PIP_EXISTS, "employee already has an in-flight PIP")
    end = start + days(template["duration_days"])
    rec = new_record()
    rec.update({
        "employee_id": emp["id"],
        "concern_id": concern["id"],
        "template_id": template["id"],
        "template_published_version": template.get("published_version"),
        "policy_version_at_issuance": ou["pip_policy_version"],
        "issuing_hrbp_id": uid,
        "start_date": fmt_like(start, start_raw),
        "end_date": fmt_like(end, start_raw),
        "check_in_interval_days": template["check_in_cadence_days"],
        "status": "DRAFT",
        "provisional_attainment_ratio": 0.0,
        "final_attainment_ratio": None,
        "extension_count": 0,
        "rebuttal_window_closes_at": None,
        "closed_at": None,
    })
    db.pips[rec["id"]] = rec
    for bp_i in template["goal_blueprints"]:
        g = new_record()
        g.update({
            "pip_id": rec["id"],
            "metric_key": bp_i["metric_key"],
            "target_value": bp_i["target_value"],
            "unit": bp_i["unit"],
            "weight": bp_i["weight"],
            "current_value": 0,
            "goal_status": "PENDING",
        })
        db.goals[g["id"]] = g
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips")
def list_pips(ouId, empId):
    uid, role = auth()
    require_role(role, READERS)
    ou, emp = resolve_employee(ouId, empId)
    filters = {"status": request.args.get("status")}
    records = [p for p in db.pips.values() if p["employee_id"] == emp["id"]]
    return list_response(records, filters)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>")
def get_pip(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, READERS)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    return ok_object(public(pip))


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/goals")
def list_goals(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, READERS)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"goal_status": request.args.get("goal_status")}
    return list_response(goals_of_pip(pip["id"]), filters)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/issue")
def issue_pip(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    b = body()
    # OCC: evaluated before any business rule, when present
    if "expected_pip_version" in b and b["expected_pip_version"] is not None:
        if b["expected_pip_version"] != pip["version"]:
            err(E_STALE_VERSION, "expected_pip_version does not match pip.version")
    if pip["status"] != "DRAFT":
        err(E_INVALID_STATE, "PIP is not DRAFT")
    if pip["issuing_hrbp_id"] != uid:
        err(E_FORBIDDEN, "only the plan's issuing HRBP may issue it")
    concern = db.concerns.get(pip["concern_id"])
    if concern is None or concern["status"] != "ACCEPTED":
        err(E_CONCERN_NOT_ACCEPTED, "concern is not ACCEPTED")
    if emp["employment_status"] != "ACTIVE":
        err(E_EMPLOYEE_NOT_ACTIVE, "employee is not ACTIVE")
    for other in db.pips.values():
        if other["id"] != pip["id"] and other["employee_id"] == emp["id"] \
                and other["status"] in PIP_INFLIGHT:
            err(E_ACTIVE_PIP_EXISTS, "employee already has an in-flight PIP")
    concern["status"] = "SUPERSEDED_BY_PIP"
    touch(concern)
    emp["active_pip_id"] = pip["id"]
    touch(emp)
    pip["status"] = "ISSUED"
    touch(pip)
    return ok_object(public(pip))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/withdraw")
def withdraw_pip(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    if pip["status"] not in ("ISSUED", "ACTIVE"):
        err(E_INVALID_STATE, "PIP is not ISSUED or ACTIVE")
    if pip["issuing_hrbp_id"] != uid:
        err(E_FORBIDDEN, "only the plan's issuing HRBP may withdraw it")
    for d in db.decisions.values():
        if d["pip_id"] == pip["id"] and d["status"] in ("PROPOSED", "APPROVED"):
            err(E_OUTCOME_ALREADY_PROPOSED,
                "an outcome decision already stands for this PIP")
    pip["status"] = "CLOSED_WITHDRAWN"
    pip["closed_at"] = ou["current_utc"]
    touch(pip)
    if emp.get("active_pip_id") == pip["id"]:
        emp["active_pip_id"] = None
        touch(emp)
    for c in checkins_of_pip(pip["id"]):
        if c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            touch(c)
    return ok_object(public(pip))


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins")
def create_checkin(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    b = body()
    sf_raw = require_field(b, "scheduled_for")
    sf = parse_dt(sf_raw)
    if sf is None:
        err(E_INVALID_REQUEST, "scheduled_for must be an ISO 8601 timestamp")
    start, end = parse_dt(pip["start_date"]), parse_dt(pip["end_date"])
    if not (start <= sf < end):
        err(E_CHECKIN_TOO_EARLY, "scheduled_for must be within [start_date, end_date)")
    interval = pip["check_in_interval_days"]
    for c in checkins_of_pip(pip["id"]):
        if c["status"] == "CANCELLED":
            continue
        delta = abs((sf - parse_dt(c["scheduled_for"])).total_seconds())
        if delta != interval * 86400:
            err(E_CHECKIN_CADENCE,
                "adjacent check-ins must be exactly check_in_interval_days apart")
    rec = new_record()
    rec.update({
        "pip_id": pip["id"],
        "scheduled_for": fmt_like(sf, sf_raw),
        "sequence_index": len(checkins_of_pip(pip["id"])) + 1,
        "held_at": None,
        "manager_attended": False,
        "hrbp_attended": False,
        "status": "SCHEDULED",
        "notes": None,
    })
    db.checkins[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins")
def list_checkins(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, READERS)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"status": request.args.get("status")}
    records = [c for c in db.checkins.values() if c["pip_id"] == pip["id"]]
    return list_response(records, filters)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins/<checkInId>/mark-held")
def mark_held(ouId, empId, pipId, checkInId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip, c = resolve_checkin(ouId, empId, pipId, checkInId)
    if c["status"] != "SCHEDULED":
        err(E_INVALID_STATE, "check-in is not SCHEDULED")
    if pip["status"] not in ("ACTIVE", "EXTENDED"):
        err(E_PIP_NOT_ACTIVE, "PIP is not ACTIVE or EXTENDED")
    b = body()
    manager_attended = b.get("manager_attended", False)
    hrbp_attended = b.get("hrbp_attended", False)
    notes = b.get("notes")
    if not (manager_attended is True and hrbp_attended is True):
        err(E_CHECKIN_QUORUM, "manager_attended and hrbp_attended must both be true")
    min_len(notes, 20, "notes")
    if parse_dt(ou["current_utc"]) < parse_dt(c["scheduled_for"]):
        err(E_CHECKIN_TOO_EARLY, "check-in cannot be held before scheduled_for")
    c["status"] = "HELD"
    c["held_at"] = ou["current_utc"]
    c["manager_attended"] = True
    c["hrbp_attended"] = True
    c["notes"] = notes
    touch(c)
    # Scoreboard: each goal takes the most recent ADMISSIBLE evidence on this check-in
    admissible = [e for e in evidence_of_checkin(c["id"])
                  if e["admissibility"] == "ADMISSIBLE"]
    for goal in goals_of_pip(pip["id"]):
        evs = [e for e in admissible if e["pip_goal_id"] == goal["id"]]
        if not evs:
            continue
        evs.sort(key=lambda e: (e["submitted_at"], e["created_at"], e["_seq"]),
                 reverse=True)
        goal["current_value"] = evs[0]["observed_value"]
        goal["goal_status"] = goal_status_for(goal["current_value"],
                                              goal["target_value"])
        touch(goal)
    recompute_provisional(pip)
    return ok_object(public(c))


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins/<checkInId>/evidence")
def create_evidence(ouId, empId, pipId, checkInId):
    uid, role = auth()
    require_role(role, ["Manager", "HRBusinessPartner"])
    ou, emp, pip, c = resolve_checkin(ouId, empId, pipId, checkInId)
    b = body()
    goal_id = require_field(b, "pip_goal_id")
    observed = require_field(b, "observed_value")
    source = enum_field(require_field(b, "source"), EVIDENCE_SOURCES, "source")
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        err(E_INVALID_REQUEST, "observed_value must be a number")
    goal = db.goals.get(goal_id) if isinstance(goal_id, str) else None
    if goal is None or goal["pip_id"] != pip["id"]:
        err(E_REFERENTIAL, "pip_goal_id must reference a goal of this PIP")
    rec = new_append_record()
    rec.update({
        "check_in_id": c["id"],
        "pip_goal_id": goal["id"],
        "observed_value": observed,
        "source": source,
        "submitted_by_id": uid,
        "submitted_at": ou["current_utc"],
        "admissibility": "PENDING_REVIEW",
        "admissibility_decided_by_id": None,
    })
    db.evidence[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins/<checkInId>/evidence")
def list_evidence(ouId, empId, pipId, checkInId):
    uid, role = auth()
    require_role(role, EVIDENCE_READERS)
    ou, emp, pip, c = resolve_checkin(ouId, empId, pipId, checkInId)
    filters = {
        "admissibility": request.args.get("admissibility"),
        "pip_goal_id": request.args.get("pip_goal_id"),
    }
    records = [e for e in db.evidence.values() if e["check_in_id"] == c["id"]]
    return list_response(records, filters)


def _adjudicate_evidence(ouId, empId, pipId, checkInId, evidenceId, admit):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip, c, ev = resolve_evidence(ouId, empId, pipId, checkInId, evidenceId)
    if ev["admissibility"] != "PENDING_REVIEW":
        err(E_INVALID_STATE, "evidence item is not PENDING_REVIEW")
    if c["status"] != "SCHEDULED":
        err(E_CHECKIN_ALREADY_HELD, "check-in is no longer SCHEDULED")
    if ev["submitted_by_id"] == pip["issuing_hrbp_id"] and \
            uid == pip["issuing_hrbp_id"]:
        err(E_SOD, "evidence submitted by the issuing HRBP must be adjudicated "
                   "by a different HRBP")
    ev["admissibility"] = "ADMISSIBLE" if admit else "INADMISSIBLE"
    ev["admissibility_decided_by_id"] = uid
    return ok_object(public(ev))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins/<checkInId>/evidence/<evidenceId>/admit")
def admit_evidence(ouId, empId, pipId, checkInId, evidenceId):
    return _adjudicate_evidence(ouId, empId, pipId, checkInId, evidenceId, True)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/check-ins/<checkInId>/evidence/<evidenceId>/exclude")
def exclude_evidence(ouId, empId, pipId, checkInId, evidenceId):
    return _adjudicate_evidence(ouId, empId, pipId, checkInId, evidenceId, False)
