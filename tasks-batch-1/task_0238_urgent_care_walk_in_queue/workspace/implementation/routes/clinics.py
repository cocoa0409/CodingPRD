"""Clinic endpoints (PRD §2.9, §3.9)."""
from flask import Blueprint

import serialize
from db import db, stamp_create
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path
from services.run_ops import run_ops

bp = Blueprint("clinics", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider", "Patient"]

DEFAULT_ESI_MINUTES = {"1": 40, "2": 30, "3": 20, "4": 12, "5": 8}


@bp.route("/clinics", methods=["POST"])
def create_clinic():
    # Bootstrap: no auth required, roles ClinicManager/Anonymous.
    body = get_json_body()
    require_str(body, "name")
    cap = body.get("exam_room_capacity")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise err("ERR_INVALID_REQUEST", "exam_room_capacity must be an integer >= 1")

    surge = body.get("surge_threshold", 8)
    diversion = body.get("diversion_threshold", 14)
    if not isinstance(surge, int) or isinstance(surge, bool) or surge < 1:
        raise err("ERR_INVALID_REQUEST", "surge_threshold must be an integer >= 1")
    if not isinstance(diversion, int) or isinstance(diversion, bool) or diversion <= surge:
        raise err("ERR_INVALID_REQUEST", "diversion_threshold must be > surge_threshold")

    discount = body.get("self_pay_discount_pct", 0.30)
    if not isinstance(discount, (int, float)) or isinstance(discount, bool) or discount < 0 or discount >= 1:
        raise err("ERR_INVALID_REQUEST", "self_pay_discount_pct must be in [0, 1)")

    esi_map = body.get("avg_provider_minutes_per_esi", dict(DEFAULT_ESI_MINUTES))
    if not isinstance(esi_map, dict):
        raise err("ERR_INVALID_REQUEST", "avg_provider_minutes_per_esi must be a map")
    # Normalize keys to strings.
    esi_map = {str(k): v for k, v in esi_map.items()}

    clinic = stamp_create({
        "name": body["name"],
        "exam_room_capacity": cap,
        "surge_threshold": surge,
        "diversion_threshold": diversion,
        "avg_provider_minutes_per_esi": esi_map,
        "self_pay_discount_pct": discount,
        "ops_run_index": 0,
    })
    db.clinics[clinic["id"]] = clinic
    return ok_object(serialize.clinic(clinic), 201)


@bp.route("/clinics/<cid>", methods=["GET"])
def get_clinic(cid):
    authorize(READ_ROLES)
    clinic = get_path("clinic", cid)
    return ok_object(serialize.clinic(clinic))


@bp.route("/clinics", methods=["GET"])
def list_clinics():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = sorted(db.clinics.values(), key=lambda c: (c["created_at"], c["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.clinic(c) for c in page], limit, offset, len(items))


@bp.route("/clinics/<cid>/run-ops", methods=["POST"])
def run_ops_endpoint(cid):
    authorize(["ClinicManager"])
    clinic = get_path("clinic", cid)
    run_ops(clinic)
    return ok_object(serialize.clinic(clinic))
