"""StoreKitConfig endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROTOTYPE_NOT_FOUND,
    ERR_KIT_CONFIG_NOT_FOUND,
    ERR_WAVE_NOT_FOUND,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_PROTOTYPE_NOT_APPROVED,
    ERR_KIT_INVALID_STATE,
    ERR_KIT_EMPTY,
    ERR_BUDGET_EXCEEDED,
    ERR_WAVE_NOT_RELEASABLE,
    ERR_WAVE_CAPACITY_EXCEEDED,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import (
    kit_totals,
    wave_release_charge,
    recompute_wave_utilization,
)
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("kits", __name__)


def _get_kit_or_404(kit_id: str) -> dict:
    kit = db.kits.get(kit_id)
    if kit is None:
        raise_err(ERR_KIT_CONFIG_NOT_FOUND, "StoreKitConfig id does not exist")
    return kit


def _validate_config_lines(config_lines) -> list:
    if not isinstance(config_lines, list):
        raise_err(ERR_INVALID_REQUEST, "config_lines must be an array")
    for line in config_lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "config_lines entries must be objects")
        part_number = line.get("part_number")
        if not isinstance(part_number, str) or part_number == "":
            raise_err(ERR_INVALID_REQUEST, "config_lines.part_number must be a non-empty string")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err(ERR_INVALID_REQUEST, "config_lines.quantity must be an integer >= 1")
        unit_cost = line.get("unit_cost_cents")
        if isinstance(unit_cost, bool) or not isinstance(unit_cost, int):
            raise_err(ERR_INVALID_REQUEST, "config_lines.unit_cost_cents must be an integer")
    return config_lines


@bp.route("/store-kit-configs", methods=["POST"])
@require_roles("ConfigCoordinator")
def create_kit(_user_id: str, _role: str):
    body = get_json_body()
    program_id = require_string(body, "program_id")
    prototype_id = require_string(body, "prototype_id")
    store_code = require_string(body, "store_code")
    config_lines = body.get("config_lines")
    if config_lines is None:
        config_lines = []
    config_lines = _validate_config_lines(config_lines)

    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")
    proto = db.prototypes.get(prototype_id)
    if proto is None:
        raise_err(ERR_PROTOTYPE_NOT_FOUND, "FixturePrototype id does not exist")

    total_components, kit_total = kit_totals(config_lines)
    kit = {
        "program_id": program_id,
        "prototype_id": prototype_id,
        "store_code": store_code,
        "config_lines": config_lines,
        "total_components": total_components,
        "kit_total_cost_cents": kit_total,
        "wave_release_charge_cents": None,
        "wave_id": None,
        "status": "DRAFT",
    }
    db.stamp_new(kit)
    db.kits[kit["id"]] = kit
    return success_object(serialize(kit), 201)


@bp.route("/store-kit-configs", methods=["GET"])
@require_roles("Any")
def list_kits(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.kits.values()))
    items = apply_filters(items, ["program_id", "prototype_id", "wave_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/store-kit-configs/<kit_id>", methods=["GET"])
@require_roles("Any")
def get_kit(kit_id: str, _user_id: str, _role: str):
    kit = _get_kit_or_404(kit_id)
    return success_object(serialize(kit))


@bp.route("/store-kit-configs/<kit_id>", methods=["PATCH"])
@require_roles("ConfigCoordinator")
def patch_kit(kit_id: str, _user_id: str, _role: str):
    kit = _get_kit_or_404(kit_id)
    if kit["status"] != "DRAFT":
        raise_err(ERR_KIT_INVALID_STATE, "PATCH requires kit DRAFT")
    body = get_json_body()
    config_lines = _validate_config_lines(body.get("config_lines"))
    expected = body.get("expected_config_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_config_version is required and must be an integer")
    if expected != kit["version"]:
        raise_err(ERR_STALE_VERSION, "expected_config_version does not match the kit's current version")

    kit["config_lines"] = config_lines
    total_components, kit_total = kit_totals(config_lines)
    kit["total_components"] = total_components
    kit["kit_total_cost_cents"] = kit_total
    db.touch(kit)
    return success_object(serialize(kit))


@bp.route("/store-kit-configs/<kit_id>/freeze", methods=["POST"])
@require_roles("ConfigCoordinator")
def freeze_kit(kit_id: str, _user_id: str, _role: str):
    kit = _get_kit_or_404(kit_id)
    if kit["status"] != "DRAFT":
        raise_err(ERR_KIT_INVALID_STATE, "freeze requires kit DRAFT")
    program = db.programs.get(kit["program_id"])
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "freeze requires program ACTIVE")
    proto = db.prototypes.get(kit["prototype_id"])
    if proto is None:
        raise_err(ERR_PROTOTYPE_NOT_FOUND, "FixturePrototype id does not exist")
    if proto["status"] not in ("APPROVED", "LOCKED"):
        raise_err(ERR_PROTOTYPE_NOT_APPROVED, "freeze requires prototype APPROVED or LOCKED")
    if len(kit["config_lines"]) == 0:
        raise_err(ERR_KIT_EMPTY, "freeze requires at least one config line")
    if kit["kit_total_cost_cents"] > program["remaining_budget_cents"]:
        raise_err(ERR_BUDGET_EXCEEDED, "kit_total_cost_cents exceeds program.remaining_budget_cents")

    # Side effects
    program["remaining_budget_cents"] -= kit["kit_total_cost_cents"]
    db.touch(program)

    # First frozen kit derived from this prototype locks it (APPROVED -> LOCKED)
    if proto["status"] == "APPROVED":
        already_frozen = any(
            other["prototype_id"] == proto["id"]
            and other["id"] != kit["id"]
            and other["status"] in ("FROZEN", "RELEASED", "FULFILLED")
            for other in db.kits.values()
        )
        if not already_frozen:
            proto["status"] = "LOCKED"
            db.touch(proto)

    kit["status"] = "FROZEN"
    db.touch(kit)
    return success_object(serialize(kit))


@bp.route("/store-kit-configs/<kit_id>/release", methods=["POST"])
@require_roles("ConfigCoordinator")
def release_kit(kit_id: str, _user_id: str, _role: str):
    kit = _get_kit_or_404(kit_id)
    if kit["status"] != "FROZEN":
        raise_err(ERR_KIT_INVALID_STATE, "release requires kit FROZEN")
    body = get_json_body()
    wave_id = require_string(body, "wave_id")
    wave = db.waves.get(wave_id)
    if wave is None or wave["program_id"] != kit["program_id"]:
        raise_err(ERR_WAVE_NOT_FOUND, "ProductionWave id does not exist or belongs to a different program")
    if wave["status"] not in ("COMMITTED", "IN_PRODUCTION"):
        raise_err(ERR_WAVE_NOT_RELEASABLE, "release requires wave COMMITTED or IN_PRODUCTION")
    if wave["committed_units"] + kit["total_components"] > wave["capacity_units"]:
        raise_err(ERR_WAVE_CAPACITY_EXCEEDED, "committed_units + total_components exceeds capacity_units")
    program = db.programs.get(kit["program_id"])
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")

    charge = wave_release_charge(kit["total_components"], wave)
    if charge > program["remaining_budget_cents"]:
        raise_err(ERR_BUDGET_EXCEEDED, "wave_release_charge_cents exceeds program.remaining_budget_cents")

    # Side effects
    kit["wave_release_charge_cents"] = charge
    kit["wave_id"] = wave_id
    program["remaining_budget_cents"] -= charge
    db.touch(program)
    wave["committed_units"] += kit["total_components"]
    recompute_wave_utilization(wave)
    db.touch(wave)
    kit["status"] = "RELEASED"
    db.touch(kit)
    return success_object(serialize(kit))


@bp.route("/store-kit-configs/<kit_id>/cancel", methods=["POST"])
@require_roles("ConfigCoordinator")
def cancel_kit(kit_id: str, _user_id: str, _role: str):
    kit = _get_kit_or_404(kit_id)
    if kit["status"] not in ("DRAFT", "FROZEN"):
        raise_err(ERR_KIT_INVALID_STATE, "cancel requires kit DRAFT or FROZEN")
    if kit["status"] == "FROZEN":
        program = db.programs.get(kit["program_id"])
        if program is not None:
            program["remaining_budget_cents"] += kit["kit_total_cost_cents"]
            db.touch(program)
    kit["status"] = "CANCELLED"
    db.touch(kit)
    return success_object(serialize(kit))
