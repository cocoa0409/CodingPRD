"""TrenchSegment endpoints: create/list/get, schedule (OCC), state transitions
with easement and permit gates (incl. the BACKFILLED -> EXCAVATING reopen cycle)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import (
    raise_err,
    ERR_VALIDATION,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_CHANGE_ORDER_FREEZE,
    ERR_EASEMENT_REFUSED_BLOCKING,
    ERR_EASEMENT_NOT_RECORDED,
    ERR_PERMIT_NOT_ISSUED,
    ERR_PERMIT_WINDOW_VIOLATION,
    ERR_RESTORATION_OPEN_BLOCKING,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import segment_view
from util import (
    get_json_body,
    get_or_404,
    parse_iso8601,
    parse_pagination,
    paginate,
    query_arg,
    require_field,
    require_id_array,
    require_int,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("segments", __name__, url_prefix="/api/trench-segments")

PM = "ProgramManager"
ANY = "Any"

TRANSITION_TARGETS = {"EXCAVATING", "BACKFILLING", "BACKFILLED", "CLOSED"}


@bp.route("", methods=["POST"])
@require_roles(PM)
def create_segment(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    segment_code = require_string(body, "segment_code")
    length_ft = require_int(body, "length_ft", minimum=1)
    max_depth_inches = require_int(body, "max_depth_inches", minimum=1)
    parcel_ids = require_id_array(body, "parcel_ids", default=[])
    for parcel_id in parcel_ids:
        get_or_404(db.parcels, parcel_id, "Parcel")

    segment = stamp_new({
        "project_id": project_id,
        "segment_code": segment_code,
        "length_ft": length_ft,
        "max_depth_inches": max_depth_inches,
        "parcel_ids": list(parcel_ids),
        "excavation_start_on": None,
        "excavation_end_on": None,
        "status": "PLANNED",
    })
    db.segments[segment["id"]] = segment
    return success_object(segment_view(segment), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_segments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.segments.values())
    project_id = query_arg("project_id")
    status = query_arg("status")
    parcel_id = query_arg("parcel_ids")
    if project_id:
        items = [s for s in items if s["project_id"] == project_id]
    if status:
        items = [s for s in items if s["status"] == status]
    if parcel_id:
        items = [s for s in items if parcel_id in (s.get("parcel_ids") or [])]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([segment_view(s) for s in page], limit, offset, total)


@bp.route("/<sid>", methods=["GET"])
@require_roles(ANY)
def get_segment(sid: str, _user_id: str, _role: str):
    return success_object(segment_view(get_or_404(db.segments, sid, "TrenchSegment")))


@bp.route("/<sid>/schedule", methods=["POST"])
@require_roles(PM)
def schedule_segment(sid: str, _user_id: str, _role: str):
    segment = get_or_404(db.segments, sid, "TrenchSegment")
    body = get_json_body()
    start = require_ts(body, "excavation_start_on")
    end = require_ts(body, "excavation_end_on")
    expected = require_int(body, "expected_trench_segment_version")
    if parse_iso8601(start) >= parse_iso8601(end):
        raise_err(ERR_VALIDATION, "excavation_start_on must be before excavation_end_on")
    if expected != segment["version"]:
        raise_err(ERR_STALE_VERSION,
                  f"expected_trench_segment_version {expected} != current "
                  f"{segment['version']}")
    if segment["status"] not in {"PLANNED", "SCHEDULED"}:
        raise_err(ERR_INVALID_STATE,
                  f"cannot schedule a segment in {segment['status']}")
    project = db.projects[segment["project_id"]]
    if project["status"] not in {"MOBILIZED", "TRENCHING"}:
        raise_err(ERR_INVALID_STATE,
                  "scheduling requires project MOBILIZED|TRENCHING")
    if domain.is_segment_frozen(segment):
        raise_err(ERR_CHANGE_ORDER_FREEZE,
                  "segment is frozen by an APPROVED change order")
    segment["excavation_start_on"] = start
    segment["excavation_end_on"] = end
    segment["status"] = "SCHEDULED"
    touch(segment)
    return success_object(segment_view(segment))


def _check_excavation_gates(segment: dict) -> None:
    """Easement + permit gates shared by SCHEDULED->EXCAVATING and the
    BACKFILLED->EXCAVATING reopen cycle."""
    project = db.projects[segment["project_id"]]
    if project["status"] != "TRENCHING":
        raise_err(ERR_INVALID_STATE, "excavation requires project TRENCHING")
    if domain.is_segment_frozen(segment):
        raise_err(ERR_CHANGE_ORDER_FREEZE,
                  "segment is frozen by an APPROVED change order")
    for parcel_id in (segment.get("parcel_ids") or []):
        trench_easements = [e for e in db.easements.values()
                            if e["parcel_id"] == parcel_id
                            and e["easement_type"] == "TRENCH"]
        if any(e["status"] == "REFUSED" for e in trench_easements):
            raise_err(ERR_EASEMENT_REFUSED_BLOCKING,
                      "a TRENCH easement on a segment parcel is REFUSED")
    for parcel_id in (segment.get("parcel_ids") or []):
        trench_easements = [e for e in db.easements.values()
                            if e["parcel_id"] == parcel_id
                            and e["easement_type"] == "TRENCH"]
        if not any(e["status"] == "RECORDED" for e in trench_easements):
            raise_err(ERR_EASEMENT_NOT_RECORDED,
                      "every parcel on the segment needs a RECORDED TRENCH easement")
    permits = [p for p in db.permits.values()
               if p["project_id"] == segment["project_id"]
               and p["permit_type"] == "ENCROACHMENT"]
    for p in permits:
        domain.refresh_permit(p)
    issued = [p for p in permits if p["status"] == "ISSUED"]
    if not issued:
        raise_err(ERR_PERMIT_NOT_ISSUED,
                  "no ISSUED ENCROACHMENT permit exists for the project")
    start_dt = parse_iso8601(segment["excavation_start_on"])
    end_dt = parse_iso8601(segment["excavation_end_on"])
    if not any(parse_iso8601(p["valid_from"]) <= start_dt
               and parse_iso8601(p["valid_to"]) >= end_dt for p in issued):
        raise_err(ERR_PERMIT_WINDOW_VIOLATION,
                  "permit validity window does not cover the excavation window")


@bp.route("/<sid>/transition", methods=["POST"])
@require_roles(PM)
def transition_segment(sid: str, _user_id: str, _role: str):
    segment = get_or_404(db.segments, sid, "TrenchSegment")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    current = segment["status"]
    if current == "CLOSED":
        raise_err(ERR_INVALID_STATE, "segment is terminal (CLOSED)")

    if to == "EXCAVATING":
        if current not in {"SCHEDULED", "BACKFILLED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> EXCAVATING")
        _check_excavation_gates(segment)
        segment["status"] = "EXCAVATING"

    elif to == "BACKFILLING":
        if current != "EXCAVATING":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> BACKFILLING")
        if domain.is_segment_frozen(segment):
            raise_err(ERR_CHANGE_ORDER_FREEZE,
                      "segment is frozen by an APPROVED change order")
        for s in domain.segment_slots(sid):
            if s["status"] not in {"INSTALLED", "VERIFIED", "RELEASED"}:
                raise_err(ERR_INVALID_STATE,
                          "every occupancy slot must be INSTALLED|VERIFIED|RELEASED")
        segment["status"] = "BACKFILLING"

    elif to == "BACKFILLED":
        if current != "BACKFILLING":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> BACKFILLED")
        if domain.is_segment_frozen(segment):
            raise_err(ERR_CHANGE_ORDER_FREEZE,
                      "segment is frozen by an APPROVED change order")
        segment["status"] = "BACKFILLED"

    elif to == "CLOSED":
        if current != "BACKFILLED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> CLOSED")
        if domain.is_segment_frozen(segment):
            raise_err(ERR_CHANGE_ORDER_FREEZE,
                      "segment is frozen by an APPROVED change order")
        for t in db.restoration_tasks.values():
            if t["trench_segment_id"] == sid and t["status"] != "ACCEPTED":
                raise_err(ERR_RESTORATION_OPEN_BLOCKING,
                          "every restoration task of the segment must be ACCEPTED")
        segment["status"] = "CLOSED"

    touch(segment)
    return success_object(segment_view(segment))
