from flask import Blueprint, request

from db import db, new_entity, public
from errors import ApiError
from logic import get_or_404
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from util import body, opt_int, req_enum, req_str

bp = Blueprint("matrix", __name__)

HANDLINGS = ("ALLOWED", "REQUIRES_CHANGEOVER", "PROHIBITED")


@bp.post("/qa/line-allergen-matrix-entries")
@require_roles("QaManager")
def create_entry():
    b = body()
    line = get_or_404("lines", req_str(b, "line_id"))
    allergen = get_or_404("allergens", req_str(b, "allergen_id"))
    handling = req_enum(b, "handling", HANDLINGS)
    minutes = opt_int(b, "changeover_minutes", 30, minv=0)
    if not allergen["is_active"]:
        raise ApiError("ERR_ALLERGEN_INACTIVE", 422,
                       "Referenced allergen is inactive")
    ent = new_entity({
        "line_id": line["id"],
        "allergen_id": allergen["id"],
        "handling": handling,
        "changeover_minutes": minutes,
    })
    db["matrix"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/line-allergen-matrix-entries")
@require_roles(*ALL_ROLES)
def list_entries():
    line_id = request.args.get("line_id")
    allergen_id = request.args.get("allergen_id")
    items = list(db["matrix"].values())
    if line_id is not None:
        items = [m for m in items if m["line_id"] == line_id]
    if allergen_id is not None:
        items = [m for m in items if m["allergen_id"] == allergen_id]
    return ok_list(items)


@bp.get("/qa/line-allergen-matrix-entries/<entryId>")
@require_roles(*ALL_ROLES)
def get_entry(entryId):
    return ok(public(get_or_404("matrix", entryId)))
