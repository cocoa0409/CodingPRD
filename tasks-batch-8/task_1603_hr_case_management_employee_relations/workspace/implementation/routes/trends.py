"""Trend snapshots by manager/location with dual window variants (PRD §3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_SCOPE_NOT_FOUND, ERR_TREND_HEADCOUNT_ZERO,
)
from middleware import authorize
from response import success_object
from services import calculations as calc
from services.core import (
    new_record, touch, require_path, list_response, serialize_snapshot,
    get_bool_filter,
)
from util import CLOCK, fmt_dt
from validate import Payload

bp = Blueprint("trends", __name__)

SCOPE_TYPES = {"MANAGER", "LOCATION"}
WINDOW_KINDS = {"ROLLING_90D", "CALENDAR_QUARTER"}
READ_ROLES = {"HRAnalyst", "ERManager", "LegalCounsel"}


@bp.post("/er/trend-snapshots")
def compute_snapshot():
    authorize({"HRAnalyst", "ERManager"})
    p = Payload(request.get_json(silent=True))
    scope_type = p.get_enum("scope_type", SCOPE_TYPES, required=True)
    scope_key = p.get_str("scope_key", required=True)
    window_kind = p.get_enum("window_kind", WINDOW_KINDS, required=True)

    # priority 21 — scope resolution, ahead of any headcount concern
    if scope_type == "MANAGER" and scope_key is not None:
        if db["employees"].get(scope_key) is None:
            raise_error(ERR_SCOPE_NOT_FOUND,
                        f"no employee with id {scope_key} for MANAGER scope")
    elif scope_type == "LOCATION" and scope_key is not None:
        if not any(e["location_code"] == scope_key
                   for e in db["employees"].values()):
            raise_error(ERR_SCOPE_NOT_FOUND,
                        f"no employee carries location_code {scope_key}")

    as_of = CLOCK.now()
    closed_count = substantiated = headcount = 0
    if scope_type is not None and scope_key is not None \
            and window_kind is not None:
        closed_count, substantiated, headcount = calc.compute_trend_figures(
            scope_type, scope_key, window_kind, as_of)

        # priority 22 — zero headcount is an error only when there are closed
        # cases to explain
        if headcount == 0 and closed_count > 0:
            raise_error(ERR_TREND_HEADCOUNT_ZERO,
                        "headcount in scope is zero while closed cases exist "
                        "in the window")

    # priority 24
    p.raise_if_errors()

    rate = 0.0 if headcount == 0 else calc.trend_rate(closed_count, headcount)

    # supersede the prior snapshot with the identical (scope_type, scope_key,
    # window_kind) triple
    for snap in db["trend_snapshots"].values():
        if (snap["scope_type"], snap["scope_key"], snap["window_kind"]) == \
                (scope_type, scope_key, window_kind) and not snap["is_stale"]:
            snap["is_stale"] = True
            touch(snap)

    rec = new_record()
    rec.update({
        "scope_type": scope_type,
        "scope_key": scope_key,
        "window_kind": window_kind,
        "as_of": fmt_dt(as_of),
        "_as_of_dt": as_of,
        "closed_case_count": closed_count,
        "substantiated_count": substantiated,
        "case_rate_per_100": rate,
        "is_stale": False,
    })
    db["trend_snapshots"][rec["id"]] = rec
    return success_object(serialize_snapshot(rec), status=201)


@bp.get("/er/trend-snapshots")
def list_snapshots():
    authorize(READ_ROLES)
    items = list(db["trend_snapshots"].values())
    for field in ("scope_type", "scope_key", "window_kind"):
        v = request.args.get(field)
        if v is not None:
            items = [s for s in items if s.get(field) == v]
    stale_filter = get_bool_filter("is_stale")
    if stale_filter is not None:
        items = [s for s in items if s["is_stale"] == stale_filter]
    return list_response(items, serialize_snapshot)


@bp.get("/er/trend-snapshots/<sid>")
def get_snapshot(sid):
    authorize(READ_ROLES)
    rec = require_path("trend_snapshots", sid)
    return success_object(serialize_snapshot(rec))
