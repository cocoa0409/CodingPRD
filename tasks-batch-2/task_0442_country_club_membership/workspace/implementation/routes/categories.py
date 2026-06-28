"""Membership category endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import category_out

bp = Blueprint("categories", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]
_CODES = {"GOLF", "SOCIAL", "CORPORATE"}


@bp.post("/membership-categories")
def create_category():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(
        body,
        [
            "club_id",
            "code",
            "initiation_fee_cents",
            "refundable_equity_cents",
            "monthly_dues_cents",
            "fb_minimum_cents",
            "capacity",
            "guest_fee_cents",
        ],
    )
    club_id = common.require_string(body, "club_id")
    # Existence of referenced club first (PRD §2.10).
    common.get_club(club_id)
    code = common.require_enum(body, "code", _CODES)
    # code unique among categories of the same club (PRD §3.1).
    for c in db.categories.values():
        if c["club_id"] == club_id and c["code"] == code:
            raise errors.invalid_request(f"Category code {code} already exists for this club")

    initiation = common.require_nonneg_int(body, "initiation_fee_cents")
    refundable = common.require_nonneg_int(body, "refundable_equity_cents")
    if refundable > initiation:
        raise errors.invalid_request("refundable_equity_cents must not exceed initiation_fee_cents")
    monthly_dues = common.require_nonneg_int(body, "monthly_dues_cents")
    fb_minimum = common.require_nonneg_int(body, "fb_minimum_cents")
    capacity = common.require_nonneg_int(body, "capacity")
    guest_fee = common.require_nonneg_int(body, "guest_fee_cents")
    allows_golf = common.optional_bool(body, "allows_golf", False)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "code": code,
            "initiation_fee_cents": initiation,
            "refundable_equity_cents": refundable,
            "monthly_dues_cents": monthly_dues,
            "fb_minimum_cents": fb_minimum,
            "capacity": capacity,
            "guest_fee_cents": guest_fee,
            "allows_golf": allows_golf,
            "active_member_count": 0,
        }
    )
    db.categories[rec["id"]] = rec
    return success_object(category_out(rec, computed), status=201)


@bp.get("/membership-categories/<cid>")
def get_category(cid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_category(cid)
    return success_object(category_out(rec, computed), status=200)


@bp.get("/membership-categories")
def list_categories():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    club_id = request.args.get("club_id")
    records = list(db.categories.values())
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [category_out(r, computed) for r in page]
    return success_array(data, limit, offset, total)
