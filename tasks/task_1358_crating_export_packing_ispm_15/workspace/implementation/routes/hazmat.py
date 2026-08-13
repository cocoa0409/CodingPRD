"""HazmatDeclaration endpoints (PRD §3.5, §2.10 SoD)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import ApiError, ERR_DECLARATION_INVALID_STATE, ERR_SOD_VIOLATION, not_found
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_enum,
                        opt_enum, paginate, enum_filter, str_filter)
from response import success
from services.state import get, ser_declaration

bp = Blueprint("hazmat", __name__)

DG_CLASSES = {"1", "2.1", "3", "4.1", "5.1", "6.1", "8", "9"}
PACKING_GROUPS = {"I", "II", "III"}
BATTERY_TYPES = {"NONE", "LITHIUM_ION", "LITHIUM_METAL", "WET_CELL"}
DECL_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"}
EDITOR_ROLES = ["ShopForeman", "ComplianceOfficer"]


def _get_decl_or_404(did):
    d = get("declarations", did)
    if not d:
        raise not_found("HazmatDeclaration not found")
    return d


@bp.post("/crating/items/<item_id>/hazmat-declarations")
def create_declaration(item_id):
    uid, _ = require_roles(EDITOR_ROLES)
    d = body()
    un_number = req_str(d, "un_number")
    dg_class = req_enum(d, "dg_class", DG_CLASSES)
    packing_group = req_enum(d, "packing_group", PACKING_GROUPS)
    battery_type = opt_enum(d, "battery_type", BATTERY_TYPES) or "NONE"
    it = get("items", item_id)
    if not it:
        raise not_found("Item not found")
    rec = {
        "id": new_id(), "item_id": item_id, "un_number": un_number,
        "dg_class": dg_class, "packing_group": packing_group,
        "battery_type": battery_type, "prepared_by_user_id": uid,
        "approved_by_user_id": None, "revision": 1, "status": "DRAFT",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    STORE["declarations"][rec["id"]] = rec
    return success(ser_declaration(rec), status=201)


@bp.get("/crating/hazmat-declarations/<did>")
def get_declaration(did):
    require_roles(ALL_OPERATIONAL)
    return success(ser_declaration(_get_decl_or_404(did)))


@bp.get("/crating/hazmat-declarations")
def list_declarations():
    require_roles(ALL_OPERATIONAL)
    item_id = str_filter("item_id")
    status = enum_filter("status", DECL_STATUSES)
    recs = [d for d in STORE["declarations"].values()
            if (item_id is None or d["item_id"] == item_id)
            and (status is None or d["status"] == status)]
    recs.sort(key=lambda d: d["created_at"])
    page, meta = paginate(recs)
    return success([ser_declaration(d) for d in page], pagination=meta)


@bp.post("/crating/hazmat-declarations/<did>/submit")
def submit_declaration(did):
    require_roles(EDITOR_ROLES)
    d = _get_decl_or_404(did)
    if d["status"] != "DRAFT":
        raise ApiError(ERR_DECLARATION_INVALID_STATE, "submit requires status DRAFT", 409)
    d["status"] = "SUBMITTED"
    touch(d)
    return success(ser_declaration(d))


@bp.post("/crating/hazmat-declarations/<did>/approve")
def approve_declaration(did):
    uid, _ = require_roles(["ComplianceOfficer"])
    d = _get_decl_or_404(did)
    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_DECLARATION_INVALID_STATE, "approve requires status SUBMITTED", 409)
    if uid == d["prepared_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Approver must differ from preparer", 403)
    d["status"] = "APPROVED"
    d["approved_by_user_id"] = uid
    touch(d)
    return success(ser_declaration(d))


@bp.post("/crating/hazmat-declarations/<did>/reject")
def reject_declaration(did):
    uid, _ = require_roles(["ComplianceOfficer"])
    d = _get_decl_or_404(did)
    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_DECLARATION_INVALID_STATE, "reject requires status SUBMITTED", 409)
    if uid == d["prepared_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Rejector must differ from preparer", 403)
    d["status"] = "REJECTED"
    touch(d)
    return success(ser_declaration(d))


@bp.post("/crating/hazmat-declarations/<did>/revise")
def revise_declaration(did):
    require_roles(EDITOR_ROLES)
    d = _get_decl_or_404(did)
    if d["status"] != "REJECTED":
        raise ApiError(ERR_DECLARATION_INVALID_STATE, "revise requires status REJECTED", 409)
    d["status"] = "DRAFT"
    d["revision"] += 1
    d["approved_by_user_id"] = None
    touch(d)
    return success(ser_declaration(d))
