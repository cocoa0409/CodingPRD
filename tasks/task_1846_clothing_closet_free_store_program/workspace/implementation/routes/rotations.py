"""Seasonal rotation: schedule, execute (phase-out then phase-in), cancel.

PRD 3.8 / scaffold seasonal_rotation_moves.
"""
from flask import Blueprint

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok
from util import get_body, v_dt, v_enum

bp = Blueprint("rotations", __name__)

TARGET_SEASONS = {"WINTER", "SUMMER"}


def get_rotation_or_404(rid):
    r = store.rotations.get(rid)
    if r is None:
        raise not_found("Seasonal rotation not found")
    return r


@bp.post("/closet/seasonal-rotations")
@require_roles("ProgramAdmin")
def create_rotation():
    data = get_body()
    target = v_enum(data, "target_season", TARGET_SEASONS)
    window_start = v_dt(data, "window_start")
    window_end = v_dt(data, "window_end")
    if not window_end > window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "window_end must be after window_start"
        )
    r = stamp_new({
        "target_season": target,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "executed_at": None,
        "moved_out_count": 0,
        "moved_in_count": 0,
    })
    store.rotations[r["id"]] = r
    return ok(svc.serialize_rotation(r), 201)


@bp.get("/closet/seasonal-rotations/<rid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_rotation(rid):
    return ok(svc.serialize_rotation(get_rotation_or_404(rid)))


@bp.post("/closet/seasonal-rotations/<rid>/execute")
@require_roles("ProgramAdmin")
def execute_rotation(rid):
    r = get_rotation_or_404(rid)
    if r["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED rotation can be executed")
    now = db.now()
    if not (r["window_start"] <= now <= r["window_end"]):
        raise ApiError(
            "ERR_ROTATION_OUTSIDE_WINDOW", 409,
            "Rotation can only execute inside [window_start, window_end]",
        )
    target = r["target_season"]

    # Phase-out: STOCKED items whose season is neither the target nor
    # ALL_SEASON move to OFF_SEASON, with per-item zone cascades.
    moved_out = 0
    phased_out = sorted(
        (
            i for i in store.items.values()
            if i["status"] == "STOCKED"
            and i["season"] not in (target, "ALL_SEASON")
        ),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    for item in phased_out:
        zone = store.zones.get(item["storage_zone_id"])
        item["status"] = "OFF_SEASON"
        item["storage_zone_id"] = None
        touch(item)
        if zone is not None:
            zone["current_stock"] -= 1
            touch(zone)
        moved_out += 1

    # Phase-in: OFF_SEASON items of the target season, oldest first, into the
    # least-stocked eligible non-FULL zone (ties: zone creation time asc).
    moved_in = 0
    candidates = sorted(
        (
            i for i in store.items.values()
            if i["status"] == "OFF_SEASON" and i["season"] == target
        ),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    for item in candidates:
        eligible = [
            z for z in store.zones.values()
            if z["season_policy"] in (target, "ALL_SEASON")
            and svc.zone_posture(z) != "FULL"
        ]
        eligible.sort(key=lambda z: (z["current_stock"], z["created_at"], z["_seq"]))
        if not eligible:
            continue  # empty placement pool: item stays OFF_SEASON, no error
        zone = eligible[0]
        item["status"] = "STOCKED"
        item["storage_zone_id"] = zone["id"]
        item["stocked_at"] = now
        touch(item)
        zone["current_stock"] += 1
        touch(zone)
        moved_in += 1

    r["status"] = "COMPLETED"
    r["executed_at"] = now
    r["moved_out_count"] = moved_out
    r["moved_in_count"] = moved_in
    touch(r)
    return ok(svc.serialize_rotation(r))


@bp.post("/closet/seasonal-rotations/<rid>/cancel")
@require_roles("ProgramAdmin")
def cancel_rotation(rid):
    r = get_rotation_or_404(rid)
    if r["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED rotation can be cancelled")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(svc.serialize_rotation(r))
