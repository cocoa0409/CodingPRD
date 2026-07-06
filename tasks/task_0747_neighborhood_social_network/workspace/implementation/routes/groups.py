"""Group endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import DB, stamp_new
from errors import (
    NotFound,
    ReferenceNotFound,
    ResidentSuspended,
    NotVerifiedInNeighborhood,
)
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_bool


bp = Blueprint("groups", __name__)

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


@bp.post("/neighborhood/groups")
@require_roles("Resident", "Moderator")
def create_group():
    payload = request.get_json(silent=True) or {}
    creator_resident_id = as_str(payload, "creator_resident_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    name = as_str(payload, "name")
    is_private = as_bool(payload, "is_private", default=False, required=False)

    if DB.residents.get(creator_resident_id) is None:
        raise ReferenceNotFound(f"Resident {creator_resident_id} not found")
    if DB.neighborhoods.get(neighborhood_id) is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    acting = DB.residents.get(g.user_id)
    if acting is not None and acting.get("is_suspended", False):
        raise ResidentSuspended("Resident is suspended")

    if not _resident_verified_in(neighborhood_id, g.user_id):
        raise NotVerifiedInNeighborhood(
            "Acting resident is not verified in the target neighborhood"
        )

    grp = {
        "creator_resident_id": creator_resident_id,
        "neighborhood_id": neighborhood_id,
        "name": name,
        "is_private": is_private,
    }
    stamp_new(grp)
    DB.groups[grp["id"]] = grp
    return success(grp, status=201)


@bp.get("/neighborhood/groups/<gid>")
@require_roles(*ALL_ROLES)
def get_group(gid: str):
    grp = DB.groups.get(gid)
    if grp is None:
        raise NotFound(f"Group {gid} not found")
    return success(grp)


@bp.get("/neighborhood/groups")
@require_roles(*ALL_ROLES)
def list_groups():
    nid = request.args.get("neighborhood_id")
    cid = request.args.get("creator_resident_id")
    is_private = request.args.get("is_private")
    rows = list(DB.groups.values())
    if nid is not None:
        rows = [r for r in rows if r["neighborhood_id"] == nid]
    if cid is not None:
        rows = [r for r in rows if r["creator_resident_id"] == cid]
    if is_private is not None:
        want = is_private.lower() in ("1", "true", "yes")
        rows = [r for r in rows if bool(r.get("is_private")) == want]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
