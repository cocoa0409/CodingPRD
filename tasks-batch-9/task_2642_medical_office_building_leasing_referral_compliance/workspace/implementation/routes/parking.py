"""The building parking pool (PRD Section 3.9)."""

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import by_creation, clock_date, db, stamp_new, touch
from errors import ApiError
from lookups import get_building, get_lease, get_resource, paged
from middleware import acting_user_id, endpoint, is_portal_user, require_tenant_scope
from response import object_response
from services import calc

bp = Blueprint("parking", __name__)


@bp.post("/parking-allocations")
@endpoint("PropertyManager")
def create_allocation():
    body = v.json_body()
    building_id = v.get_string(body, "building_id")
    lease_id = v.get_string(body, "lease_id")
    category = v.get_enum(body, "category", enums.PARKING_CATEGORIES)
    stall_count = v.get_int(body, "stall_count", minimum=1)
    # Parsed during the rung-3 pass so a malformed version still outranks a
    # missing building.
    expected_building_version = v.get_int(body, "expected_building_version")

    building = get_building(building_id)
    lease = get_lease(lease_id)
    if expected_building_version != building["version"]:
        raise ApiError(
            "ERR_STALE_BUILDING_VERSION",
            "Building '%s' is at version %d." % (building["id"], building["version"]),
        )
    if lease["status"] in calc.CLOSED_LEASE_STATUSES:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' has reached %s." % (lease["id"], lease["status"]),
        )

    if stall_count > building["unallocated_stalls"]:
        raise ApiError(
            "ERR_INSUFFICIENT_UNALLOCATED_STALLS",
            "Only %d of the %d requested stalls remain unallocated."
            % (building["unallocated_stalls"], stall_count),
        )
    if category == "STAFF":
        minimum = calc.patient_reserve_minimum(building)
        staff_after = building["staff_allocated_stalls"] + stall_count
        non_staff_after = building["total_parking_stalls"] - staff_after
        if non_staff_after < minimum:
            raise ApiError(
                "ERR_PATIENT_PARKING_RESERVE_BREACH",
                "The request would leave %d non-staff stalls against a reserve "
                "minimum of %d." % (non_staff_after, minimum),
            )

    row = {
        "building_id": building["id"],
        "lease_id": lease["id"],
        "category": category,
        "stall_count": stall_count,
        "status": "ACTIVE",
        "revoked_on": None,
    }
    stamp_new(row)
    db.parking_allocations[row["id"]] = row
    calc.recompute_parking_pool(building)
    touch(building)
    return object_response(ser.parking_allocation_out(row), 201)


@bp.get("/parking-allocations")
@endpoint()
def list_allocations():
    limit, offset = v.pagination()
    building_id = v.query_string("building_id")
    lease_id = v.query_string("lease_id")
    category = v.query_enum("category", enums.PARKING_CATEGORIES)
    status = v.query_enum("status", enums.PARKING_STATUSES)

    rows = list(db.parking_allocations.values())
    if is_portal_user():
        owned = {
            l["id"] for l in db.leases.values() if l["tenant_id"] == acting_user_id()
        }
        rows = [a for a in rows if a["lease_id"] in owned]
    if building_id is not None:
        rows = [a for a in rows if a["building_id"] == building_id]
    if lease_id is not None:
        rows = [a for a in rows if a["lease_id"] == lease_id]
    if category is not None:
        rows = [a for a in rows if a["category"] == category]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paged(by_creation(rows), ser.parking_allocation_out, limit, offset)


@bp.get("/parking-allocations/<allocation_id>")
@endpoint()
def get_allocation(allocation_id):
    alloc = get_resource(db.parking_allocations, allocation_id, "Parking allocation")
    lease = db.leases[alloc["lease_id"]]
    require_tenant_scope(lease["tenant_id"])
    return object_response(ser.parking_allocation_out(alloc))


@bp.post("/parking-allocations/<allocation_id>/revoke")
@endpoint("PropertyManager")
def revoke_allocation(allocation_id):
    body = v.json_body()
    # revocation_note is accepted and optional; the allocation stores only the
    # revocation date.
    v.get_string(body, "revocation_note", required=False, allow_empty=True)

    alloc = get_resource(db.parking_allocations, allocation_id, "Parking allocation")
    if alloc["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Allocation '%s' is already %s." % (alloc["id"], alloc["status"]),
        )

    alloc["status"] = "REVOKED"
    alloc["revoked_on"] = clock_date()
    touch(alloc)
    building = db.buildings[alloc["building_id"]]
    calc.recompute_parking_pool(building)
    touch(building)
    return object_response(ser.parking_allocation_out(alloc))
