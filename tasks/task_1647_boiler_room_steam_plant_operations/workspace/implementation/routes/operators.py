"""Operator endpoints: enrollment, roster, license renewal and revocation."""
from flask import Blueprint, request

import clock
import resolve
import store
from auth import authenticate, authorize
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services import LICENSE_CLASSES, operator_json, operators_of
from util import (
    body_json,
    list_response,
    new_record,
    opt_bool,
    req_dt,
    req_enum,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("operators", __name__)

READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/operators")
def create_operator(plantId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    body = body_json()
    full_name = req_str(body, "full_name")
    license_class = req_enum(body, "license_class", LICENSE_CLASSES)
    license_state = req_str(body, "license_state")
    license_expires_on = req_dt(body, "license_expires_on")
    is_lead_qualified = opt_bool(body, "is_lead_qualified", False)
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "full_name": full_name,
        "license_class": license_class,
        "license_state": license_state,
        "license_expires_on": license_expires_on,
        "license_status": "ACTIVE",
        "is_lead_qualified": is_lead_qualified,
    })
    store.operators[rec["id"]] = rec
    return success_object(operator_json(rec), 201)


@bp.get("/plants/<plantId>/operators/<operatorId>")
def get_operator(plantId, operatorId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    rec = resolve.operator(plant, operatorId)
    return success_object(operator_json(rec))


@bp.get("/plants/<plantId>/operators")
def list_operators(plantId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    recs = operators_of(plant["id"])
    status = request.args.get("license_status")
    if status is not None:
        recs = [o for o in recs if o["license_status"] == status]
    return list_response(recs, operator_json)


@bp.post("/plants/<plantId>/operators/<operatorId>/renew-license")
def renew_license(plantId, operatorId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    rec = resolve.operator(plant, operatorId)
    body = body_json()
    new_expiry = req_dt(body, "new_license_expires_on")
    # state(4): only EXPIRING / EXPIRED may be renewed
    if rec["license_status"] not in ("EXPIRING", "EXPIRED"):
        raise_err(ERR_INVALID_STATE,
                  "renew-license requires license_status EXPIRING or EXPIRED")
    if new_expiry <= clock.now():
        raise_err(ERR_INVALID_REQUEST,
                  "new_license_expires_on must lie strictly after the plant clock")
    rec["license_expires_on"] = new_expiry
    rec["license_status"] = "ACTIVE"
    touch(rec)
    return success_object(operator_json(rec))


@bp.post("/plants/<plantId>/operators/<operatorId>/revoke-license")
def revoke_license(plantId, operatorId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    rec = resolve.operator(plant, operatorId)
    # state(4): ACTIVE or EXPIRED only; REVOKED is terminal
    if rec["license_status"] not in ("ACTIVE", "EXPIRED"):
        raise_err(ERR_INVALID_STATE,
                  "revoke-license requires license_status ACTIVE or EXPIRED")
    rec["license_status"] = "REVOKED"
    touch(rec)
    return success_object(operator_json(rec))
