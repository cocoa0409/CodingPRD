from flask import Blueprint, request

from db import db, new_entity, public, touch
from errors import ApiError
from logic import INITIAL_SCORE, REINSTATE_SCORE_FLOOR, get_or_404
from middleware import require_roles
from response import ok, ok_list
from util import body, req_dt_str, req_list_str, req_str

bp = Blueprint("technicians", __name__)

READ_ROLES = ("QaManager", "QaSupervisor", "Auditor")


@bp.post("/qa/technicians")
@require_roles("QaManager")
def create_technician():
    b = body()
    tech_code = req_str(b, "tech_code")
    if any(t["tech_code"] == tech_code for t in db["technicians"].values()):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"Duplicate tech_code: {tech_code}")
    full_name = req_str(b, "full_name")
    certified = req_list_str(b, "certified_allergen_ids")
    for aid in certified:
        get_or_404("allergens", aid)
    expiry = req_dt_str(b, "certification_expiry_utc")
    ent = new_entity({
        "tech_code": tech_code,
        "full_name": full_name,
        "certified_allergen_ids": certified,
        "certification_expiry_utc": expiry,
        "training_score": INITIAL_SCORE,
        "status": "ACTIVE",
    })
    db["technicians"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/technicians")
@require_roles(*READ_ROLES)
def list_technicians():
    status = request.args.get("status")
    items = list(db["technicians"].values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return ok_list(items)


@bp.get("/qa/technicians/<techId>")
@require_roles(*READ_ROLES)
def get_technician(techId):
    return ok(public(get_or_404("technicians", techId)))


@bp.post("/qa/technicians/<techId>/suspend")
@require_roles("QaManager")
def suspend_technician(techId):
    tech = get_or_404("technicians", techId)
    if tech["status"] == "SEPARATED":
        raise ApiError("ERR_TECH_TERMINAL", 409, "Technician is SEPARATED")
    if tech["status"] != "ACTIVE":
        raise ApiError("ERR_TECH_NOT_ACTIVE", 403, "Technician is not ACTIVE")
    tech["status"] = "SUSPENDED"
    touch(tech)
    return ok(public(tech))


@bp.post("/qa/technicians/<techId>/reinstate")
@require_roles("QaManager")
def reinstate_technician(techId):
    tech = get_or_404("technicians", techId)
    if tech["status"] != "SUSPENDED":
        raise ApiError("ERR_TECH_NOT_SUSPENDED", 409,
                       "Technician is not SUSPENDED")
    tech["status"] = "ACTIVE"
    tech["training_score"] = REINSTATE_SCORE_FLOOR
    touch(tech)
    return ok(public(tech))


@bp.post("/qa/technicians/<techId>/separate")
@require_roles("QaManager")
def separate_technician(techId):
    tech = get_or_404("technicians", techId)
    if tech["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_TECH_TERMINAL", 409, "Technician is SEPARATED")
    tech["status"] = "SEPARATED"
    touch(tech)
    return ok(public(tech))
