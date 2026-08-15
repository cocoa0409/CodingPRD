"""OverheadSchedule endpoints (PRD 3.1): effective-dated, immutable, non-overlapping."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_OVERHEAD_SCHEDULE_OVERLAP
from middleware import authorized
from response import success_object
from services.core import new_record, serialize_schedule
from util import parse_date
from validate import get_body, req_enum, req_num, req_date, opt_date
from routes.helpers import list_response, get_one

bp = Blueprint("overhead_schedules", __name__)


@bp.route("/ucp/overhead-schedules", methods=["POST"])
def create_schedule():
    authorized(["SystemAdmin"])
    body = get_body()
    cost_type = req_enum(body, "cost_type", ["LABOR", "EQUIPMENT", "MATERIAL"])
    order_type = req_enum(body, "order_type", ["CAPITAL", "EXPENSE"])
    rate_pct = req_num(body, "rate_pct", non_negative=True)
    effective_from = req_date(body, "effective_from")
    effective_to = opt_date(body, "effective_to")  # null = open-ended

    from_d = parse_date(effective_from)
    to_d = parse_date(effective_to) if effective_to is not None else None

    # Priority 10 — half-open interval overlap per (cost_type, order_type).
    # Touching bounds (one row's effective_to == another's effective_from) is
    # NOT an overlap.
    for s in db["overhead_schedules"].values():
        if s["cost_type"] != cost_type or s["order_type"] != order_type:
            continue
        if from_d < (s["_to"] if s["_to"] is not None else _INF) and \
           (to_d if to_d is not None else _INF) > s["_from"]:
            raise_error(
                ERR_OVERHEAD_SCHEDULE_OVERLAP,
                "schedule interval overlaps an existing schedule for this (cost_type, order_type)",
            )

    rec = new_record()
    rec.update({
        "cost_type": cost_type,
        "order_type": order_type,
        "rate_pct": rate_pct,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "_from": from_d,
        "_to": to_d,
    })
    db["overhead_schedules"][rec["id"]] = rec
    return success_object(serialize_schedule(rec), status=201)


@bp.route("/ucp/overhead-schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    return get_one("overhead_schedules", serialize_schedule, schedule_id)


@bp.route("/ucp/overhead-schedules", methods=["GET"])
def list_schedules():
    filters = {
        "cost_type": request.args.get("cost_type"),
        "order_type": request.args.get("order_type"),
    }
    return list_response("overhead_schedules", serialize_schedule, filters)


class _Inf:
    """Sentinel greater than any date (open-ended upper bound)."""
    def __lt__(self, other): return False
    def __le__(self, other): return False
    def __gt__(self, other): return True
    def __ge__(self, other): return True


_INF = _Inf()
