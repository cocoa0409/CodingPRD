"""Technician routes."""
from flask import Blueprint

from db import db, new_id
from errors import ERR_BAD_REQUEST, raise_err
from middleware import require_role
from response import success_object
from services.calculations import compute_open_load
from services.common import (
    bump_version,
    check_version,
    get_json_body,
    get_site_or_404,
    get_technician_or_404,
)
from services.serialize import serialize_technician

bp = Blueprint("technicians", __name__)

VALID_SKILLS = {"MECHANICAL", "ELECTRICAL", "HYDRAULIC", "HVAC_CERT", "CONTROLS"}
VALID_STATUSES = {"ACTIVE", "OFF_DUTY"}


def _validate_skills(skills):
    if not isinstance(skills, list):
        raise_err(ERR_BAD_REQUEST, "skills must be an array")
    for s in skills:
        if s not in VALID_SKILLS:
            raise_err(ERR_BAD_REQUEST, f"invalid skill: {s}")


@bp.route("/sites/<site_id>/technicians", methods=["POST"])
def create_technician(site_id):
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    body = get_json_body()

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise_err(ERR_BAD_REQUEST, "name is required")
    skills = body.get("skills")
    if skills is None:
        raise_err(ERR_BAD_REQUEST, "skills is required")
    _validate_skills(skills)

    tid = new_id()
    clock = db.site_clock(site_id)
    t = {
        "id": tid,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "site_id": site_id,
        "name": name,
        "skills": list(skills),
        "status": "ACTIVE",
        "open_load": 0,
    }
    db.technicians[tid] = t
    return success_object(serialize_technician(t), 201)


@bp.route("/sites/<site_id>/technicians/<tech_id>", methods=["GET"])
def get_technician(site_id, tech_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    t = get_technician_or_404(site_id, tech_id)
    t["open_load"] = compute_open_load(t["id"])
    return success_object(serialize_technician(t))


@bp.route("/sites/<site_id>/technicians/<tech_id>", methods=["PATCH"])
def patch_technician(site_id, tech_id):
    require_role(["SiteManager"])
    get_site_or_404(site_id)
    t = get_technician_or_404(site_id, tech_id)
    body = get_json_body()
    check_version(t, body)

    if "skills" in body:
        _validate_skills(body["skills"])
        t["skills"] = list(body["skills"])
    if "status" in body:
        if body["status"] not in VALID_STATUSES:
            raise_err(ERR_BAD_REQUEST, "invalid status")
        t["status"] = body["status"]

    bump_version(t, site_id)
    t["open_load"] = compute_open_load(t["id"])
    return success_object(serialize_technician(t))
