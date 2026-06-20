"""Patient endpoints."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from calculations import bsa_mosteller
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created, get_patient,
)
from validation import (
    get_body, require_str, require_number, optional_number,
    get_pagination, paginate,
)

bp = Blueprint("patients", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}


@bp.route("/patients", methods=["POST"])
def create_patient():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    mrn = require_str(body, "mrn")
    full_name = require_str(body, "full_name")
    height_cm = require_number(body, "height_cm", gt=0)
    weight_kg = require_number(body, "weight_kg", gt=0)
    gfr_ml_min = require_number(body, "gfr_ml_min", gt=0)

    with db.lock:
        entity = make_common()
        entity.update({
            "mrn": mrn,
            "full_name": full_name,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "gfr_ml_min": gfr_ml_min,
            "bsa_m2": bsa_mosteller(height_cm, weight_kg),
            "status": "ACTIVE",
        })
        db.patients[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/patients", methods=["GET"])
def list_patients():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    mrn = request.args.get("mrn")
    items = [p for p in db.patients.values() if mrn is None or p.get("mrn") == mrn]
    items = sort_by_created(items)
    total = len(items)
    window = [public(p) for p in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/patients/<pid>", methods=["GET"])
def get_one_patient(pid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_patient(pid)
    return success(public(entity), status=200)


@bp.route("/patients/<pid>", methods=["PATCH"])
def update_patient(pid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    entity = get_patient(pid)
    body = get_body()
    height_cm = optional_number(body, "height_cm", default=None, gt=0)
    weight_kg = optional_number(body, "weight_kg", default=None, gt=0)
    gfr_ml_min = optional_number(body, "gfr_ml_min", default=None, gt=0)

    with db.lock:
        if height_cm is not None:
            entity["height_cm"] = height_cm
        if weight_kg is not None:
            entity["weight_kg"] = weight_kg
        if gfr_ml_min is not None:
            entity["gfr_ml_min"] = gfr_ml_min
        if height_cm is not None or weight_kg is not None:
            entity["bsa_m2"] = bsa_mosteller(entity["height_cm"], entity["weight_kg"])
        touch(entity, bump_version=True)
        return success(public(entity), status=200)


@bp.route("/patients/<pid>/mark-deceased", methods=["POST"])
def mark_deceased(pid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    entity = get_patient(pid)
    with db.lock:
        entity["status"] = "DECEASED"
        touch(entity, bump_version=True)
        return success(public(entity), status=200)
