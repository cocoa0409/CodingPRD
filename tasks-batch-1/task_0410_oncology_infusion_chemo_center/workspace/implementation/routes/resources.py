"""Chair and Nurse endpoints."""
from flask import Blueprint

from db import db
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created, get_chair, get_nurse,
)
from validation import (
    get_body, require_str, optional_bool, optional_int,
    get_pagination, paginate,
)

bp = Blueprint("resources", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}


# ---------- Chairs ----------

@bp.route("/chairs", methods=["POST"])
def create_chair():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    label = require_str(body, "label")
    is_isolation = optional_bool(body, "is_isolation", default=False)

    with db.lock:
        entity = make_common()
        entity.update({
            "label": label,
            "is_isolation": is_isolation,
            "status": "OPEN",
        })
        db.chairs[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/chairs", methods=["GET"])
def list_chairs():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    items = sort_by_created(list(db.chairs.values()))
    total = len(items)
    window = [public(c) for c in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/chairs/<cid>", methods=["GET"])
def get_one_chair(cid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_chair(cid)
    return success(public(entity), status=200)


@bp.route("/chairs/<cid>/close", methods=["POST"])
def close_chair(cid):
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    entity = get_chair(cid)
    with db.lock:
        entity["status"] = "CLOSED"
        touch(entity, bump_version=True)
        return success(public(entity), status=200)


# ---------- Nurses ----------

@bp.route("/nurses", methods=["POST"])
def create_nurse():
    _, role = get_auth()
    require_roles(role, {"Pharmacist"})
    body = get_body()
    full_name = require_str(body, "full_name")
    is_chemo_certified = optional_bool(body, "is_chemo_certified", default=False)
    max_acuity_load = optional_int(body, "max_acuity_load", default=6, ge=1)

    with db.lock:
        entity = make_common()
        entity.update({
            "full_name": full_name,
            "is_chemo_certified": is_chemo_certified,
            "max_acuity_load": max_acuity_load,
        })
        db.nurses[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/nurses", methods=["GET"])
def list_nurses():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    items = sort_by_created(list(db.nurses.values()))
    total = len(items)
    window = [public(n) for n in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/nurses/<nid>", methods=["GET"])
def get_one_nurse(nid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_nurse(nid)
    return success(public(entity), status=200)
