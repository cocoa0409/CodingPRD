"""Modalities (PRD §3.1)."""
import re

from flask import Blueprint

import db
import helpers as h
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import authenticate, require_role

bp = Blueprint("modalities", __name__)

CODE_RE = re.compile(r"^[A-Z]{2,8}$")


@bp.post("/practice/modalities")
def create_modality():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin"})
    body = h.get_body()

    name = h.as_str(h.require(body, "name"), "name")
    code = h.as_str(h.require(body, "code"), "code")
    if not CODE_RE.match(code):
        raise ApiError(*ERR_INVALID_REQUEST, message="code must be 2-8 uppercase letters")
    base_price_cents = h.as_int(h.require(body, "base_price_cents"), "base_price_cents", minimum=0)
    requires_certification = h.opt(body, "requires_certification", False)
    if not isinstance(requires_certification, bool):
        raise ApiError(*ERR_INVALID_REQUEST, message="requires_certification must be boolean")
    contraindication_tags = h.opt(body, "contraindication_tags", [])
    if not isinstance(contraindication_tags, list):
        raise ApiError(*ERR_INVALID_REQUEST, message="contraindication_tags must be a list")

    # name unique (case-insensitively) among non-archived modalities
    lname = name.lower()
    for m in db.modalities.values():
        if not m["archived"] and m["name"].lower() == lname:
            raise ApiError(*ERR_INVALID_REQUEST, message="name not unique")
    # code unique across all modalities
    for m in db.modalities.values():
        if m["code"] == code:
            raise ApiError(*ERR_INVALID_REQUEST, message="code not unique")

    ent = h.new_entity({
        "name": name,
        "code": code,
        "base_price_cents": base_price_cents,
        "requires_certification": requires_certification,
        "contraindication_tags": list(contraindication_tags),
        "archived": False,
    })
    db.modalities[ent["id"]] = ent
    return response.success(h.public(ent), status=201)


@bp.get("/practice/modalities")
def list_modalities():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Therapist"})
    limit, offset = h.get_pagination()
    include_archived = h.get_bool_flag("include_archived")
    items = [m for m in db.modalities.values() if include_archived or not m["archived"]]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([h.public(m) for m in page], limit, offset, total)


@bp.get("/practice/modalities/<id>")
def get_modality(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Therapist"})
    ent = h.resolve(db.modalities, id)
    return response.success(h.public(ent))
