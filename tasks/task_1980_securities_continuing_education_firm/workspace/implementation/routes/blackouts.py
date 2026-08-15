"""Training blackout windows: create / list / get."""

from flask import Blueprint

from db import store, base_record
from errors import ApiError, ERR_WINDOW_INVALID
from middleware import require_roles, json_body, require_fields
from response import success, paginate
from services import get_or_404, by_seq
from util import require_str, parse_dt, view

bp = Blueprint("blackouts", __name__)

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


@bp.post("/blackout-windows")
@require_roles("ComplianceOfficer")
def create_blackout():
    body = json_body()
    require_fields(body, "label", "start_at", "end_at")
    label = require_str(body["label"], "label")
    start_at = parse_dt(body["start_at"], "start_at")
    end_at = parse_dt(body["end_at"], "end_at")
    if not end_at > start_at:
        raise ApiError(ERR_WINDOW_INVALID, 400,
                       "end_at must be strictly later than start_at")
    rec = base_record()
    rec.update({
        "label": label,
        "start_at": start_at,
        "end_at": end_at,
    })
    store.blackouts[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/blackout-windows")
@require_roles(*ANY)
def list_blackouts():
    items = sorted(by_seq(store.blackouts.values()),
                   key=lambda b: (b["created_at"], b["_seq"]))
    page, pagination = paginate(items)
    return success([view(b) for b in page], is_list=True, pagination=pagination)


@bp.get("/blackout-windows/<windowId>")
@require_roles(*ANY)
def get_blackout(windowId):
    rec = get_or_404(store.blackouts, windowId, "TrainingBlackoutWindow")
    return success(view(rec))
