"""WaitlistEntry routes and promotion-driven offers."""
from flask import Blueprint, request

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_enum, check_owner, ApiError, now_clock,
)
from services import ser_waitlist, run_waitlist_promotion

bp = Blueprint("waitlist", __name__)

UNIT_CLASSES = {"STANDARD", "CLIMATE", "SHOWCASE"}
WAITLIST_STATUSES = {"WAITING", "OFFERED", "CLAIMED", "EXPIRED", "CANCELLED"}


def _release_offered_unit(entry):
    unit = db.units.get(entry["offered_unit_id"]) if entry["offered_unit_id"] else None
    entry["offered_unit_id"] = None
    entry["offer_expires_at"] = None
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        touch(unit)
        run_waitlist_promotion(unit)


@bp.post("/waitlist")
def join_waitlist():
    uid, role = require("Member")
    body = get_body()
    member_id = req_str(body, "member_id")
    facility_id = req_str(body, "facility_id")
    desired_unit_class = req_enum(body, "desired_unit_class", UNIT_CLASSES)
    check_owner(role, uid, member_id)
    get_or_404(db.members, member_id)
    get_or_404(db.facilities, facility_id)
    available = sum(1 for u in db.units.values()
                    if u["facility_id"] == facility_id
                    and u["unit_class"] == desired_unit_class
                    and u["status"] == "AVAILABLE")
    if available > 0:
        raise ApiError("ERR_UNITS_AVAILABLE", 409, "An available unit of that class exists")
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "desired_unit_class": desired_unit_class,
        "facility_id": facility_id,
        "status": "WAITING",
        "offered_unit_id": None,
        "offer_expires_at": None,
    })
    db.waitlist[rec["id"]] = rec
    return success(ser_waitlist(rec), status=201)


@bp.get("/waitlist/<wid>")
def get_waitlist(wid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.waitlist, wid)
    return success(ser_waitlist(rec))


@bp.get("/waitlist")
def list_waitlist():
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    member_id = request.args.get("member_id")
    facility_id = request.args.get("facility_id")
    offered_unit_id = request.args.get("offered_unit_id")
    status = request.args.get("status")
    items = [w for w in db.waitlist.values()
             if (member_id is None or w["member_id"] == member_id)
             and (facility_id is None or w["facility_id"] == facility_id)
             and (offered_unit_id is None or w["offered_unit_id"] == offered_unit_id)
             and (status is None or w["status"] == status)]
    return list_response(items, ser_waitlist)


@bp.post("/waitlist/<wid>/claim")
def claim(wid):
    uid, role = require("Member")
    entry = get_or_404(db.waitlist, wid)
    check_owner(role, uid, entry["member_id"])
    if entry["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Entry is not OFFERED")
    if now_clock() >= entry["offer_expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer has expired")
    entry["status"] = "CLAIMED"
    touch(entry)
    return success(ser_waitlist(entry))


@bp.post("/waitlist/<wid>/cancel")
def cancel_waitlist(wid):
    uid, role = require("Member", "VaultManager")
    entry = get_or_404(db.waitlist, wid)
    check_owner(role, uid, entry["member_id"])
    if entry["status"] not in ("WAITING", "OFFERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Entry cannot be cancelled")
    was_offered = entry["status"] == "OFFERED"
    entry["status"] = "CANCELLED"
    if was_offered:
        _release_offered_unit(entry)
    touch(entry)
    return success(ser_waitlist(entry))


@bp.post("/waitlist/<wid>/refresh-offer")
def refresh_offer(wid):
    require("VaultManager")
    entry = get_or_404(db.waitlist, wid)
    if entry["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Entry is not OFFERED")
    if now_clock() >= entry["offer_expires_at"]:
        entry["status"] = "EXPIRED"
        _release_offered_unit(entry)
        touch(entry)
    return success(ser_waitlist(entry))
