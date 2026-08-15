"""Site endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_site
from services import suspend_site, confirmed_incident_open
from util import (
    caller, require_role, forbid, get_body, respond, paginate,
    req_str, req_int, req_num, req_bool, req_enum, stamp_new, touch, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_OPEN_COMPLIANCE_INCIDENT,
)

bp = Blueprint("sites", __name__)

CONTAINMENT_TYPES = {"NONE", "BERMS", "RECLAIM_MAT", "VACUUM_RECOVERY"}


@bp.post("/fleet-wash/sites")
def create_site():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    if customer_id not in store.customers:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % customer_id)
    name = req_str(body, "name")
    lot_size = req_int(body, "lot_size_sqft")
    if lot_size <= 0:
        raise ApiError(ERR_VALIDATION, "lot_size_sqft must be > 0")
    containment = req_enum(body, "containment_type", CONTAINMENT_TYPES)
    reclaim_required = req_bool(body, "water_reclaim_required")
    max_discharge = req_num(body, "max_discharge_gal")
    if max_discharge < 0:
        raise ApiError(ERR_VALIDATION, "max_discharge_gal must be >= 0")
    rec = {
        "customer_id": customer_id,
        "name": name,
        "lot_size_sqft": lot_size,
        "containment_type": containment,
        "water_reclaim_required": reclaim_required,
        "max_discharge_gal": max_discharge,
        "status": "ACTIVE",
        "suspension_reason": None,
    }
    stamp_new(rec)
    store.sites[rec["id"]] = rec
    return respond(ser_site(rec), 201)


@bp.get("/fleet-wash/sites/<sid>")
def get_site(sid):
    uid, role = caller()
    rec = store.sites.get(sid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Site %s not found" % sid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own sites")
    return respond(ser_site(rec), 200)


@bp.get("/fleet-wash/sites")
def list_sites():
    uid, role = caller()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own sites")
        customer_id = uid
    recs = list(store.sites.values())
    if customer_id is not None:
        recs = [s for s in recs if s["customer_id"] == customer_id]
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    return paginate(recs, ser_site)


@bp.post("/fleet-wash/sites/<sid>/events")
def site_event(sid):
    _uid, role = caller()
    require_role(role, {"ComplianceOfficer"})
    rec = store.sites.get(sid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Site %s not found" % sid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("SUSPEND", "REINSTATE"):
        raise ApiError(ERR_VALIDATION, "event_type must be SUSPEND or REINSTATE")
    if event == "SUSPEND":
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Site is not ACTIVE")
        suspend_site(rec, "MANUAL")
    else:
        if rec["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "Site is not SUSPENDED")
        if confirmed_incident_open(rec["id"]):
            raise ApiError(ERR_OPEN_COMPLIANCE_INCIDENT,
                           "A confirmed compliance incident remains open at this site")
        rec["status"] = "ACTIVE"
        rec["suspension_reason"] = None
        touch(rec)
    return respond(ser_site(rec), 200)
