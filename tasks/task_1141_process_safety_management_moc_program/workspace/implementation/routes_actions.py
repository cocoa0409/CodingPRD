"""ActionItem and EvidenceItem endpoints."""
from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_ACTION_ITEM_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_SOD_VERIFIER_IS_COMPLETER, ERR_NO_EVIDENCE_ATTACHED, ERR_INVALID_REQUEST,
)
from helpers import (
    ALL_ROLES, ENTITY_ROLES, require_roles, body_json, ok, ok_list,
    pagination_params, f_str, f_enum, f_int, now_iso,
)
from services import (
    OPEN_ACTION_STATUSES, new_entity, touch, get_unit, get_person,
    get_action_item, recompute_unit, spawn_action_item, bubble_on_verify,
    bubble_on_reopen, ser_action_item, ser_evidence, ser_finding, sorted_rows,
    require_active_person, evidence_count,
)
import uuid

bp = Blueprint("actions", __name__)

PRIORITIES = ["P1", "P2", "P3"]
ACTION_STATUSES = ["OPEN", "IN_PROGRESS", "SUBMITTED_FOR_VERIFICATION",
                   "VERIFIED_CLOSED", "REJECTED", "VOID"]


@bp.post("/psm/units/<unit_id>/action-items")
@require_roles("PsmManager")
def create_action_item(unit_id):
    unit = get_unit(unit_id)
    b = body_json()
    title = f_str(b, "title")
    priority = f_enum(b, "priority", PRIORITIES)
    assignee_id = f_str(b, "assignee_id")
    due_in_days = f_int(b, "due_in_days", required=False, lo=1)
    require_active_person(assignee_id, "Assignee")
    item = spawn_action_item(unit["id"], "MANUAL", None, title, priority,
                             assignee_id, due_in_days=due_in_days)
    recompute_unit(unit)
    return ok(ser_action_item(item), 201)


@bp.get("/psm/units/<uid>/action-items")
@require_roles(*ALL_ROLES)
def list_unit_action_items(uid):
    unit = get_unit(uid)
    limit, offset = pagination_params()
    from flask import request
    status_f = request.args.get("status")
    priority_f = request.args.get("priority")
    if status_f is not None and status_f not in ACTION_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown status filter: {status_f}", 400)
    if priority_f is not None and priority_f not in PRIORITIES:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown priority filter: {priority_f}", 400)
    rows = [a for a in sorted_rows(store.action_items.values()) if a["unit_id"] == unit["id"]]
    if status_f is not None:
        rows = [a for a in rows if a["status"] == status_f]
    if priority_f is not None:
        rows = [a for a in rows if a["priority"] == priority_f]
    return ok_list([ser_action_item(a) for a in rows], limit, offset)


