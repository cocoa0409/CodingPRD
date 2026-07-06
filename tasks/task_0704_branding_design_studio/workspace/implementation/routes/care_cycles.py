"""CareCycle endpoints (PRD §3.10, §2.10)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_INTERVAL,
    ERR_INTERVAL_OVERLAP, ERR_INVALID_STATE, ERR_CYCLE_NOT_ENDED,
)
from helpers import (
    require_role, get_json_body, require_fields, require_nonneg_int,
    as_string, parse_pagination, paginate,
)
from util import parse_iso8601
from response import success, success_list
from serialize import view
from services.calc import retainer_overage
from routes.retainers import _resolve_retainer

bp = Blueprint("care_cycles", __name__)


def _resolve_cycle(studio_id, retainer_id, cycle_id):
    rt = _resolve_retainer(studio_id, retainer_id)
    cyc = db.care_cycles.get(cycle_id)
    if cyc is None or cyc["retainer_id"] != retainer_id:
        raise err(ERR_NOT_FOUND, "CareCycle not found")
    return rt, cyc


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open [a_start, a_end) and [b_start, b_end) overlap iff
    a_start < b_end and b_start < a_end (PRD §2.10)."""
    return a_start < b_end and b_start < a_end


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/care-cycles", methods=["POST"])
def open_cycle(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    _resolve_retainer(studio_id, retainer_id)
    body = get_json_body()
    require_fields(body, "period_start", "period_end")
    period_start_raw = as_string(body["period_start"], "period_start")
    period_end_raw = as_string(body["period_end"], "period_end")
    period_start = parse_iso8601(period_start_raw)
    period_end = parse_iso8601(period_end_raw)
    if period_start is None or period_end is None:
        raise err(ERR_INVALID_REQUEST, "period_start/period_end must be ISO 8601 datetimes")
    hours_used = 0
    if "hours_used" in body and body["hours_used"] is not None:
        hours_used = require_nonneg_int(body["hours_used"], "hours_used")

    # Malformed window: start not strictly before end (PRD §2.10).
    if not (period_start < period_end):
        raise err(ERR_INVALID_INTERVAL, "period_start must be strictly before period_end")

    # Half-open overlap with another cycle on the same retainer (§2.10).
    for other in db.care_cycles.values():
        if other["retainer_id"] != retainer_id:
            continue
        os_ = parse_iso8601(other["period_start"])
        oe = parse_iso8601(other["period_end"])
        if _half_open_overlap(period_start, period_end, os_, oe):
            raise err(ERR_INTERVAL_OVERLAP, "CareCycle window overlaps an existing cycle")

    rec = db.create(db.care_cycles, {
        "retainer_id": retainer_id,
        "period_start": period_start_raw,
        "period_end": period_end_raw,
        "hours_used": hours_used,
        "overage_cents": 0,
        "billed_cents": 0,
        "status": "OPEN",
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/care-cycles", methods=["GET"])
def list_cycles(studio_id, retainer_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps")
    _resolve_retainer(studio_id, retainer_id)
    limit, offset = parse_pagination()
    records = [c for c in db.care_cycles.values() if c["retainer_id"] == retainer_id]
    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/care-cycles/<cycle_id>",
          methods=["GET"])
def get_cycle(studio_id, retainer_id, cycle_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps")
    rt, cyc = _resolve_cycle(studio_id, retainer_id, cycle_id)
    return success(view(cyc), status=200)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/care-cycles/<cycle_id>/close",
          methods=["POST"])
def close_cycle(studio_id, retainer_id, cycle_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    rt, cyc = _resolve_cycle(studio_id, retainer_id, cycle_id)
    # OPEN -> CLOSED.
    if cyc["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "CareCycle is not OPEN")
    # Clock must have reached or passed period_end.
    period_end = parse_iso8601(cyc["period_end"])
    if not (clock.now() >= period_end):
        raise err(ERR_CYCLE_NOT_ENDED, "Cycle period has not ended")

    overage = retainer_overage(
        cyc["hours_used"], rt["included_hours"],
        rt["tier1_rate_cents"], rt["tier2_rate_cents"])
    cyc["overage_cents"] = overage
    cyc["billed_cents"] = rt["monthly_fee_cents"] + overage
    cyc["status"] = "CLOSED"
    db.touch(cyc)
    return success(view(cyc), status=200)


@bp.route("/studios/<studio_id>/retainers/<retainer_id>/care-cycles/<cycle_id>/bill",
          methods=["POST"])
def bill_cycle(studio_id, retainer_id, cycle_id):
    caller = authenticate()
    require_role(caller, "BillingOps")
    rt, cyc = _resolve_cycle(studio_id, retainer_id, cycle_id)
    # CLOSED -> BILLED.
    if cyc["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE, "CareCycle is not CLOSED")
    cyc["status"] = "BILLED"
    db.touch(cyc)
    return success(view(cyc), status=200)
