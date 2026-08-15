"""Member endpoints."""
from flask import Blueprint

from db import DB, new_id, today
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import lookup, ser_booking, ser_member, sort_items, stamp, touch
from util import body, pagination_args, req_date, req_str

bp = Blueprint("members", __name__)

MEMBER_ROLES = ["MuseumAdmin", "FrontDeskStaff", "Member"]


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


@bp.post("/members")
def create_member():
    auth(["MuseumAdmin", "FrontDeskStaff"])
    data = body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    member_number = req_str(data, "member_number")
    renews_on, _ = req_date(data, "renews_on")
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "member_number": member_number,
        "renews_on": renews_on,
        "status": "ACTIVE",
    }
    stamp(rec)
    DB["members"][rec["id"]] = rec
    return ok(ser_member(rec), 201)


@bp.get("/members/<mid>")
def get_member(mid):
    user_id, role = auth(MEMBER_ROLES)
    if role == "Member" and mid != user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Members may read only their own record")
    return ok(ser_member(lookup("members", mid)))


@bp.post("/members/<mid>/renew")
def renew_member(mid):
    auth(["MuseumAdmin", "FrontDeskStaff"])
    member = lookup("members", mid)
    data = body()
    renews_on, renews_date = req_date(data, "renews_on")
    if renews_date <= today():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "renews_on must be strictly after the current date",
        )
    if member["status"] == "EXPIRED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "An EXPIRED member cannot be renewed"
        )
    member["renews_on"] = renews_on
    member["status"] = "ACTIVE"
    touch(member)
    return ok(ser_member(member))


@bp.get("/members/<mid>/bookings")
def list_member_bookings(mid):
    user_id, role = auth(MEMBER_ROLES)
    if role == "Member" and mid != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Members may read only their own bookings"
        )
    member = lookup("members", mid)
    items = sort_items(
        [b for b in DB["bookings"].values() if b["member_id"] == member["id"]]
    )
    return _paginate(items, ser_booking)
