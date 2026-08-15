"""MoveRecord endpoints (PRD §3.5)."""
from decimal import Decimal

from flask import Blueprint, g, request

import errors
import services
from db import get, new_resource, pub, save, touch
from middleware import list_response, opt_int, req_datetime, req_field, req_int, req_num, require_roles
from response import get_body, ok

bp = Blueprint("moves", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "LaborHallDispatcher",
              "GangForeman", "PayrollClerk", "BillingClerk")


@bp.post("/api/move-records")
def create_move_record():
    require_roles("GangForeman")
    body = get_body()
    # existence (3)
    gang_order_id = req_field(body, "gang_order_id")
    gang = get("gang_orders", gang_order_id)
    if gang is None:
        raise errors.not_found("Gang order not found")
    # schema (4)
    start_raw, start = req_datetime(body, "period_start_utc")
    end_raw, end = req_datetime(body, "period_end_utc")
    if end <= start:
        raise errors.validation("period_end_utc must be later than period_start_utc")
    moves_count = req_int(body, "moves_count", min_value=0)
    tons_lifted = req_num(body, "tons_lifted", min_value=0)
    period_minutes = Decimal(str((end - start).total_seconds())) / Decimal(60)
    stoppage_minutes = opt_int(body, "stoppage_minutes", min_value=0)
    if stoppage_minutes is None:
        stoppage_minutes = 0
    if Decimal(stoppage_minutes) > period_minutes:
        raise errors.validation("stoppage_minutes may not exceed the period length")
    # state (6): gang must be WORKING or SUSPENDED
    if gang["status"] not in ("WORKING", "SUSPENDED"):
        raise errors.invalid_state("Move records require a WORKING or SUSPENDED gang order")
    # temporal (9): no overlap with another RECORDED period on this gang (half-open)
    for r in services.all_of("move_records"):
        if r["gang_order_id"] == gang["id"] and r["status"] == "RECORDED":
            if services._half_open_overlap(start, end, r["_pstart"], r["_pend"]):
                raise errors.move_period_overlap()
    rec = new_resource("move_records")
    rec.update({
        "gang_order_id": gang_order_id,
        "recorded_by_worker_id": g.user_id,
        "period_start_utc": start_raw,
        "period_end_utc": end_raw,
        "moves_count": moves_count,
        "tons_lifted": tons_lifted,
        "stoppage_minutes": stoppage_minutes,
        "status": "RECORDED",
        "_pstart": start,
        "_pend": end,
    })
    save("move_records", rec)
    services.recompute_vessel_actuals(services.gang_vessel(gang))
    return ok(pub(rec), 201)


@bp.get("/api/move-records")
def list_move_records():
    require_roles(*READ_ROLES)
    return list_response("move_records", {
        "gang_order_id": request.args.get("gang_order_id"),
        "status": request.args.get("status"),
    })


def _get_move(mid):
    r = get("move_records", mid)
    if r is None:
        raise errors.not_found("Move record not found")
    return r


@bp.get("/api/move-records/<mid>")
def get_move_record(mid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_move(mid)))


@bp.post("/api/move-records/<mid>/void")
def void_move_record(mid):
    require_roles("GangForeman")
    r = _get_move(mid)
    if r["status"] != "RECORDED":
        raise errors.invalid_state("Only a RECORDED move record can be voided")
    r["status"] = "VOIDED"
    touch(r)
    gang = get("gang_orders", r["gang_order_id"])
    services.recompute_vessel_actuals(services.gang_vessel(gang))
    return ok(pub(r))
