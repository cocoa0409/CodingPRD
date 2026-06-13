"""RiskHold endpoints: fetch, list/filter, clear, block (with segregation of duties)."""
from flask import Blueprint, request

import models
import response
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import transfer as transfer_svc

bp = Blueprint("risk_holds", __name__)


@bp.route("/risk-holds/<h_id>", methods=["GET"])
def get_risk_hold(h_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin", "AccountHolder"})
        hold = db.risk_holds.get(h_id)
        if not hold:
            raise err("ERR_NOT_FOUND", "Risk hold not found.")
        if p.role == "AccountHolder":
            t = db.transfers.get(hold["transfer_id"])
            if not t or (p.user_id != t["sender_account_id"]
                         and p.user_id != t["recipient_account_id"]):
                raise err("ERR_NOT_RESOURCE_OWNER", "Not a party to this hold's transfer.")
        return response.ok(models.serialize(hold))


@bp.route("/risk-holds", methods=["GET"])
def list_risk_holds():
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer", "PlatformAdmin"})
        limit, offset = parse_pagination()
        items = list(db.risk_holds.values())
        for key in ("transfer_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [h for h in items if h.get(key) == val]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


def _segregation_check(principal, transfer):
    """Acting officer must not be sender or recipient of the underlying transfer."""
    if (principal.user_id == transfer["sender_account_id"]
            or principal.user_id == transfer["recipient_account_id"]):
        raise err("ERR_SEGREGATION_OF_DUTIES", "Officer is a party to the transfer.")


@bp.route("/risk-holds/<h_id>/clear", methods=["POST"])
def clear_risk_hold(h_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer"})
        hold = db.risk_holds.get(h_id)
        if not hold:
            raise err("ERR_NOT_FOUND", "Risk hold not found.")
        transfer = db.transfers.get(hold["transfer_id"])
        _segregation_check(p, transfer)
        if hold["status"] != "PENDING_REVIEW":
            raise err("ERR_INVALID_STATE", "Hold is not PENDING_REVIEW.")
        hold["status"] = "CLEARED"
        hold["reviewer_user_id"] = p.user_id
        models.touch(hold)
        transfer_svc.clear_hold_cascade(transfer)
        return response.ok(models.serialize(hold))


@bp.route("/risk-holds/<h_id>/block", methods=["POST"])
def block_risk_hold(h_id):
    with db.lock:
        p = authenticate()
        require_roles(p, {"ComplianceOfficer"})
        hold = db.risk_holds.get(h_id)
        if not hold:
            raise err("ERR_NOT_FOUND", "Risk hold not found.")
        transfer = db.transfers.get(hold["transfer_id"])
        _segregation_check(p, transfer)
        if hold["status"] != "PENDING_REVIEW":
            raise err("ERR_INVALID_STATE", "Hold is not PENDING_REVIEW.")
        hold["status"] = "BLOCKED"
        hold["reviewer_user_id"] = p.user_id
        models.touch(hold)
        transfer_svc.block_hold_cascade(transfer)
        return response.ok(models.serialize(hold))
