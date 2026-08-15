"""Participation offerings (PRD 3.4)."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_AGREEMENT_NOT_ACTIVE, ERR_CU_NOT_ACTIVE, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, body, req_str, req_int, req_num, req_dt,
    opt_enum, touch, paginate, ALL_ROLES,
)
from response import success

bp = Blueprint("offerings", __name__)

LOSS_BASES = {"OUTSTANDING", "COMMITTED"}


def _get_offering(oid):
    o = db.offerings.get(oid)
    if o is None:
        not_found("ParticipationOffering")
    return o


def _own_agreement_originator(uid, agreement):
    if agreement["originator_id"] != uid:
        raise_err(ERR_NOT_OWNER, "OriginatorUser must own the servicing agreement")


@bp.post("/network/offerings")
def create_offering():
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    b = body()
    # existence (priority 4)
    aid = b.get("servicing_agreement_id")
    if aid is not None and aid not in db.agreements:
        not_found("ServicingAgreement")
    # ownership (priority 3) on the referenced agreement
    agreement = db.agreements.get(aid) if aid is not None else None
    if agreement is not None:
        _own_agreement_originator(uid, agreement)
    # shape (priority 5)
    if aid is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: servicing_agreement_id")
    pool_name = req_str(b, "pool_name")
    pool_principal = req_int(b, "pool_principal_cents", minimum=1)
    min_share = req_num(b, "min_share_pct")
    if min_share <= 0:
        raise_err(ERR_INVALID_REQUEST, "min_share_pct must be positive")
    yield_bps = req_int(b, "yield_rate_bps", minimum=0)
    loss_basis = opt_enum(b, "loss_basis", LOSS_BASES, "OUTSTANDING")
    open_at = req_dt(b, "open_at")
    close_at = req_dt(b, "close_at")
    if close_at <= open_at:
        raise_err(ERR_INVALID_REQUEST, "close_at must fall after open_at")
    # linked-entity state (priority 9): agreement must be ACTIVE
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Servicing agreement must be ACTIVE to create an offering")
    o = db.insert("offering", {
        "servicing_agreement_id": aid,
        "pool_name": pool_name,
        "pool_principal_cents": pool_principal,
        "min_share_pct": min_share,
        "yield_rate_bps": yield_bps,
        "loss_basis": loss_basis,
        "open_at": open_at,
        "close_at": close_at,
        "status": "DRAFT",
    })
    return success(ser.offering(o), 201)


@bp.get("/network/offerings/<oid>")
def get_offering(oid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.offering(_get_offering(oid)))


@bp.get("/network/offerings")
def list_offerings():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.offerings.values())
    aid = request.args.get("servicing_agreement_id")
    if aid is not None:
        items = [o for o in items if o["servicing_agreement_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, meta = paginate(items, ser.offering)
    return success(page, 200, meta)


@bp.post("/network/offerings/<oid>/open")
def open_offering(oid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    o = _get_offering(oid)
    agreement = db.agreements[o["servicing_agreement_id"]]
    _own_agreement_originator(uid, agreement)
    if o["status"] != "DRAFT":
        invalid_state("Only a DRAFT offering can be opened")
    if agreement["status"] != "ACTIVE":
        raise_err(ERR_AGREEMENT_NOT_ACTIVE, "Servicing agreement must be ACTIVE to open an offering")
    originator = db.credit_unions.get(agreement["originator_id"])
    if originator is None or originator["status"] != "ACTIVE":
        raise_err(ERR_CU_NOT_ACTIVE, "Originator credit union must be ACTIVE to open an offering")
    o["status"] = "OPEN"
    touch("offering", o)
    return success(ser.offering(o))


@bp.post("/network/offerings/<oid>/close")
def close_offering(oid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    o = _get_offering(oid)
    agreement = db.agreements[o["servicing_agreement_id"]]
    _own_agreement_originator(uid, agreement)
    # close on an OPEN offering closes it; close on a DRAFT offering withdraws it
    if o["status"] == "OPEN":
        o["status"] = "CLOSED"
    elif o["status"] == "DRAFT":
        o["status"] = "WITHDRAWN"
    else:
        invalid_state("Only an OPEN or DRAFT offering can be closed")
    touch("offering", o)
    return success(ser.offering(o))
