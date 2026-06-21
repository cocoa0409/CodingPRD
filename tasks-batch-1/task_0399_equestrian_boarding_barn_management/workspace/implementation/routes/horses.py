"""Horse routes and horse-scoped reverse-reachability lists (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from middleware import get_caller, require_role
from response import success
from services.common import (
    new_common, require_str, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services.lookups import get_owner, get_horse, require_owner_owns

bp = Blueprint("horses", __name__)


@bp.route("/horses", methods=["POST"])
def create_horse():
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    body = request.get_json(silent=True) or {}
    owner_id = require_str(body, "owner_id")
    name = require_str(body, "name")
    # ownership check applies to Owner-scoped writes before body-FK resolution would
    # matter for authz, but FK existence is part of priority-5; resolve owner first.
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    horse = new_common()
    horse.update({
        "owner_id": owner["id"],
        "name": name,
        "status": "ACTIVE",
    })
    db.horses[horse["id"]] = horse
    return success(view(horse), 201)


@bp.route("/owners/<owner_id>/horses", methods=["GET"])
def list_owner_horses(owner_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    owner = get_owner(owner_id)
    require_owner_owns(caller, owner["id"])
    limit, offset = parse_pagination(request.args)
    items = [h for h in db.horses.values() if h["owner_id"] == owner["id"]]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.route("/horses/<horse_id>", methods=["GET"])
def get_horse_route(horse_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    return success(view(horse), 200)


def _horse_list(horse_id, store_attr, fk_field, allowed_roles):
    caller = get_caller()
    require_role(caller, allowed_roles)
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    limit, offset = parse_pagination(request.args)
    store = getattr(db, store_attr)
    items = [x for x in store.values() if x[fk_field] == horse_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.route("/horses/<horse_id>/boarding-agreements", methods=["GET"])
def list_horse_agreements(horse_id):
    return _horse_list(horse_id, "agreements", "horse_id", ["BarnManager", "Owner"])


@bp.route("/horses/<horse_id>/lessons", methods=["GET"])
def list_horse_lessons(horse_id):
    return _horse_list(horse_id, "lessons", "horse_id", ["BarnManager", "Owner", "Instructor"])


@bp.route("/horses/<horse_id>/service-visits", methods=["GET"])
def list_horse_visits(horse_id):
    return _horse_list(horse_id, "visits", "horse_id", ["BarnManager", "Owner", "ServiceProvider"])


@bp.route("/horses/<horse_id>/show-entries", methods=["GET"])
def list_horse_entries(horse_id):
    return _horse_list(horse_id, "entries", "horse_id", ["BarnManager", "Owner"])


@bp.route("/horses/<horse_id>/turnouts", methods=["GET"])
def list_horse_turnouts(horse_id):
    return _horse_list(horse_id, "turnouts", "horse_id", ["BarnManager", "Owner"])
