"""VacationHold top-level endpoints (list/get/cancel/resume)."""
from flask import Blueprint, request

import domain
from db import bump, by_created, store
from errors import ApiError
from middleware import own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_hold

bp = Blueprint("holds", __name__)


def _hold_and_owner_check(hid, uid, role):
    hold = domain.fetch(store.holds, hid)
    sub = store.subscriptions.get(hold["subscription_id"])
    own_check(uid, role, sub["subscriber_id"] if sub else None)
    return hold


@bp.get("/api/vacation-holds")
def list_holds():
    require_roles("ServiceRep", "DistrictManager", "CirculationDirector")
    recs = by_created(store.holds.values())
    subscription_id = request.args.get("subscription_id")
    if subscription_id is not None:
        recs = [h for h in recs if h["subscription_id"] == subscription_id]
    status = request.args.get("status")
    if status is not None:
        recs = [h for h in recs if h["status"] == status]
    return paginate(recs, ser_hold)


@bp.get("/api/vacation-holds/<hid>")
def get_hold(hid):
    uid, role = require_roles("Subscriber", "ServiceRep", "DistrictManager",
                              "CirculationDirector")
    hold = _hold_and_owner_check(hid, uid, role)
    return ok_obj(ser_hold(hold))


@bp.post("/api/vacation-holds/<hid>/cancel")
def cancel_hold(hid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    hold = _hold_and_owner_check(hid, uid, role)
    if hold["status"] != "SCHEDULED":
        raise ApiError("ERR_HOLD_NOT_CANCELLABLE", 409,
                       "Hold cancel requires status SCHEDULED")
    hold["status"] = "CANCELLED"  # no credit, no delivery change, no drift
    bump(hold)
    return ok_obj(ser_hold(hold))


@bp.post("/api/vacation-holds/<hid>/resume")
def resume_hold(hid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    hold = _hold_and_owner_check(hid, uid, role)
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_NOT_ACTIVE", 409,
                       "Hold resume requires status ACTIVE")
    # Early resume: effective end = today; proration over actual held days.
    domain.complete_hold(hold, domain.today())
    return ok_obj(ser_hold(hold))
