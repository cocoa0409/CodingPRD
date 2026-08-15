from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("invoices", __name__)
COLL = "invoices"


def _get_invoice_or_404(iid):
    inv = db.collections[COLL].get(iid)
    if inv is None:
        raise errors.not_found("invoice not found")
    return inv


@bp.post("/invoices")
def create_invoice():
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk"})
    body = mw.get_body()
    # Priority 3: existence, left-to-right.
    client = None
    cid = body.get("client_id")
    if cid is not None:
        if not isinstance(cid, str) or cid not in db.collections["clients"]:
            raise errors.not_found("client not found")
        client = db.collections["clients"][cid]
    project = None
    pid = body.get("project_id")
    if pid is not None:
        if not isinstance(pid, str) or pid not in db.collections["projects"]:
            raise errors.not_found("project not found")
        project = db.collections["projects"][pid]
    # Priority 5: cross-entity ownership.
    if client is not None and project is not None and project["client_id"] != cid:
        raise errors.cross_entity_mismatch("project does not belong to client")
    # Business: only one live (OPEN or FINALIZED) invoice per project.
    if project is not None and services.find_live_invoice(pid) is not None:
        raise errors.duplicate_invoice()
    # Priority 13: input sanitization.
    if client is None:
        raise errors.invalid_request("client_id is required")
    if project is None:
        raise errors.invalid_request("project_id is required")
    adjustment = mw.opt_int(body, "adjustment_cents")
    inv = services.create_invoice(cid, pid, adjustment if adjustment is not None else 0)
    return resp.success_object(db.serialize(inv), 201)


@bp.get("/invoices")
def list_invoices():
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk", "ProjectManager", "Client"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [i for i in items if i["client_id"] == uid]
    for key in ("client_id", "project_id", "status"):
        v = mw.request.args.get(key)
        if v is not None:
            items = [i for i in items if i.get(key) == v]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk", "ProjectManager", "Client"})
    inv = _get_invoice_or_404(iid)
    if role == "Client" and inv["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's invoice")
    return resp.success_object(db.serialize(inv))


@bp.post("/invoices/<iid>/finalize")
def finalize_invoice(iid):
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk"})
    inv = _get_invoice_or_404(iid)
    body = mw.get_body()
    # Priority 4: state legality.
    if inv["status"] != "OPEN":
        raise errors.invalid_state("invoice is not OPEN")
    project = services.get_project(inv["project_id"])
    if project is None or project["status"] != "RECONCILING":
        raise errors.invalid_state("project is not RECONCILING")
    # Priority 11: no exception on any visit of the project may remain OPEN.
    for v in services.visits_of_project(project["id"]):
        for e in db.collections["exceptions"].values():
            if e["store_visit_id"] == v["id"] and e["resolution"] == "OPEN":
                raise errors.open_exceptions()
    # Priority 13: input sanitization.
    expected = mw.req_int(body, "expected_invoice_version")
    adjustment = mw.opt_int(body, "adjustment_cents")
    # Priority 15: OCC.
    if expected != inv["version"]:
        raise errors.stale_invoice_version()
    if adjustment is not None:
        inv["adjustment_cents"] = adjustment
    inv["line_total_cents"] = services.compute_line_total_cents(project["id"])
    inv["grand_total_cents"] = inv["line_total_cents"] + inv["adjustment_cents"]
    inv["status"] = "FINALIZED"
    db.touch(inv)
    project["status"] = "COMPLETED"
    db.touch(project)
    return resp.success_object(db.serialize(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk"})
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "OPEN":
        raise errors.invalid_state("invoice is not OPEN")
    inv["status"] = "VOID"
    db.touch(inv)
    return resp.success_object(db.serialize(inv))
