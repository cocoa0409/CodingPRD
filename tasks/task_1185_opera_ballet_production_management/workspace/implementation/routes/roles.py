"""Role routes (PRD 3.5)."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, opt_bool, req_enum, req_str, to_public

bp = Blueprint("roles", __name__)

VOICE_TYPES = ("SOPRANO", "MEZZO", "TENOR", "BARITONE", "BASS", "DANCER_M",
               "DANCER_F", "NON_SINGING")


@bp.post("/opera/roles")
def create_role():
    require_roles("CastingDirector")
    body = json_body()
    production_id = req_str(body, "production_id")
    role_name = req_str(body, "role_name")
    voice_type = req_enum(body, "voice_type", VOICE_TYPES)
    is_title = opt_bool(body, "is_title_role", default=False)
    prod = get_or_404(store.productions, production_id, "Production")
    rec = new_record(
        production_id=prod["id"],
        role_name=role_name,
        voice_type=voice_type,
        is_title_role=is_title,
        casting_status="UNFILLED",
    )
    store.roles[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/roles")
def list_roles():
    require_roles("Any")
    return list_response(store.roles.values(), [("production_id", "production_id")])


@bp.get("/opera/roles/<rid>")
def get_role(rid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.roles, rid, "Role")))
