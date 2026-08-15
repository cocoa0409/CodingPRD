"""WatchGroup routes."""

import re
from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("watch_groups", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

DEPOT_SIGN_BUDGET = 50


def _serialize_group(g):
    return {
        "id": g["id"],
        "name": g["name"],
        "precinct_code": g["precinct_code"],
        "certification_status": g["certification_status"],
        "certification_valid_until": g.get("certification_valid_until"),
        "posture": g["posture"],
        "sign_inventory_count": g["sign_inventory_count"],
        "materials_inventory_count": g["materials_inventory_count"],
        "participation_score": g["participation_score"],
        "training_cooldown_until": g.get("training_cooldown_until"),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


@bp.route("/watch/watch-groups", methods=["POST"])
def create_group():
    user_id, role = require_roles("ProgramCoordinator")
    body = request.get_json(force=True, silent=True) or {}

    name = body.get("name")
    precinct_code = body.get("precinct_code")

    # Field-level validation
    if not name or not isinstance(name, str) or len(name) < 1 or len(name) > 120:
        raise errors.invalid_request("name must be 1-120 characters")
    if not precinct_code or not isinstance(precinct_code, str):
        raise errors.invalid_request("precinct_code is required")
    if not re.match(r"^[A-Z0-9]{2,12}$", precinct_code):
        raise errors.invalid_request("precinct_code must be uppercase alphanumeric, 2-12 chars")

    # Uniqueness: name unique within precinct_code
    for g in db.watch_groups.values():
        if g["precinct_code"] == precinct_code and g["name"] == name:
            raise errors.constraint_violation("Watch group name must be unique within precinct")

    record = {
        "name": name,
        "precinct_code": precinct_code,
        "certification_status": "UNCERTIFIED",
        "certification_valid_until": None,
        "posture": "DORMANT",
        "sign_inventory_count": 0,
        "materials_inventory_count": 0,
        "participation_score": 0,
        "training_cooldown_until": None,
    }
    svc.stamp_new(record)
    db.watch_groups[record["id"]] = record
    return success_object(_serialize_group(record), 201)


@bp.route("/watch/watch-groups", methods=["GET"])
def list_groups():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.watch_groups.values())

    # Filters
    precinct = request.args.get("precinct_code")
    if precinct:
        items = [g for g in items if g["precinct_code"] == precinct]
    cert = request.args.get("certification_status")
    if cert:
        items = [g for g in items if g["certification_status"] == cert]
    posture = request.args.get("posture")
    if posture:
        items = [g for g in items if g["posture"] == posture]

    # Sort by created_at ascending
    items.sort(key=lambda g: g["created_at"])

    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]

    return success_list([_serialize_group(g) for g in items], limit, offset, total)


@bp.route("/watch/watch-groups/<id>", methods=["GET"])
def get_group(id):
    user_id, role = require_roles(*ALL_ROLES)
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    # Lazy expiry sweep for this group
    svc.sweep_agreement_expiry(id)
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/certification-suspend", methods=["POST"])
def certification_suspend(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["certification_status"] in ("SUSPENDED", "REVOKED"):
        raise errors.invalid_state("Cannot suspend from current certification status")
    g["certification_status"] = "SUSPENDED"
    g["certification_valid_until"] = None
    svc.touch(g)
    svc.recompute_posture(id)
    # Re-fetch after recompute
    g = db.watch_groups[id]
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/certification-reinstate", methods=["POST"])
def certification_reinstate(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["certification_status"] != "SUSPENDED":
        raise errors.invalid_state("Can only reinstate a SUSPENDED certification")
    g["certification_status"] = "PROVISIONAL"
    svc.touch(g)
    svc.recompute_posture(id)
    g = db.watch_groups[id]
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/freeze", methods=["POST"])
def freeze_group(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["posture"] == "FROZEN":
        raise errors.invalid_state("Group is already FROZEN")
    if g["certification_status"] != "SUSPENDED":
        raise errors.invalid_state("Can only freeze a group with SUSPENDED certification")
    if g["posture"] not in ("OPERATIONAL", "DEGRADED", "FORMATION"):
        raise errors.invalid_state(f"Cannot freeze from posture {g['posture']}")
    g["posture"] = "FROZEN"
    svc.touch(g)
    svc._recompute_participation(g)
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/unfreeze", methods=["POST"])
def unfreeze_group(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    if g["posture"] != "FROZEN":
        raise errors.invalid_state("Group is not FROZEN")
    if g["certification_status"] not in ("PROVISIONAL", "CERTIFIED"):
        raise errors.invalid_state("Certification must be PROVISIONAL or CERTIFIED to unfreeze")
    # Recompute from scratch
    g["posture"] = "FORMATION"  # temporary to escape FROZEN guard
    svc.recompute_posture(id)
    g = db.watch_groups[id]
    svc.touch(g)
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/materials/issue", methods=["POST"])
def materials_issue(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    body = request.get_json(force=True, silent=True) or {}
    signs = body.get("signs", 0)
    materials = body.get("materials", 0)
    if not isinstance(signs, int) or not isinstance(materials, int) or signs < 0 or materials < 0:
        raise errors.invalid_request("signs and materials must be non-negative integers")

    # Depot budget check
    if g["sign_inventory_count"] + signs > DEPOT_SIGN_BUDGET:
        raise errors.inventory_limit(f"Sign issue would exceed depot budget of {DEPOT_SIGN_BUDGET}")

    g["sign_inventory_count"] += signs
    g["materials_inventory_count"] += materials
    svc.touch(g)
    return success_object(_serialize_group(g))


@bp.route("/watch/watch-groups/<id>/materials/recall", methods=["POST"])
def materials_recall(id):
    user_id, role = require_roles("ProgramCoordinator")
    g = db.watch_groups.get(id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    body = request.get_json(force=True, silent=True) or {}
    signs = body.get("signs", 0)
    materials = body.get("materials", 0)
    if not isinstance(signs, int) or not isinstance(materials, int) or signs < 0 or materials < 0:
        raise errors.invalid_request("signs and materials must be non-negative integers")

    if g["sign_inventory_count"] - signs < 0:
        raise errors.inventory_limit("Recall would drive sign inventory below 0")
    if g["materials_inventory_count"] - materials < 0:
        raise errors.inventory_limit("Recall would drive materials inventory below 0")

    g["sign_inventory_count"] -= signs
    g["materials_inventory_count"] -= materials
    svc.touch(g)
    return success_object(_serialize_group(g))


def _pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
