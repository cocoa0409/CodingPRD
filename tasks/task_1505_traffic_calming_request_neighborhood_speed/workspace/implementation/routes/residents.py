"""Residents (PRD §3.1) and per-resident signature/vote history listings."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from envelope import object_response
from errors import ApiError, ERR_DUPLICATE_RESIDENT_EMAIL, ERR_DUPLICATE_HOUSEHOLD
from helpers import get_resident, get_segment, paginated
from store import store
from validate import parse_body, Struct

bp = Blueprint("residents", __name__)


@bp.post("/api/residents")
@require_roles("CityAdmin")
def create_resident():
    data, perr = parse_body()
    s = Struct(data, perr)
    full_name = s.get_str("full_name")
    email = s.get_str("email")
    segment_id = s.get_str("street_segment_id")
    household_ref = s.get_str("household_ref")
    # Tier 3: body-level FK existence (PRD §2.9/§2.10)
    if segment_id is not None:
        get_segment(segment_id)
    # Tier 8: structural first
    s.raise_if_errors()
    # Tier 8 conflicts, PRD §3.1 order: email, then household within segment
    for r in store.residents.values():
        if r["email"] == email:
            raise ApiError(409, ERR_DUPLICATE_RESIDENT_EMAIL,
                           "email already registered")
    for r in store.residents.values():
        if r["street_segment_id"] == segment_id and r["household_ref"] == household_ref:
            raise ApiError(409, ERR_DUPLICATE_HOUSEHOLD,
                           "household_ref already registered on this segment")
    resident = {
        "id": store.new_id(),
        "full_name": full_name,
        "email": email,
        "street_segment_id": segment_id,
        "household_ref": household_ref,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.residents[resident["id"]] = resident
    return object_response(resident, 201)


@bp.get("/api/residents/<residentId>")
@require_roles(*ALL_ROLES)
def get_one(residentId):
    return object_response(get_resident(residentId))


@bp.get("/api/residents")
@require_roles(*ALL_ROLES)
def list_residents():
    return paginated(list(store.residents.values()),
                     {"street_segment_id": request.args.get("street_segment_id")})


@bp.get("/api/residents/<rid>/petition-signatures")
@require_roles(*ALL_ROLES)
def list_signatures_by_resident(rid):
    get_resident(rid)
    items = [s for s in store.signatures.values() if s["resident_id"] == rid]
    return paginated(items)


@bp.get("/api/residents/<rid>/ballot-votes")
@require_roles(*ALL_ROLES)
def list_votes_by_resident(rid):
    get_resident(rid)
    items = [v for v in store.votes.values() if v["resident_id"] == rid]
    return paginated(items)
