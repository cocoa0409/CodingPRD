"""Moratorium routes and active-window helper (PRD §3.11)."""
from flask import Blueprint

import clock
import db
import middleware
from response import object_response, array_response
from services.common import (
    get_json_body, require_str, require_datetime, public,
    parse_pagination, paginate, parse_datetime,
)

bp = Blueprint("moratoriums", __name__)


def _is_active(rec, at_dt):
    """active is true exactly when at_dt is in [window_start, window_end)."""
    start = parse_datetime(rec["window_start"])
    end = parse_datetime(rec["window_end"])
    return start <= at_dt < end


def moratorium_covers(at_dt):
    """True if any declared moratorium's window covers the instant at_dt
    (PRD §3.11)."""
    for m in db.moratoriums.values():
        if _is_active(m, at_dt):
            return True
    return False


def _public(rec):
    out = public(rec)
    # active is derived against the current server clock (PRD §3.11).
    out["active"] = _is_active(rec, clock.now())
    return out


@bp.post("/moratoriums")
def create():
    middleware.require_role({"AssistanceCaseworker", "BillingClerk"})
    body = get_json_body()

    label = require_str(body, "label")
    require_datetime(body, "window_start")
    require_datetime(body, "window_end")

    rec = db.make_record({
        "label": label,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
    })
    db.moratoriums[rec["id"]] = rec
    return object_response(_public(rec), 201)


@bp.get("/moratoriums")
def list_all():
    middleware.require_role({"FieldOps", "BillingClerk", "AssistanceCaseworker", "Customer"})
    limit, offset = parse_pagination()

    records = list(db.moratoriums.values())
    window, total = paginate(records, limit, offset)
    return array_response([_public(m) for m in window], limit, offset, total, 200)
