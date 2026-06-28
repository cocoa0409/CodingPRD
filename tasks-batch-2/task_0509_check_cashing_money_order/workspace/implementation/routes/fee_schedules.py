"""FeeSchedule routes (PRD §3.2)."""
from flask import Blueprint, request

from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, new_id, common_fields, serialize
from helpers import (
    get_json_body,
    parse_pagination,
    paginate,
    sort_by_creation,
    require_int,
    require_enum,
    require_bool,
)
import lookups
from response import created, ok, listed

bp = Blueprint("fee_schedules", __name__)

CHECK_TYPES = {"PAYROLL", "GOVERNMENT", "PERSONAL", "MONEY_ORDER_CHECK", "INSURANCE"}


@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require_auth(MANAGER_ONLY)
    body = get_json_body()
    check_type = require_enum(body, "check_type", CHECK_TYPES)
    base_fee_cents = require_int(body, "base_fee_cents", minimum=0)
    percent_rate_bps = require_int(body, "percent_rate_bps", minimum=0)
    tier_breakpoint_cents = require_int(body, "tier_breakpoint_cents", minimum=0)
    high_percent_rate_bps = require_int(body, "high_percent_rate_bps", minimum=0)
    max_fee_cents = require_int(body, "max_fee_cents", minimum=0)
    active = require_bool(body, "active", required=False, default=True)

    fid = new_id()
    schedule = {
        "id": fid,
        "check_type": check_type,
        "base_fee_cents": base_fee_cents,
        "percent_rate_bps": percent_rate_bps,
        "tier_breakpoint_cents": tier_breakpoint_cents,
        "high_percent_rate_bps": high_percent_rate_bps,
        "max_fee_cents": max_fee_cents,
        "active": active,
    }
    schedule.update(common_fields())
    db.fee_schedules[fid] = schedule
    return created(serialize(schedule))


@bp.route("/fee-schedules/<fid>", methods=["GET"])
def get_fee_schedule(fid):
    require_auth(BOTH)
    schedule = lookups.get_fee_schedule(fid)
    return ok(serialize(schedule))


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_auth(BOTH)
    limit, offset = parse_pagination()
    items = list(db.fee_schedules.values())

    check_type = request.args.get("check_type")
    if check_type is not None:
        items = [s for s in items if s["check_type"] == check_type]

    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [s for s in items if s["active"] == want]

    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(s) for s in page], limit, offset, total)
