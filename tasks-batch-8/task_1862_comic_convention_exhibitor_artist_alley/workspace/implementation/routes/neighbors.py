"""NeighborRequest routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_enum, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("neighbors", __name__)

LIVE = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION",
        "JURIED_ACCEPTED", "JURIED_WAITLISTED", "CONTRACTED", "PLACED")


def neighbor_view(n):
    return {k: n[k] for k in (
        "id", "convention_id", "requester_exhibitor_id", "target_exhibitor_id",
        "kind", "status", "created_at", "updated_at", "version")}


def _has_live_application(exhibitor_id, convention_id):
    for a in db.applications.values():
        if a["exhibitor_id"] == exhibitor_id and a["convention_id"] == convention_id \
                and a["status"] in LIVE:
            return True
    return False


@bp.route("/neighbor-requests", methods=["POST"])
def create_neighbor_request():
    user_id, _ = require_roles("Exhibitor")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    target = require_str(body, "target_exhibitor_id")
    kind = require_enum(body, "kind", ("ADJACENT_TO", "AWAY_FROM"))

    conv = db.conventions.get(convention_id)
    if conv is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    if db.exhibitors.get(target) is None:
        fail("ERR_NOT_FOUND", "target_exhibitor_id does not exist")
    if target == user_id:
        fail("ERR_NEIGHBOR_SELF_TARGET", "Cannot target the requester itself")
    if not _has_live_application(target, convention_id) \
            or not _has_live_application(user_id, convention_id):
        fail("ERR_NEIGHBOR_TARGET_NOT_APPLIED",
             "Both parties must hold a live application in this convention")
    for nr in db.neighbor_requests.values():
        if nr["status"] == "PENDING" \
                and nr["requester_exhibitor_id"] == user_id \
                and nr["target_exhibitor_id"] == target \
                and nr["kind"] == kind:
            fail("ERR_DUPLICATE_NEIGHBOR_REQUEST",
                 "A PENDING request for this (requester, target, kind) already exists")

    nr = {
        "id": db.new_id(),
        "convention_id": convention_id,
        "requester_exhibitor_id": user_id,
        "target_exhibitor_id": target,
        "kind": kind,
        "status": "PENDING",
    }
    db.stamp_created(nr)
    db.neighbor_requests[nr["id"]] = nr
    return success_object(neighbor_view(nr), 201)


@bp.route("/neighbor-requests", methods=["GET"])
def list_neighbor_requests():
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    items = list(db.neighbor_requests.values())
    if role == "Exhibitor":
        items = [n for n in items
                 if n["requester_exhibitor_id"] == user_id or n["target_exhibitor_id"] == user_id]
    for f in ("convention_id", "requester_exhibitor_id", "target_exhibitor_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [n for n in items if n[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([neighbor_view(n) for n in page], limit, offset, total)


@bp.route("/neighbor-requests/<neighborRequestId>", methods=["GET"])
def get_neighbor_request(neighborRequestId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "Exhibitor")
    nr = get_or_404(db.neighbor_requests, neighborRequestId)
    if role == "Exhibitor" and user_id not in (nr["requester_exhibitor_id"], nr["target_exhibitor_id"]):
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Exhibitor role may only read requests where it is requester or target")
    return success_object(neighbor_view(nr), 200)


@bp.route("/neighbor-requests/<neighborRequestId>/withdraw", methods=["POST"])
def withdraw_neighbor_request(neighborRequestId):
    user_id, _ = require_roles("Exhibitor")
    nr = get_or_404(db.neighbor_requests, neighborRequestId)
    if nr["requester_exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Only the requester may withdraw a neighbor request")
    if nr["status"] != "PENDING":
        fail("ERR_INVALID_TRANSITION", "withdraw requires PENDING")
    nr["status"] = "WITHDRAWN"
    db.touch(nr)
    return success_object(neighbor_view(nr), 200)
