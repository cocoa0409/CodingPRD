from flask import Blueprint

import services
from db import bump, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj
from serialize import ser_recall
from validate import req_enum, req_str

bp = Blueprint("recalls", __name__)

SEVERITIES = ("ADVISORY", "MANDATORY")


def _get_recall(rid):
    r = store.recalls.get(rid)
    if r is None:
        raise ApiError("ERR_RECALL_NOT_FOUND", 404, "Recall notice not found")
    return r


@bp.post("/recalls")
def create_recall():
    require_roles("OperationsAdmin")
    b = body()
    item_id = b.get("catalog_item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "catalog_item_id is required")
    if item_id not in store.catalog_items:
        raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND", 404, "Catalog item not found")
    code = req_str(b, "recall_code")
    severity = req_enum(b, "severity", SEVERITIES)
    description = req_str(b, "description")
    rec = create_rec(store.recalls, {
        "catalog_item_id": item_id, "recall_code": code, "severity": severity,
        "description": description, "status": "DRAFT", "activated_at": None})
    return ok_obj(ser_recall(rec), 201)


@bp.get("/recalls/<rid>")
def get_recall(rid):
    require_roles("Inspector", "OperationsAdmin")
    return ok_obj(ser_recall(_get_recall(rid)))


@bp.post("/recalls/<rid>/activate")
def activate(rid):
    require_roles("OperationsAdmin")
    recall = _get_recall(rid)
    services.activate_recall(recall)
    return ok_obj(ser_recall(recall))


@bp.post("/recalls/<rid>/close")
def close(rid):
    require_roles("OperationsAdmin")
    recall = _get_recall(rid)
    if recall["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Recall is not ACTIVE")
    if any(u["catalog_item_id"] == recall["catalog_item_id"]
           and u["status"] == "QUARANTINED" for u in store.units.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Units of the recalled item are still QUARANTINED")
    recall["status"] = "CLOSED"
    bump(recall)
    return ok_obj(ser_recall(recall))
