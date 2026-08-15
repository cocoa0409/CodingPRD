from flask import Blueprint, request

from clock import now_iso, today_str
from db import db
from errors import (
    ApiError, ERR_INVALID_PRICE, ERR_SCHEDULE_DATE_IN_PAST,
    ERR_SCHEDULE_NOT_DRAFT, ERR_STALE_VERSION, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_schedule, touch,
)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("schedules", __name__)

_ROLES = ["PlatformAdmin", "RackPriceAnalyst", "TerminalOperator"]


def _get_schedule(schedule_id):
    s = db.price_schedules.get(schedule_id)
    if s is None:
        raise not_found("RackPriceSchedule {} does not exist".format(schedule_id))
    return s


def _check_terminal_occ(body, terminal):
    """Optimistic concurrency guard of PRD §2.7 (publish endpoints only)."""
    expected = body.get("expected_terminal_version")
    try:
        ok = expected is not None and int(expected) == terminal["version"]
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_terminal_version does not match current Terminal.version",
        )


@bp.post("/rack/price-schedules")
def create_schedule():
    require_roles(["RackPriceAnalyst"])
    body = get_body()
    if body.get("terminal_id") not in db.terminals:
        raise not_found("Terminal {} does not exist".format(body.get("terminal_id")))
    if body.get("product_id") not in db.products:
        raise not_found("Product {} does not exist".format(body.get("product_id")))
    s = new_entity({
        "terminal_id": body.get("terminal_id"),
        "product_id": body.get("product_id"),
        "effective_date": body.get("effective_date"),
        "posted_rack_cents_per_gal": body.get("posted_rack_cents_per_gal"),
        "branded_premium_cents_per_gal": body.get("branded_premium_cents_per_gal", 0),
        "status": "DRAFT",
        "published_at": None,
    })
    db.price_schedules[s["id"]] = s
    return success_object(ser_schedule(s), 201)


@bp.get("/rack/price-schedules/<scheduleId>")
def get_schedule(scheduleId):
    require_roles(_ROLES)
    return success_object(ser_schedule(_get_schedule(scheduleId)))


@bp.get("/rack/price-schedules")
def list_schedules():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.price_schedules.values(), request.args,
        ["terminal_id", "product_id", "effective_date", "status"],
    )
    return success_list([ser_schedule(s) for s in page], total, limit, offset)


@bp.post("/rack/price-schedules/<scheduleId>/publish")
def publish_schedule(scheduleId):
    require_roles(["RackPriceAnalyst"])
    s = _get_schedule(scheduleId)
    # Fixed check order (PRD §3.3): DRAFT -> date -> price -> OCC.
    if s["status"] != "DRAFT":
        raise ApiError(
            ERR_SCHEDULE_NOT_DRAFT, 409,
            "RackPriceSchedule must be DRAFT to publish",
        )
    if s["effective_date"] < today_str():
        raise ApiError(
            ERR_SCHEDULE_DATE_IN_PAST, 422,
            "effective_date is before the logical clock's current date",
        )
    price = s.get("posted_rack_cents_per_gal")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        raise ApiError(
            ERR_INVALID_PRICE, 422, "posted_rack_cents_per_gal must be > 0"
        )
    terminal = db.terminals.get(s["terminal_id"])
    if terminal is None:
        raise not_found("Terminal {} does not exist".format(s["terminal_id"]))
    _check_terminal_occ(get_body(), terminal)

    # Supersede any other PUBLISHED schedule for the same triple.
    for other in list(db.price_schedules.values()):
        if (
            other["id"] != s["id"]
            and other["status"] == "PUBLISHED"
            and other["terminal_id"] == s["terminal_id"]
            and other["product_id"] == s["product_id"]
            and other["effective_date"] == s["effective_date"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    s["status"] = "PUBLISHED"
    s["published_at"] = now_iso()  # stamped once, immutable thereafter
    touch(s)
    touch(terminal)
    return success_object(ser_schedule(s))


@bp.post("/rack/price-schedules/<scheduleId>/void")
def void_schedule(scheduleId):
    require_roles(["RackPriceAnalyst"])
    s = _get_schedule(scheduleId)
    if s["status"] != "DRAFT":
        raise ApiError(
            ERR_SCHEDULE_NOT_DRAFT, 409,
            "RackPriceSchedule must be DRAFT to void",
        )
    s["status"] = "VOIDED"
    touch(s)
    return success_object(ser_schedule(s))
