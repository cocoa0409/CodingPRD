"""RampService endpoints + de-ice charge (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_enum,
                     pagination_params, paginate)
from services.calculations import deice_service_charge, FLAT_SERVICE_FEE_CENTS

bp = Blueprint("ramp_services", __name__)

DEICE_FIELDS = ("deice_fluid_gallons", "deice_fluid_type", "deice_holdover_minutes")


def service_view(s):
    return {
        "id": s["id"],
        "service_visit_id": s["service_visit_id"],
        "service_type": s["service_type"],
        "status": s["status"],
        "deice_fluid_gallons": s["deice_fluid_gallons"],
        "deice_fluid_type": s["deice_fluid_type"],
        "deice_holdover_minutes": s["deice_holdover_minutes"],
        "charge_cents": s["charge_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _owner_operator_id(svc):
    visit = db.service_visits.get(svc["service_visit_id"])
    return visit["operator_id"] if visit else None


def _present(body, name):
    return name in body and body.get(name) is not None


@bp.route("/ramp-services", methods=["POST"])
def create_service():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    body = get_json()
    service_visit_id = require_string(body, "service_visit_id")
    service_type = require_enum(body, "service_type",
                                {"LAVATORY", "GPU", "DE_ICE", "CREW_CAR", "CATERING"})

    visit = db.service_visits.get(service_visit_id)
    if visit is None:
        raise err(errors.ERR_NOT_FOUND, "Service visit not found.")
    if role == "Operator" and user_id != visit["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may request only for its own visits.")

    deice_fluid_gallons = 0
    deice_fluid_type = None
    deice_holdover_minutes = 0

    if service_type == "DE_ICE":
        # All required de-ice fields must be present and well-typed; gallons >= 1,
        # holdover >= 0; fluid type one of TYPE_I/TYPE_IV.
        ft = body.get("deice_fluid_type")
        fg = body.get("deice_fluid_gallons")
        hm = body.get("deice_holdover_minutes")
        if ft not in ("TYPE_I", "TYPE_IV"):
            raise err(errors.ERR_DEICE_FIELDS_REQUIRED, "DE_ICE requires a valid deice_fluid_type.")
        if isinstance(fg, bool) or not isinstance(fg, int) or fg < 1:
            raise err(errors.ERR_DEICE_FIELDS_REQUIRED, "DE_ICE requires deice_fluid_gallons >= 1.")
        if hm is None:
            hm = 0
        if isinstance(hm, bool) or not isinstance(hm, int) or hm < 0:
            raise err(errors.ERR_DEICE_FIELDS_REQUIRED, "DE_ICE requires deice_holdover_minutes >= 0.")
        deice_fluid_gallons = fg
        deice_fluid_type = ft
        deice_holdover_minutes = hm
    else:
        # Non-DE_ICE must NOT carry de-ice fields.
        for f in DEICE_FIELDS:
            if _present(body, f):
                raise err(errors.ERR_DEICE_FIELDS_REQUIRED,
                          "Non-DE_ICE service must not supply de-ice fields.")

    s = db.common_create()
    s.update({
        "service_visit_id": service_visit_id,
        "service_type": service_type,
        "status": "REQUESTED",
        "deice_fluid_gallons": deice_fluid_gallons,
        "deice_fluid_type": deice_fluid_type,
        "deice_holdover_minutes": deice_holdover_minutes,
        "charge_cents": 0,
    })
    db.ramp_services[s["id"]] = s
    # Increment parent visit's services_outstanding by 1.
    visit["services_outstanding"] += 1
    db.touch(visit)
    return success(service_view(s), 201)


@bp.route("/ramp-services/<id>", methods=["GET"])
def get_service(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    s = db.ramp_services.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp service not found.")
    if role == "Operator" and user_id != _owner_operator_id(s):
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own services.")
    return success(service_view(s), 200)


@bp.route("/ramp-services", methods=["GET"])
def list_services():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.ramp_services.values())
    if role == "Operator":
        records = [r for r in records if _owner_operator_id(r) == user_id]
    v_f = request.args.get("service_visit_id")
    t_f = request.args.get("service_type")
    st_f = request.args.get("status")
    if v_f is not None:
        records = [r for r in records if r["service_visit_id"] == v_f]
    if t_f is not None:
        records = [r for r in records if r["service_type"] == t_f]
    if st_f is not None:
        records = [r for r in records if r["status"] == st_f]
    window, total = paginate(records, limit, offset)
    return list_response([service_view(r) for r in window], limit, offset, total)


@bp.route("/ramp-services/<id>/start", methods=["POST"])
def start_service(id):
    _, role = authenticate()
    require_role(role, {"LineManager", "OpsDispatcher"})
    s = db.ramp_services.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp service not found.")
    if s["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "start requires REQUESTED status.")
    visit = db.service_visits.get(s["service_visit_id"])
    if visit["status"] != "SERVICING":
        raise err(errors.ERR_VISIT_NOT_SERVICEABLE, "Parent visit must be SERVICING.")
    s["status"] = "IN_PROGRESS"
    db.touch(s)
    return success(service_view(s), 200)


@bp.route("/ramp-services/<id>/complete", methods=["POST"])
def complete_service(id):
    _, role = authenticate()
    require_role(role, {"LineManager", "OpsDispatcher"})
    s = db.ramp_services.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp service not found.")
    if s["status"] != "IN_PROGRESS":
        raise err(errors.ERR_INVALID_STATE, "complete requires IN_PROGRESS status.")
    if s["service_type"] == "DE_ICE":
        s["charge_cents"] = deice_service_charge(
            s["deice_fluid_gallons"], s["deice_fluid_type"], s["deice_holdover_minutes"])
    else:
        s["charge_cents"] = FLAT_SERVICE_FEE_CENTS.get(s["service_type"], 0)
    s["status"] = "COMPLETED"
    db.touch(s)
    # BUBBLE UP: decrement parent visit's services_outstanding by 1.
    visit = db.service_visits.get(s["service_visit_id"])
    visit["services_outstanding"] -= 1
    db.touch(visit)
    return success(service_view(s), 200)


@bp.route("/ramp-services/<id>/cancel", methods=["POST"])
def cancel_service(id):
    _, role = authenticate()
    require_role(role, {"LineManager", "OpsDispatcher"})
    s = db.ramp_services.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Ramp service not found.")
    if s["status"] not in ("REQUESTED", "IN_PROGRESS"):
        raise err(errors.ERR_INVALID_STATE, "cancel requires REQUESTED or IN_PROGRESS status.")
    s["status"] = "CANCELLED"
    db.touch(s)
    visit = db.service_visits.get(s["service_visit_id"])
    visit["services_outstanding"] -= 1
    db.touch(visit)
    return success(service_view(s), 200)
