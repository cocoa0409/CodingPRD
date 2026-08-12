from flask import Blueprint, request

from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_partner
from validate import opt_enum, opt_num, opt_str, req_num, req_str

bp = Blueprint("partners", __name__)


def _get_partner(pid):
    p = store.partners.get(pid)
    if p is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND", 404, "Hotel partner not found")
    return p


def _check_commission(v):
    # PRD section 3.2: outside [0, 0.30] -> ERR_INVALID_REQUEST (400)
    if v < 0 or v > 0.30:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "commission_pct must be within [0, 0.30]")


@bp.post("/hotel-partners")
def create_partner():
    require_roles("OperationsAdmin")
    b = body()
    name = req_str(b, "name")
    zone = req_str(b, "zone_code")
    commission = req_num(b, "commission_pct")
    _check_commission(commission)
    rec = create_rec(store.partners, {
        "name": name, "zone_code": zone,
        "commission_pct": commission, "status": "ACTIVE"})
    return ok_obj(ser_partner(rec), 201)


@bp.get("/hotel-partners/<pid>")
def get_partner(pid):
    uid, role = require_roles("HotelPartner", "OperationsAdmin")
    if role == "HotelPartner" and pid != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Partners may only read their own record")
    return ok_obj(ser_partner(_get_partner(pid)))


@bp.get("/hotel-partners")
def list_partners():
    require_roles("OperationsAdmin")
    recs = sorted_ords(list(store.partners.values()))
    zone = request.args.get("zone_code")
    if zone is not None:
        recs = [p for p in recs if p["zone_code"] == zone]
    status = request.args.get("status")
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    return paginate(recs, ser_partner)


@bp.patch("/hotel-partners/<pid>")
def patch_partner(pid):
    require_roles("OperationsAdmin")
    p = _get_partner(pid)
    b = body()
    name = opt_str(b, "name")
    if name is not None:
        p["name"] = name
    commission = opt_num(b, "commission_pct")
    if commission is not None:
        _check_commission(commission)
        p["commission_pct"] = commission
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED"))
    if status is not None:
        p["status"] = status
    bump(p)
    return ok_obj(ser_partner(p))
