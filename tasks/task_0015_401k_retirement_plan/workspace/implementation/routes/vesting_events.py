"""VestingEvent — immutable append-only audit row."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from middleware import auth_required
from response import success_array, success_object
from services.clock_and_age import parse_iso
from services.entities import serialize_vesting_event, stamp_create
from services.validators import require_dict, require_int, require_str


bp = Blueprint("vesting_events", __name__)


def _get_ve_or_404(vid: str) -> dict:
    v = db.vesting_events.get(vid)
    if not v:
        raise APIError(ERR_NOT_FOUND, 404, f"VestingEvent '{vid}' not found")
    return v


@bp.post("/vesting-events")
@auth_required("PlanAdmin")
def create_vesting_event():
    body = require_dict(request.get_json(silent=True))
    participant_id = require_str(body, "participant_id")
    as_of_date = require_str(body, "as_of_date")
    yos_after = require_int(body, "years_of_service_after", minimum=0)
    pct_after = require_int(body, "vested_pct_bps_after", minimum=0, maximum=10_000)

    try:
        parse_iso(as_of_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "as_of_date must be ISO 8601")

    with db.LOCK:
        if participant_id not in db.participants:
            raise APIError(ERR_NOT_FOUND, 404, f"Participant '{participant_id}' not found")
        v = stamp_create(
            {
                "participant_id": participant_id,
                "as_of_date": as_of_date,
                "years_of_service_after": yos_after,
                "vested_pct_bps_after": pct_after,
            },
            immutable=True,
        )
        db.vesting_events[v["id"]] = v
    return success_object(serialize_vesting_event(v), status=201)


@bp.get("/vesting-events/<vid>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_vesting_event(vid: str):
    v = _get_ve_or_404(vid)
    if g.user_role == "Participant" and g.user_id != v["participant_id"]:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own vesting events")
    return success_object(serialize_vesting_event(v))


@bp.get("/vesting-events")
@auth_required("PlanAdmin", "Custodian", "Participant")
def list_vesting_events():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    participant_filter = request.args.get("participant_id")

    with db.LOCK:
        items = list(db.vesting_events.values())
    if participant_filter is not None:
        items = [v for v in items if v["participant_id"] == participant_filter]
    if g.user_role == "Participant":
        items = [v for v in items if v["participant_id"] == g.user_id]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_vesting_event(v) for v in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )
