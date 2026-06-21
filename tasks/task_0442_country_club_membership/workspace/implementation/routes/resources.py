"""Reservable resource endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import common
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import resource_out

bp = Blueprint("resources", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]
_KINDS = {"TEE_TIME", "COURT", "DINING_TABLE"}


@bp.post("/resources")
def create_resource():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "kind", "label"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    kind = common.require_enum(body, "kind", _KINDS)
    label = common.require_string(body, "label")
    turnaround = common.optional_int(body, "turnaround_minutes", 0)
    if turnaround < 0:
        raise errors.invalid_request("turnaround_minutes must be non-negative")
    seat_capacity = common.optional_int(body, "seat_capacity", 1)
    if seat_capacity < 1:
        raise errors.invalid_request("seat_capacity must be at least 1")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "kind": kind,
            "label": label,
            "turnaround_minutes": turnaround,
            "seat_capacity": seat_capacity,
        }
    )
    db.resources[rec["id"]] = rec
    return success_object(resource_out(rec), status=201)


@bp.get("/resources/<rid>")
def get_resource(rid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_resource(rid)
    return success_object(resource_out(rec), status=200)


@bp.get("/resources")
def list_resources():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    club_id = request.args.get("club_id")
    records = list(db.resources.values())
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [resource_out(r) for r in page]
    return success_array(data, limit, offset, total)
