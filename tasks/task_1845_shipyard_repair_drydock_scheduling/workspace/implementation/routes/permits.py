"""Permit endpoints: environmental controls with per-dock hot-work exclusivity."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_HOT_WORK_PERMIT_CONFLICT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PERMIT_WINDOW_INVALID,
)
from middleware import require_roles
from response import success_list, success_object
from services.project_ops import PERMIT_TYPES
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("permits", __name__)

READ_ROLES = ("YardAdmin", "ProjectManager", "CommercialApprover", "EnvironmentalOfficer")


def get_permit_or_404(permit_id: str) -> dict:
    permit = db.permits.get(permit_id)
    if permit is None:
        raise_err(ERR_NOT_FOUND, "Permit id does not exist")
    return permit


@bp.route("/v1/permits", methods=["POST"])
@require_roles("EnvironmentalOfficer")
def create_permit(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    project_id = require_string(body, "project_id")
    permit_type = require_enum(body, "permit_type", PERMIT_TYPES)
    valid_from = require_ts(body, "valid_from")
    valid_to = require_ts(body, "valid_to")

    # Rung 4: the project exists.
    if project_id not in db.projects:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")

    # Rung 8: the closed validity window must be strictly positive.
    if not (parse_iso8601(valid_to, "valid_to") > parse_iso8601(valid_from, "valid_from")):
        raise_err(ERR_PERMIT_WINDOW_INVALID, "valid_to must be strictly after valid_from")

    permit = {
        "project_id": project_id,
        "permit_type": permit_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "APPLIED",
    }
    db.stamp_new(permit)
    db.permits[permit["id"]] = permit
    return success_object(serialize(permit), 201)


@bp.route("/v1/permits", methods=["GET"])
@require_roles(*READ_ROLES)
def list_permits(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.permits.values()))
    items = apply_filters(items, ["project_id", "permit_type", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/permits/<permit_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_permit(permit_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_permit_or_404(permit_id)))


@bp.route("/v1/permits/<permit_id>/grant", methods=["POST"])
@require_roles("EnvironmentalOfficer")
def grant_permit(permit_id: str, _user_id: str, _role: str):
    permit = get_permit_or_404(permit_id)
    if permit["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "grant requires an APPLIED permit")
    # Rung 9: HOT_WORK grants are exclusive per dock under closed day-interval
    # semantics; touching days count as overlap.
    if permit["permit_type"] == "HOT_WORK":
        own_dock = db.projects[permit["project_id"]]["dock_id"]
        from_dt = parse_iso8601(permit["valid_from"], "valid_from")
        to_dt = parse_iso8601(permit["valid_to"], "valid_to")
        for other in db.permits.values():
            if (
                other["id"] == permit["id"]
                or other["permit_type"] != "HOT_WORK"
                or other["status"] != "GRANTED"
            ):
                continue
            other_dock = db.projects[other["project_id"]]["dock_id"]
            if other_dock != own_dock:
                continue
            other_from = parse_iso8601(other["valid_from"], "valid_from")
            other_to = parse_iso8601(other["valid_to"], "valid_to")
            if from_dt <= other_to and other_from <= to_dt:
                raise_err(
                    ERR_HOT_WORK_PERMIT_CONFLICT,
                    "another GRANTED hot-work permit overlaps this window on the same dock",
                )
    permit["status"] = "GRANTED"
    db.touch(permit)
    return success_object(serialize(permit))


@bp.route("/v1/permits/<permit_id>/suspend", methods=["POST"])
@require_roles("EnvironmentalOfficer")
def suspend_permit(permit_id: str, _user_id: str, _role: str):
    permit = get_permit_or_404(permit_id)
    if permit["status"] != "GRANTED":
        raise_err(ERR_INVALID_STATE, "suspend requires a GRANTED permit")
    permit["status"] = "SUSPENDED"
    db.touch(permit)
    return success_object(serialize(permit))


@bp.route("/v1/permits/<permit_id>/close", methods=["POST"])
@require_roles("EnvironmentalOfficer")
def close_permit(permit_id: str, _user_id: str, _role: str):
    permit = get_permit_or_404(permit_id)
    if permit["status"] not in ("APPLIED", "GRANTED", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "only an APPLIED, GRANTED, or SUSPENDED permit may be closed")
    permit["status"] = "CLOSED"
    db.touch(permit)
    return success_object(serialize(permit))
