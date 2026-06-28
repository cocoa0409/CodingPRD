"""CastingDirector endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, lock
from middleware import get_identity, require_role
from response import object_response
from services.common import mint_common, public, get_json_body, require_str, lookup

bp = Blueprint("casting_directors", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/casting-directors", methods=["POST"])
def create_casting_director():
    _, role = get_identity()
    require_role(role, {"Agent", "CastingDirector"})
    body = get_json_body()
    display_name = require_str(body, "display_name")
    studio = require_str(body, "studio")
    with lock:
        record = mint_common({
            "display_name": display_name,
            "studio": studio,
        })
        db.casting_directors[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/casting-directors/<cd_id>", methods=["GET"])
def get_casting_director(cd_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("CastingDirector", cd_id)
        return object_response(public(record), status=200)
