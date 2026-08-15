"""Bid creation and selection (selection cascades into the work order)."""

from db import store
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, req_string, req_int,
    get_bid_or_404, get_holdback_or_404, file_of_holdback, work_order_of,
    new_entity, touch, rhu_mul_div, refresh_holdback_derived,
    ser_bid,
)
from middleware import authenticate, authorize
from response import success

from . import bp


@bp.post("/escrow/bids")
def create_bid():
    uid, role = authenticate()
    authorize(role, ["Contractor"])
    data = get_body()
    raw_hid = data.get("holdback_id")
    if isinstance(raw_hid, str) and raw_hid not in store.holdbacks:
        raise ApiError("ERR_NOT_FOUND", "Holdback not found: %s" % raw_hid)
    check_allowed_fields(data, {"holdback_id", "amount_cents", "scope_text"})
    hid = req_string(data, "holdback_id")
    hb = get_holdback_or_404(hid)
    amount = req_int(data, "amount_cents", lo=1)
    scope = req_string(data, "scope_text")

    # Rung 8: bidding requires an ACTIVE holdback.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Bids require an ACTIVE holdback")
    # Rung 10: one SUBMITTED bid per contractor per holdback; bidding closes
    # once a selection exists.
    for b in store.bids.values():
        if b["holdback_id"] == hid and b["status"] == "SUBMITTED" and b["contractor_user_id"] == uid:
            raise ApiError("ERR_BID_ALREADY_SUBMITTED", "Contractor already has a SUBMITTED bid")
    if hb["selected_bid_id"] is not None or work_order_of(hid) is not None:
        raise ApiError("ERR_WORK_ORDER_EXISTS", "A bid is already selected for this holdback")

    b = new_entity()
    b.update({
        "holdback_id": hid,
        "contractor_user_id": uid,
        "amount_cents": amount,
        "scope_text": scope,
        "status": "SUBMITTED",
    })
    store.bids[b["id"]] = b
    return success(ser_bid(b), response_type="object", status=201)


@bp.post("/escrow/bids/<bid>/select")
def select_bid(bid):
    uid, role = authenticate()
    authorize(role, ["Buyer"])
    b = get_bid_or_404(bid)
    data = get_body()
    check_allowed_fields(data, set())
    hb = get_holdback_or_404(b["holdback_id"])
    f = file_of_holdback(hb)

    # Rung 5: selection belongs to the buyer of record.
    if f is None or uid != f["buyer_user_id"]:
        raise ApiError("ERR_NOT_FILE_PARTY", "Only the buyer of record may select a bid")
    # Rung 8 (fixed internal order): holdback ACTIVE, then bid SUBMITTED.
    if hb["status"] != "ACTIVE":
        raise ApiError("ERR_HOLDBACK_NOT_ACTIVE", "Bid selection requires an ACTIVE holdback")
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_SELECTABLE", "Bid is not in SUBMITTED state")
    # Rung 10: no other bid already SELECTED.
    if hb["selected_bid_id"] is not None or work_order_of(hb["id"]) is not None:
        raise ApiError("ERR_WORK_ORDER_EXISTS", "A bid is already selected for this holdback")

    # Cascade: this bid SELECTED; every other SUBMITTED bid REJECTED.
    b["status"] = "SELECTED"
    touch(b)
    for other in store.bids.values():
        if other["holdback_id"] == hb["id"] and other["id"] != b["id"] and other["status"] == "SUBMITTED":
            other["status"] = "REJECTED"
            touch(other)

    # The work order springs into existence from the selected bid.
    wo = new_entity()
    wo.update({
        "holdback_id": hb["id"],
        "contractor_user_id": b["contractor_user_id"],
        "agreed_amount_cents": b["amount_cents"],
        "started_at": wo["created_at"],
        "completion_deadline_date": hb["effective_deadline_date"],
        "status": "IN_PROGRESS",
        "failed_final_count": 0,
        "submitted_completion_at": None,
    })
    store.work_orders[wo["id"]] = wo

    hb["selected_bid_id"] = b["id"]
    hb["commitment_basis_cents"] = rhu_mul_div(b["amount_cents"], 100 + hb["contingency_pct"], 100)
    refresh_holdback_derived(hb)
    touch(hb)
    return success(ser_bid(b), response_type="object", status=200)
