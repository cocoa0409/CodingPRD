"""The bid book and the data-room reservation rule (PRD section 3.7).

A data-room reservation is a **closed** interval and a mandatory 60-minute buffer
must separate a new reservation from every live reservation across all bidders on
the same institution, so exact adjacency is rejected here -- a deliberate
contrast with the half-open, unbuffered branch windows of section 3.8.
"""

from datetime import timedelta

from flask import Blueprint, g, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, BIDDER, require
from db import db, new_row, touch
from errors import ApiError
from services import aggregates, least_cost
from util import format_iso, parse_iso

bp = Blueprint("bids", __name__)

DATA_ROOM_BUFFER = timedelta(minutes=60)

BLOCKING_BID_STATUSES = (
    "SUBMITTED",
    "CONFORMING",
    "NON_CONFORMING",
    "WINNER",
    "REJECTED",
)

BIDDABLE_INSTITUTION_STATUSES = ("RESOLUTION_READY", "CLOSED_IN_RECEIVERSHIP")


@bp.post("/bids")
@require(BIDDER)
def submit_bid():
    # Stage 3 in the declared entity order: institution, then bidder.
    raw = shape.raw_body()
    institution = None
    if shape.present(raw, "institution_id"):
        institution = lookup.institution(raw["institution_id"])
    bidder = None
    if shape.present(raw, "bidder_id"):
        bidder = lookup.bidder(raw["bidder_id"])

    payload = shape.body()
    shape.req_id(payload, "institution_id")
    bidder_id = shape.req_id(payload, "bidder_id")
    structure = shape.req_enum(payload, "structure", least_cost.BID_STRUCTURES)
    deposit_premium_bps = shape.req_int(
        payload, "deposit_premium_bps", minimum=0, maximum=10000
    )
    asset_discount_bps = shape.req_int(
        payload, "asset_discount_bps", minimum=0, maximum=10000
    )
    window_start = shape.req_datetime(payload, "data_room_window_start")
    window_end = shape.req_datetime(payload, "data_room_window_end")
    loss_share_pct_bps = shape.opt_int(
        payload, "loss_share_pct_bps", default=0, minimum=0, maximum=10000
    )
    asset_retention_pool_cents = shape.opt_int(
        payload, "asset_retention_pool_cents", default=0, minimum=0
    )
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "data_room_window_end must be strictly after data_room_window_start",
        )

    # Six guards screen a submission, in the order PRD 3.7 pins them.
    if g.user_id != bidder_id:
        raise ApiError("ERR_BIDDER_MISMATCH")
    if institution["status"] not in BIDDABLE_INSTITUTION_STATUSES:
        raise ApiError("ERR_BID_INSTITUTION_INELIGIBLE")
    if institution["franchise_marketing_status"] != "OPEN":
        raise ApiError("ERR_MARKETING_NOT_OPEN")
    deadline = parse_iso(institution["bid_deadline_at"])
    if deadline is None or db.clock > deadline:
        raise ApiError("ERR_BID_WINDOW_CLOSED")
    for existing in dbmod.ordered(lookup.bids_of_institution(institution["id"])):
        if existing["status"] not in BLOCKING_BID_STATUSES:
            continue
        existing_start = parse_iso(existing["data_room_window_start"])
        existing_end = parse_iso(existing["data_room_window_end"])
        if (
            window_start <= existing_end + DATA_ROOM_BUFFER
            and existing_start <= window_end + DATA_ROOM_BUFFER
        ):
            raise ApiError("ERR_DATA_ROOM_WINDOW_CONFLICT")
    if bidder["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_BIDDER_NOT_QUALIFIED")

    row = new_row(
        {
            "institution_id": institution["id"],
            "bidder_id": bidder["id"],
            "structure": structure,
            "deposit_premium_bps": deposit_premium_bps,
            "asset_discount_bps": asset_discount_bps,
            "loss_share_pct_bps": loss_share_pct_bps,
            "asset_retention_pool_cents": asset_retention_pool_cents,
            "data_room_window_start": format_iso(window_start),
            "data_room_window_end": format_iso(window_end),
            "status": "SUBMITTED",
            # Snapshotted at submission; the least-cost test overwrites it.
            "assumed_deposit_base_cents": aggregates.total_deposit_balance_cents(
                institution["id"]
            ),
            "pre_fee_cost_cents": None,
            "loss_share_fee_cents": None,
            "expected_loss_share_reimbursement_cents": None,
            "evaluated_cost_cents": None,
            "non_conformance_reason": None,
        }
    )
    db.bids[row["id"]] = row
    return response.created(serializers.bid(row))


@bp.get("/bids")
@require(ALL_ROLES)
def list_bids():
    rows = list(db.bids.values())
    for field in ("institution_id", "bidder_id", "status", "structure"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return response.paginated(dbmod.ordered(rows), serializers.bid)


@bp.get("/bids/<bid_id>")
@require(ALL_ROLES)
def get_bid(bid_id):
    return response.ok(serializers.bid(lookup.bid(bid_id)))


@bp.post("/bids/<bid_id>/withdraw")
@require(BIDDER)
def withdraw_bid(bid_id):
    bid = lookup.bid(bid_id)
    shape.body()

    if g.user_id != bid["bidder_id"]:
        raise ApiError("ERR_BIDDER_MISMATCH")
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_WITHDRAWABLE")

    bid["status"] = "WITHDRAWN"
    touch(bid)
    return response.ok(serializers.bid(bid))
