"""ConflictDeclaration endpoints (PRD §3.2).

POST   /conflict-declarations
GET    /conflict-declarations
GET    /conflict-declarations/{id}

Immutable junction: id + created_at only (no version / updated_at).
"""
from flask import Blueprint, request

import db
import lookup
import serialize
from errors import err, ERR_INVALID_REQUEST
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate

bp = Blueprint("conflicts", __name__)

SCOPES = {"TEAM", "OFFICIAL"}
WRITE_ROLES = {"LeagueAdmin", "Official"}
READ_ROLES = {"LeagueAdmin", "Assignor", "Official"}


@bp.route("/conflict-declarations", methods=["POST"])
def create_conflict():
    _, role = get_user_context()
    require_role(role, WRITE_ROLES)
    data = validate.body()
    official_id = validate.require_str(data, "official_id")
    scope = validate.enum(data, "scope", SCOPES)
    team_name = validate.opt_str(data, "team_name")
    peer_official_id = validate.opt_str(data, "peer_official_id")
    # Scope/field consistency (PRD §3.2).
    if scope == "TEAM":
        if not team_name or peer_official_id:
            err(ERR_INVALID_REQUEST,
                "TEAM scope requires team_name and no peer_official_id")
    else:  # OFFICIAL
        if not peer_official_id or team_name:
            err(ERR_INVALID_REQUEST,
                "OFFICIAL scope requires peer_official_id and no team_name")
    with db.lock:
        lookup.official(official_id)
        if scope == "OFFICIAL":
            lookup.official(peer_official_id)
        rec = {
            "official_id": official_id,
            "scope": scope,
            "team_name": team_name if scope == "TEAM" else None,
            "peer_official_id": peer_official_id if scope == "OFFICIAL" else None,
        }
        db.stamp_create(rec, common_fields=False)
        db.conflict_declarations[rec["id"]] = rec
    return object_response(serialize.conflict(rec), 201)


@bp.route("/conflict-declarations", methods=["GET"])
def list_conflicts():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    official_id = request.args.get("official_id")
    peer_official_id = request.args.get("peer_official_id")
    with db.lock:
        rows = list(db.conflict_declarations.values())
        if official_id is not None:
            rows = [c for c in rows if c["official_id"] == official_id]
        if peer_official_id is not None:
            rows = [c for c in rows if c.get("peer_official_id") == peer_official_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.conflict(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/conflict-declarations/<conflict_id>", methods=["GET"])
def get_conflict(conflict_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.conflict(conflict_id)
        return object_response(serialize.conflict(rec))
