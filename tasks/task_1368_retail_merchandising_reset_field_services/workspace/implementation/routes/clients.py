from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("clients", __name__)

COLL = "clients"


@bp.post("/clients")
def create_client():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    name = mw.req_str(body, "name")
    billing_model = mw.opt_enum(body, "billing_model", {"PER_STORE", "HOURLY"})
    hourly = mw.opt_int(body, "hourly_rate_cents", min_val=0)
    per_store = mw.opt_int(body, "per_store_rate_cents", min_val=0)
    if billing_model == "HOURLY" and hourly is None:
        raise errors.invalid_request("hourly_rate_cents is required when billing_model is HOURLY")
    if billing_model == "PER_STORE" and per_store is None:
        raise errors.invalid_request("per_store_rate_cents is required when billing_model is PER_STORE")
    client = db.base_fields()
    client.update({
        "name": name,
        "billing_model": billing_model,
        "status": "ACTIVE",
        "hourly_rate_cents": hourly,
        "per_store_rate_cents": per_store,
    })
    db.collections[COLL][client["id"]] = client
    return resp.success_object(db.serialize(client), 201)


@bp.get("/clients")
def list_clients():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "BillingClerk", "PayrollAdmin"})
    items = list(db.collections[COLL].values())
    status = mw.request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/clients/<cid>")
def get_client(cid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "BillingClerk", "PayrollAdmin", "Client"})
    client = db.collections[COLL].get(cid)
    if client is None:
        raise errors.not_found("client not found")
    if role == "Client" and client["id"] != uid:
        raise errors.unauthorized("client acting on another client")
    return resp.success_object(db.serialize(client))


@bp.get("/clients/<cid>/invoices")
def list_client_invoices(cid):
    uid, role = mw.auth()
    mw.require_role(role, {"BillingClerk", "ProjectManager", "Client"})
    client = db.collections[COLL].get(cid)
    if client is None:
        raise errors.not_found("client not found")
    if role == "Client" and client["id"] != uid:
        raise errors.unauthorized("client acting on another client")
    items = [i for i in db.collections["invoices"].values() if i["client_id"] == cid]
    status = mw.request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)
