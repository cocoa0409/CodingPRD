"""Placement routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, paginate, sort_by_created,
                     get_or_404)
from middleware import require_roles
from response import success_object, success_list
from services import calc, workflow

bp = Blueprint("placements", __name__)


def placement_view(p):
    return {k: p[k] for k in (
        "id", "application_id", "space_unit_id", "status",
        "created_at", "updated_at", "version")}


def _exhibitor_scope_check(user_id, placement):
    app = db.applications.get(placement["application_id"])
    if app is None or app["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Exhibitor role may only read its own placements")


@bp.route("/placements", methods=["POST"])
def create_placement():
    require_roles("ShowDirector")
    body = get_json_body()
    application_id = require_str(body, "application_id")
    space_unit_id = require_str(body, "space_unit_id")
    a = db.applications.get(application_id)
    if a is None:
        fail("ERR_NOT_FOUND", "application_id does not exist")
    su = db.space_units.get(space_unit_id)
    if su is None:
        fail("ERR_NOT_FOUND", "space_unit_id does not exist")
    if su["convention_id"] != a["convention_id"]:
        fail("ERR_NOT_FOUND", "space_unit_id belongs to another convention")
    if a["status"] not in ("JURIED_ACCEPTED", "CONTRACTED"):
        fail("ERR_INVALID_TRANSITION",
             "Placement target application must be JURIED_ACCEPTED or CONTRACTED")
    if su["kind"] not in a["requested_space_kinds"]:
        fail("ERR_SPACE_KIND_MISMATCH",
             "Space kind not in the application's requested_space_kinds")
    if (su["kind"], su["hall"]) not in _zone_triples(a["category"]):
        fail("ERR_CATEGORY_ZONE_VIOLATION",
             "(category, kind, hall) violates the category-zone map")
    if su["status"] != "AVAILABLE":
        fail("ERR_SPACE_NOT_AVAILABLE",
             "SpaceUnit status is not AVAILABLE")

    p = {
        "id": db.new_id(),
        "application_id": application_id,
        "space_unit_id": space_unit_id,
        "status": "TENTATIVE",
    }
    db.stamp_created(p)
    db.placements[p["id"]] = p
    su["status"] = "RESERVED"
    su["current_application_id"] = application_id
    db.touch(su)
    return success_object(placement_view(p), 201)


def _zone_triples(category):
    from services.calc import CATEGORY_ZONE_MAP
    return CATEGORY_ZONE_MAP.get(category, set())


@bp.route("/placements", methods=["GET"])
def list_placements():
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.placements.values())
    if role == "Exhibitor":
        own_apps = {a["id"] for a in db.applications.values() if a["exhibitor_id"] == user_id}
        items = [p for p in items if p["application_id"] in own_apps]
    for f in ("application_id", "space_unit_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([placement_view(p) for p in page], limit, offset, total)


@bp.route("/placements/<placementId>", methods=["GET"])
def get_placement(placementId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    p = get_or_404(db.placements, placementId)
    if role == "Exhibitor":
        _exhibitor_scope_check(user_id, p)
    return success_object(placement_view(p), 200)


@bp.route("/placements/<placementId>/confirm", methods=["POST"])
def confirm_placement(placementId):
    require_roles("ShowDirector")
    p = get_or_404(db.placements, placementId)
    if p["status"] != "TENTATIVE":
        fail("ERR_INVALID_TRANSITION", "confirm requires TENTATIVE placement")
    a = db.applications[p["application_id"]]
    if a["status"] not in ("CONTRACTED", "PLACED"):
        fail("ERR_INVALID_TRANSITION",
             "Application must be CONTRACTED or PLACED")
    conv = db.conventions[a["convention_id"]]
    if conv["phase"] != "PLACEMENT":
        fail("ERR_PHASE_PRECONDITION", "confirm requires phase PLACEMENT")

    su = db.space_units[p["space_unit_id"]]
    p["status"] = "CONFIRMED"
    db.touch(p)
    su["status"] = "ASSIGNED"
    db.touch(su)
    if a["status"] == "CONTRACTED":
        a["status"] = "PLACED"
    a["included_badges"] = calc.included_badges_for(a["id"], a["convention_id"])
    calc.recompute_balance_due(a)
    db.touch(a)
    workflow.evaluate_neighbor_requests(a["convention_id"])
    return success_object(placement_view(p), 200)


@bp.route("/placements/<placementId>/release", methods=["POST"])
def release_placement(placementId):
    require_roles("ShowDirector")
    p = get_or_404(db.placements, placementId)
    if p["status"] != "TENTATIVE":
        fail("ERR_INVALID_TRANSITION", "release requires TENTATIVE placement")
    workflow._release_placement(p)
    return success_object(placement_view(p), 200)
