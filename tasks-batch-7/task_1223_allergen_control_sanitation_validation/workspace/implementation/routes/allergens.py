import re

from flask import Blueprint

from db import db, new_entity, public
from middleware import ALL_ROLES, require_roles
from errors import ApiError
from response import ok, ok_list
from util import body, query_bool, req_enum, opt_bool, req_str

bp = Blueprint("allergens", __name__)

CODE_RE = re.compile(r"^[A-Z_]+$")
REG_CLASSES = ("MAJOR_9", "SESAME", "SULFITE", "OTHER")


@bp.post("/qa/allergens")
@require_roles("QaManager")
def create_allergen():
    b = body()
    code = req_str(b, "code")
    if not CODE_RE.fullmatch(code):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "code must contain only uppercase letters and underscores")
    if any(a["code"] == code for a in db["allergens"].values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Duplicate allergen code: {code}")
    ent = new_entity({
        "code": code,
        "display_name": req_str(b, "display_name"),
        "regulatory_class": req_enum(b, "regulatory_class", REG_CLASSES),
        "is_active": opt_bool(b, "is_active", True),
    })
    db["allergens"][ent["id"]] = ent
    return ok(public(ent), 201)


@bp.get("/qa/allergens")
@require_roles(*ALL_ROLES)
def list_allergens():
    active = query_bool("is_active")
    items = list(db["allergens"].values())
    if active is not None:
        items = [a for a in items if a["is_active"] == active]
    return ok_list(items)


@bp.get("/qa/allergens/<allergenId>")
@require_roles(*ALL_ROLES)
def get_allergen(allergenId):
    from logic import get_or_404
    return ok(public(get_or_404("allergens", allergenId)))
