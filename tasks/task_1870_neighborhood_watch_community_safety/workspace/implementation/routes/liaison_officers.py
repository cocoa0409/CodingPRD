"""LiaisonOfficer routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("liaison_officers", __name__)


def _serialize_officer(o):
    return {
        "id": o["id"],
        "badge_number": o["badge_number"],
        "full_name": o["full_name"],
        "precinct_code": o["precinct_code"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.route("/watch/liaison-officers", methods=["POST"])
def create_officer():
    user_id, role = require_roles("ProgramCoordinator")
    body = request.get_json(force=True, silent=True) or {}

    badge_number = body.get("badge_number")
    full_name = body.get("full_name")
    precinct_code = body.get("precinct_code")

    if not badge_number or not isinstance(badge_number, str):
        raise errors.invalid_request("badge_number is required")
    if not full_name or not isinstance(full_name, str):
        raise errors.invalid_request("full_name is required")
    if not precinct_code or not isinstance(precinct_code, str):
        raise errors.invalid_request("precinct_code is required")

    # Uniqueness
    for o in db.liaison_officers.values():
        if o["badge_number"] == badge_number:
            raise errors.constraint_violation("Duplicate badge_number")

    record = {
        "badge_number": badge_number,
        "full_name": full_name,
        "precinct_code": precinct_code,
    }
    svc.stamp_new(record)
    db.liaison_officers[record["id"]] = record
    return success_object(_serialize_officer(record), 201)


@bp.route("/watch/liaison-officers", methods=["GET"])
def list_officers():
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")

    items = list(db.liaison_officers.values())

    pc = request.args.get("precinct_code")
    if pc:
        items = [o for o in items if o["precinct_code"] == pc]

    items.sort(key=lambda o: o["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_officer(o) for o in items], limit, offset, total)


@bp.route("/watch/liaison-officers/<id>", methods=["GET"])
def get_officer(id):
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")
    o = db.liaison_officers.get(id)
    if not o:
        raise errors.not_found("LiaisonOfficer not found")
    return success_object(_serialize_officer(o))
