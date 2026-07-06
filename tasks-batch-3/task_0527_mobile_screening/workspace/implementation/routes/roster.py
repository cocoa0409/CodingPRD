from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (stamp_new, bump, public, get_json_body, require_str,
                             require_int, require_enum, paginate, sorted_by_creation)
from services.lookup import get_or_404
from errors import err

bp = Blueprint("roster", __name__)

MODALITIES = {"MAMMOGRAPHY", "BLOOD_PANEL", "BONE_DENSITY", "SKIN"}
STAFF_ROLES = {"TECHNOLOGIST", "RADIOLOGIST", "NAVIGATOR", "PHLEBOTOMIST"}
ALL_ROLES = {"ProgramManager", "ClinicalStaff", "BillingClerk", "PatientNavigator"}


# ---------------- Mobile Units ----------------

@bp.route("/mobile-units", methods=["POST"])
def create_unit():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    name = require_str(body, "name")
    modality = require_enum(body, "modality", MODALITIES)
    daily_capacity = require_int(body, "daily_capacity", minimum=1)
    unit = stamp_new({
        "name": name, "modality": modality,
        "daily_capacity": daily_capacity, "status": "AVAILABLE",
    })
    db.mobile_units[unit["id"]] = unit
    return object_response(public(unit), 201)


@bp.route("/mobile-units", methods=["GET"])
def list_units():
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.mobile_units.values())
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(u) for u in page], limit, offset, total)


@bp.route("/mobile-units/<rid>", methods=["GET"])
def get_unit(rid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    return object_response(public(get_or_404("mobile_units", rid)), 200)


@bp.route("/mobile-units/<rid>/retire", methods=["POST"])
def retire_unit(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    unit = get_or_404("mobile_units", rid)
    if unit["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Unit not AVAILABLE")
    unit["status"] = "RETIRED"
    bump(unit)
    return object_response(public(unit), 200)


# ---------------- Staff ----------------

@bp.route("/staff", methods=["POST"])
def create_staff():
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    role_type = require_enum(body, "role_type", STAFF_ROLES)
    modality = require_enum(body, "modality", MODALITIES)
    member = stamp_new({
        "full_name": full_name, "role_type": role_type,
        "modality": modality, "status": "ACTIVE",
    })
    db.staff[member["id"]] = member
    return object_response(public(member), 201)


@bp.route("/staff", methods=["GET"])
def list_staff():
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    items = list(db.staff.values())
    for f in ("role_type", "modality", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s[f] == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(s) for s in page], limit, offset, total)


@bp.route("/staff/<rid>", methods=["GET"])
def get_staff(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager", "ClinicalStaff"})
    return object_response(public(get_or_404("staff", rid)), 200)


@bp.route("/staff/<rid>/deactivate", methods=["POST"])
def deactivate_staff(rid):
    _, role = require_user_context()
    require_role(role, {"ProgramManager"})
    member = get_or_404("staff", rid)
    if member["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Staff not ACTIVE")
    member["status"] = "INACTIVE"
    bump(member)
    return object_response(public(member), 200)
