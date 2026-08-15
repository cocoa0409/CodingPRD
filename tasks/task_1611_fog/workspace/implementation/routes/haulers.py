"""Hauler endpoints: register, read, permit, suspend, reinstate, revoke."""
import uuid

from flask import Blueprint

from db import STORE, now, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INSURANCE_EXPIRED,
)
from middleware import auth, require_roles, forbid_unless, get_or_404
from response import success
from services.posture import suspend_hauler
from services.serializers import ser_hauler
from validation import body_json, v_str, v_dt

bp = Blueprint("haulers", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "HaulerAdmin"]


@bp.post("/haulers")
def create_hauler():
    uid, role = auth()
    body = body_json()
    name = v_str(body, "name")
    permit_number = v_str(body, "permit_number")
    insurance = v_dt(body, "insurance_expires_on")
    require_roles(role, ["ProgramAdmin"])
    for h in STORE["haulers"].values():
        if h["permit_number"] == permit_number:
            raise ApiError(ERR_INVALID_REQUEST, 400, "permit_number must be unique across all haulers")
    current = now()
    h = {
        "id": str(uuid.uuid4()),
        "name": name,
        "permit_number": permit_number,
        "insurance_expires_on": insurance,
        "status": "APPLIED",
        "mismatch_count": 0,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["haulers"][h["id"]] = h
    return success(ser_hauler(h), 201)


@bp.get("/haulers/<hid>")
def get_hauler(hid):
    uid, role = auth()
    require_roles(role, READERS)
    if role == "HaulerAdmin":
        forbid_unless(uid == hid)
    h = get_or_404("haulers", hid)
    return success(ser_hauler(h))


@bp.post("/haulers/<hid>/permit")
def permit_hauler(hid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    h = get_or_404("haulers", hid)
    if h["status"] != "APPLIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Hauler is not in APPLIED status")
    current = now()
    if not h["insurance_expires_on"] > current:
        raise ApiError(ERR_INSURANCE_EXPIRED, 422, "insurance_expires_on is at or before the current clock")
    h["status"] = "PERMITTED"
    h["updated_at"] = current
    h["version"] += 1
    return success(ser_hauler(h))


@bp.post("/haulers/<hid>/suspend")
def suspend_hauler_route(hid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    h = get_or_404("haulers", hid)
    if h["status"] != "PERMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Hauler is not in PERMITTED status")
    suspend_hauler(h, now())
    return success(ser_hauler(h))


@bp.post("/haulers/<hid>/reinstate")
def reinstate_hauler(hid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    h = get_or_404("haulers", hid)
    if h["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Hauler is not in SUSPENDED status")
    h["status"] = "PERMITTED"
    h["mismatch_count"] = 0
    h["updated_at"] = now()
    h["version"] += 1
    return success(ser_hauler(h))


@bp.post("/haulers/<hid>/revoke")
def revoke_hauler(hid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    h = get_or_404("haulers", hid)
    if h["status"] not in ("PERMITTED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Hauler cannot be revoked from its current status")
    h["status"] = "REVOKED"
    h["updated_at"] = now()
    h["version"] += 1
    return success(ser_hauler(h))
