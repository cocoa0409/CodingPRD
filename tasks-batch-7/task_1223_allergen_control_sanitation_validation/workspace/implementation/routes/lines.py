from flask import Blueprint, request

from db import db, new_entity, public
from errors import ApiError
from logic import get_or_404
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, req_enum, req_str

bp = Blueprint("lines", __name__)

SANITATION_CLASSES = ("WET_WASH", "DRY_CLEAN", "ALLERGEN_DEDICATED")


@bp.post("/qa/production-lines")
@require_roles("QaManager")
def create_line():
    b = body()
    line_code = req_str(b, "line_code")
    if any(l["line_code"] == line_code for l in db["lines"].values()):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"Duplicate line_code: {line_code}")
    ent = new_entity({
        "line_code": line_code,
        "description": req_str(b, "description"),
        "sanitation_class": req_enum(b, "sanitation_class", SANITATION_CLASSES),
        "posture": "OPEN",
        "last_validated_changeover_id": None,
    })
    db["lines"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/production-lines")
@require_roles(*ALL_ROLES)
def list_lines():
    posture = request.args.get("posture")
    items = list(db["lines"].values())
    if posture is not None:
        items = [l for l in items if l["posture"] == posture]
    return ok_list(items)


@bp.get("/qa/production-lines/<lineId>")
@require_roles(*ALL_ROLES)
def get_line(lineId):
    return ok(public(get_or_404("lines", lineId)))
