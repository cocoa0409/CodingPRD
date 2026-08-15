"""Moderator endpoints."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch, check_unique, require_enum
from errors import raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE
from services.serializers import public

bp = make_blueprint("moderators")


def _get_moderator(mid):
    m = db.moderators.get(mid)
    if m is None:
        raise_error(ERR_NOT_FOUND, "Moderator not found")
    return m


@bp.route("/playtests/moderators", methods=["POST"])
def create_moderator():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    display_name = require_string(body, "display_name")
    email = require_string(body, "email")
    check_unique(db.moderators, "email", email)
    rec = {"display_name": display_name, "email": email, "status": "ACTIVE"}
    stamp_new(rec)
    db.moderators[rec["id"]] = rec
    return success(public(rec, "moderator"), status=201)


@bp.route("/playtests/moderators", methods=["GET"])
def list_moderators():
    require_roles("ResearchOpsAdmin", "Researcher")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.moderators.values())
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(m, "moderator") for m in page], status=200, pagination=pagination)


@bp.route("/playtests/moderators/<mid>", methods=["GET"])
def get_moderator(mid):
    require_roles("ResearchOpsAdmin", "Researcher", "Moderator")
    m = _get_moderator(mid)
    return success(public(m, "moderator"), status=200)


@bp.route("/playtests/moderators/<mid>", methods=["PATCH"])
def update_moderator(mid):
    require_roles("ResearchOpsAdmin")
    m = _get_moderator(mid)
    body = get_payload()
    status = require_enum(body, "status", ("ACTIVE", "INACTIVE"))
    if status == m["status"]:
        raise_error(ERR_INVALID_STATE, "Moderator already in status %s" % status)
    m["status"] = status
    touch(m)
    return success(public(m, "moderator"), status=200)
