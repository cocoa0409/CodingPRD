"""Service-bay routes (PRD §3.5).

Bay close/reopen are OCC-guarded by expected_service_bay_version. A version
mismatch surfaces ERR_STALE_VERSION (the generic OCC error, scaffold §1.4
priority 17 / PRD §2.9).
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_path_or_404,
    optional_bool,
    optional_int,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("service_bays", __name__)

BAY_STATUSES = {"OPEN", "OUT_OF_SERVICE"}
LIVE_APPT_STATES = {"SCHEDULED", "RESCHEDULE_PENDING", "CHECKED_IN"}


@bp.post("/service-bays")
def create_service_bay():
    require_auth(["InventoryManager"])()
    body = get_json_body()
    require_fields(body, ["bay_name"])
    bay_name = require_string(body["bay_name"], "bay_name")
    alignment_capable = optional_bool(body.get("alignment_capable"),
                                      "alignment_capable", False)
    turnover_buffer_min = optional_int(body.get("turnover_buffer_min"),
                                       "turnover_buffer_min", 15,
                                       min_value=0, max_value=60)

    with db.mutation_lock:
        # bay_name unique across ServiceBay -> field-level constraint.
        for b in db.service_bays.values():
            if b["bay_name"] == bay_name:
                raise APIError(ERR_INVALID_REQUEST, 422, "bay_name already in use")
        bay = {
            "bay_name": bay_name,
            "alignment_capable": alignment_capable,
            "turnover_buffer_min": turnover_buffer_min,
            "status": "OPEN",
        }
        db.stamp_common(bay)
        db.service_bays[bay["id"]] = bay
        return ok_object(bay, 201)


@bp.get("/service-bays/<bid>")
def get_service_bay(bid: str):
    require_auth(["InventoryManager", "ServiceAdvisor", "Technician"])()
    bay = lookup_path_or_404(db.service_bays, bid, "ServiceBay")
    return ok_object(bay, 200)


@bp.get("/service-bays")
def list_service_bays():
    require_auth(["InventoryManager", "ServiceAdvisor", "Technician"])()
    limit, offset = paginate_params(request.args)
    items = list(db.service_bays.values())
    if "status" in request.args:
        items = [b for b in items if b["status"] == request.args["status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/service-bays/<bid>/close")
def close_service_bay(bid: str):
    require_auth(["InventoryManager"])()
    bay = lookup_path_or_404(db.service_bays, bid, "ServiceBay")
    body = get_json_body()
    require_fields(body, ["expected_service_bay_version"])
    expected = require_int(body["expected_service_bay_version"],
                           "expected_service_bay_version")
    with db.mutation_lock:
        if bay["status"] != "OPEN":
            raise APIError(ERR_INVALID_STATE, 409, "Bay is not OPEN")
        for a in db.appointments.values():
            if a["service_bay_id"] == bay["id"] and a["status"] in LIVE_APPT_STATES:
                raise APIError(ERR_INVALID_STATE, 409,
                               "Bay has live appointments; cannot close")
        if expected != bay["version"]:
            raise APIError(ERR_STALE_VERSION, 412,
                           "expected_service_bay_version does not match")
        bay["status"] = "OUT_OF_SERVICE"
        db.bump(bay)
        return ok_object(bay, 200)


@bp.post("/service-bays/<bid>/reopen")
def reopen_service_bay(bid: str):
    require_auth(["InventoryManager"])()
    bay = lookup_path_or_404(db.service_bays, bid, "ServiceBay")
    body = get_json_body()
    require_fields(body, ["expected_service_bay_version"])
    expected = require_int(body["expected_service_bay_version"],
                           "expected_service_bay_version")
    with db.mutation_lock:
        if bay["status"] != "OUT_OF_SERVICE":
            raise APIError(ERR_INVALID_STATE, 409, "Bay is not OUT_OF_SERVICE")
        if expected != bay["version"]:
            raise APIError(ERR_STALE_VERSION, 412,
                           "expected_service_bay_version does not match")
        bay["status"] = "OPEN"
        db.bump(bay)
        return ok_object(bay, 200)
