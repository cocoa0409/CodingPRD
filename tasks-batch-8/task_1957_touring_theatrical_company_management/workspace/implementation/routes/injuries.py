"""InjuryEvent endpoints: report (atomic COVERED/REPLACED fork), list, resolve."""

from flask import Blueprint

import db
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_CAST_INVALID_STATE, ERR_DUPLICATE_RECORD,
                    ERR_PRINCIPAL_NOT_CONTRACTED, ERR_INJURY_INVALID_STATE)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain
from util import (get_body, reject_unknown, require_present, as_enum,
                  paginate)

bp = Blueprint("injuries", __name__)

INJURY_STATUSES = ("COVERED", "RESOLVED", "REPLACED")


@bp.route("/cast/<cast_id>/injuries", methods=["POST"])
def create_injury(cast_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    member = db.cast_members.get(cast_id)
    if member is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    body = get_body()
    reject_unknown(body, {"notes"})
    notes = body.get("notes", "")
    if not isinstance(notes, str):
        raise err(ERR_INVALID_REQUEST, 400, "notes must be a string")
    # State (priority 5): injuries only on CONTRACTED members.
    if member["status"] != "CONTRACTED":
        raise err(ERR_CAST_INVALID_STATE, 409,
                  "An injury may be reported only on a CONTRACTED member")
    # Uniqueness (priority 7): at most one open (COVERED) injury per member.
    for i in db.injuries.values():
        if i["cast_member_id"] == cast_id and i["status"] == "COVERED":
            raise err(ERR_DUPLICATE_RECORD, 422,
                      "This member already has an open (COVERED) injury")
    # Selector runs atomically; the empty-pool fallback (REPLACED branch) is
    # only available to a member who is principal of some track of the tour.
    track = domain.principal_track_of(member["tour_id"], cast_id)
    if track is None or domain.select_coverage(track) is None:
        if track is None:
            raise err(ERR_PRINCIPAL_NOT_CONTRACTED, 422,
                      "Injured member is not the principal of any track of this tour")
        # principal with an empty coverage pool -> REPLACED branch (no error)
    rec = domain.run_injury_cascade(member, notes)
    return success(db.serialize("injury", rec), 201)


@bp.route("/cast/<cast_id>/injuries", methods=["GET"])
def list_injuries(cast_id):
    authenticate()
    if db.cast_members.get(cast_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    items = [i for i in db.injuries.values() if i["cast_member_id"] == cast_id]
    items.sort(key=lambda i: i["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("injury", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/injuries/<injury_id>", methods=["PUT"])
def put_injury(injury_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    injury = db.injuries.get(injury_id)
    if injury is None:
        raise err(ERR_NOT_FOUND, 404, "Injury not found")
    body = get_body()
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", INJURY_STATUSES)
    if target != "RESOLVED" or injury["status"] != "COVERED":
        raise err(ERR_INJURY_INVALID_STATE, 409,
                  "Only a COVERED injury may be resolved")
    domain.resolve_injury(injury)
    return success(db.serialize("injury", injury), 200)
