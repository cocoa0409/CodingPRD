"""Pssr endpoints."""
from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_STALE_MOC_VERSION, ERR_MOC_INVALID_STATE, ERR_PSSR_INVALID_STATE,
    ERR_QUALIFICATION_MISSING, ERR_NOT_RESOURCE_OWNER, ERR_SOD_PSSR_LEAD_IS_REQUESTER,
    ERR_FIELDWORK_WINDOW_NOT_ACTIVE, ERR_PSSR_WINDOW_OVERLAP,
    ERR_PSSR_OPEN_PUNCH_ITEMS, ERR_INVALID_REQUEST,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_enum, f_day, f_int,
)
from services import (
    new_entity, touch, get_person, get_moc, get_pssr, recompute_unit,
    spawn_action_item, ser_pssr, ser_action_item, sorted_rows,
    require_active_person,
)

bp = Blueprint("pssr", __name__)

LIVE_PSSR_STATUSES = ("PLANNED", "IN_FIELD", "PUNCH_LIST")


def _check_occ(b, moc):
    """OCC (priority 4): expected_moc_version must match before any business check."""
    v = b.get("expected_moc_version")
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: expected_moc_version", 400)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_moc_version must be an integer", 400)
    if v != moc["version"]:
        raise ApiError(ERR_STALE_MOC_VERSION, "expected_moc_version is stale", 412)


@bp.post("/psm/moc-requests/<mid>/pssrs")
@require_roles("PssrLead")
def create_pssr(mid):
    m = get_moc(mid)
    b = body_json()
    _check_occ(b, m)
    if m["status"] not in ("APPROVED_IMPLEMENTATION", "IMPLEMENTED_PSSR_PENDING"):
        raise ApiError(ERR_MOC_INVALID_STATE,
                       "MOC must be APPROVED_IMPLEMENTATION or IMPLEMENTED_PSSR_PENDING", 409)
    lead = store.personnel.get(g.user_id)
    if lead is None or "PSSR_CERTIFIED" not in lead["qualifications"]:
        raise ApiError(ERR_QUALIFICATION_MISSING, "PSSR lead must hold PSSR_CERTIFIED", 403)
    start = f_day(b, "field_window_start")
    end = f_day(b, "field_window_end")
    if end < start:
        raise ApiError(ERR_INVALID_REQUEST, "field_window_end must be on or after field_window_start", 400)
    unit_id = m["unit_id"]
    # Half-open [start, end) overlap vs live PSSRs on the same unit (any MOC),
    # excluding the same-MOC PLANNED sibling that this create supersedes.
    for p in store.pssrs.values():
        other_moc = store.mocs[p["moc_id"]]
        if other_moc["unit_id"] != unit_id or p["status"] not in LIVE_PSSR_STATUSES:
            continue
        if p["moc_id"] == m["id"] and p["status"] == "PLANNED":
            continue
        if start < p["field_window_end"] and p["field_window_start"] < end:
            raise ApiError(ERR_PSSR_WINDOW_OVERLAP,
                           "Window overlaps a live PSSR on the same unit", 409)
    # Supersede the prior PLANNED sibling on this MOC.
    for p in store.pssrs.values():
        if p["moc_id"] == m["id"] and p["status"] == "PLANNED":
            p["status"] = "VOID"
            touch(p)
    p = new_entity()
    p.update({
        "moc_id": m["id"],
        "lead_id": g.user_id,
        "status": "PLANNED",
        "field_window_start": start,
        "field_window_end": end,
        "approved_at": None,
    })
    store.pssrs[p["id"]] = p
    touch(m)  # supersede decision advances the parent MOC version
    return ok(ser_pssr(p), 201)


