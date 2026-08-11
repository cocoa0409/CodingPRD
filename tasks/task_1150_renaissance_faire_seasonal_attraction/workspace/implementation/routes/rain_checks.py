"""RainCheck endpoints."""
from flask import Blueprint

from db import store, clock_now
from errors import (
    ERR_RAIN_CHECK_NOT_FOUND,
    ERR_FAIRE_DAY_NOT_FOUND,
    ERR_RAIN_CHECK_NOT_ISSUED,
    ERR_RAIN_CHECK_EXPIRED,
    ERR_DAY_NOT_REDEEMABLE,
    ERR_DAY_AT_CAPACITY,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import lazy_expire_rain_check, mint_tickets, tickets_sold_count
from util import req, check_unknown, mutate, public_view

bp = Blueprint("rain_checks", __name__)


def load_check(rid):
    check = load(store.rain_checks, rid, ERR_RAIN_CHECK_NOT_FOUND, "rain check")
    lazy_expire_rain_check(check)
    return check


@bp.route("/rain-checks", methods=["GET"])
def list_checks():
    require_roles()
    for check in store.rain_checks.values():
        lazy_expire_rain_check(check)
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.rain_checks),
        [
            ("season_id", "season_id"),
            ("ticket_id", "ticket_id"),
            ("issued_for_day_id", "issued_for_day_id"),
            ("redeemed_on_day_id", "redeemed_on_day_id"),
            ("status", "status"),
        ],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(r) for r in page], limit, offset, total)


@bp.route("/rain-checks/<rid>", methods=["GET"])
def get_check(rid):
    require_roles()
    return obj_response(public_view(load_check(rid)))


@bp.route("/rain-checks/<rid>/redeem", methods=["POST"])
def redeem_check(rid):
    uid, _ = require_roles("Guest")
    check = load(store.rain_checks, rid, ERR_RAIN_CHECK_NOT_FOUND, "rain check")
    body = get_body()
    if isinstance(body.get("target_faire_day_id"), str):
        load(store.faire_days, body["target_faire_day_id"], ERR_FAIRE_DAY_NOT_FOUND, "faire day")
    check_unknown(body, {"target_faire_day_id"})
    target_day_id = req(body, "target_faire_day_id", "str")
    target_day = store.faire_days[target_day_id]

    source_ticket = store.tickets[check["ticket_id"]]
    order = store.orders[source_ticket["order_id"]]
    require_owner(uid == order["buyer_email"])

    if check["status"] != "ISSUED":
        raise conflict(ERR_RAIN_CHECK_NOT_ISSUED, "redeem requires an ISSUED rain check")
    if clock_now() > check["redeem_by_date"]:
        # Lazy expiry surfaces on this write, then the clock gate fires.
        lazy_expire_rain_check(check)
        raise conflict(ERR_RAIN_CHECK_EXPIRED, "redeem after redeem_by_date")
    if target_day["status"] not in ("SCHEDULED", "OPEN_FOR_SALES"):
        raise conflict(
            ERR_DAY_NOT_REDEEMABLE, "target day must be SCHEDULED or OPEN_FOR_SALES"
        )
    season = store.seasons[check["season_id"]]
    if tickets_sold_count(target_day) + 1 > season["daily_capacity"]:
        raise conflict(ERR_DAY_AT_CAPACITY, "target day is at capacity")

    mutate(check, status="REDEEMED", redeemed_on_day_id=target_day["id"])
    # A fresh DAY ticket under the same order; outstanding_admissions unchanged.
    mint_tickets(order, 1, target_day["id"], "DAY")
    return obj_response(public_view(check))
