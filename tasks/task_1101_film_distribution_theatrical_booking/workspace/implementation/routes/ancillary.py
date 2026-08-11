"""AncillaryWindow endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_ancillary_too_early,
)
from services.core import (
    serialize_ancillary_window, get_ancillary_window, get_film,
    new_entity_common, touch,
)
from services.clock import get_logical_clock
from util import parse_dt, iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("ancillary", __name__)


WINDOW_KINDS = {"HOME_VIDEO", "TVOD", "SVOD", "AIRLINE"}


@bp.route("/distributors/<did>/films/<fid>/ancillary-windows", methods=["POST"])
@require_roles("Booker")
def create_ancillary_window(did, fid, _user_id, _role):
    f = get_film(did, fid)
    body = get_json_body()
    require_fields(body, ["window_kind", "scheduled_start_utc"])
    if body["window_kind"] not in WINDOW_KINDS:
        raise err_invalid_request("window_kind must be HOME_VIDEO|TVOD|SVOD|AIRLINE")
    ss = parse_dt(body["scheduled_start_utc"])
    if ss is None:
        raise err_invalid_request("scheduled_start_utc must be ISO 8601")
    twe = parse_dt(f["theatrical_window_end"])
    if twe is None or ss < twe:
        raise err_ancillary_too_early()
    common = new_entity_common()
    w = {
        **common,
        "film_id": fid,
        "window_kind": body["window_kind"],
        "scheduled_start_utc": iso_from_dt(ss),
        "actual_start_utc": None,
        "status": "SCHEDULED",
    }
    db.ancillary_windows[w["id"]] = w
    return success_object(serialize_ancillary_window(w), 201)


@bp.route("/distributors/<did>/films/<fid>/ancillary-windows/<awid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Auditor")
def read_ancillary_window(did, fid, awid, _user_id, _role):
    return success_object(serialize_ancillary_window(get_ancillary_window(did, fid, awid)))


@bp.route("/distributors/<did>/films/<fid>/ancillary-windows", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Auditor")
def list_ancillary_windows(did, fid, _user_id, _role):
    get_film(did, fid)
    items = [w for w in db.ancillary_windows.values() if w["film_id"] == fid]
    filters = {}
    for k in ("window_kind", "status", "film_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_ancillary_window, filters)


@bp.route("/distributors/<did>/films/<fid>/ancillary-windows/<awid>/cancel", methods=["POST"])
@require_roles("Booker")
def cancel_ancillary_window(did, fid, awid, _user_id, _role):
    w = get_ancillary_window(did, fid, awid)
    if w["status"] != "SCHEDULED":
        raise err_invalid_state("AncillaryWindow must be SCHEDULED")
    ss = parse_dt(w["scheduled_start_utc"])
    now = get_logical_clock()
    if ss is not None and now >= ss:
        raise err_invalid_state("Cannot cancel after scheduled_start_utc")
    w["status"] = "CANCELLED"
    touch(w)
    return success_object(serialize_ancillary_window(w))