@bp.get("/psm/personnel/<pid>/action-items")
@require_roles(*ALL_ROLES)
def list_personnel_action_items(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_action_item(a) for a in sorted_rows(store.action_items.values())
            if a["assignee_id"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/action-items/<aid>")
@require_roles(*ALL_ROLES)
def get_one_action_item(aid):
    return ok(ser_action_item(get_action_item(aid)), 200)


@bp.post("/psm/action-items/<aid>/start")
@require_roles(*ENTITY_ROLES)
def start_action_item(aid):
    a = get_action_item(aid)
    if a["status"] not in ("OPEN", "REJECTED"):
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only OPEN or REJECTED items can be started", 409)
    if a["assignee_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the assignee may start work", 403)
    a["status"] = "IN_PROGRESS"
    touch(a)
    return ok(ser_action_item(a), 200)


@bp.post("/psm/action-items/<aid>/submit-verification")
@require_roles(*ENTITY_ROLES)
def submit_verification(aid):
    a = get_action_item(aid)
    if a["status"] != "IN_PROGRESS":
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only IN_PROGRESS items can be submitted", 409)
    if a["assignee_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the assignee may submit for verification", 403)
    if evidence_count(a) < 1:
        raise ApiError(ERR_NO_EVIDENCE_ATTACHED, "At least one evidence item is required", 409)
    a["completer_id"] = g.user_id
    a["status"] = "SUBMITTED_FOR_VERIFICATION"
    touch(a)
    return ok(ser_action_item(a), 200)


@bp.post("/psm/action-items/<aid>/verify")
@require_roles("PsmManager")
def verify_action_item(aid):
    a = get_action_item(aid)
    if a["status"] != "SUBMITTED_FOR_VERIFICATION":
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only SUBMITTED_FOR_VERIFICATION items can be verified", 409)
    if g.user_id == a["completer_id"]:
        raise ApiError(ERR_SOD_VERIFIER_IS_COMPLETER, "Verifier must differ from completer", 403)
    a["verifier_id"] = g.user_id
    a["status"] = "VERIFIED_CLOSED"
    touch(a)
    bubble_on_verify(a)
    recompute_unit(store.units[a["unit_id"]])
    return ok(ser_action_item(a), 200)


@bp.post("/psm/action-items/<aid>/reject-verification")
@require_roles("PsmManager")
def reject_verification(aid):
    a = get_action_item(aid)
    if a["status"] != "SUBMITTED_FOR_VERIFICATION":
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only SUBMITTED_FOR_VERIFICATION items can be rejected", 409)
    a["status"] = "REJECTED"  # completer_id retained for audit
    touch(a)
    return ok(ser_action_item(a), 200)


@bp.post("/psm/action-items/<aid>/reopen")
@require_roles("PsmManager")
def reopen_action_item(aid):
    a = get_action_item(aid)
    if a["status"] != "VERIFIED_CLOSED":
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only VERIFIED_CLOSED items can be reopened", 409)
    b = body_json()
    f_str(b, "reason")
    a["reopen_count"] += 1
    a["status"] = "IN_PROGRESS"
    touch(a)
    bubble_on_reopen(a)
    recompute_unit(store.units[a["unit_id"]])
    return ok(ser_action_item(a), 200)


@bp.post("/psm/action-items/<aid>/void")
@require_roles("PsmManager")
def void_action_item(aid):
    a = get_action_item(aid)
    if a["status"] not in ("OPEN", "IN_PROGRESS", "REJECTED"):
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE, "Only OPEN/IN_PROGRESS/REJECTED items can be voided", 409)
    a["status"] = "VOID"
    touch(a)
    recompute_unit(store.units[a["unit_id"]])
    return ok(ser_action_item(a), 200)


# ---------------------------------------------------------------------------
# Evidence (append-only: id + created_at only)
# ---------------------------------------------------------------------------

@bp.post("/psm/action-items/<aid>/evidence-items")
@require_roles(*ENTITY_ROLES)
def attach_evidence(aid):
    a = get_action_item(aid)
    if a["status"] not in ("OPEN", "IN_PROGRESS", "REJECTED"):
        raise ApiError(ERR_ACTION_ITEM_INVALID_STATE,
                       "Evidence accepted only while OPEN, IN_PROGRESS or REJECTED", 409)
    if a["assignee_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the assignee may attach evidence", 403)
    b = body_json()
    file_ref = f_str(b, "file_ref")
    description = f_str(b, "description")
    store.seq += 1
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": store.seq,
        "action_item_id": a["id"],
        "file_ref": file_ref,
        "description": description,
        "uploaded_by": g.user_id,
    }
    store.evidence[e["id"]] = e
    touch(a)  # evidence_count changed
    return ok(ser_evidence(e), 201)


@bp.get("/psm/action-items/<aid>/evidence-items")
@require_roles(*ALL_ROLES)
def list_item_evidence(aid):
    a = get_action_item(aid)
    limit, offset = pagination_params()
    rows = [ser_evidence(e) for e in sorted_rows(store.evidence.values())
            if e["action_item_id"] == a["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>/evidence-items")
@require_roles(*ALL_ROLES)
def list_personnel_evidence(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_evidence(e) for e in sorted_rows(store.evidence.values())
            if e["uploaded_by"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/action-items/<aid>/audit-findings")
@require_roles(*ALL_ROLES)
def list_item_audit_findings(aid):
    a = get_action_item(aid)
    limit, offset = pagination_params()
    rows = [ser_finding(f) for f in sorted_rows(store.findings.values())
            if f["corrective_action_id"] == a["id"]]
    return ok_list(rows, limit, offset)
