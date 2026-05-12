"""Task template routes."""
from flask import Blueprint

from db import db, new_id
from errors import ERR_BAD_REQUEST, raise_err
from middleware import require_role
from response import success_object
from services.common import get_json_body, get_site_or_404, get_template_or_404
from services.serialize import serialize_template

bp = Blueprint("templates", __name__)

VALID_CATEGORIES = {"PUMP", "COMPRESSOR", "HVAC", "CONVEYOR", "BOILER"}
VALID_SKILLS = {"MECHANICAL", "ELECTRICAL", "HYDRAULIC", "HVAC_CERT", "CONTROLS"}
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


@bp.route("/sites/<site_id>/templates", methods=["POST"])
def create_template(site_id):
    require_role(["PlanOwner"])
    get_site_or_404(site_id)
    body = get_json_body()

    for f in ["code", "title", "equipment_category", "required_skill", "estimated_minutes", "default_priority"]:
        if f not in body or body.get(f) in (None, ""):
            raise_err(ERR_BAD_REQUEST, f"{f} is required")

    if body["equipment_category"] not in VALID_CATEGORIES:
        raise_err(ERR_BAD_REQUEST, "invalid equipment_category")
    if body["required_skill"] not in VALID_SKILLS:
        raise_err(ERR_BAD_REQUEST, "invalid required_skill")
    if body["default_priority"] not in VALID_PRIORITIES:
        raise_err(ERR_BAD_REQUEST, "invalid default_priority")

    em = body["estimated_minutes"]
    if not isinstance(em, int) or isinstance(em, bool) or em <= 0:
        raise_err(ERR_BAD_REQUEST, "estimated_minutes must be a positive integer")

    code = body["code"]
    for t in db.templates_for_site(site_id):
        if t["code"] == code:
            raise_err(ERR_BAD_REQUEST, "code must be unique per site")

    tid = new_id()
    clock = db.site_clock(site_id)
    t = {
        "id": tid,
        "created_at": clock,
        "site_id": site_id,
        "code": code,
        "title": body["title"],
        "equipment_category": body["equipment_category"],
        "required_skill": body["required_skill"],
        "estimated_minutes": em,
        "default_priority": body["default_priority"],
    }
    db.templates[tid] = t
    return success_object(serialize_template(t), 201)


@bp.route("/sites/<site_id>/templates/<template_id>", methods=["GET"])
def get_template(site_id, template_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    t = get_template_or_404(site_id, template_id)
    return success_object(serialize_template(t))
