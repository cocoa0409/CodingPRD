"""Business endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    LocationOutsideGeofence,
    NotVerifiedInNeighborhood,
    InvalidState,
)
from geo import point_inside
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_number


bp = Blueprint("businesses", __name__)

ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


@bp.post("/neighborhood/businesses")
@require_roles("Resident", "PlatformAdmin")
def create_business():
    payload = request.get_json(silent=True) or {}
    owner_resident_id = as_str(payload, "owner_resident_id")
    name = as_str(payload, "name")
    address_line = as_str(payload, "address_line")
    business_lat = as_number(payload, "business_lat")
    business_lng = as_number(payload, "business_lng")
    primary_neighborhood_id = as_str(payload, "primary_neighborhood_id")

    owner = DB.residents.get(owner_resident_id)
    if owner is None:
        raise ReferenceNotFound(f"Resident {owner_resident_id} not found")
    n = DB.neighborhoods.get(primary_neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {primary_neighborhood_id} not found")

    # Verified-in-neighborhood (priority 100) — applies to the acting Resident (only)
    if g.user_role == "Resident":
        if not _resident_verified_in(primary_neighborhood_id, g.user_id):
            raise NotVerifiedInNeighborhood(
                "Acting resident is not verified in the target neighborhood"
            )

    # Geofence (priority 151)
    if not point_inside(n, business_lat, business_lng):
        raise LocationOutsideGeofence("business coordinates outside neighborhood geofence")

    b = {
        "owner_resident_id": owner_resident_id,
        "name": name,
        "address_line": address_line,
        "business_lat": business_lat,
        "business_lng": business_lng,
        "primary_neighborhood_id": primary_neighborhood_id,
        "recommendation_count": 0,
        "state": "CLAIMED",
    }
    stamp_new(b)
    DB.businesses[b["id"]] = b
    return success(b, status=201)


@bp.get("/neighborhood/businesses/<bid>")
@require_roles(*ALL_ROLES)
def get_business(bid: str):
    b = DB.businesses.get(bid)
    if b is None:
        raise NotFound(f"Business {bid} not found")
    return success(b)


@bp.get("/neighborhood/businesses")
@require_roles(*ALL_ROLES)
def list_businesses():
    pnid = request.args.get("primary_neighborhood_id")
    oid = request.args.get("owner_resident_id")
    state = request.args.get("state")
    rows = list(DB.businesses.values())
    if pnid is not None:
        rows = [b for b in rows if b["primary_neighborhood_id"] == pnid]
    if oid is not None:
        rows = [b for b in rows if b["owner_resident_id"] == oid]
    if state is not None:
        rows = [b for b in rows if b["state"] == state]
    rows.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/businesses/<bid>/verify")
@require_roles("PlatformAdmin")
def verify_business(bid: str):
    b = DB.businesses.get(bid)
    if b is None:
        raise NotFound(f"Business {bid} not found")
    if b["state"] != "CLAIMED":
        raise InvalidState(f"Business.state is {b['state']}, expected CLAIMED")
    b["state"] = "VERIFIED_BUSINESS"
    bump(b)
    return success(b)
