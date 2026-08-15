"""Giveaway awards under the monthly quota (PRD §3.10)."""

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import (make_common, touch, paginate, sorted_by_created,
                           giveaway_month_count, month_of, parse_month_param,
                           MONTHLY_GIVEAWAY_CAP)

bp = Blueprint("giveaways", __name__)


def giveaway_view(g):
    return {
        "id": g["id"],
        "bike_id": g["bike_id"],
        "partner_org": g["partner_org"],
        "referral_code": g["referral_code"],
        "recipient_age_group": g["recipient_age_group"],
        "status": g["status"],
        "decided_by_user_id": g["decided_by_user_id"],
        "decided_at": g["decided_at"],
        "fulfilled_by_user_id": g["fulfilled_by_user_id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def _get_giveaway(giveaway_id):
    g = db.giveaways.get(giveaway_id)
    if g is None:
        raise ApiError("ERR_NOT_FOUND", f"GiveawayAward {giveaway_id} does not exist")
    return g


@bp.post("/giveaways")
def create_giveaway():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "bike_id": {"type": "string", "required": True},
        "partner_org": {"type": "string", "required": True},
        "referral_code": {"type": "string", "required": True},
        "recipient_age_group": {"type": "string", "required": True, "enum": ["YOUTH", "ADULT"]},
    })
    bike = db.bikes.get(body["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {body['bike_id']} does not exist")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    g = make_common()
    g.update({
        "bike_id": bike["id"],
        "partner_org": body["partner_org"],
        "referral_code": body["referral_code"],
        "recipient_age_group": body["recipient_age_group"],
        "status": "REQUESTED",
        "decided_by_user_id": None,
        "decided_at": None,
        "fulfilled_by_user_id": None,
    })
    db.giveaways[g["id"]] = g
    return success(giveaway_view(g), status=201)


@bp.get("/giveaways/<giveaway_id>")
def get_giveaway(giveaway_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    return success(giveaway_view(_get_giveaway(giveaway_id)))


@bp.get("/giveaways")
def list_giveaways():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.giveaways.values())
    for param in ("bike_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [g for g in rows if g[param] == value]
    raw_month = request.args.get("month")
    if raw_month is not None:
        year, month = parse_month_param(raw_month)
        rows = [
            g for g in rows
            if g["decided_at"] is not None
            and month_of(_parse_iso(g["decided_at"])) == (year, month)
        ]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([giveaway_view(g) for g in page], pagination=pg)


@bp.post("/giveaways/<giveaway_id>/approve")
def approve_giveaway(giveaway_id):
    user_id, _ = require_roles("ProgramDirector")
    g = _get_giveaway(giveaway_id)
    bike = db.bikes.get(g["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {g['bike_id']} does not exist")
    if g["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED award can be approved")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    now = db.now()
    if giveaway_month_count(now.year, now.month) >= MONTHLY_GIVEAWAY_CAP:
        raise ApiError("ERR_GIVEAWAY_QUOTA_EXCEEDED", "Monthly giveaway quota reached")
    g["status"] = "APPROVED"
    g["decided_by_user_id"] = user_id
    g["decided_at"] = db.now_iso()
    touch(g)
    return success(giveaway_view(g))


@bp.post("/giveaways/<giveaway_id>/deny")
def deny_giveaway(giveaway_id):
    user_id, _ = require_roles("ProgramDirector")
    get_body()
    g = _get_giveaway(giveaway_id)
    if g["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED award can be denied")
    g["status"] = "DENIED"
    g["decided_by_user_id"] = user_id
    g["decided_at"] = db.now_iso()
    touch(g)
    return success(giveaway_view(g))


@bp.post("/giveaways/<giveaway_id>/fulfill")
def fulfill_giveaway(giveaway_id):
    user_id, _ = require_roles("ShopCoordinator")
    g = _get_giveaway(giveaway_id)
    bike = db.bikes.get(g["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {g['bike_id']} does not exist")
    if g["status"] != "APPROVED":
        raise ApiError("ERR_AWARD_NOT_APPROVED", "Only an APPROVED award can be fulfilled")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    if user_id == g["decided_by_user_id"]:
        raise ApiError("ERR_FULFILLER_IS_APPROVER", "The fulfiller must differ from the approver")
    if any(s["bike_id"] == bike["id"] and s["status"] == "PENDING" for s in db.sales.values()):
        raise ApiError("ERR_SALE_PENDING_CONFLICT", "A PENDING sale blocks fulfillment")
    if g["recipient_age_group"] == "YOUTH":
        if not any(d["recipient_kind"] == "GIVEAWAY_RECIPIENT" and d.get("giveaway_id") == g["id"]
                   for d in db.helmet_distributions.values()):
            raise ApiError("ERR_HELMET_REQUIRED", "YOUTH recipients require a helmet distribution")
    g["status"] = "FULFILLED"
    g["fulfilled_by_user_id"] = user_id
    touch(g)
    bike["status"] = "GIFTED"
    touch(bike)
    return success(giveaway_view(g))


@bp.post("/giveaways/<giveaway_id>/cancel")
def cancel_giveaway(giveaway_id):
    require_roles("ProgramDirector")
    get_body()
    g = _get_giveaway(giveaway_id)
    if g["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED award can be cancelled")
    g["status"] = "CANCELLED"
    touch(g)
    return success(giveaway_view(g))
