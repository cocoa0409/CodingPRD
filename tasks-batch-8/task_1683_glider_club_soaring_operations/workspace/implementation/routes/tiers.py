"""MembershipTier endpoints."""

import uuid

from flask import Blueprint

import db
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_UNIQUE_CONSTRAINT
from middleware import auth, require_role
from response import success
from services import ser_tier
from util import (
    get_body,
    need_int,
    need_number,
    need_str,
    opt_bool,
    paginate,
    sort_items,
    to_decimal,
)

bp = Blueprint("tiers", __name__)

ALL_ROLES = ["ClubAdmin", "Member", "DutyOfficer", "Instructor", "TowPilot"]


@bp.post("/soaring/tiers")
def create_tier():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    body = get_body()
    tier_code = need_str(body, "tier_code")
    monthly_dues_cents = need_int(body, "monthly_dues_cents")
    tow_fee_discount_pct = need_number(body, "tow_fee_discount_pct")
    if to_decimal(tow_fee_discount_pct) < 0 or to_decimal(tow_fee_discount_pct) > to_decimal(0.50):
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY", 422,
            "tow_fee_discount_pct must be between 0.00 and 0.50 inclusive",
        )
    included = body.get("included_tows_per_month", 0)
    if isinstance(included, bool) or not isinstance(included, int) or included < 0:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY", 422,
            "included_tows_per_month must be a non-negative integer",
        )
    student_tier = opt_bool(body, "student_tier", False)
    for existing in db.STORE["tiers"].values():
        if existing["tier_code"] == tier_code:
            raise ApiError(
                ERR_UNIQUE_CONSTRAINT, 409,
                "tier_code '%s' already exists" % tier_code,
            )
    record = {
        "id": str(uuid.uuid4()),
        "tier_code": tier_code,
        "monthly_dues_cents": monthly_dues_cents,
        "tow_fee_discount_pct": tow_fee_discount_pct,
        "included_tows_per_month": included,
        "student_tier": student_tier,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["tiers"][record["id"]] = record
    return success(ser_tier(record), "object", 201)


@bp.get("/soaring/tiers")
def list_tiers():
    auth()
    items = sort_items(db.STORE["tiers"].values())
    page, meta = paginate(items)
    return success([ser_tier(t) for t in page], "array", 200, meta)


@bp.get("/soaring/tiers/<tid>")
def get_tier(tid):
    auth()
    record = db.STORE["tiers"].get(tid)
    if record is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "MembershipTier not found")
    return success(ser_tier(record), "object", 200)
