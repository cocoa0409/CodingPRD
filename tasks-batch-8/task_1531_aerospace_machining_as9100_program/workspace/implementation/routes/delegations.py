"""Delegated inspection authority endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, base_record, public, touch
from errors import (
    ApiError,
    ERR_DELEGATION_NOT_FOUND,
    ERR_DELEGATION_WINDOW_OVERLAP,
    ERR_DIA_COOLING_OFF,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_PO_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from validate import json_body, no_unknown, paginate, req_date, req_str

bp = Blueprint("delegations", __name__)

CQR = "CustomerQualityRep"
COOLING_OFF_DAYS = 30


def get_delegation(dia_id):
    d = db.delegations.get(dia_id)
    if d is None:
        raise ApiError(ERR_DELEGATION_NOT_FOUND, 404, "Delegation %s not found" % dia_id)
    return d


@bp.route("/api/delegations", methods=["POST"])
def create_delegation():
    uid = require_roles(CQR)
    data = json_body()
    no_unknown(data, {"po_id", "inspector_user_id", "valid_from", "valid_to"})
    po_id = req_str(data, "po_id")
    inspector = req_str(data, "inspector_user_id")
    valid_from, from_d = req_date(data, "valid_from")
    valid_to, to_d = req_date(data, "valid_to")

    po = db.purchase_orders.get(po_id)
    if po is None:
        raise ApiError(ERR_PO_NOT_FOUND, 404, "Purchase order %s not found" % po_id)
    # Closed window: valid_to earlier than valid_from is invalid
    if to_d < from_d:
        raise ApiError(ERR_INVALID_WINDOW, 400, "valid_to must not be earlier than valid_from")
    # Closed windows: touching boundaries count as overlap
    for d in db.delegations.values():
        if (
            d["po_id"] == po_id
            and d["inspector_user_id"] == inspector
            and d["status"] == "ACTIVE"
            and from_d <= d["_to_d"]
            and d["_from_d"] <= to_d
        ):
            raise ApiError(
                ERR_DELEGATION_WINDOW_OVERLAP,
                409,
                "Window intersects an ACTIVE delegation for this PO and inspector",
            )
    # 30-day post-revocation cooling-off
    for d in db.delegations.values():
        if (
            d["po_id"] == po_id
            and d["inspector_user_id"] == inspector
            and d["status"] == "REVOKED"
            and d.get("_revoked_dt") is not None
        ):
            threshold = d["_revoked_dt"].date() + timedelta(days=COOLING_OFF_DAYS)
            if from_d < threshold:
                raise ApiError(
                    ERR_DIA_COOLING_OFF,
                    409,
                    "Re-grant inside the 30-day post-revocation cooling-off window",
                )

    rec = base_record(db.new_id())
    rec.update(
        {
            "po_id": po_id,
            "inspector_user_id": inspector,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "granted_by_user_id": uid,
            "revoked_at": None,
            "status": "ACTIVE",
            "_from_d": from_d,
            "_to_d": to_d,
            "_revoked_dt": None,
        }
    )
    db.delegations[rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/api/delegations", methods=["GET"])
def list_delegations():
    require_roles(*ALL_ROLES)
    items = list(db.delegations.values())
    po_id = request.args.get("po_id")
    inspector = request.args.get("inspector_user_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [d for d in items if d["po_id"] == po_id]
    if inspector is not None:
        items = [d for d in items if d["inspector_user_id"] == inspector]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/delegations/<diaId>", methods=["GET"])
def get_one_delegation(diaId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_delegation(diaId)))


@bp.route("/api/delegations/<diaId>/revoke", methods=["POST"])
def revoke_delegation(diaId):
    require_roles(CQR)
    data = json_body()
    no_unknown(data, {"reason"})
    req_str(data, "reason")
    d = get_delegation(diaId)
    if d["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Delegation revoke requires ACTIVE")
    d["status"] = "REVOKED"
    d["revoked_at"] = db.now_iso()
    d["_revoked_dt"] = db.now()
    touch(d)
    return success_object(public(d))
