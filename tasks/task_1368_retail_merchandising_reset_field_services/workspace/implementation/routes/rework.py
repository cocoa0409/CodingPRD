from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("rework", __name__)
COLL = "rework_auths"


def _get_ra_or_404(rid):
    ra = db.collections[COLL].get(rid)
    if ra is None:
        raise errors.not_found("rework authorization not found")
    return ra


def _require_owning_client(uid, ra):
    project = services.get_project(ra["project_id"])
    if project is None or project["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's project")
    return project


@bp.post("/rework-authorizations")
def create_rework_authorization():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    # Priority 3: existence, left-to-right.
    project = None
    pid = body.get("project_id")
    if pid is not None:
        if not isinstance(pid, str) or pid not in db.collections["projects"]:
            raise errors.not_found("project not found")
        project = db.collections["projects"][pid]
    ps = None
    psid = body.get("project_store_id")
    if psid is not None:
        if not isinstance(psid, str) or psid not in db.collections["project_stores"]:
            raise errors.not_found("project-store row not found")
        ps = db.collections["project_stores"][psid]
    visit = None
    vid = body.get("rejected_store_visit_id")
    if vid is not None:
        if not isinstance(vid, str) or vid not in db.collections["store_visits"]:
            raise errors.not_found("store visit not found")
        visit = db.collections["store_visits"][vid]
    # Priority 5: cross-entity ownership — store must belong to the project, and
    # the rejected visit must belong to that store's chain.
    if project is not None and ps is not None and ps["project_id"] != pid:
        raise errors.cross_entity_mismatch("project_store does not belong to project")
    if visit is not None and ps is not None:
        a = db.collections["assignments"].get(visit["assignment_id"])
        if a is None or a["project_store_id"] != psid:
            raise errors.cross_entity_mismatch("rejected visit does not belong to the store")
    # Priority 13: input sanitization.
    if project is None:
        raise errors.invalid_request("project_id is required")
    if ps is None:
        raise errors.invalid_request("project_store_id is required")
    if visit is None:
        raise errors.invalid_request("rejected_store_visit_id is required")
    reason = mw.req_str(body, "reason")
    ra = db.base_fields()
    ra.update({
        "project_id": pid,
        "project_store_id": psid,
        "rejected_store_visit_id": vid,
        "status": "REQUESTED",
        "reason": reason,
    })
    db.collections[COLL][ra["id"]] = ra
    return resp.success_object(db.serialize(ra), 201)


@bp.get("/rework-authorizations")
def list_rework_authorizations():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [r for r in items
                 if (services.get_project(r["project_id"]) or {}).get("client_id") == uid]
    for key in ("project_id", "project_store_id", "rejected_store_visit_id", "status"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/rework-authorizations/<rid>")
def get_rework_authorization(rid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client"})
    ra = _get_ra_or_404(rid)
    if role == "Client":
        _require_owning_client(uid, ra)
    return resp.success_object(db.serialize(ra))


@bp.post("/rework-authorizations/<rid>/approve")
def approve_rework(rid):
    uid, role = mw.auth()
    mw.require_role(role, {"Client"})
    ra = _get_ra_or_404(rid)
    project = _require_owning_client(uid, ra)
    if ra["status"] != "REQUESTED":
        raise errors.invalid_state("rework authorization is not REQUESTED")
    if project is not None and project["posture"] == "ESCALATED":
        raise errors.posture_escalated()
    ra["status"] = "APPROVED"
    db.touch(ra)
    return resp.success_object(db.serialize(ra))


@bp.post("/rework-authorizations/<rid>/deny")
def deny_rework(rid):
    uid, role = mw.auth()
    mw.require_role(role, {"Client"})
    ra = _get_ra_or_404(rid)
    project = _require_owning_client(uid, ra)
    if ra["status"] != "REQUESTED":
        raise errors.invalid_state("rework authorization is not REQUESTED")
    ra["status"] = "DENIED"
    db.touch(ra)
    if project is not None:
        services.add_penalty(project, services.DENY_PENALTY)
    return resp.success_object(db.serialize(ra))
