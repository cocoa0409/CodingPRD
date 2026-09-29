"""Bidder registration and qualification (PRD section 3.7).

Qualification is a supervisory judgement backed by two hard floors: a tier-1
leverage ratio of at least ten percent and a CAMELS composite no worse than 2.
"""

from flask import Blueprint, request

import db as dbmod
import lookup
import response
import serializers
import shape
from auth import ALL_ROLES, RESOLUTION_ANALYST, require
from db import db, new_row, touch
from errors import ApiError

bp = Blueprint("bidders", __name__)

DECISIONS = ("QUALIFY", "DISQUALIFY")

DISQUALIFICATION_REASONS = ("CAPITAL_BELOW_FLOOR", "CAMELS_ABOVE_CEILING", "MANUAL")

BIDDER_CAPITAL_FLOOR_BPS = 1000
BIDDER_CAMELS_CEILING = 2


@bp.post("/bidders")
@require(RESOLUTION_ANALYST)
def create_bidder():
    payload = shape.body()
    legal_name = shape.req_str(payload, "legal_name", min_len=1, max_len=160)
    cert_number = shape.req_str(
        payload, "cert_number", min_len=4, max_len=6, pattern=shape.DIGITS_4_6
    )
    tier1_capital_ratio_bps = shape.req_int(
        payload, "tier1_capital_ratio_bps", minimum=0
    )
    camels_composite = shape.req_int(
        payload, "camels_composite", minimum=1, maximum=5
    )

    for existing in db.bidders.values():
        if existing["cert_number"] == cert_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    row = new_row(
        {
            "legal_name": legal_name,
            "cert_number": cert_number,
            "tier1_capital_ratio_bps": tier1_capital_ratio_bps,
            "camels_composite": camels_composite,
            "qualification_status": "PENDING",
            "qualified_at": None,
            "disqualification_reason": None,
        }
    )
    db.bidders[row["id"]] = row
    return response.created(serializers.bidder(row))


@bp.get("/bidders")
@require(ALL_ROLES)
def list_bidders():
    rows = list(db.bidders.values())
    qualification_status = request.args.get("qualification_status")
    if qualification_status is not None:
        rows = [r for r in rows if r["qualification_status"] == qualification_status]
    return response.paginated(dbmod.ordered(rows), serializers.bidder)


@bp.get("/bidders/<bidder_id>")
@require(ALL_ROLES)
def get_bidder(bidder_id):
    return response.ok(serializers.bidder(lookup.bidder(bidder_id)))


@bp.post("/bidders/<bidder_id>/qualification")
@require(RESOLUTION_ANALYST)
def qualify_bidder(bidder_id):
    bidder = lookup.bidder(bidder_id)
    payload = shape.body()
    decision = shape.req_enum(payload, "decision", DECISIONS)
    reason = shape.opt_enum(payload, "disqualification_reason", DISQUALIFICATION_REASONS)

    if decision == "QUALIFY":
        if (
            bidder["tier1_capital_ratio_bps"] < BIDDER_CAPITAL_FLOOR_BPS
            or bidder["camels_composite"] > BIDDER_CAMELS_CEILING
        ):
            raise ApiError("ERR_BIDDER_INELIGIBLE")
        bidder["qualification_status"] = "QUALIFIED"
        bidder["qualified_at"] = db.now_iso()
    else:
        bidder["qualification_status"] = "DISQUALIFIED"
        bidder["disqualification_reason"] = reason or "MANUAL"
    touch(bidder)
    return response.ok(serializers.bidder(bidder))
