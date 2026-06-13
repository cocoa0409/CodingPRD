from flask import Blueprint

from db import store
from errors import err
from middleware import require
from response import success
from services.common import base_record, touch, require_str, require_body
from services import serialize

bp = Blueprint("schedules", __name__)


def _validate_tiers(tiers):
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise err("ERR_INVALID_SCHEDULE", "tiers must be a non-empty array")
    cleaned = []
    prev_age = None
    for idx, t in enumerate(tiers):
        if not isinstance(t, dict):
            raise err("ERR_INVALID_SCHEDULE", "each tier must be an object")
        age = t.get("min_age_days")
        disc = t.get("discount_pct")
        if isinstance(age, bool) or not isinstance(age, int):
            raise err("ERR_INVALID_SCHEDULE", "min_age_days must be an integer")
        if not isinstance(disc, (int, float)) or isinstance(disc, bool):
            raise err("ERR_INVALID_SCHEDULE", "discount_pct must be a number")
        if idx == 0 and age != 0:
            raise err("ERR_INVALID_SCHEDULE", "first tier min_age_days must be 0")
        if prev_age is not None and age <= prev_age:
            raise err("ERR_INVALID_SCHEDULE", "min_age_days must be strictly increasing")
        if not (0 <= disc < 1):
            raise err("ERR_INVALID_SCHEDULE", "discount_pct must be in [0,1)")
        prev_age = age
        cleaned.append({"min_age_days": age, "discount_pct": disc})
    return cleaned


@bp.post("/markdown-schedules")
@require("StoreAdmin")
def create_schedule():
    body = require_body()
    name = require_str(body, "name")

    if "base_floor_pct" in body and body["base_floor_pct"] is not None:
        bf = body["base_floor_pct"]
        if isinstance(bf, bool) or not isinstance(bf, (int, float)):
            raise err("ERR_INVALID_REQUEST", "base_floor_pct must be a number")
        if not (0 < bf <= 1):
            raise err("ERR_INVALID_REQUEST", "base_floor_pct must be in (0,1]")
        base_floor_pct = bf
    else:
        base_floor_pct = 0.30

    if "tiers" not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: tiers")
    tiers = _validate_tiers(body["tiers"])

    rec = base_record()
    rec.update({
        "name": name,
        "base_floor_pct": base_floor_pct,
        "tiers": tiers,
        "is_archived": False,
    })
    store.markdown_schedules[rec["id"]] = rec
    return success(serialize.schedule_out(rec), 201)


@bp.get("/markdown-schedules/<sid>")
@require("StoreAdmin", "SettlementManager", "IntakeGrader")
def get_schedule(sid):
    s = store.markdown_schedules.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Schedule not found")
    return success(serialize.schedule_out(s), 200)


@bp.post("/markdown-schedules/<sid>/archive")
@require("StoreAdmin")
def archive_schedule(sid):
    s = store.markdown_schedules.get(sid)
    if s is None:
        raise err("ERR_NOT_FOUND", "Schedule not found")
    s["is_archived"] = True
    touch(s)
    return success(serialize.schedule_out(s), 200)
