"""ServiceConversion endpoints: two parallel state dimensions (work + temp
service) on one resource."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_PANEL_CAPACITY_INADEQUATE,
    ERR_SEGMENT_NOT_BACKFILLED,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import conversion_view
from util import (
    get_json_body,
    get_or_404,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    require_string,
    sort_created,
)

bp = Blueprint("conversions", __name__, url_prefix="/api/service-conversions")

CC = "ConversionContractor"
ANY = "Any"

WORK_TARGETS = {"ROUGH_IN", "PANEL_SET", "READY_TO_ENERGIZE", "ENERGIZED",
                "INSPECTED", "COMPLETE"}
TEMP_TARGETS = {"TEMP_INSTALLED", "TEMP_ACTIVE", "TEMP_REMOVED"}
OUTCOMES = {"PASS", "FAIL"}


@bp.route("", methods=["POST"])
@require_roles(CC)
def create_conversion(_user_id: str, _role: str):
    body = get_json_body()
    # Existence left to right: parcel_id, then project_id.
    if body.get("parcel_id") is not None:
        get_or_404(db.parcels, body["parcel_id"], "Parcel")
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    parcel_id = require_string(body, "parcel_id")
    project_id = require_string(body, "project_id")
    parcel = db.parcels[parcel_id]
    if parcel["project_id"] != project_id:
        raise_err(ERR_VALIDATION,
                  "project_id must equal the parcel's project_id")

    conversion = stamp_new({
        "parcel_id": parcel_id,
        "project_id": project_id,
        "work_status": "PLANNED",
        "temp_service_status": "NONE",
        "panel_capacity_amps": None,
        "last_inspection_outcome": None,
        "energized_on": None,
    })
    db.conversions[conversion["id"]] = conversion
    return success_object(conversion_view(conversion), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_conversions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.conversions.values())
    project_id = query_arg("project_id")
    parcel_id = query_arg("parcel_id")
    work_status = query_arg("work_status")
    if project_id:
        items = [c for c in items if c["project_id"] == project_id]
    if parcel_id:
        items = [c for c in items if c["parcel_id"] == parcel_id]
    if work_status:
        items = [c for c in items if c["work_status"] == work_status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([conversion_view(c) for c in page], limit, offset, total)


@bp.route("/<cid>", methods=["GET"])
@require_roles(ANY)
def get_conversion(cid: str, _user_id: str, _role: str):
    return success_object(conversion_view(get_or_404(db.conversions, cid,
                                                     "ServiceConversion")))


def _ceil_125(load_amps: int) -> int:
    """ceil(load_calc_amps * 1.25) in exact integer arithmetic."""
    return (load_amps * 5 + 3) // 4


@bp.route("/<cid>/work-transition", methods=["POST"])
@require_roles(CC)
def work_transition(cid: str, _user_id: str, _role: str):
    conversion = get_or_404(db.conversions, cid, "ServiceConversion")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in WORK_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(WORK_TARGETS)}")

    current = conversion["work_status"]

    # Target-specific payload validation (structural, before state checks).
    panel_capacity = None
    outcome = None
    if to == "PANEL_SET":
        from util import require_int as _require_int
        panel_capacity = _require_int(body, "panel_capacity_amps", minimum=1)
    if to == "INSPECTED":
        outcome = body.get("outcome")
        if outcome != "PASS":
            raise_err(ERR_VALIDATION, "INSPECTED requires outcome PASS")
    if to == "ROUGH_IN" and current == "ENERGIZED":
        outcome = body.get("outcome")
        if outcome != "FAIL":
            raise_err(ERR_VALIDATION, "rework cycle requires outcome FAIL")
    if "outcome" in body and body["outcome"] is not None \
            and not isinstance(body["outcome"], str):
        raise_err(ERR_VALIDATION, "outcome must be a string")

    if current == "COMPLETE":
        raise_err(ERR_INVALID_STATE, "conversion work axis is terminal (COMPLETE)")

    if to == "ROUGH_IN":
        if current == "PLANNED":
            project = db.projects[conversion["project_id"]]
            if project["status"] not in {"TRENCHING", "CONVERTING"}:
                raise_err(ERR_INVALID_STATE,
                          "rough-in requires project TRENCHING|CONVERTING")
            conversion["work_status"] = "ROUGH_IN"
        elif current == "ENERGIZED":
            # rework cycle on failed inspection
            conversion["work_status"] = "ROUGH_IN"
            conversion["last_inspection_outcome"] = "FAIL"
            conversion["panel_capacity_amps"] = None
        else:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> ROUGH_IN")

    elif to == "PANEL_SET":
        if current != "ROUGH_IN":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PANEL_SET")
        parcel = db.parcels[conversion["parcel_id"]]
        if panel_capacity < _ceil_125(parcel["load_calc_amps"]):
            raise_err(ERR_PANEL_CAPACITY_INADEQUATE,
                      f"panel_capacity_amps must be >= "
                      f"ceil(load_calc_amps * 1.25) = {_ceil_125(parcel['load_calc_amps'])}")
        conversion["panel_capacity_amps"] = panel_capacity
        conversion["work_status"] = "PANEL_SET"

    elif to == "READY_TO_ENERGIZE":
        if current != "PANEL_SET":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> READY_TO_ENERGIZE")
        conversion["work_status"] = "READY_TO_ENERGIZE"

    elif to == "ENERGIZED":
        if current != "READY_TO_ENERGIZE":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> ENERGIZED")
        containing = [s for s in db.segments.values()
                      if conversion["parcel_id"] in (s.get("parcel_ids") or [])]
        if not any(s["status"] in {"BACKFILLED", "CLOSED"} for s in containing):
            raise_err(ERR_SEGMENT_NOT_BACKFILLED,
                      "the parcel's trench segment must be BACKFILLED|CLOSED")
        from services import domain as _domain
        conversion["energized_on"] = _domain.clock_str()
        conversion["work_status"] = "ENERGIZED"

    elif to == "INSPECTED":
        if current != "ENERGIZED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INSPECTED")
        conversion["last_inspection_outcome"] = "PASS"
        conversion["work_status"] = "INSPECTED"

    elif to == "COMPLETE":
        if current != "INSPECTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> COMPLETE")
        if conversion["temp_service_status"] not in {"NONE", "TEMP_REMOVED"}:
            raise_err(ERR_INVALID_STATE,
                      "completion requires temp service NONE|TEMP_REMOVED")
        conversion["work_status"] = "COMPLETE"

    touch(conversion)
    return success_object(conversion_view(conversion))


_TEMP_FLOW = {
    ("NONE", "TEMP_INSTALLED"),
    ("TEMP_INSTALLED", "TEMP_ACTIVE"),
    ("TEMP_ACTIVE", "TEMP_REMOVED"),
}


@bp.route("/<cid>/temp-service-transition", methods=["POST"])
@require_roles(CC)
def temp_service_transition(cid: str, _user_id: str, _role: str):
    conversion = get_or_404(db.conversions, cid, "ServiceConversion")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TEMP_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TEMP_TARGETS)}")
    current = conversion["temp_service_status"]
    if (current, to) not in _TEMP_FLOW:
        raise_err(ERR_INVALID_STATE, f"cannot move temp service {current} -> {to}")
    if to == "TEMP_REMOVED" and conversion["work_status"] not in {"ENERGIZED", "INSPECTED"}:
        raise_err(ERR_INVALID_STATE,
                  "temp removal requires work ENERGIZED|INSPECTED")
    conversion["temp_service_status"] = to
    touch(conversion)
    return success_object(conversion_view(conversion))
