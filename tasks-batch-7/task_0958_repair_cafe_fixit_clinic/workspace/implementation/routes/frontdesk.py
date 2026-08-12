"""Visitor registration and Waiver signing/revocation."""

from flask import Blueprint

import db
import serializers as ser
import services
from errors import (
    ERR_INVALID_WAIVER_STATE,
    ERR_VISITOR_NOT_FOUND,
    ERR_WAIVER_NOT_FOUND,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_bool, as_str, body, list_response, opt, req

bp = Blueprint("frontdesk", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")


def get_visitor_or_404(visitor_id):
    visitor = db.visitors.get(visitor_id)
    if visitor is None:
        raise_err(ERR_VISITOR_NOT_FOUND, "Visitor %s does not exist" % visitor_id)
    return visitor


def get_waiver_or_404(waiver_id):
    waiver = db.waivers.get(waiver_id)
    if waiver is None:
        raise_err(ERR_WAIVER_NOT_FOUND, "Waiver %s does not exist" % waiver_id)
    return waiver


# ---------------------------------------------------------------- visitors ---

@bp.post("/api/visitors")
@require_roles("IntakeVolunteer")
def create_visitor():
    b = body()
    full_name = as_str(req(b, "full_name"), "full_name")
    email = as_str(req(b, "email"), "email")
    phone = as_str(opt(b, "phone", ""), "phone")
    rec = db.stamp_new({"full_name": full_name, "email": email, "phone": phone})
    db.visitors[rec["id"]] = rec
    return success(ser.visitor(rec), 201)


@bp.get("/api/visitors")
@require_roles(*ALL_ROLES)
def list_visitors():
    return list_response(db.visitors.values(), ser.visitor, [])


@bp.get("/api/visitors/<visitor_id>")
@require_roles(*ALL_ROLES)
def get_visitor(visitor_id):
    return success(ser.visitor(get_visitor_or_404(visitor_id)), 200)


# ----------------------------------------------------------------- waivers ---

@bp.post("/api/waivers")
@require_roles("IntakeVolunteer")
def create_waiver():
    b = body()
    visitor_id = as_str(req(b, "visitor_id"), "visitor_id")
    get_visitor_or_404(visitor_id)
    clause = as_bool(opt(b, "safety_clause_accepted", False), "safety_clause_accepted")
    rec = db.stamp_new(
        {
            "visitor_id": visitor_id,
            "signed_at": db.clock.now_iso(),
            "safety_clause_accepted": clause,
            "status": "ACTIVE",
        }
    )
    db.waivers[rec["id"]] = rec
    return success(ser.waiver(rec), 201)


@bp.get("/api/waivers")
@require_roles(*ALL_ROLES)
def list_waivers():
    for w in db.waivers.values():
        services.refresh_waiver(w)
    return list_response(
        db.waivers.values(),
        ser.waiver,
        [("visitor_id", "visitor_id"), ("status", "status")],
    )


@bp.get("/api/waivers/<waiver_id>")
@require_roles(*ALL_ROLES)
def get_waiver(waiver_id):
    return success(ser.waiver(get_waiver_or_404(waiver_id)), 200)


@bp.post("/api/waivers/<waiver_id>/revoke")
@require_roles("Coordinator", "SafetyOfficer")
def revoke_waiver(waiver_id):
    waiver = get_waiver_or_404(waiver_id)
    services.refresh_waiver(waiver)
    if waiver["status"] != "ACTIVE":
        raise_err(ERR_INVALID_WAIVER_STATE, "Only an ACTIVE waiver can be revoked")
    waiver["status"] = "REVOKED"
    db.touch(waiver)
    return success(ser.waiver(waiver), 200)
