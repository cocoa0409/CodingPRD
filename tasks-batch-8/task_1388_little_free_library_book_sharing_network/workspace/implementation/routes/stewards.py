"""Steward lifecycle endpoints (PRD §3.1 / §3.2)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_EMAIL_TAKEN,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORIENTATION_REQUIRED,
    ERR_STALE_VERSION,
    ERR_STEWARD_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_steward
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("stewards", __name__)


def _load_steward(steward_id: str) -> dict:
    steward = db.stewards.get(steward_id)
    if steward is None:
        raise_err(ERR_STEWARD_NOT_FOUND, "No steward with the given id")
    return steward


@bp.route("/library-network/stewards", methods=["POST"])
@require_roles("Anonymous", "NetworkAdmin")
def create_steward(_user_id, _role):
    body = get_json_body()
    email = body.get("email")
    # Business constraint (stage 9): email unique across all stewards.
    if isinstance(email, str) and email != "":
        for s in db.stewards.values():
            if s["email"] == email:
                raise_err(ERR_EMAIL_TAKEN, "Another steward already uses this email")
    # Schema validation (stage 11).
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    region_code = require_string(body, "region_code")

    steward = {
        "full_name": full_name,
        "email": email,
        "region_code": region_code,
        "status": "APPLIED",
        "suspended_at": None,
    }
    db.stamp_new(steward)
    db.stewards[steward["id"]] = steward
    return success_object(serialize_steward(steward), 201)


@bp.route("/library-network/stewards", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_stewards(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_steward(s) for s in sort_by_created_at(list(db.stewards.values()))]
    items = apply_filters(items, ["status", "region_code"])
    tier = request.args.get("tier")
    if tier:
        items = [s for s in items if s["recognition_tier"] == tier]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/stewards/<steward_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_steward(steward_id: str, _user_id, _role):
    return success_object(serialize_steward(_load_steward(steward_id)))


@bp.route("/library-network/stewards/<steward_id>", methods=["PATCH"])
@require_roles("Steward", "NetworkAdmin")
def patch_steward(steward_id: str, _user_id, _role):
    # Ownership (stage 2): a steward may patch only their own record.
    if _role == "Steward" and _user_id != steward_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only patch their own profile")
    steward = _load_steward(steward_id)
    body = get_json_body()

    # OCC (stage 10): expected_steward_version is a non-optional input (§2.7).
    expected = body.get("expected_steward_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != steward["version"]:
            raise_err(ERR_STALE_VERSION, "expected_steward_version does not match current version")
    # Schema validation (stage 11) — expected_steward_version is mandatory.
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "Field expected_steward_version is required and must be an integer")
    full_name = optional_string(body, "full_name")
    region_code = optional_string(body, "region_code")

    if full_name is not None:
        steward["full_name"] = full_name
    if region_code is not None:
        steward["region_code"] = region_code
    db.touch(steward)
    return success_object(serialize_steward(steward))


@bp.route("/library-network/stewards/<steward_id>/activate", methods=["POST"])
@require_roles("NetworkAdmin")
def activate_steward(steward_id: str, _user_id, _role):
    steward = _load_steward(steward_id)
    if steward["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "Steward is not in APPLIED status")
    # Cross-entity gate: a PASSED ORIENTATION completion is required.
    orientation_ids = {
        m["id"] for m in db.training_modules.values() if m["code"] == "ORIENTATION"
    }
    passed = any(
        t["steward_id"] == steward_id
        and t["module_id"] in orientation_ids
        and t["result"] == "PASSED"
        for t in db.training_completions.values()
    )
    if not passed:
        raise_err(ERR_ORIENTATION_REQUIRED, "Steward lacks a PASSED ORIENTATION completion")
    steward["status"] = "ACTIVE"
    db.touch(steward)
    return success_object(serialize_steward(steward))


@bp.route("/library-network/stewards/<steward_id>/suspend", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def suspend_steward(steward_id: str, _user_id, _role):
    steward = _load_steward(steward_id)
    if steward["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Steward is not in ACTIVE status")
    steward["status"] = "SUSPENDED"
    steward["suspended_at"] = db.now_logical_iso()
    db.touch(steward)
    return success_object(serialize_steward(steward))


@bp.route("/library-network/stewards/<steward_id>/reinstate", methods=["POST"])
@require_roles("NetworkAdmin")
def reinstate_steward(steward_id: str, _user_id, _role):
    steward = _load_steward(steward_id)
    if steward["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Steward is not in SUSPENDED status")
    steward["status"] = "ACTIVE"
    steward["suspended_at"] = None
    db.touch(steward)
    return success_object(serialize_steward(steward))


@bp.route("/library-network/stewards/<steward_id>/retire", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def retire_steward(steward_id: str, _user_id, _role):
    # Ownership (stage 2): a steward may retire only themself.
    if _role == "Steward" and _user_id != steward_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only retire their own record")
    steward = _load_steward(steward_id)
    if steward["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Steward must be ACTIVE or SUSPENDED to retire")
    steward["status"] = "RETIRED"
    db.touch(steward)
    return success_object(serialize_steward(steward))
