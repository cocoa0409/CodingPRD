"""GuestPass endpoints: purchase, list, read, void."""
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_MEMBER_NOT_FOUND,
    ERR_GUEST_PASS_NOT_FOUND, ERR_NOT_OWNER, ERR_MEMBER_NOT_ACTIVE,
    ERR_GUEST_PASS_NOT_VOIDABLE, ERR_GUEST_PASS_MONTHLY_LIMIT,
)
from helpers import (
    get_body, req_string, req_enum, parse_date, parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("guest_passes", __name__)

PASS_STATUSES = ("ISSUED", "REDEEMED", "VOID", "EXPIRED")


@bp.route("/dog-park/guest-passes", methods=["POST"])
def purchase_pass():
    uid, role = require_auth(["Member"])
    body = get_body()
    size_class = req_enum(body, "guest_dog_size_class", ("SMALL", "LARGE"))
    valid_on = req_string(body, "valid_on")
    valid_date = parse_date(valid_on)
    if valid_date is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "valid_on must be an ISO date YYYY-MM-DD")
    sponsor = store.members.get(uid)
    if sponsor is None:
        raise ApiError(ERR_MEMBER_NOT_FOUND, 404, "Sponsoring member not found")
    if sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409,
                       "Only ACTIVE members may purchase guest passes")
    # Stage 12 quota — always last.
    if domain.guest_usage(uid) >= domain.GUEST_MONTHLY_LIMIT:
        raise ApiError(ERR_GUEST_PASS_MONTHLY_LIMIT, 409,
                       "Monthly guest-pass allotment exhausted")
    guest_pass = domain.new_entity(store.guest_passes, {
        "sponsor_member_id": uid,
        "guest_dog_size_class": size_class,
        "valid_on": valid_on,
        "fee_cents": domain.guest_pass_fee(valid_date),
        "status": "ISSUED",
    })
    return ok(domain.public(guest_pass), 201)


@bp.route("/dog-park/guest-passes", methods=["GET"])
def list_passes():
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    sponsor_filter = request.args.get("sponsor_member_id")
    # Stage 4 ownership: a Member's sponsor filter must equal their own id
    # or is auto-scoped to it.
    if role == "Member":
        if sponsor_filter is not None and sponsor_filter != uid:
            raise ApiError(ERR_NOT_OWNER, 403,
                           "Members may only list their own guest passes")
        sponsor_filter = uid
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in PASS_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter")
    valid_on_filter = request.args.get("valid_on")
    if valid_on_filter is not None and parse_date(valid_on_filter) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "valid_on filter must be an ISO date YYYY-MM-DD")
    limit, offset = parse_pagination()
    items = []
    for p in store.guest_passes.values():
        if sponsor_filter is not None and p["sponsor_member_id"] != sponsor_filter:
            continue
        if status_filter is not None and p["status"] != status_filter:
            continue
        if valid_on_filter is not None and p["valid_on"] != valid_on_filter:
            continue
        items.append(p)
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(p) for p in page], 200, meta)


@bp.route("/dog-park/guest-passes/<passId>", methods=["GET"])
def get_pass(passId):
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    guest_pass = store.guest_passes.get(passId)
    if guest_pass is None:
        raise ApiError(ERR_GUEST_PASS_NOT_FOUND, 404, "Guest pass not found")
    if role == "Member" and guest_pass["sponsor_member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only read their own guest passes")
    return ok(domain.public(guest_pass))


@bp.route("/dog-park/guest-passes/<passId>/void", methods=["POST"])
def void_pass(passId):
    require_auth(["ParkAdmin"])
    guest_pass = store.guest_passes.get(passId)
    if guest_pass is None:
        raise ApiError(ERR_GUEST_PASS_NOT_FOUND, 404, "Guest pass not found")
    if guest_pass["status"] != "ISSUED":
        raise ApiError(ERR_GUEST_PASS_NOT_VOIDABLE, 409,
                       "Only an ISSUED guest pass may be voided")
    guest_pass["status"] = "VOID"
    domain.touch(guest_pass)
    return ok(domain.public(guest_pass))
