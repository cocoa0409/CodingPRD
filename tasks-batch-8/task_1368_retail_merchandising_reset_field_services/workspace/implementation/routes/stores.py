from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("stores", __name__)
COLL = "stores"


@bp.post("/stores")
def create_store():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    body = mw.get_body()
    store = db.base_fields()
    store.update({
        "store_number": mw.req_str(body, "store_number"),
        "name": mw.req_str(body, "name"),
        "address": mw.req_str(body, "address"),
        "timezone": mw.req_str(body, "timezone"),
    })
    db.collections[COLL][store["id"]] = store
    return resp.success_object(db.serialize(store), 201)


@bp.get("/stores")
def list_stores():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "FieldRep"})
    items = db.sorted_by_creation(list(db.collections[COLL].values()))
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/stores/<sid>")
def get_store(sid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "FieldRep", "Client"})
    store = db.collections[COLL].get(sid)
    if store is None:
        raise errors.not_found("store not found")
    return resp.success_object(db.serialize(store))
