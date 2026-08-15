"""FinalistRecord endpoints: category list, notify / acknowledge / decline."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import services
import store
from auth import authenticate, authorize, forbid, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_OUTSIDE_WINDOW, ERR_EMBARGO_ACTIVE,
    ERR_REFERENTIAL_INTEGRITY,
)
from util import bump, success_object, list_response, get_or_404

bp = Blueprint("finalists", __name__)


@bp.get("/awards/categories/<cid>/finalists")
def list_finalists(cid):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    cat = get_or_404(store.categories, cid, "Category")
    season = store.seasons.get(cat["season_id"])
    if role == "Anonymous":
        # priority 23: embargo gate
        if season is not None and season["status"] in ("FINALISTS_LOCKED", "EMBARGOED"):
            lift = season.get("embargo_lifts_at")
            if lift is None or clock.now() < lift:
                raise_err(ERR_EMBARGO_ACTIVE,
                          "finalist results are embargo-protected")
    records = services.finalists_of_category(cat["id"])
    if role == "Anonymous":
        records = [f for f in records if f["embargo_visible"]]
    status = request.args.get("notification_status")
    if status:
        records = [f for f in records if f["notification_status"] == status]
    return list_response(records, services.serialize_finalist)


@bp.post("/awards/finalists/<fid>/notify")
def notify_finalist(fid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    fr = get_or_404(store.finalists, fid, "FinalistRecord")
    services.guard_transition("finalist", fr, {"PENDING"}, )
    cat = store.categories.get(fr["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    if season is None or season["status"] not in ("FINALISTS_LOCKED", "EMBARGOED"):
        raise_err(ERR_INVALID_STATE,
                  "notification requires season FINALISTS_LOCKED or EMBARGOED")
    e = store.entries.get(fr["entry_id"])
    if e is None or e["status"] != "FINALIST":
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  "finalist record references a non-FINALIST entry")
    fr["notification_status"] = "NOTIFIED"
    fr["notified_at"] = clock.now()
    bump(fr)
    return success_object(services.serialize_finalist(fr), 200)


@bp.post("/awards/finalists/<fid>/acknowledge")
def acknowledge_finalist(fid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    fr = get_or_404(store.finalists, fid, "FinalistRecord")
    services.guard_transition("finalist", fr, {"NOTIFIED"})
    e = store.entries.get(fr["entry_id"])
    if e is None or e["entrant_id"] != uid:
        forbid("only the finalist entry's entrant may acknowledge")
    cat = store.categories.get(fr["category_id"])
    season = store.seasons.get(cat["season_id"]) if cat else None
    deadline = fr["notified_at"] + timedelta(hours=season["ack_window_hours"])
    if clock.now() > deadline:
        raise_err(ERR_OUTSIDE_WINDOW,
                  "acknowledgement window (ack_window_hours) has lapsed")
    fr["notification_status"] = "ACKNOWLEDGED"
    bump(fr)
    return success_object(services.serialize_finalist(fr), 200)


@bp.post("/awards/finalists/<fid>/decline")
def decline_finalist(fid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    fr = get_or_404(store.finalists, fid, "FinalistRecord")
    services.guard_transition("finalist", fr, {"NOTIFIED"})
    e = store.entries.get(fr["entry_id"])
    if e is None or e["entrant_id"] != uid:
        forbid("only the finalist entry's entrant may decline")
    services.decline_finalist_record(fr)
    return success_object(services.serialize_finalist(fr), 200)
