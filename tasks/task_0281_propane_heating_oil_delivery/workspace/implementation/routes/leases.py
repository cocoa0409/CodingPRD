"""TankLease endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
import errors
from clock import parse_iso
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_iso_datetime)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L

bp = Blueprint("leases", __name__)


def _owner_account_id_of_tank(tank):
    return tank["account_id"]


@bp.post("/tanks/<tank_id>/leases")
def create_lease(tank_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    tank = L.get_tank(tank_id)
    body = get_json_body()

    monthly_rent = require_int(body, "monthly_rent_cents", minimum=0)
    lease_start = require_iso_datetime(body, "lease_start")
    lease_end = require_iso_datetime(body, "lease_end")
    start_dt = parse_iso(lease_start)
    end_dt = parse_iso(lease_end)
    if not (end_dt > start_dt):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "lease_end must be after lease_start")

    # Overlap check vs other ACTIVE leases on the same tank (half-open intervals).
    for other in L.leases_for_tank(tank_id):
        if other["status"] != "ACTIVE":
            continue
        o_start = parse_iso(other["lease_start"])
        o_end = parse_iso(other["lease_end"])
        # Half-open [start, end) overlap: start < o_end AND o_start < end.
        if start_dt < o_end and o_start < end_dt:
            raise errors.ApiError(errors.ERR_LEASE_PERIOD_OVERLAP, 409,
                                  "Lease period overlaps an active lease")

    rec = {
        "tank_id": tank["id"],
        "monthly_rent_cents": monthly_rent,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "status": "ACTIVE",
    }
    db.stamp_create_full(rec)
    db.tank_leases[rec["id"]] = rec
    return object_response(L.serialize_lease(rec), 201)


@bp.get("/tank-leases/<lease_id>")
def get_lease(lease_id):
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Customer"})
    rec = L.get_lease(lease_id)
    tank = db.tanks.get(rec["tank_id"])
    if tank is not None:
        check_owner(role, user_id, tank["account_id"])
    return object_response(L.serialize_lease(rec), 200)


@bp.get("/tank-leases")
def list_leases():
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Customer"})
    limit, offset = parse_pagination()
    tank_id = request.args.get("tank_id")
    status = request.args.get("status")

    items = list(db.tank_leases.values())
    if role == "Customer":
        owned = {t["id"] for t in L.tanks_for_account(user_id)}
        items = [le for le in items if le.get("tank_id") in owned]
    if tank_id is not None:
        items = [le for le in items if le.get("tank_id") == tank_id]
    if status is not None:
        items = [le for le in items if le.get("status") == status]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_lease(le) for le in page], limit, offset, total)


@bp.post("/tanks/<tank_id>/leases/<lease_id>/terminate")
def terminate_lease(tank_id, lease_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    tank = L.get_tank(tank_id)
    lease = L.get_lease(lease_id)
    if lease["tank_id"] != tank["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Lease not under tank")
    if lease["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Lease is not ACTIVE")
    lease["status"] = "TERMINATED"
    db.touch(lease)
    return object_response(L.serialize_lease(lease), 200)
