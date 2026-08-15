"""AreaClosure endpoints: schedule, list, cancel."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_AREA_NOT_FOUND, ERR_CLOSURE_NOT_FOUND,
    ERR_CLOSURE_OVERLAP, ERR_CLOSURE_NOT_CANCELLABLE,
)
from helpers import (
    get_body, req_string, parse_datetime, parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("closures", __name__)


def _get_area_or_404(area_id):
    area = store.areas.get(area_id)
    if area is None:
        raise ApiError(ERR_AREA_NOT_FOUND, 404, "Park area not found")
    return area


@bp.route("/dog-park/areas/<areaId>/closures", methods=["POST"])
def schedule_closure(areaId):
    require_auth(["ParkAdmin"])
    body = get_body()
    starts_raw = req_string(body, "starts_at")
    ends_raw = req_string(body, "ends_at")
    starts_dt = parse_datetime(starts_raw)
    ends_dt = parse_datetime(ends_raw)
    if starts_dt is None or ends_dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "starts_at and ends_at must be ISO 8601 UTC instants")
    if ends_dt <= starts_dt:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ends_at must be strictly after starts_at")
    reason = req_string(body, "reason")
    _get_area_or_404(areaId)
    # Stage 11 temporal: no overlap with SCHEDULED/ACTIVE closures on the area;
    # half-open windows, adjacency allowed.
    for c in store.closures.values():
        if c["area_id"] != areaId or c["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if starts_dt < c["_ends_dt"] and c["_starts_dt"] < ends_dt:
            raise ApiError(ERR_CLOSURE_OVERLAP, 409,
                           "Closure window overlaps an existing closure on this area")
    closure = domain.new_entity(store.closures, {
        "area_id": areaId,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "reason": reason,
        "status": "SCHEDULED",
    })
    closure["_starts_dt"] = starts_dt
    closure["_ends_dt"] = ends_dt
    return ok(domain.public(closure), 201)


@bp.route("/dog-park/areas/<areaId>/closures", methods=["GET"])
def list_closures(areaId):
    require_auth(["Member", "Steward", "ParkAdmin"])
    limit, offset = parse_pagination()
    _get_area_or_404(areaId)
    items = [c for c in store.closures.values() if c["area_id"] == areaId]
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(c) for c in page], 200, meta)


@bp.route("/dog-park/closures/<closureId>/cancel", methods=["POST"])
def cancel_closure(closureId):
    require_auth(["ParkAdmin"])
    closure = store.closures.get(closureId)
    if closure is None:
        raise ApiError(ERR_CLOSURE_NOT_FOUND, 404, "Closure not found")
    if closure["status"] != "SCHEDULED":
        raise ApiError(ERR_CLOSURE_NOT_CANCELLABLE, 409,
                       "Only a SCHEDULED closure may be cancelled")
    closure["status"] = "CANCELLED"
    domain.touch(closure)
    return ok(domain.public(closure))
