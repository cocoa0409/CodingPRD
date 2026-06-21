"""Problem / KnownError routes and asset-health cascades (PRD §3.8)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from response import success_object, success_array
from services import serialize
from services.common import (
    stamp_create,
    touch,
    paginate,
    require_fields,
    require_string,
    sorted_by_created,
    recompute_linked_ticket_count,
)

bp = Blueprint("problems", __name__)

ALL_ROLES = ["PlatformAdmin", "Agent", "ChangeManager", "CabMember", "Requester"]

PROBLEM_ACTIVE_STATES = {"OPEN", "ROOT_CAUSE_IDENTIFIED", "KNOWN_ERROR"}


def _body():
    return request.get_json(silent=True) or {}


def _get_problem_or_404(pid):
    rec = store.problems.get(pid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Problem not found.")
    return rec


@bp.route("/problems", methods=["POST"])
def create_problem():
    require_auth(["Agent"])
    body = _body()
    require_fields(body, ["title", "owner_user_id"])
    title = require_string(body, "title")
    owner_user_id = require_string(body, "owner_user_id")
    asset_id = body.get("asset_id")
    if asset_id is not None and asset_id not in store.assets:
        raise err("ERR_FK_NOT_FOUND", "asset_id does not resolve.")
    rec = {
        "title": title,
        "owner_user_id": owner_user_id,
        "state": "OPEN",
        "linked_ticket_count": 0,
        "asset_id": asset_id,
    }
    stamp_create(rec)
    store.problems[rec["id"]] = rec
    return success_object(serialize.problem(rec), 201)


@bp.route("/problems/<pid>", methods=["GET"])
def get_problem(pid):
    rec = _get_problem_or_404(pid)
    return success_object(serialize.problem(rec), 200)


@bp.route("/problems", methods=["GET"])
def list_problems():
    items = list(store.problems.values())
    asset_id = request.args.get("asset_id")
    state = request.args.get("state")
    if asset_id is not None:
        items = [p for p in items if p.get("asset_id") == asset_id]
    if state is not None:
        items = [p for p in items if p["state"] == state]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.problem(p) for p in window], limit, offset, total)


@bp.route("/problems/<pid>/identify-root-cause", methods=["POST"])
def identify_root_cause(pid):
    require_auth(["Agent"])
    rec = _get_problem_or_404(pid)
    body = _body()
    asset_id = body.get("asset_id")
    if asset_id is not None and asset_id not in store.assets:
        raise err("ERR_FK_NOT_FOUND", "asset_id does not resolve.")
    if rec["state"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Problem must be OPEN to identify root cause.")
    rec["state"] = "ROOT_CAUSE_IDENTIFIED"
    if asset_id is not None:
        rec["asset_id"] = asset_id
        asset = store.assets.get(asset_id)
        if asset is not None and asset["status"] == "OPERATIONAL":
            asset["status"] = "DEGRADED"
            touch(asset)
    touch(rec)
    return success_object(serialize.problem(rec), 200)


@bp.route("/problems/<pid>/known-errors", methods=["POST"])
def create_known_error(pid):
    require_auth(["Agent"])
    rec = _get_problem_or_404(pid)
    body = _body()
    require_fields(body, ["symptom", "workaround"])
    symptom = require_string(body, "symptom")
    workaround = require_string(body, "workaround")
    if rec["state"] != "ROOT_CAUSE_IDENTIFIED":
        raise err("ERR_INVALID_STATE", "Problem must be ROOT_CAUSE_IDENTIFIED to promote.")
    ke = {
        "problem_id": pid,
        "symptom": symptom,
        "workaround": workaround,
        "published": True,
    }
    stamp_create(ke)
    store.known_errors[ke["id"]] = ke
    rec["state"] = "KNOWN_ERROR"
    touch(rec)
    return success_object(serialize.known_error(ke), 201)


@bp.route("/problems/<pid>/known-errors", methods=["GET"])
def list_known_errors(pid):
    _get_problem_or_404(pid)
    items = [k for k in store.known_errors.values() if k["problem_id"] == pid]
    items = sorted_by_created(items)
    window, limit, offset, total = paginate(items, request.args)
    return success_array([serialize.known_error(k) for k in window], limit, offset, total)


@bp.route("/problems/<pid>/resolve", methods=["POST"])
def resolve_problem(pid):
    require_auth(["Agent"])
    rec = _get_problem_or_404(pid)
    if rec["state"] != "KNOWN_ERROR":
        raise err("ERR_INVALID_STATE", "Problem must be KNOWN_ERROR to resolve.")
    recompute_linked_ticket_count(pid)
    if rec["linked_ticket_count"] > 0:
        raise err("ERR_PROBLEM_HAS_OPEN_TICKETS", "Problem has open linked tickets.")
    rec["state"] = "RESOLVED"
    touch(rec)
    # Asset cascade: if this problem had a recorded asset and no other active
    # problem references it, degrade -> operational (PRD §3.8).
    asset_id = rec.get("asset_id")
    if asset_id is not None:
        others = any(
            p["id"] != pid
            and p.get("asset_id") == asset_id
            and p["state"] in PROBLEM_ACTIVE_STATES
            for p in store.problems.values()
        )
        if not others:
            asset = store.assets.get(asset_id)
            if asset is not None and asset["status"] == "DEGRADED":
                asset["status"] = "OPERATIONAL"
                touch(asset)
    return success_object(serialize.problem(rec), 200)


# ---------------- KnownError direct get ----------------

@bp.route("/known-errors/<kid>", methods=["GET"])
def get_known_error(kid):
    rec = store.known_errors.get(kid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Known error not found.")
    return success_object(serialize.known_error(rec), 200)
