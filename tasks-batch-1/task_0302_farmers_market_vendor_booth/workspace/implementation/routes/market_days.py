"""MarketDay routes (§3.1, §3.5, §3.6)."""
from flask import Blueprint, request

from common import init_common, require_fields, req_str, req_date, req_enum, paginate
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import marketday as svc

bp = Blueprint("market_days", __name__)

CANCEL_REASONS = {"WEATHER", "SAFETY", "LOW_TURNOUT"}


@bp.route("/market-days", methods=["POST"])
def create_market_day():
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    body = get_json_body()
    require_fields(body, ["market_id", "market_date"])
    market_id = req_str(body, "market_id")
    market_date = req_date(body, "market_date")

    market = fk_or_404("market", market_id)

    # temporal: date within season window (ERR_OUTSIDE_WINDOW)
    if market_date < market["season_start_date"] or market_date > market["season_end_date"]:
        raise err("ERR_OUTSIDE_WINDOW", "market_date outside season window")

    # uniqueness: market_date per market (ERR_DUPLICATE)
    for d in db.market_days.values():
        if d["market_id"] == market_id and d["market_date"] == market_date:
            raise err("ERR_DUPLICATE", "Duplicate market_date within market")

    md = {
        "market_id": market_id,
        "market_date": market_date,
        "status": "SCHEDULED",
        "opened_at": None,
        "cancellation_reason": None,
        "daily_fee_refundable": False,
        "attendance_count": 0,
    }
    init_common(md)
    db.market_days[md["id"]] = md
    return success(view(md), 201)


@bp.route("/market-days/<market_day_id>", methods=["GET"])
def get_market_day(market_day_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    md = get_or_404("market_day", market_day_id)
    return success(view(md), 200)


@bp.route("/market-days", methods=["GET"])
def list_market_days():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.market_days.values())
    market_id = request.args.get("market_id")
    status = request.args.get("status")
    if market_id is not None:
        items = [d for d in items if d["market_id"] == market_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/market-days/<market_day_id>/open", methods=["POST"])
def open_market_day(market_day_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    md = get_or_404("market_day", market_day_id)
    if md["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "MarketDay is not SCHEDULED")
    svc.do_open(md)
    return success(view(md), 200)


@bp.route("/market-days/<market_day_id>/close", methods=["POST"])
def close_market_day(market_day_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    md = get_or_404("market_day", market_day_id)
    if md["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "MarketDay is not OPEN")
    svc.do_close(md)
    return success(view(md), 200)


@bp.route("/market-days/<market_day_id>/cancel", methods=["POST"])
def cancel_market_day(market_day_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    md = get_or_404("market_day", market_day_id)
    body = get_json_body()
    require_fields(body, ["cancellation_reason"])
    reason = req_enum(body, "cancellation_reason", CANCEL_REASONS)
    if md["status"] not in ("SCHEDULED", "OPEN"):
        raise err("ERR_INVALID_STATE", "MarketDay cannot be cancelled from its state")
    svc.do_cancel(md, reason)
    return success(view(md), 200)