@bp.get("/psm/moc-requests/<mid>/pssrs")
@require_roles(*ALL_ROLES)
def list_moc_pssrs(mid):
    m = get_moc(mid)
    limit, offset = pagination_params()
    rows = [ser_pssr(p) for p in sorted_rows(store.pssrs.values()) if p["moc_id"] == m["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>/pssrs")
@require_roles(*ALL_ROLES)
def list_personnel_pssrs(pid):
    person = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_pssr(p) for p in sorted_rows(store.pssrs.values()) if p["lead_id"] == person["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/pssrs/<pid>")
@require_roles(*ALL_ROLES)
def get_one_pssr(pid):
    return ok(ser_pssr(get_pssr(pid)), 200)


@bp.post("/psm/pssrs/<pid>/begin-fieldwork")
@require_roles("PssrLead")
def begin_fieldwork(pid):
    p = get_pssr(pid)
    if p["status"] != "PLANNED":
        raise ApiError(ERR_PSSR_INVALID_STATE, "Only a PLANNED PSSR can begin fieldwork", 409)
    if p["lead_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the recorded lead may begin fieldwork", 403)
    if not (p["field_window_start"] <= store.clock <= p["field_window_end"]):
        raise ApiError(ERR_FIELDWORK_WINDOW_NOT_ACTIVE, "Clock is outside the field window", 409)
    p["status"] = "IN_FIELD"
    touch(p)
    return ok(ser_pssr(p), 200)


@bp.post("/psm/pssrs/<pid>/punch-items")
@require_roles("PssrLead")
def raise_punch_item(pid):
    p = get_pssr(pid)
    if p["status"] != "IN_FIELD":
        raise ApiError(ERR_PSSR_INVALID_STATE, "Punch items may be raised only while IN_FIELD", 409)
    if p["lead_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the recorded lead may raise punch items", 403)
    b = body_json()
    title = f_str(b, "title")
    priority = f_enum(b, "priority", ["P1", "P2", "P3"])
    assignee_id = f_str(b, "assignee_id")
    due_in_days = f_int(b, "due_in_days", required=False, lo=1)
    require_active_person(assignee_id, "Assignee")
    m = store.mocs[p["moc_id"]]
    item = spawn_action_item(m["unit_id"], "PSSR", p["id"], title, priority,
                             assignee_id, due_in_days=due_in_days)
    p["status"] = "PUNCH_LIST"  # first punch item moves IN_FIELD -> PUNCH_LIST
    touch(p)
    recompute_unit(store.units[m["unit_id"]])
    return ok(ser_action_item(item), 201)


@bp.post("/psm/pssrs/<pid>/approve")
@require_roles("PssrLead")
def approve_pssr(pid):
    p = get_pssr(pid)
    if p["status"] not in ("IN_FIELD", "PUNCH_LIST"):
        raise ApiError(ERR_PSSR_INVALID_STATE, "PSSR must be IN_FIELD or PUNCH_LIST to approve", 409)
    if p["lead_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the recorded lead may approve", 403)
    m = store.mocs[p["moc_id"]]
    if g.user_id == m["requester_id"]:
        raise ApiError(ERR_SOD_PSSR_LEAD_IS_REQUESTER, "Lead must differ from the MOC requester", 403)
    from services import punch_open_count
    if punch_open_count(p) != 0:
        raise ApiError(ERR_PSSR_OPEN_PUNCH_ITEMS, "Open punch items block PSSR approval", 409)
    if m["status"] != "IMPLEMENTED_PSSR_PENDING":
        raise ApiError(ERR_MOC_INVALID_STATE, "MOC must be IMPLEMENTED_PSSR_PENDING", 409)
    p["approved_at"] = store.clock
    p["status"] = "APPROVED"
    touch(p)
    return ok(ser_pssr(p), 200)


@bp.post("/psm/pssrs/<pid>/reject")
@require_roles("PssrLead")
def reject_pssr(pid):
    p = get_pssr(pid)
    if p["status"] not in ("IN_FIELD", "PUNCH_LIST"):
        raise ApiError(ERR_PSSR_INVALID_STATE, "PSSR must be IN_FIELD or PUNCH_LIST to reject", 409)
    if p["lead_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the recorded lead may reject", 403)
    p["status"] = "REJECTED"
    touch(p)
    m = store.mocs[p["moc_id"]]
    if m["status"] == "IMPLEMENTED_PSSR_PENDING":
        # Backward branch: the MOC must re-clear mark-implemented.
        m["status"] = "APPROVED_IMPLEMENTATION"
        touch(m)
    return ok(ser_pssr(p), 200)
