from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("project_stores", __name__)
COLL = "project_stores"


def _get_ps_or_404(psid):
    ps = db.collections[COLL].get(psid)
    if ps is None:
        raise errors.not_found("project-store row not found")
    return ps


@bp.post("/project-stores")
def create_project_store():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    # Priority 3: existence, left-to-right (project_id, then store_id).
    project = None
    pid = body.get("project_id")
    if pid is not None:
        if not isinstance(pid, str) or pid not in db.collections["projects"]:
            raise errors.not_found("project not found")
        project = db.collections["projects"][pid]
    store = None
    sid = body.get("store_id")
    if sid is not None:
        if not isinstance(sid, str) or sid not in db.collections["stores"]:
            raise errors.not_found("store not found")
        store = db.collections["stores"][sid]
    # Priority 4: project must be in a mutable (non-terminal, non-reconciling) state.
    if project is not None and project["status"] in ("RECONCILING", "COMPLETED", "CANCELLED"):
        raise errors.invalid_state(f"cannot add store rows to a {project['status']} project")
    # Priority 6: due_date not before the current logical date.
    due_raw = body.get("due_date")
    due = mw.parse_date(due_raw) if due_raw is not None else None
    if due is not None and due < db.now().date():
        raise errors.temporal_invalid("due_date is before the project's scope date")
    # Priority 8: store-list uniqueness among non-DROPPED rows.
    if project is not None and store is not None:
        for row in db.collections[COLL].values():
            if (row["project_id"] == pid and row["store_id"] == sid
                    and row["status"] != "DROPPED"):
                raise errors.duplicate_store()
    # Priority 13: input sanitization.
    if project is None:
        raise errors.invalid_request("project_id is required")
    if store is None:
        raise errors.invalid_request("store_id is required")
    if due is None:
        raise errors.invalid_request("due_date is required and must be an ISO date")
    ps = db.base_fields()
    ps.update({
        "project_id": pid,
        "store_id": sid,
        "status": "PENDING",
        "due_date": due_raw,
        "assigned_rep_id": None,
    })
    db.collections[COLL][ps["id"]] = ps
    # Store-list mutation is a project mutation for OCC purposes.
    db.touch(project)
    return resp.success_object(db.serialize(ps), 201)


@bp.get("/project-stores")
def list_project_stores():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [ps for ps in items
                 if (services.get_project(ps["project_id"]) or {}).get("client_id") == uid]
    elif role == "FieldRep":
        items = [ps for ps in items if ps.get("assigned_rep_id") == uid]
    for key in ("project_id", "store_id", "status", "assigned_rep_id"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [ps for ps in items if ps.get(key) == v]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/project-stores/<psid>")
def get_project_store(psid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    ps = _get_ps_or_404(psid)
    if role == "Client":
        project = services.get_project(ps["project_id"])
        if project is None or project["client_id"] != uid:
            raise errors.unauthorized("client acting on another client's project")
    return resp.success_object(db.serialize(ps))


@bp.post("/project-stores/<psid>/drop")
def drop_project_store(psid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    ps = _get_ps_or_404(psid)
    project = services.get_project(ps["project_id"])
    # Priority 4: state legality.
    if project is not None and project["status"] in ("COMPLETED", "CANCELLED"):
        raise errors.invalid_state("project is terminal")
    if ps["status"] not in ("PENDING", "ASSIGNED", "REWORK_REQUIRED"):
        raise errors.invalid_state(f"project-store row in {ps['status']} cannot be dropped")
    if ps["status"] == "ASSIGNED":
        for a in db.collections["assignments"].values():
            if a["project_store_id"] == psid and a["status"] == "ON_SITE":
                raise errors.invalid_state("an assignment of the store is ON_SITE")
    # Side effects: cancel non-terminal assignments of the store.
    for a in db.collections["assignments"].values():
        if a["project_store_id"] == psid and a["status"] in ("SCHEDULED", "EN_ROUTE"):
            a["status"] = "CANCELLED"
            db.touch(a)
    # Expire open rework authorizations for the store (no penalty on drop path).
    for ra in db.collections["rework_auths"].values():
        if ra["project_store_id"] == psid and ra["status"] in ("REQUESTED", "APPROVED"):
            ra["status"] = "EXPIRED"
            db.touch(ra)
    ps["status"] = "DROPPED"
    ps["assigned_rep_id"] = None
    db.touch(ps)
    # Store-list mutation is a project mutation for OCC purposes.
    if project is not None:
        db.touch(project)
        services.maybe_cascade_reconciling(project)
    return resp.success_object(db.serialize(ps))
