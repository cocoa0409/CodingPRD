"""PhaStudy and PhaRevalidation endpoints."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_PHA_STUDY_INVALID_STATE, ERR_REVALIDATION_INVALID_STATE,
    ERR_PHA_STUDY_EXISTS, ERR_QUALIFICATION_MISSING, ERR_INVALID_REQUEST,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_enum, f_day, f_list, f_int,
)
from services import (
    new_entity, touch, get_unit, get_person, get_study, get_revalidation,
    study_of_unit, compute_study_dues, recompute_unit, spawn_action_item,
    ser_study, ser_revalidation, sorted_rows, require_active_person,
)

bp = Blueprint("pha", __name__)

METHODS = ["HAZOP", "WHAT_IF", "CHECKLIST"]


@bp.post("/psm/units/<unit_id>/pha-studies")
@require_roles("PsmManager")
def create_study(unit_id):
    unit = get_unit(unit_id)
    b = body_json()
    method = f_enum(b, "method", METHODS)
    initial = f_day(b, "initial_validated_at")
    if study_of_unit(unit["id"]) is not None:
        raise ApiError(ERR_PHA_STUDY_EXISTS, "Unit already has a PhaStudy", 409)
    s = new_entity()
    s.update({
        "unit_id": unit["id"],
        "method": method,
        "status": "CURRENT",
        "last_validated_at": initial,
        "revalidation_count": 0,
        "status_before_revalidation": None,
    })
    store.studies[s["id"]] = s
    compute_study_dues(s, unit)
    recompute_unit(unit)
    return ok(ser_study(s), 201)


@bp.get("/psm/units/<uid>/pha-studies")
@require_roles(*ALL_ROLES)
def list_unit_studies(uid):
    unit = get_unit(uid)
    limit, offset = pagination_params()
    rows = [ser_study(s) for s in sorted_rows(store.studies.values()) if s["unit_id"] == unit["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/pha-studies/<sid>")
@require_roles(*ALL_ROLES)
def get_one_study(sid):
    return ok(ser_study(get_study(sid)), 200)


@bp.post("/psm/pha-studies/<sid>/open-revalidation")
@require_roles("PsmManager")
def open_revalidation(sid):
    s = get_study(sid)
    if s["status"] not in ("DUE_SOON", "OVERDUE", "REVALIDATION_REQUIRED"):
        raise ApiError(
            ERR_PHA_STUDY_INVALID_STATE,
            "Study must be DUE_SOON, OVERDUE or REVALIDATION_REQUIRED to open a revalidation",
            409,
        )
    b = body_json()
    leader_id = f_str(b, "leader_id")
    leader = get_person(leader_id)  # 404 for unknown referenced Personnel
    if not leader["active"] or "HAZOP_LEADER" not in leader["qualifications"]:
        raise ApiError(ERR_QUALIFICATION_MISSING, "Leader must be active and hold HAZOP_LEADER", 403)
    s["status_before_revalidation"] = s["status"]
    s["status"] = "IN_REVALIDATION"
    touch(s)
    r = new_entity()
    r.update({
        "study_id": s["id"],
        "leader_id": leader_id,
        "status": "OPEN",
        "findings_summary": None,
        "findings": [],
    })
    store.revalidations[r["id"]] = r
    recompute_unit(store.units[s["unit_id"]])
    return ok(ser_revalidation(r), 201)


@bp.get("/psm/pha-studies/<sid>/revalidations")
@require_roles(*ALL_ROLES)
def list_study_revalidations(sid):
    s = get_study(sid)
    limit, offset = pagination_params()
    rows = [ser_revalidation(r) for r in sorted_rows(store.revalidations.values())
            if r["study_id"] == s["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>/pha-revalidations")
@require_roles(*ALL_ROLES)
def list_personnel_revalidations(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_revalidation(r) for r in sorted_rows(store.revalidations.values())
            if r["leader_id"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.post("/psm/pha-revalidations/<rid>/complete")
@require_roles("PsmManager")
def complete_revalidation(rid):
    r = get_revalidation(rid)
    if r["status"] != "OPEN":
        raise ApiError(ERR_REVALIDATION_INVALID_STATE, "Revalidation is not OPEN", 409)
    b = body_json()
    findings_summary = f_str(b, "findings_summary")
    findings = f_list(b, "findings", required=False) or []
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, "Each finding must be an object", 400)
        title = f_str(f, "title")
        priority = f_enum(f, "priority", ["P1", "P2", "P3"])
        assignee_id = f_str(f, "assignee_id")
        require_active_person(assignee_id, "Assignee")
        parsed.append((title, priority, assignee_id))
    s = store.studies[r["study_id"]]
    unit = store.units[s["unit_id"]]
    r["findings_summary"] = findings_summary
    r["findings"] = findings
    r["status"] = "COMPLETED"
    touch(r)
    s["last_validated_at"] = store.clock
    s["revalidation_count"] += 1
    s["status"] = "CURRENT"
    s["status_before_revalidation"] = None
    compute_study_dues(s, unit)
    touch(s)
    for title, priority, assignee_id in parsed:
        spawn_action_item(unit["id"], "PHA_REVALIDATION", r["id"], title, priority, assignee_id)
    recompute_unit(unit)
    return ok(ser_revalidation(r), 200)


@bp.post("/psm/pha-revalidations/<rid>/abandon")
@require_roles("PsmManager")
def abandon_revalidation(rid):
    r = get_revalidation(rid)
    if r["status"] != "OPEN":
        raise ApiError(ERR_REVALIDATION_INVALID_STATE, "Revalidation is not OPEN", 409)
    s = store.studies[r["study_id"]]
    r["status"] = "ABANDONED"
    touch(r)
    # Compensating invariant: restore prior status; schedule fields unchanged.
    s["status"] = s["status_before_revalidation"]
    s["status_before_revalidation"] = None
    touch(s)
    recompute_unit(store.units[s["unit_id"]])
    return ok(ser_revalidation(r), 200)
