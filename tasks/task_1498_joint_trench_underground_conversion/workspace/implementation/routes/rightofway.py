"""Parcel, Easement, and Permit endpoints (right-of-way group)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import raise_err, ERR_VALIDATION, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import parcel_view, easement_view, permit_view
from util import (
    get_json_body,
    get_or_404,
    parse_iso8601,
    parse_pagination,
    paginate,
    query_arg,
    require_enum,
    require_field,
    require_int,
    require_string,
    require_ts,
    sort_created,
)

parcels_bp = Blueprint("parcels", __name__, url_prefix="/api/parcels")
easements_bp = Blueprint("easements", __name__, url_prefix="/api/easements")
permits_bp = Blueprint("permits", __name__, url_prefix="/api/permits")

PM = "ProgramManager"
ROW = "RightOfWayAgent"
ANY = "Any"

EASEMENT_TYPES = {"TRENCH", "ACCESS", "ANCHOR"}
EASEMENT_TARGETS = {"REQUESTED", "SIGNED", "RECORDED", "REFUSED"}
PERMIT_TYPES = {"ENCROACHMENT", "TRAFFIC_CONTROL", "GRADING"}
PERMIT_TARGETS = {"SUBMITTED", "ISSUED", "REVOKED", "CLOSED"}


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------

@parcels_bp.route("", methods=["POST"])
@require_roles(ROW, PM)
def create_parcel(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    address = require_string(body, "address")
    owner_name = require_string(body, "owner_name")
    existing_panel_amps = require_int(body, "existing_panel_amps", minimum=1)
    load_calc_amps = require_int(body, "load_calc_amps", minimum=1)

    parcel = stamp_new({
        "project_id": project_id,
        "address": address,
        "owner_name": owner_name,
        "existing_panel_amps": existing_panel_amps,
        "load_calc_amps": load_calc_amps,
    })
    db.parcels[parcel["id"]] = parcel
    return success_object(parcel_view(parcel), 201)


@parcels_bp.route("", methods=["GET"])
@require_roles(ANY)
def list_parcels(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.parcels.values())
    project_id = query_arg("project_id")
    if project_id:
        items = [p for p in items if p["project_id"] == project_id]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([parcel_view(p) for p in page], limit, offset, total)


@parcels_bp.route("/<pid>", methods=["GET"])
@require_roles(ANY)
def get_parcel(pid: str, _user_id: str, _role: str):
    return success_object(parcel_view(get_or_404(db.parcels, pid, "Parcel")))


# ---------------------------------------------------------------------------
# Easements
# ---------------------------------------------------------------------------

@easements_bp.route("", methods=["POST"])
@require_roles(ROW)
def create_easement(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("parcel_id") is not None:
        get_or_404(db.parcels, body["parcel_id"], "Parcel")
    parcel_id = require_string(body, "parcel_id")
    easement_type = require_enum(body, "easement_type", EASEMENT_TYPES)

    easement = stamp_new({
        "parcel_id": parcel_id,
        "easement_type": easement_type,
        "status": "DRAFT",
        "requested_on": None,
        "signed_on": None,
        "recorded_on": None,
    })
    db.easements[easement["id"]] = easement
    return success_object(easement_view(easement), 201)


@easements_bp.route("", methods=["GET"])
@require_roles(ANY)
def list_easements(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.easements.values())
    parcel_id = query_arg("parcel_id")
    status = query_arg("status")
    if parcel_id:
        items = [e for e in items if e["parcel_id"] == parcel_id]
    if status:
        items = [e for e in items if e["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([easement_view(e) for e in page], limit, offset, total)


@easements_bp.route("/<eid>", methods=["GET"])
@require_roles(ANY)
def get_easement(eid: str, _user_id: str, _role: str):
    return success_object(easement_view(get_or_404(db.easements, eid, "Easement")))


_EASEMENT_FLOW = {
    ("DRAFT", "REQUESTED"),
    ("REQUESTED", "SIGNED"),
    ("SIGNED", "RECORDED"),
    ("REQUESTED", "REFUSED"),
    ("REFUSED", "REQUESTED"),  # renegotiation cycle
}


@easements_bp.route("/<eid>/transition", methods=["POST"])
@require_roles(ROW)
def transition_easement(eid: str, _user_id: str, _role: str):
    easement = get_or_404(db.easements, eid, "Easement")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in EASEMENT_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(EASEMENT_TARGETS)}")
    current = easement["status"]
    if current == "RECORDED":
        raise_err(ERR_INVALID_STATE, "easement is terminal (RECORDED)")
    if (current, to) not in _EASEMENT_FLOW:
        raise_err(ERR_INVALID_STATE, f"cannot move {current} -> {to}")

    if to == "REQUESTED":
        easement["requested_on"] = domain.clock_str()  # refreshed on renegotiation
    elif to == "SIGNED":
        easement["signed_on"] = domain.clock_str()
    elif to == "RECORDED":
        easement["recorded_on"] = domain.clock_str()
    easement["status"] = to
    touch(easement)
    # REFUSED / RECORDED / re-REQUESTED recompute project posture — derived at read.
    return success_object(easement_view(easement))


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------

@permits_bp.route("", methods=["POST"])
@require_roles(ROW)
def create_permit(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    permit_type = require_enum(body, "permit_type", PERMIT_TYPES)
    valid_from = require_ts(body, "valid_from")
    valid_to = require_ts(body, "valid_to")
    if parse_iso8601(valid_from) >= parse_iso8601(valid_to):
        raise_err(ERR_VALIDATION, "valid_to must be after valid_from")

    permit = stamp_new({
        "project_id": project_id,
        "permit_type": permit_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "APPLICATION",
    })
    db.permits[permit["id"]] = permit
    return success_object(permit_view(permit), 201)


@permits_bp.route("", methods=["GET"])
@require_roles(ANY)
def list_permits(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.permits.values())
    project_id = query_arg("project_id")
    permit_type = query_arg("permit_type")
    status = query_arg("status")
    if project_id:
        items = [p for p in items if p["project_id"] == project_id]
    if permit_type:
        items = [p for p in items if p["permit_type"] == permit_type]
    for p in items:
        domain.refresh_permit(p)
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([permit_view(p) for p in page], limit, offset, total)


@permits_bp.route("/<pid>", methods=["GET"])
@require_roles(ANY)
def get_permit(pid: str, _user_id: str, _role: str):
    return success_object(permit_view(get_or_404(db.permits, pid, "Permit")))


@permits_bp.route("/<pid>/transition", methods=["POST"])
@require_roles(ROW)
def transition_permit(pid: str, _user_id: str, _role: str):
    permit = get_or_404(db.permits, pid, "Permit")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in PERMIT_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(PERMIT_TARGETS)}")

    domain.refresh_permit(permit)  # a transition references the permit
    current = permit["status"]
    if current in {"EXPIRED", "REVOKED", "CLOSED"}:
        raise_err(ERR_INVALID_STATE, f"permit is terminal ({current})")

    if to == "SUBMITTED":
        if current != "APPLICATION":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> SUBMITTED")
        permit["status"] = "SUBMITTED"
    elif to == "ISSUED":
        if current != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> ISSUED")
        permit["status"] = "ISSUED"
    elif to == "REVOKED":
        if current != "ISSUED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> REVOKED")
        permit["status"] = "REVOKED"
        # posture recompute is derived at read
    elif to == "CLOSED":
        if current != "ISSUED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> CLOSED")
        project = db.projects[permit["project_id"]]
        if project["status"] != "CLOSED":
            raise_err(ERR_INVALID_STATE,
                      "permit close requires the project to be CLOSED")
        permit["status"] = "CLOSED"

    touch(permit)
    return success_object(permit_view(permit))
