from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("projects", __name__)
COLL = "projects"

SCOPE_TYPES = {"RESET", "NEW_ITEM_CUTOVER", "AUDIT", "FIXTURE_INSTALL"}


def _get_project_or_404(pid):
    project = db.collections[COLL].get(pid)
    if project is None:
        raise errors.not_found("project not found")
    return project


@bp.post("/projects")
def create_project():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    # Priority 3 (existence) precedes priority 13 (input sanitization): a
    # present-but-unresolvable client_id is 404; a missing one is 400.
    client_id = body.get("client_id")
    client = None
    if client_id is not None:
        if not isinstance(client_id, str) or client_id not in db.collections["clients"]:
            raise errors.not_found("client not found")
        client = db.collections["clients"][client_id]
    # Priority 13: input sanitization
    if client is None:
        raise errors.invalid_request("client_id is required")
    title = mw.req_str(body, "title")
    scope_type = mw.req_enum(body, "scope_type", SCOPE_TYPES)
    billing_model = mw.opt_enum(body, "billing_model", {"PER_STORE", "HOURLY"})
    project = db.base_fields()
    project.update({
        "client_id": client_id,
        "title": title,
        "scope_type": scope_type,
        "status": "DRAFT",
        "billing_model": billing_model,
        "effective_billing_model": None,
        "rework_penalty_score": 0,
        "posture": "NORMAL",
        "completed_store_count": 0,
    })
    db.collections[COLL][project["id"]] = project
    return resp.success_object(db.serialize(project), 201)


@bp.get("/projects")
def list_projects():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "BillingClerk", "Client"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [p for p in items if p["client_id"] == uid]
    cid = mw.request.args.get("client_id")
    if cid is not None:
        items = [p for p in items if p["client_id"] == cid]
    st = mw.request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    posture = mw.request.args.get("posture")
    if posture is not None:
        items = [p for p in items if p["posture"] == posture]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/projects/<pid>")
def get_project(pid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "BillingClerk", "Client", "PayrollAdmin"})
    project = _get_project_or_404(pid)
    if role == "Client" and project["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's project")
    return resp.success_object(db.serialize(project))


@bp.get("/projects/<pid>/project-stores")
def list_project_project_stores(pid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    project = _get_project_or_404(pid)
    if role == "Client" and project["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's project")
    items = [ps for ps in db.collections["project_stores"].values() if ps["project_id"] == pid]
    st = mw.request.args.get("status")
    if st is not None:
        items = [ps for ps in items if ps["status"] == st]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.post("/projects/<pid>/scope")
def scope_project(pid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    project = _get_project_or_404(pid)
    body = mw.get_body()
    # Priority 4: state legality (DRAFT + transition preconditions).
    if project["status"] != "DRAFT":
        raise errors.invalid_state("project is not DRAFT")
    pending = [ps for ps in services.project_store_rows(pid) if ps["status"] == "PENDING"]
    if not pending:
        raise errors.invalid_state("project has no PENDING store-list rows")
    client = services.get_client(project["client_id"])
    if client is None or client["status"] != "ACTIVE":
        raise errors.invalid_state("client is not ACTIVE")
    # Priority 10: billing model resolvability.
    effective = project["billing_model"] or client["billing_model"]
    if effective is None:
        raise errors.billing_model_unresolvable(
            "neither project.billing_model nor client.billing_model is set")
    if effective == "HOURLY" and client.get("hourly_rate_cents") is None:
        raise errors.billing_model_unresolvable("client.hourly_rate_cents is not set")
    if effective == "PER_STORE" and client.get("per_store_rate_cents") is None:
        raise errors.billing_model_unresolvable("client.per_store_rate_cents is not set")
    # Priority 13: input sanitization.
    expected = mw.req_int(body, "expected_project_version")
    # Priority 14: OCC.
    if expected != project["version"]:
        raise errors.stale_project_version()
    project["status"] = "SCOPED"
    project["effective_billing_model"] = effective
    db.touch(project)
    return resp.success_object(db.serialize(project))


@bp.post("/projects/<pid>/cancel")
def cancel_project(pid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    project = _get_project_or_404(pid)
    status = project["status"]
    if status in ("DRAFT", "SCOPED"):
        drop_statuses = {"PENDING", "ASSIGNED"}
    elif status == "IN_FIELD":
        # No assignment of the project may be ON_SITE.
        for a in db.collections["assignments"].values():
            if a["project_id"] == pid and a["status"] == "ON_SITE":
                raise errors.invalid_state("an assignment of the project is ON_SITE")
        drop_statuses = {"PENDING", "ASSIGNED", "IN_PROGRESS", "REWORK_REQUIRED"}
    else:
        raise errors.invalid_state(f"project in {status} cannot be cancelled")
    # Cascade: cancel live assignments and drop store rows.
    for a in db.collections["assignments"].values():
        if a["project_id"] == pid and a["status"] in ("SCHEDULED", "EN_ROUTE"):
            a["status"] = "CANCELLED"
            db.touch(a)
    for ps in services.project_store_rows(pid):
        if ps["status"] in drop_statuses:
            ps["status"] = "DROPPED"
            ps["assigned_rep_id"] = None
            db.touch(ps)
    project["status"] = "CANCELLED"
    db.touch(project)
    return resp.success_object(db.serialize(project))
