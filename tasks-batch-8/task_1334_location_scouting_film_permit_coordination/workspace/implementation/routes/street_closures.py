"""StreetClosure endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, parse_datetime,
    make_entity, touch, get_production, get_scoped,
    list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("street_closures", __name__)


@bp.route("/productions/<pid>/street-closures", methods=["POST"])
def create_street_closure(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["permit_application_id", "street_segment", "closure_start", "closure_end"])
    pa_id = require_str(payload, "permit_application_id")
    pa = store.permit_applications.get(pa_id)
    if not pa or pa.get("production_id") != pid:
        raise ApiError(ERR_NOT_FOUND, "PermitApplication not found", 404)
    entity = make_entity({
        "production_id": pid,
        "permit_application_id": pa_id,
        "street_segment": require_str(payload, "street_segment"),
        "closure_start": require_str(payload, "closure_start"),
        "closure_end": require_str(payload, "closure_end"),
        "status": "REQUESTED",
    })
    store.street_closures[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/street-closures", methods=["GET"])
def list_street_closures(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("permit_application_id", "street_segment", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.street_closures, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/street-closures/<rid>/approve", methods=["POST"])
def approve_street_closure(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    sc = get_scoped(store.street_closures, rid, pid, "StreetClosure")
    if sc["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, "StreetClosure is not REQUESTED", 409)
    # Backing permit must be ISSUED
    pa = store.permit_applications.get(sc["permit_application_id"])
    if not pa or pa["status"] != "ISSUED":
        raise ApiError(ERR_PERMIT_NOT_ISSUED, "Backing permit is not ISSUED", 422)
    # Overlap check: half-open [closure_start, closure_end) on same street_segment
    new_start = parse_datetime(sc["closure_start"])
    new_end = parse_datetime(sc["closure_end"])
    for other in store.street_closures.values():
        if (other["id"] != sc["id"]
                and other.get("street_segment") == sc["street_segment"]
                and other["status"] in ("APPROVED", "ACTIVE")):
            o_start = parse_datetime(other["closure_start"])
            o_end = parse_datetime(other["closure_end"])
            # Half-open interval overlap: [a,b) intersects [c,d) iff a < d and c < b
            if new_start < o_end and o_start < new_end:
                raise ApiError(ERR_CLOSURE_OVERLAP, "Street closure overlap on segment", 409)
    sc["status"] = "APPROVED"
    touch(sc)
    return success_object(sc)


@bp.route("/productions/<pid>/street-closures/<rid>/cancel", methods=["POST"])
def cancel_street_closure(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    sc = get_scoped(store.street_closures, rid, pid, "StreetClosure")
    if sc["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, "Can only cancel REQUESTED or APPROVED closures", 409)
    sc["status"] = "CANCELLED"
    touch(sc)
    return success_object(sc)
