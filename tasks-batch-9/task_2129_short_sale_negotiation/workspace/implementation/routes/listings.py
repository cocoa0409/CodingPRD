"""Listings, marketing windows and price reductions (PRD §3.4)."""
from decimal import Decimal

from flask import Blueprint

import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, success
from errors import fail
from serializers import listing_out

bp = Blueprint("listings", __name__)

LISTING_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_LISTING_AGENT,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_PLATFORM_ADMIN,
)


@bp.post("/short-sale/cases/<case_id>/listings")
def create_listing(case_id):
    user_id = require(K.ROLE_LISTING_AGENT)
    case = S.need_case(case_id)
    data = V.body()
    listing = {
        "id": db.new_id(),
        "case_id": case["id"],
        "list_price_cents": V.req_int(data, "list_price_cents", minimum=1),
        "commission_pct": V.req_decimal(
            data, "commission_pct", minimum=Decimal(0), maximum=Decimal("0.10"),
            exclusive_min=True,
        ),
        "listed_at": V.req_datetime(data, "listed_at"),
        "ended_at": None,
        "listing_agent_user_id": user_id,
        "price_reduction_count": 0,
        "marketing_status": "ACTIVE",
    }

    # rung 9 — state admissibility
    S.require_case_actionable(case)

    # rung 12 — interval admission
    if S.listing_window_conflict(case["id"], listing["listed_at"]):
        fail(
            "ERR_LISTING_WINDOW_OVERLAP",
            "The new marketing window overlaps an existing window on this case.",
        )

    db.insert("listings", listing)
    return created(listing_out(listing))


@bp.get("/short-sale/cases/<case_id>/listings")
def list_case_listings(case_id):
    require(*LISTING_READ_ROLES)
    case = S.need_case(case_id)
    status = enum_filter("marketing_status", K.MARKETING_STATUSES)
    rows = S.case_listings(case["id"])
    if status is not None:
        rows = [r for r in rows if r["marketing_status"] == status]
    return collection(rows, listing_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/listings/<listing_id>/price-reduction")
def price_reduction(listing_id):
    require(K.ROLE_LISTING_AGENT)
    listing = S.need_listing(listing_id)
    data = V.body()
    new_price = V.req_int(data, "new_list_price_cents", minimum=1)

    # rung 9 — state admissibility
    if listing["marketing_status"] == "WITHDRAWN":
        fail("ERR_LISTING_NOT_ACTIONABLE", "A withdrawn listing accepts no price reduction.")

    listing["list_price_cents"] = new_price
    listing["price_reduction_count"] += 1
    case = db.get("cases", listing["case_id"])
    if case is not None:
        case["price_reduction_required"] = False
    return success(listing_out(listing))


@bp.post("/short-sale/listings/<listing_id>/withdraw")
def withdraw_listing(listing_id):
    require(K.ROLE_LISTING_AGENT)
    listing = S.need_listing(listing_id)
    data = V.body()
    ended_at = V.req_datetime(data, "ended_at")

    # rung 9 — state admissibility
    if listing["marketing_status"] == "WITHDRAWN":
        fail("ERR_LISTING_NOT_ACTIONABLE", "The listing is already withdrawn.")
    if ended_at <= listing["listed_at"]:
        fail(
            "ERR_LISTING_NOT_ACTIONABLE",
            "ended_at must fall strictly after listed_at.",
        )

    listing["marketing_status"] = "WITHDRAWN"
    listing["ended_at"] = ended_at
    return success(listing_out(listing))
