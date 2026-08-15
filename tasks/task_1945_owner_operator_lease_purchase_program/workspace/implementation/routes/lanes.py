"""LaneAssignment routes."""

from flask import Blueprint, request

import errors
import middleware
from db import db
from response import success
from services.core import base_entity, touch, LANE_MIN_COMMITMENT_CENTS
from services.serialize import serialize_lane
from util import get_body, req_str, req_int, req_dt, parse_pagination, paginate

bp = Blueprint("lanes", __name__)


def _get_lane_or_404(lane_id):
    lane = db.lane_assignments.get(lane_id)
    if lane is None:
        raise errors.err(errors.ERR_LANE_NOT_FOUND, "LaneAssignment not found", 404)
    return lane


@bp.post("/lane-assignments")
def create_lane():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    lease_id = req_str(body, "lease_id")
    origin = req_str(body, "origin")
    destination = req_str(body, "destination")
    weekly_commitment_cents = req_int(body, "weekly_commitment_cents")
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")

    if lease_id not in db.lease_agreements:
        raise errors.err(errors.ERR_LEASE_NOT_FOUND, "LeaseAgreement not found", 404)
    if end_date <= start_date:
        raise errors.err(errors.ERR_INVALID_DATE_RANGE, "end_date must be after start_date", 400)

    lane = base_entity()
    lane.update({
        "lease_id": lease_id,
        "origin": origin,
        "destination": destination,
        "weekly_commitment_cents": weekly_commitment_cents,
        "_start_date": start_date,
        "_end_date": end_date,
        "status": "OFFERED",
    })
    db.lane_assignments[lane["id"]] = lane
    return success(serialize_lane(lane), "object", 201)


@bp.get("/lane-assignments")
def list_lanes():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.lane_assignments.values())
    lease_filter = request.args.get("lease_id")
    status_filter = request.args.get("status")
    if lease_filter is not None:
        items = [l for l in items if l["lease_id"] == lease_filter]
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_lane(l) for l in page], "array", 200, pagination=pg)


@bp.get("/lane-assignments/<lane_id>")
def get_lane(lane_id):
    middleware.require_roles(middleware.ALL_ROLES)
    return success(serialize_lane(_get_lane_or_404(lane_id)), "object", 200)


@bp.post("/lane-assignments/<lane_id>/accept")
def accept_lane(lane_id):
    user_id, _ = middleware.require_roles({"Driver"})
    lane = _get_lane_or_404(lane_id)
    if lane["status"] != "OFFERED":
        raise errors.err(errors.ERR_LANE_NOT_OFFERED, "Lane is not OFFERED", 409)
    lease = db.lease_agreements[lane["lease_id"]]
    middleware.check_ownership(user_id, lease["owner_operator_id"])
    if lease["status"] not in ("ACTIVE", "DEFAULTED"):
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease must be ACTIVE or DEFAULTED", 409)
    for other in db.lane_assignments.values():
        if (
            other["id"] != lane["id"]
            and other["lease_id"] == lane["lease_id"]
            and other["status"] == "ACCEPTED"
            and lane["_start_date"] < other["_end_date"]
            and other["_start_date"] < lane["_end_date"]
        ):
            raise errors.err(
                errors.ERR_LANE_WINDOW_OVERLAP,
                "Window overlaps an ACCEPTED lane of the same lease",
                409,
            )
    if lane["weekly_commitment_cents"] < LANE_MIN_COMMITMENT_CENTS:
        raise errors.err(
            errors.ERR_LANE_COMMITMENT_BELOW_MIN,
            "weekly_commitment_cents must be >= 50000",
            422,
        )
    lane["status"] = "ACCEPTED"
    touch(lane)
    return success(serialize_lane(lane), "object", 200)


@bp.post("/lane-assignments/<lane_id>/decline")
def decline_lane(lane_id):
    user_id, _ = middleware.require_roles({"Driver"})
    lane = _get_lane_or_404(lane_id)
    if lane["status"] != "OFFERED":
        raise errors.err(errors.ERR_LANE_NOT_OFFERED, "Lane is not OFFERED", 409)
    lease = db.lease_agreements[lane["lease_id"]]
    middleware.check_ownership(user_id, lease["owner_operator_id"])
    lane["status"] = "DECLINED"
    touch(lane)
    return success(serialize_lane(lane), "object", 200)


@bp.post("/lane-assignments/<lane_id>/revoke")
def revoke_lane(lane_id):
    middleware.require_roles({"LeaseAdmin"})
    lane = _get_lane_or_404(lane_id)
    if lane["status"] != "ACCEPTED":
        raise errors.err(errors.ERR_LANE_NOT_ACCEPTED, "Lane is not ACCEPTED", 409)
    lane["status"] = "REVOKED"
    touch(lane)
    return success(serialize_lane(lane), "object", 200)
