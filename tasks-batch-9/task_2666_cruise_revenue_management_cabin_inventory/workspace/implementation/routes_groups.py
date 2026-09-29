"""Group blocks: tentative holds, the four-eyes signature, reviews and extensions."""

from flask import Blueprint

import calcs
import cascade
import ops
import shape
import store
from auth import actor, require_four_eyes
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("groups", __name__)

READ_ROLES = ("RevenueManager", "GroupSalesAgent", "ReservationAgent")
RELEASE_POLICIES = ("FULL_RELEASE", "ATTRITION_50")
SELLING_STATUSES = ("OPEN_FOR_SALE", "SALES_SUSPENDED")
REVIEWABLE = ("TENTATIVE", "PARTIALLY_RELEASED")


@bp.post("/group-blocks")
def create_group_block():
    user_id, _role = actor("GroupSalesAgent")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    cabin_category_id = shape.req_str(data, "cabin_category_id")
    agency_name = shape.req_str(data, "agency_name", max_len=64)
    cabins_held = shape.req_int(data, "cabins_held", minimum=1)
    review_date = shape.req_dt(data, "review_date")
    release_policy = shape.req_enum(data, "release_policy", RELEASE_POLICIES)

    # Tier 6.
    sailing = cascade.sailing_or_404(sailing_id)
    category = cascade.category_or_404(cabin_category_id)

    # Tier 11: the voyage must be selling.
    if sailing["status"] not in SELLING_STATUSES:
        raise ApiError("ERR_SAILING_NOT_OPEN")

    # Tier 17: the category must exist on the voyage.
    inv = cascade.inventory_for(sailing_id, cabin_category_id)
    if inv is None:
        raise ApiError("ERR_CATEGORY_NOT_ON_SAILING")

    # Tier 18: only an OPEN sailing accepts new group holds.
    posture = sailing["inventory_posture"]
    if posture == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")
    if posture == "RESTRICTED":
        raise ApiError("ERR_POSTURE_RESTRICTED")

    # Tier 19: the allotment must actually have room.
    if inv["available_cabins"] < cabins_held:
        raise ApiError("ERR_INSUFFICIENT_GROUP_INVENTORY")

    row = store.stamp_new({})
    row.update({
        "sailing_id": sailing["id"],
        "cabin_category_id": category["id"],
        "agency_name": agency_name,
        "cabins_held": cabins_held,
        "picked_up_cabins": 0,
        "review_date": store.iso(review_date),
        "release_policy": release_policy,
        "status": "TENTATIVE",
        "review_count": 0,
        "review_extension_count": 0,
        "released_cabins_total": 0,
        "created_by_user_id": user_id,
        "confirmed_by_user_id": None,
        "contract_reference": None,
    })
    store.group_blocks[row["id"]] = row

    # The fence widens immediately, and the net capacity basis follows it.
    cascade.recompute_inventory(inv, bump=True)
    cascade.recompute_sailing(sailing, bump=True)
    return created(row)


@bp.get("/group-blocks/<block_id>")
def read_group_block(block_id):
    actor(*READ_ROLES)
    return object_response(cascade.block_or_404(block_id))


@bp.get("/group-blocks")
def list_group_blocks():
    actor(*READ_ROLES)
    limit, offset = shape.pagination()
    sailing_id = shape.filter_str("sailing_id")
    category_id = shape.filter_str("cabin_category_id")
    status = shape.filter_str("status")

    rows = []
    for row in store.group_blocks.values():
        if sailing_id is not None and row["sailing_id"] != sailing_id:
            continue
        if category_id is not None and row["cabin_category_id"] != category_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/group-blocks/<block_id>/confirm-definite")
def confirm_definite(block_id):
    user_id, _role = actor("GroupSalesAgent")
    data = shape.body()
    contract_reference = shape.req_str(data, "contract_reference")
    block = cascade.block_or_404(block_id)

    # Tier 8: four eyes, evaluated before any state check.
    require_four_eyes(user_id, block)

    # Tier 10.
    if block["status"] != "TENTATIVE":
        raise ApiError("ERR_GROUP_BLOCK_NOT_TENTATIVE")

    # Tier 11.
    sailing = store.sailings.get(block["sailing_id"])
    if sailing is not None and sailing["status"] not in SELLING_STATUSES:
        raise ApiError("ERR_SAILING_NOT_OPEN")

    block["status"] = "DEFINITE"
    block["confirmed_by_user_id"] = user_id
    block["contract_reference"] = contract_reference
    store.touch(block)
    return object_response(block)


@bp.post("/group-blocks/<block_id>/review")
def review_group_block(block_id):
    actor("GroupSalesAgent")
    shape.body()
    block = cascade.block_or_404(block_id)

    # Tier 10: review is unavailable from DEFINITE and RELEASED.
    if block["status"] not in REVIEWABLE:
        raise ApiError("ERR_GROUP_BLOCK_CLOSED")

    # Tier 16: the review date must have been reached.
    review_date = store.parse_iso(block["review_date"])
    if review_date is None or store.now_dt() < review_date:
        raise ApiError("ERR_REVIEW_DATE_NOT_REACHED")

    sailing = store.sailings.get(block["sailing_id"])
    ops.review_block(block, sailing)
    if sailing is not None:
        cascade.recompute_sailing(sailing, bump=True)
    return object_response(block)


@bp.post("/group-blocks/<block_id>/extend-review")
def extend_review(block_id):
    actor("GroupSalesAgent")
    data = shape.body()
    new_review_date = shape.req_dt(data, "new_review_date")
    block = cascade.block_or_404(block_id)

    # Tier 10.
    if block["status"] not in REVIEWABLE:
        raise ApiError("ERR_GROUP_BLOCK_CLOSED")

    # Tier 16: the new date must be strictly in the future.
    if new_review_date <= store.now_dt():
        raise ApiError("ERR_REVIEW_DATE_IN_PAST")

    # Tier 19: at most MAX_REVIEW_EXTENSIONS extensions per block.
    if block["review_extension_count"] >= calcs.MAX_REVIEW_EXTENSIONS:
        raise ApiError("ERR_MAX_REVIEW_EXTENSIONS_EXCEEDED")

    # No cabins move on an extension; the block simply returns to TENTATIVE.
    block["review_date"] = store.iso(new_review_date)
    block["review_extension_count"] = block["review_extension_count"] + 1
    block["status"] = "TENTATIVE"
    store.touch(block)
    return object_response(block)
