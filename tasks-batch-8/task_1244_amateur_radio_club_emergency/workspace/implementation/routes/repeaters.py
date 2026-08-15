"""Repeater endpoints (PRD §3.2): registration and status lifecycle."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_STATE, ERR_NO_COORDINATION_GRANT, ERR_REPEATER_CALLSIGN_TAKEN,
    ERR_SITE_AGREEMENT_INACTIVE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_enum, as_num, as_str, body_json, need, reject_unknown_fields

bp = Blueprint("repeaters", __name__)

REPEATER_STATUSES = {"OPERATIONAL", "DEGRADED", "MAINTENANCE", "OFFLINE"}
ADMIN = {"ClubAdmin"}
READ_ROLES = {"ClubAdmin", "NetControl", "Member"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


def _has_granted_coordination(repeater_id):
    return any(c["repeater_id"] == repeater_id and c["status"] == "GRANTED"
               for c in db.STORE["coordination_requests"].values())


@bp.post("/repeaters")
def create_repeater():
    _auth(ADMIN)
    body = body_json(request)
    reject_unknown_fields(body, {"callsign", "output_frequency_mhz",
                                 "site_agreement_id"})
    callsign = as_str(need(body, "callsign"), "callsign")
    output_frequency_mhz = as_num(need(body, "output_frequency_mhz"),
                                  "output_frequency_mhz")
    site_agreement_id = as_str(need(body, "site_agreement_id"),
                               "site_agreement_id")
    svc.get_site(site_agreement_id)  # body FK existence
    for r in db.STORE["repeaters"].values():
        if r["callsign"] == callsign:
            raise ApiError(ERR_REPEATER_CALLSIGN_TAKEN, 409,
                           "repeater callsign already registered: %s" % callsign)
    repeater = {
        "callsign": callsign,
        "output_frequency_mhz": output_frequency_mhz,
        "site_agreement_id": site_agreement_id,
        "status": "MAINTENANCE",
    }
    svc.stamp_new(repeater)
    db.STORE["repeaters"][repeater["id"]] = repeater
    return success(svc.ser_repeater(repeater), "object", 201)


@bp.get("/repeaters")
def list_repeaters():
    _auth(READ_ROLES)
    status = request.args.get("status")
    site_agreement_id = request.args.get("site_agreement_id")
    items = []
    for r in svc.sorted_records("repeaters"):
        if status is not None and r["status"] != status:
            continue
        if site_agreement_id is not None and r["site_agreement_id"] != site_agreement_id:
            continue
        items.append(svc.ser_repeater(r))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/repeaters/<rid>")
def get_repeater(rid):
    _auth(READ_ROLES)
    return success(svc.ser_repeater(svc.get_repeater(rid)), "object", 200)


@bp.post("/repeaters/<rid>/set-status")
def set_repeater_status(rid):
    _auth(ADMIN)
    repeater = svc.get_repeater(rid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", REPEATER_STATUSES)
    current = repeater["status"]
    if to == "OPERATIONAL":
        if current not in ("MAINTENANCE", "DEGRADED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot move repeater from %s to OPERATIONAL" % current)
        site = svc.get_site(repeater["site_agreement_id"])
        if site["status"] != "ACTIVE":
            raise ApiError(ERR_SITE_AGREEMENT_INACTIVE, 409,
                           "site agreement is not ACTIVE")
        if not _has_granted_coordination(repeater["id"]):
            raise ApiError(ERR_NO_COORDINATION_GRANT, 409,
                           "no GRANTED coordination request for this repeater")
        repeater["status"] = "OPERATIONAL"
        svc.touch(repeater)
    elif to == "DEGRADED":
        if current != "OPERATIONAL":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot move repeater from %s to DEGRADED" % current)
        repeater["status"] = "DEGRADED"
        svc.touch(repeater)
    elif to == "MAINTENANCE":
        if current not in ("OPERATIONAL", "DEGRADED", "OFFLINE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot move repeater from %s to MAINTENANCE" % current)
        repeater["status"] = "MAINTENANCE"
        svc.touch(repeater)
    else:  # OFFLINE — cancels nets in {SCHEDULED, OPEN} (PRD §2.6)
        if current not in ("OPERATIONAL", "DEGRADED", "MAINTENANCE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot move repeater from %s to OFFLINE" % current)
        svc.repeater_offline_cascade(repeater)
    return success(svc.ser_repeater(repeater), "object", 200)
