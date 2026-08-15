"""SterilizationTurn routes."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body
from response import success_object, success_list, parse_pagination
from services import core
from services.core import DECON_MIN_MINUTES, MAX_REWORKS

bp = Blueprint("turns", __name__)


def _get_turn_or_404(turn_id):
    t = db.turns.get(turn_id)
    if t is None:
        raise_err("ERR_TURN_NOT_FOUND", "Sterilization turn not found")
    return t


def _request_for_tray(tray):
    return db.requests.get(tray["request_id"]) if tray else None


@bp.post("/trays/<id>/turns")
def create_turn(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["SterileProcessingTech"])

    tray = db.trays.get(id)
    if tray is None:
        raise_err("ERR_TRAY_NOT_FOUND", "Tray not found")

    if tray["status"] != "CHECKED_IN":
        raise_err("ERR_TRAY_INVALID_STATE", "Tray must be CHECKED_IN to open a sterilization turn")

    prior = [t for t in db.turns.values() if t["tray_id"] == id]
    turn = {
        "tray_id": id,
        "sterilizer_unit_id": None,
        "attempt_number": 1 + len(prior),
        "status": "DECONTAMINATING",
        "decon_started_at": db.fmt_ts(db.now_dt()),
        "cycle_started_at": None,
        "cycle_completed_at": None,
        "released_at": None,
    }
    core.stamp_new(turn)
    db.turns[turn["id"]] = turn

    tray["status"] = "PROCESSING"
    core.recompute_tray_projection(tray)
    core.touch(tray)
    request = _request_for_tray(tray)
    if request is not None:
        core.recompute_readiness(request)

    return success_object(core.serialize(turn), status=201)


@bp.get("/turns")
def list_turns():
    get_auth()
    tray_id = flask_request.args.get("tray_id")
    sterilizer_unit_id = flask_request.args.get("sterilizer_unit_id")
    status = flask_request.args.get("status")
    items = sorted(db.turns.values(), key=lambda t: t["_seq"])
    if tray_id:
        items = [t for t in items if t["tray_id"] == tray_id]
    if sterilizer_unit_id:
        items = [t for t in items if t["sterilizer_unit_id"] == sterilizer_unit_id]
    if status:
        items = [t for t in items if t["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(t) for t in page], limit, offset, total)


@bp.get("/turns/<id>")
def get_turn(id):
    get_auth()
    turn = _get_turn_or_404(id)
    return success_object(core.serialize(turn))


@bp.post("/turns/<id>/start-cycle")
def start_cycle(id):
    _, role = get_auth()
    body = get_body(required=True)

    sterilizer_unit_id = body.get("sterilizer_unit_id")
    if not isinstance(sterilizer_unit_id, str) or not sterilizer_unit_id:
        raise_err("ERR_VALIDATION", "sterilizer_unit_id is required")

    require_role(role, ["SterileProcessingTech"])
    turn = _get_turn_or_404(id)

    if sterilizer_unit_id not in db.sterilizer_units:
        raise_err("ERR_STERILIZER_NOT_FOUND", "Sterilizer unit not found")
    unit = db.sterilizer_units[sterilizer_unit_id]

    if turn["status"] != "DECONTAMINATING":
        raise_err("ERR_TURN_INVALID_STATE", "Turn must be DECONTAMINATING to start the cycle")

    # Decon minimum.
    decon_started = db.parse_dt(turn["decon_started_at"])
    if db.now_dt() < decon_started + timedelta(minutes=DECON_MIN_MINUTES):
        raise_err("ERR_DECON_MIN_NOT_ELAPSED", "Decontamination minimum has not elapsed")

    # Slot capacity: count of turns currently STERILIZING on this unit.
    in_flight = sum(
        1
        for t in db.turns.values()
        if t["sterilizer_unit_id"] == sterilizer_unit_id and t["status"] == "STERILIZING"
    )
    if in_flight >= unit["slot_capacity"]:
        raise_err("ERR_STERILIZER_CAPACITY_EXCEEDED", "Sterilizer unit has no free slot")

    now = db.now_dt()
    turn["sterilizer_unit_id"] = sterilizer_unit_id
    turn["cycle_started_at"] = db.fmt_ts(now)
    turn["status"] = "STERILIZING"
    core.touch(turn)

    tray = db.trays.get(turn["tray_id"])
    if tray is not None:
        tray["projected_sterile_ready_at"] = db.fmt_ts(
            now + timedelta(minutes=unit["cycle_minutes"] + unit["cooldown_minutes"])
        )
        core.touch(tray)
        request = _request_for_tray(tray)
        if request is not None:
            core.recompute_readiness(request)

    return success_object(core.serialize(turn))


@bp.post("/turns/<id>/release")
def release_turn(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["SterileProcessingTech"])
    turn = _get_turn_or_404(id)

    if turn["status"] != "COOLDOWN":
        raise_err("ERR_TURN_INVALID_STATE", "Turn must be in COOLDOWN to release")

    unit = db.sterilizer_units.get(turn["sterilizer_unit_id"])
    cycle_completed = db.parse_dt(turn["cycle_completed_at"])
    if db.now_dt() < cycle_completed + timedelta(minutes=unit["cooldown_minutes"]):
        raise_err("ERR_COOLDOWN_NOT_ELAPSED", "Cooldown has not elapsed")

    now = db.now_dt()
    turn["released_at"] = db.fmt_ts(now)
    turn["status"] = "RELEASED"
    core.touch(turn)

    tray = db.trays.get(turn["tray_id"])
    if tray is not None:
        tray["status"] = "STERILE_READY"
        tray["projected_sterile_ready_at"] = None
        core.touch(tray)
        request = _request_for_tray(tray)
        if request is not None:
            core.recompute_readiness(request)

    return success_object(core.serialize(turn))


@bp.post("/turns/<id>/fail-qa")
def fail_qa(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["SterileProcessingTech"])
    turn = _get_turn_or_404(id)

    if turn["status"] not in {"STERILIZING", "COOLDOWN"}:
        raise_err("ERR_TURN_INVALID_STATE", "QA failure requires a turn in STERILIZING or COOLDOWN")

    turn["status"] = "FAILED_QA"
    core.touch(turn)

    tray = db.trays.get(turn["tray_id"])
    if tray is not None:
        tray["rework_count"] = tray.get("rework_count", 0) + 1
        request = _request_for_tray(tray)
        if tray["rework_count"] <= MAX_REWORKS:
            # Rework loop: tray returns to CHECKED_IN and needs a fresh turn.
            tray["status"] = "CHECKED_IN"
            core.recompute_tray_projection(tray)
            core.touch(tray)
            if request is not None:
                core.recompute_readiness(request)
        else:
            # Third QA failure: quarantine + escalation.
            tray["status"] = "QUARANTINED"
            core.recompute_tray_projection(tray)
            core.touch(tray)
            if request is not None:
                core.create_escalation(request["id"], "STERILIZATION_DELAY", linked_tray_id=tray["id"])
                core.recompute_readiness(request)

    return success_object(core.serialize(turn))
