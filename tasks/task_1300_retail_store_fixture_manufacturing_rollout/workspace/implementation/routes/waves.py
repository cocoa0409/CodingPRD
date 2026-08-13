"""ProductionWave endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_PROGRAM_NOT_FOUND,
    ERR_WAVE_NOT_FOUND,
    ERR_WAVE_INVALID_STATE,
    ERR_PROGRAM_NOT_ACTIVE,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("waves", __name__)


def _get_wave_or_404(wave_id: str) -> dict:
    wave = db.waves.get(wave_id)
    if wave is None:
        raise_err(ERR_WAVE_NOT_FOUND, "ProductionWave id does not exist")
    return wave


@bp.route("/production-waves", methods=["POST"])
@require_roles("ProductionPlanner")
def create_wave(_user_id: str, _role: str):
    body = get_json_body()
    program_id = require_string(body, "program_id")
    wave_label = require_string(body, "wave_label")
    start_date = require_date(body, "start_date")
    end_date = require_date(body, "end_date")
    capacity_units = require_int(body, "capacity_units")

    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")

    if not (end_date > start_date):
        raise_err(ERR_INVALID_WINDOW, "end_date must be strictly after start_date")
    if capacity_units < 1:
        raise_err(ERR_INVALID_REQUEST, "capacity_units must be >= 1")

    wave = {
        "program_id": program_id,
        "wave_label": wave_label,
        "start_date": start_date,
        "end_date": end_date,
        "capacity_units": capacity_units,
        "committed_units": 0,
        "utilization_pct": 0,
        "utilization_posture": "NORMAL",
        "status": "PLANNED",
    }
    db.stamp_new(wave)
    db.waves[wave["id"]] = wave
    return success_object(serialize(wave), 201)


@bp.route("/production-waves", methods=["GET"])
@require_roles("Any")
def list_waves(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.waves.values()))
    items = apply_filters(items, ["program_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/production-waves/<wave_id>", methods=["GET"])
@require_roles("Any")
def get_wave(wave_id: str, _user_id: str, _role: str):
    wave = _get_wave_or_404(wave_id)
    return success_object(serialize(wave))


@bp.route("/production-waves/<wave_id>/commit", methods=["POST"])
@require_roles("ProductionPlanner")
def commit_wave(wave_id: str, _user_id: str, _role: str):
    wave = _get_wave_or_404(wave_id)
    if wave["status"] != "PLANNED":
        raise_err(ERR_WAVE_INVALID_STATE, "commit requires wave PLANNED")
    program = db.programs.get(wave["program_id"])
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "commit requires program ACTIVE")
    wave["status"] = "COMMITTED"
    db.touch(wave)
    return success_object(serialize(wave))


@bp.route("/production-waves/<wave_id>/complete", methods=["POST"])
@require_roles("ProductionPlanner")
def complete_wave(wave_id: str, _user_id: str, _role: str):
    wave = _get_wave_or_404(wave_id)
    if wave["status"] not in ("COMMITTED", "IN_PRODUCTION"):
        raise_err(ERR_WAVE_INVALID_STATE, "complete requires wave COMMITTED or IN_PRODUCTION")
    wave["status"] = "COMPLETE"
    db.touch(wave)
    return success_object(serialize(wave))


@bp.route("/production-waves/<wave_id>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_wave(wave_id: str, _user_id: str, _role: str):
    wave = _get_wave_or_404(wave_id)
    if wave["status"] != "PLANNED":
        raise_err(ERR_WAVE_INVALID_STATE, "cancel requires wave PLANNED")
    wave["status"] = "CANCELLED"
    db.touch(wave)
    return success_object(serialize(wave))
