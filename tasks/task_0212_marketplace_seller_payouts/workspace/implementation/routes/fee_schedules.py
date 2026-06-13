"""Fee schedule endpoints (PRD §3.4)."""
from flask import Blueprint, request

from common import (
    parse_pagination, paginate, sort_by_created, get_json_body,
    require_fields, require_enum, require_int,
)
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch
from services.entity import stamp_create, touch

bp = Blueprint("fee_schedules", __name__)

CATEGORIES = {"ELECTRONICS", "APPAREL", "MEDIA", "GROCERY", "HANDMADE"}


@bp.post("/fee-schedules")
def create_fee_schedule():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE])
    body = get_json_body()
    fields = ["category", "commission_bps", "fixed_fee_cents",
              "payment_processing_bps", "payment_processing_fixed_cents",
              "reserve_pct_standard", "reserve_pct_elevated", "reserve_pct_high",
              "maturation_days"]
    require_fields(body, fields)
    require_enum(body["category"], CATEGORIES, "category")
    require_int(body["commission_bps"], "commission_bps", 0, 5000)
    require_int(body["fixed_fee_cents"], "fixed_fee_cents", 0)
    require_int(body["payment_processing_bps"], "payment_processing_bps", 0, 1000)
    require_int(body["payment_processing_fixed_cents"], "payment_processing_fixed_cents", 0)
    require_int(body["reserve_pct_standard"], "reserve_pct_standard", 0, 100)
    require_int(body["reserve_pct_elevated"], "reserve_pct_elevated", 0, 100)
    require_int(body["reserve_pct_high"], "reserve_pct_high", 0, 100)
    require_int(body["maturation_days"], "maturation_days", 0, 90)

    category = body["category"]
    schedule = {
        "category": category,
        "commission_bps": body["commission_bps"],
        "fixed_fee_cents": body["fixed_fee_cents"],
        "payment_processing_bps": body["payment_processing_bps"],
        "payment_processing_fixed_cents": body["payment_processing_fixed_cents"],
        "reserve_pct_standard": body["reserve_pct_standard"],
        "reserve_pct_elevated": body["reserve_pct_elevated"],
        "reserve_pct_high": body["reserve_pct_high"],
        "maturation_days": body["maturation_days"],
        "is_active": True,
    }
    stamp_create(schedule)
    db.fee_schedules[schedule["id"]] = schedule
    _recompute_active(category)
    return success(schedule, status=201)


def _recompute_active(category):
    """is_active is true for exactly one schedule per category — the latest by
    created_at ascending, last wins (PRD §3.4)."""
    cat_schedules = [s for s in db.fee_schedules.values() if s["category"] == category]
    for s in cat_schedules:
        s["is_active"] = False
    if cat_schedules:
        latest = sorted(cat_schedules, key=lambda s: (s["created_at"], s["id"]))[-1]
        latest["is_active"] = True


def active_schedule_for_category(category):
    cat = [s for s in db.fee_schedules.values()
           if s["category"] == category and s.get("is_active")]
    if not cat:
        return None
    return sorted(cat, key=lambda s: (s["created_at"], s["id"]))[-1]


@bp.get("/fee-schedules/<schedule_id>")
def get_fee_schedule(schedule_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    schedule = fetch(db.fee_schedules, schedule_id)
    return success(schedule)


@bp.get("/fee-schedules")
def list_fee_schedules():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FINANCE, ROLE_REVIEWER, ROLE_SELLER])
    limit, offset = parse_pagination()
    category = request.args.get("category")
    items = list(db.fee_schedules.values())
    if category is not None:
        items = [s for s in items if s["category"] == category]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)
