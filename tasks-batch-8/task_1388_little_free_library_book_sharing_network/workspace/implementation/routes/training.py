"""Training module and completion endpoints (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_MODULE_ALREADY_PASSED,
    ERR_MODULE_CYCLE,
    ERR_MODULE_INACTIVE,
    ERR_MODULE_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_PREREQUISITE_NOT_MET,
    ERR_STEWARD_NOT_FOUND,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_completion, serialize_module
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("training", __name__)


def _load_module(module_id: str) -> dict:
    module = db.training_modules.get(module_id)
    if module is None:
        raise_err(ERR_MODULE_NOT_FOUND, "No training module with the given id")
    return module


@bp.route("/library-network/training-modules", methods=["POST"])
@require_roles("NetworkAdmin")
def create_module(_user_id, _role):
    body = get_json_body()
    prereq = body.get("prerequisite_module_id")
    # Body referential integrity (stage 4).
    if prereq is not None:
        if not isinstance(prereq, str) or prereq not in db.training_modules:
            raise_body_ref_err(ERR_MODULE_NOT_FOUND, "prerequisite_module_id does not resolve")
    # Schema (stage 11).
    code = require_string(body, "code")
    title = require_string(body, "title")
    level = require_int(body, "level")
    active = optional_field(body, "active", True)
    if not isinstance(active, bool):
        raise_err(ERR_INVALID_REQUEST, "Field active must be a boolean")
    if prereq is not None and not isinstance(prereq, str):
        raise_err(ERR_INVALID_REQUEST, "Field prerequisite_module_id must be a string")

    for m in db.training_modules.values():
        if m["code"] == code:
            raise_err(ERR_INVALID_REQUEST, "Module code must be unique")

    module = {
        "code": code,
        "title": title,
        "level": level,
        "prerequisite_module_id": prereq,
        "active": active,
    }
    db.stamp_new(module)
    db.training_modules[module["id"]] = module
    return success_object(serialize_module(module), 201)


@bp.route("/library-network/training-modules", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_modules(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_module(m) for m in sort_by_created_at(list(db.training_modules.values()))]
    items = apply_filters(items, ["prerequisite_module_id"])
    active = request.args.get("active")
    if active is not None and active != "":
        want = active.lower() == "true"
        items = [m for m in items if m["active"] == want]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/training-modules/<module_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_module(module_id: str, _user_id, _role):
    return success_object(serialize_module(_load_module(module_id)))


@bp.route("/library-network/training-modules/<module_id>", methods=["PATCH"])
@require_roles("NetworkAdmin")
def patch_module(module_id: str, _user_id, _role):
    module = _load_module(module_id)
    body = get_json_body()

    if "prerequisite_module_id" in body:
        prereq = body["prerequisite_module_id"]
        if prereq is not None:
            if not isinstance(prereq, str) or prereq not in db.training_modules:
                raise_body_ref_err(ERR_MODULE_NOT_FOUND, "prerequisite_module_id does not resolve")
            # Business constraint: the prerequisite graph must stay acyclic.
            if domain.module_would_cycle(module_id, prereq):
                raise_err(ERR_MODULE_CYCLE, "prerequisite_module_id would create a cycle")
        module["prerequisite_module_id"] = prereq
    if "active" in body:
        active = body["active"]
        if not isinstance(active, bool):
            raise_err(ERR_INVALID_REQUEST, "Field active must be a boolean")
        module["active"] = active
    db.touch(module)
    return success_object(serialize_module(module))


@bp.route("/library-network/stewards/<steward_id>/training-completions", methods=["POST"])
@require_roles("Steward", "NetworkAdmin")
def create_completion(steward_id: str, _user_id, _role):
    # Ownership (stage 2): steward self-service only.
    if _role == "Steward" and _user_id != steward_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only record their own completions")
    steward = db.stewards.get(steward_id)
    if steward is None:
        raise_err(ERR_STEWARD_NOT_FOUND, "No steward with the given id")
    body = get_json_body()

    module_id = body.get("module_id")
    module = None
    # Body referential integrity (stage 4).
    if module_id is not None:
        if not isinstance(module_id, str) or module_id not in db.training_modules:
            raise_body_ref_err(ERR_MODULE_NOT_FOUND, "No training module with the given id")
        module = db.training_modules[module_id]

    # Business constraints (stage 9), in PRD order: active -> prerequisite -> already passed.
    if module is not None:
        if not module.get("active", True):
            raise_err(ERR_MODULE_INACTIVE, "Module is inactive")
        if not domain.prerequisite_chain_passed(steward_id, module):
            raise_err(ERR_PREREQUISITE_NOT_MET, "Prerequisite chain not fully passed")
        if domain.has_passed(steward_id, module["id"]):
            raise_err(ERR_MODULE_ALREADY_PASSED, "Module already passed by this steward")

    # Schema (stage 11).
    module_id = require_field(body, "module_id")
    if not isinstance(module_id, str):
        raise_err(ERR_INVALID_REQUEST, "Field module_id must be a string")
    score = require_int(body, "score", minimum=0, maximum=100)

    result = "PASSED" if score >= 80 else "FAILED"
    completion = {
        "steward_id": steward_id,
        "module_id": module_id,
        "score": score,
        "result": result,
    }
    db.stamp_new_light(completion)
    db.training_completions[completion["id"]] = completion

    if result == "PASSED":
        # +25 TRAINING_PASSED; refreshes recognition figures (and bumps the
        # steward's version via the cascaded recompute, §2.7).
        domain.add_recognition_event(
            steward_id, "TRAINING_PASSED", 25, "TRAINING_COMPLETION", completion["id"]
        )
    return success_object(serialize_completion(completion), 201)


@bp.route("/library-network/training-completions", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_completions(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_completion(t) for t in sort_by_created_at(list(db.training_completions.values()))]
    items = apply_filters(items, ["steward_id", "module_id", "result"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/training-completions/<completion_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_completion(completion_id: str, _user_id, _role):
    completion = db.training_completions.get(completion_id)
    if completion is None:
        raise_err(ERR_NOT_FOUND, "No training completion with the given id")
    return success_object(serialize_completion(completion))
