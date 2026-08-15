"""Rodeo endpoints: create, get, posture transitions (PRD 3.1)."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    cancel_rodeo_cascade,
    events_of_rodeo,
    get_or_404,
    payout_of_event,
    perfs_of_rodeo,
    ser,
    settle_rodeo_cascade,
    stamp,
    touch,
    unlock_draw_cascade,
)
from util import as_iso_dt, as_str, body, parse_dt, required

bp = Blueprint("rodeos", __name__, url_prefix="/api")

_ACTIONS = {
    "OPEN_ENTRIES",
    "LOCK_DRAW",
    "UNLOCK_DRAW",
    "START_RODEO",
    "COMPLETE_RODEO",
    "SETTLE_RODEO",
    "CANCEL_RODEO",
}

_TRANSITIONS = {
    ("DRAFT", "OPEN_ENTRIES"): "ENTRIES_OPEN",
    ("ENTRIES_OPEN", "LOCK_DRAW"): "DRAW_LOCKED",
    ("DRAW_LOCKED", "UNLOCK_DRAW"): "ENTRIES_OPEN",
    ("DRAW_LOCKED", "START_RODEO"): "IN_PROGRESS",
    ("IN_PROGRESS", "COMPLETE_RODEO"): "COMPLETED",
    ("COMPLETED", "SETTLE_RODEO"): "SETTLED",
    ("DRAFT", "CANCEL_RODEO"): "CANCELLED",
    ("ENTRIES_OPEN", "CANCEL_RODEO"): "CANCELLED",
    ("DRAW_LOCKED", "CANCEL_RODEO"): "CANCELLED",
}


@bp.post("/rodeos")
def create_rodeo():
    auth(["CommitteeAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    city = as_str(required(data, "city"), "city")
    entries_close_at = as_iso_dt(
        required(data, "entries_close_at"), "entries_close_at"
    )
    rec = {
        "id": new_id(),
        "name": name,
        "city": city,
        "entries_close_at": entries_close_at,
        "posture": "DRAFT",
        "unclaimed_purse_cents": 0,
        "_close_dt": parse_dt(entries_close_at),
    }
    stamp(rec)
    DB["rodeos"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/rodeos/<rodeo_id>")
def get_rodeo(rodeo_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("rodeos", rodeo_id)))


@bp.post("/rodeos/<rodeo_id>/transition")
def transition_rodeo(rodeo_id):
    auth(["CommitteeAdmin"])
    rodeo = get_or_404("rodeos", rodeo_id)
    data = body()
    action = as_enum_action(data.get("action"))
    target = _TRANSITIONS.get((rodeo["posture"], action))
    if target is None:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Action {action} is not valid from posture {rodeo['posture']}",
        )
    # Transition preconditions (state-machine table).
    if action == "OPEN_ENTRIES":
        if not events_of_rodeo(rodeo_id) or not perfs_of_rodeo(rodeo_id):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "OPEN_ENTRIES requires at least one event and one performance",
            )
    elif action == "START_RODEO":
        for event in events_of_rodeo(rodeo_id):
            if 1 not in event["drawn_rounds"]:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "START_RODEO requires go-round 1 drawn for every event",
                )
    elif action == "COMPLETE_RODEO":
        for perf in perfs_of_rodeo(rodeo_id):
            if perf["status"] not in ("COMPLETED", "CANCELLED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "COMPLETE_RODEO requires every performance COMPLETED or CANCELLED",
                )
        event_ids = {e["id"] for e in events_of_rodeo(rodeo_id)}
        for r in DB["run_results"].values():
            if r["rodeo_event_id"] in event_ids and r["status"] in (
                "RECORDED",
                "AMENDED",
            ):
                raise ApiError(
                    "ERR_RESULTS_PENDING",
                    409,
                    "Unverified results remain for this rodeo",
                )
    elif action == "SETTLE_RODEO":
        for event in events_of_rodeo(rodeo_id):
            payout = payout_of_event(event["id"])
            if payout is None or payout["status"] != "FINAL":
                raise ApiError(
                    "ERR_PAYOUT_NOT_FINAL",
                    409,
                    "Every event requires a FINAL payout before settlement",
                )
    # Side effects.
    if action == "UNLOCK_DRAW":
        unlock_draw_cascade(rodeo_id)
    elif action == "CANCEL_RODEO":
        cancel_rodeo_cascade(rodeo_id)
    elif action == "SETTLE_RODEO":
        settle_rodeo_cascade(rodeo)
    rodeo["posture"] = target
    touch(rodeo)
    return ok(ser(rodeo))


def as_enum_action(value):
    if value not in _ACTIONS:
        raise ApiError(
            "ERR_VALIDATION", 400, f"Field action must be one of {sorted(_ACTIONS)}"
        )
    return value
