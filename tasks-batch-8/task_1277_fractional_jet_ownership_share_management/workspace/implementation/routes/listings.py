"""Transfer listing endpoints: create, accept, close-sale, withdraw (PRD 3.8)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import listing_view, new_common, share_view, touch
from util import as_bool, as_int, body, paginate_sorted, required

bp = Blueprint("listings", __name__)


def _get_listing(tid):
    t = db.transfer_listings.get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", 404, "Transfer listing not found")
    return t


def _program_of_share(share):
    cls = db.aircraft_classes[share["class_id"]]
    return db.programs[cls["program_id"]]


@bp.route("/transfer-listings", methods=["POST"])
def create_listing():
    user_id, role = require_roles("Owner")
    data = body()
    share_id = data.get("share_id")
    if not isinstance(share_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "share_id must be a string")
    share = db.shares.get(share_id)
    if not share:
        raise ApiError("ERR_NOT_FOUND", 404, "Share not found")
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may list it")
    asking = as_int(required(data, "asking_price_cents"), "asking_price_cents")
    if asking <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "asking_price_cents must be > 0")
    repurchase = data.get("program_repurchase_flag", False)
    as_bool(repurchase, "program_repurchase_flag")
    expected = as_int(
        required(data, "expected_share_version"), "expected_share_version"
    )

    # Stage 5: posture gate
    program = _program_of_share(share)
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks listing creation")
    # Stage 9: referential — share must be ACTIVE with no live listing.
    if share["share_status"] != "ACTIVE":
        raise ApiError("ERR_REFERENTIAL_CONFLICT", 409,
                       "Share must be ACTIVE to be listed")
    live = any(
        t["share_id"] == share_id
        and t["listing_status"] in ("LISTED", "UNDER_OFFER")
        for t in db.transfer_listings.values()
    )
    if live:
        raise ApiError("ERR_REFERENTIAL_CONFLICT", 409,
                       "Share already has a live transfer listing")
    # Stage 12: OCC
    if expected != share["version"]:
        raise ApiError("ERR_STALE_SHARE_VERSION", 412,
                       "Share version has advanced since last observation")

    rec = new_common()
    rec.update({
        "share_id": share_id,
        "asking_price_cents": asking,
        "listing_status": "LISTED",
        "buyer_owner_id": None,
        "program_repurchase_flag": repurchase,
    })
    db.transfer_listings[rec["id"]] = rec
    share["share_status"] = "LISTED"
    touch(share)
    return ok(listing_view(rec), status=201)


@bp.route("/transfer-listings/<tid>", methods=["GET"])
def get_listing(tid):
    require_roles(*ALL_ROLES)
    return ok(listing_view(_get_listing(tid)))


@bp.route("/transfer-listings", methods=["GET"])
def list_listings():
    require_roles(*ALL_ROLES)
    share_id = request.args.get("share_id")
    status = request.args.get("listing_status")
    buyer = request.args.get("buyer_owner_id")
    items = list(db.transfer_listings.values())
    if share_id is not None:
        items = [t for t in items if t["share_id"] == share_id]
    if status is not None:
        items = [t for t in items if t["listing_status"] == status]
    if buyer is not None:
        items = [t for t in items if t["buyer_owner_id"] == buyer]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([listing_view(t) for t in page], total, limit, offset)


@bp.route("/transfer-listings/<tid>/accept", methods=["POST"])
def accept_listing(tid):
    user_id, role = require_roles("Owner")
    t = _get_listing(tid)
    share = db.shares[t["share_id"]]
    data = body()
    buyer_id = data.get("buyer_owner_id")
    if not isinstance(buyer_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "buyer_owner_id must be a string")
    buyer = db.owners.get(buyer_id)
    if not buyer:
        raise ApiError("ERR_NOT_FOUND", 404, "Buyer owner not found")
    if buyer_id != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "X-User-ID must match buyer_owner_id")
    expected = as_int(
        required(data, "expected_listing_version"), "expected_listing_version"
    )

    # Stage 4: state
    if t["listing_status"] in ("SOLD", "WITHDRAWN", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Listing is already {t['listing_status']}")
    if t["listing_status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Listing must be LISTED to accept")
    # Stage 5: posture
    program = _program_of_share(share)
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks listing acceptance")
    # Self-dealing
    if buyer_id == share["owner_id"]:
        raise ApiError("ERR_SELF_DEALING", 422,
                       "Buyer may not be the share's current owner")
    # Stage 6: buyer standing
    if buyer["owner_standing"] != "GOOD":
        raise ApiError("ERR_OWNER_STANDING_BLOCKS", 422,
                       "Buyer owner standing blocks acceptance")
    # Stage 12: OCC
    if expected != t["version"]:
        raise ApiError("ERR_STALE_LISTING_VERSION", 412,
                       "Listing version has advanced since last observation")

    t["listing_status"] = "UNDER_OFFER"
    t["buyer_owner_id"] = buyer_id
    touch(t)
    return ok(listing_view(t))


@bp.route("/transfer-listings/<tid>/close-sale", methods=["POST"])
def close_sale(tid):
    require_roles("FinanceOps")
    t = _get_listing(tid)
    if t["listing_status"] != "UNDER_OFFER":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Listing must be UNDER_OFFER to close the sale")
    data = body()
    final_price = as_int(
        required(data, "final_sale_price_cents"), "final_sale_price_cents"
    )
    if final_price <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "final_sale_price_cents must be > 0")

    share = db.shares[t["share_id"]]
    share["owner_id"] = t["buyer_owner_id"]
    # Entitlement follows the share; hours_remaining_cy unchanged.
    if share["share_status"] == "LISTED":
        share["share_status"] = "ACTIVE"
    touch(share)

    # Rebase depreciation schedule for the buyer.
    sched = next(
        (d for d in db.depreciation_schedules.values()
         if d["share_id"] == share["id"]),
        None,
    )
    if sched:
        sched["basis_cents"] = final_price
        sched["accumulated_depreciation_cents"] = 0
        sched["current_year_allowance_cents"] = 0

    t["listing_status"] = "SOLD"
    touch(t)
    return ok(listing_view(t))


@bp.route("/transfer-listings/<tid>/withdraw", methods=["POST"])
def withdraw_listing(tid):
    user_id, role = require_roles("Owner")
    t = _get_listing(tid)
    share = db.shares[t["share_id"]]
    if t["listing_status"] in ("SOLD", "WITHDRAWN", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Listing is already {t['listing_status']}")
    if t["listing_status"] not in ("LISTED", "UNDER_OFFER"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Listing must be LISTED or UNDER_OFFER to withdraw")
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's current owner may withdraw the listing")
    t["listing_status"] = "WITHDRAWN"
    touch(t)
    if share["share_status"] == "LISTED":
        share["share_status"] = "ACTIVE"
        touch(share)
    return ok(listing_view(t))
