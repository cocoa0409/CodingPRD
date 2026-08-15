"""Club setup and nested club collections (PRD 3.1)."""

from flask import Blueprint, request

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        new_common_fields)
from validation import (get_body, as_str, pagination_params, paginate,
                        sort_by_creation)
from errors import ApiError, ERR_INVALID_REQUEST
from services.serialize import (club_view, member_view, volunteer_view,
                                meeting_view, treasury_transaction_view)

bp = Blueprint("clubs", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]


@bp.post("/clubs")
def create_club():
    role, user_id = authenticate(["ProgramAdmin"])
    resolve_caller(role, user_id)
    body = get_body()
    name = as_str(body, "name")
    county_code = as_str(body, "county_code")
    if len(county_code) != 2:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'county_code': must be a two-letter county code")
    # Club names are unique within their county code (PRD 3.1).
    for existing in db.table("clubs").values():
        if existing["name"] == name and existing["county_code"] == county_code:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "A club named '%s' already exists in county '%s'"
                           % (name, county_code))
    rec = new_common_fields()
    rec.update({
        "name": name,
        "county_code": county_code,
        "treasury_balance_cents": 0,
        "star_nomination_count": 0,
        "status": "ACTIVE",
    })
    db.table("clubs")[rec["id"]] = rec
    return response.success(club_view(rec), status=201)


@bp.get("/clubs")
def list_clubs():
    role, user_id = authenticate(ALL_ROLES)
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = list(db.table("clubs").values())
    county = request.args.get("county_code")
    if county is not None:
        items = [c for c in items if c["county_code"] == county]
    items = sort_by_creation(items)
    page, meta = paginate(items, limit, offset)
    return response.success([club_view(c) for c in page],
                            response_type="array", pagination=meta)


@bp.get("/clubs/<cid>")
def get_club(cid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("clubs", cid, "Club")
    resolve_caller(role, user_id)
    return response.success(club_view(rec))


@bp.get("/clubs/<cid>/members")
def list_club_members(cid):
    role, user_id = authenticate(ALL_ROLES)
    club = must_find("clubs", cid, "Club")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [m for m in db.table("members").values() if m["club_id"] == club["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([member_view(m) for m in page],
                            response_type="array", pagination=meta)


@bp.get("/clubs/<cid>/volunteers")
def list_club_volunteers(cid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    club = must_find("clubs", cid, "Club")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [v for v in db.table("volunteers").values() if v["club_id"] == club["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([volunteer_view(v) for v in page],
                            response_type="array", pagination=meta)


@bp.get("/clubs/<cid>/meetings")
def list_club_meetings(cid):
    role, user_id = authenticate(ALL_ROLES)
    club = must_find("clubs", cid, "Club")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [m for m in db.table("meetings").values() if m["club_id"] == club["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([meeting_view(m) for m in page],
                            response_type="array", pagination=meta)


@bp.get("/clubs/<cid>/treasury-transactions")
def list_club_treasury_transactions(cid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    club = must_find("clubs", cid, "Club")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [t for t in db.table("treasury_transactions").values()
         if t["club_id"] == club["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([treasury_transaction_view(t) for t in page],
                            response_type="array", pagination=meta)
