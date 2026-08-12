"""CoreReturn endpoints: receive, inspect, waive-penalty."""

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS
from calc import core_penalty_final, ceil_div, DAY_S
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CORE_RETURN_NOT_FOUND, ERR_DUPLICATE_SERIAL,
                    ERR_WAIVER_EXCEEDS_PENALTY)
from helpers import (new_record, touch, get_or_404, bump_unit_status,
                     post_ledger, ser_core_return, sort_asc,
                     maybe_close_order)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_enum, fmt_dt, bad)

bp = Blueprint("core_returns", __name__)

VERDICTS = {"ACCEPTED", "ACCEPTED_WITH_PENALTY", "REJECTED"}


@bp.get("/aog/core-returns")
def list_core_returns():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["core_returns"].values())
    if role == "CustomerContact":
        recs = [c for c in recs if c["customer_id"] == uid]
    q = request.args
    if q.get("order_line_id") is not None:
        recs = [c for c in recs
                if c["order_line_id"] == q.get("order_line_id")]
    if q.get("customer_id") is not None:
        recs = [c for c in recs if c["customer_id"] == q.get("customer_id")]
    if q.get("status") is not None:
        recs = [c for c in recs if c["status"] == q.get("status")]
    return paged([ser_core_return(c) for c in sort_asc(recs)], limit, offset)


@bp.get("/aog/core-returns/<cid>")
def get_core_return(cid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("core_returns", cid, ERR_CORE_RETURN_NOT_FOUND,
                     "CoreReturn")
    return success(ser_core_return(rec))


def _order_of_core_return(cr):
    line = store["order_lines"].get(cr["order_line_id"])
    return store["orders"].get(line["order_id"]) if line else None


@bp.post("/aog/core-returns/<cid>/receive")
def receive_core_return(cid):
    require_roles("WarehouseOperator")
    cr = get_or_404("core_returns", cid, ERR_CORE_RETURN_NOT_FOUND,
                    "CoreReturn")
    body = get_body()
    serial = as_str(req_present(body, "core_serial_number"),
                    "core_serial_number")
    if cr["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OPEN or OVERDUE core return can be received")
    line = store["order_lines"].get(cr["order_line_id"])
    part_id = line["part_id"] if line else None
    for u in store["units"].values():
        if u["part_id"] == part_id and u["serial_number"] == serial:
            raise ApiError(ERR_DUPLICATE_SERIAL, 409,
                           "serial_number already exists for this part")
    now = clock.current
    delta_s = (now - cr["_due_dt"]).total_seconds()
    days_overdue = 0 if delta_s <= 0 else ceil_div(delta_s, DAY_S)
    penalty = core_penalty_final(cr["core_value_cents"], days_overdue)
    out_unit = store["units"].get(line["allocated_unit_id"]) if line else None
    warehouse = out_unit["warehouse_code"] if out_unit else "INBOUND"
    inbound = new_record("units", {
        "part_id": part_id,
        "serial_number": serial,
        "condition": "AS_REMOVED",
        "trace_doc_level": "TRACE_MISSING",
        "warehouse_code": warehouse,
        "status": "UNDER_INSPECTION",
        "reserved_by_request_id": None,
    })
    cr["received_at"] = fmt_dt(now)
    cr["_received_dt"] = now
    cr["days_overdue"] = days_overdue
    cr["penalty_cents"] = penalty
    cr["status"] = "RECEIVED"
    cr["_inbound_unit_id"] = inbound["id"]
    touch(cr)
    return success(ser_core_return(cr))


@bp.post("/aog/core-returns/<cid>/inspect")
def inspect_core_return(cid):
    require_roles("WarehouseOperator")
    cr = get_or_404("core_returns", cid, ERR_CORE_RETURN_NOT_FOUND,
                    "CoreReturn")
    body = get_body()
    verdict = req_present(body, "verdict")
    if verdict not in VERDICTS:
        bad("verdict must be ACCEPTED, ACCEPTED_WITH_PENALTY or REJECTED")
    if cr["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a RECEIVED core return can be inspected")
    if verdict == "REJECTED" and not body.get("reject_reason"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "reject_reason is required for a REJECTED verdict")
    if verdict == "ACCEPTED_WITH_PENALTY" and cr["penalty_cents"] <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ACCEPTED_WITH_PENALTY requires a positive penalty")
    unit = store["units"].get(cr.get("_inbound_unit_id"))
    if verdict == "ACCEPTED":
        cr["refunded_cents"] = cr["core_value_cents"]
        cr["penalty_retained_cents"] = 0
        cr["forfeited_cents"] = 0
        if unit is not None and unit["status"] == "UNDER_INSPECTION":
            bump_unit_status(unit, "AVAILABLE")
    elif verdict == "ACCEPTED_WITH_PENALTY":
        retained = cr["penalty_cents"] - cr["penalty_waived_cents"]
        cr["penalty_retained_cents"] = retained
        cr["refunded_cents"] = cr["core_value_cents"] - retained
        cr["forfeited_cents"] = 0
        if unit is not None and unit["status"] == "UNDER_INSPECTION":
            bump_unit_status(unit, "AVAILABLE")
    else:  # REJECTED
        cr["forfeited_cents"] = cr["core_value_cents"] - \
            cr["penalty_waived_cents"]
        cr["refunded_cents"] = 0
        cr["penalty_retained_cents"] = cr["penalty_waived_cents"]
        if unit is not None and unit["status"] == "UNDER_INSPECTION":
            bump_unit_status(unit, "QUARANTINED")
    cr["verdict"] = verdict
    cr["status"] = "SETTLED"
    touch(cr)
    if cr["refunded_cents"] > 0:
        post_ledger(cr["customer_id"], "CORE_REFUND_CREDIT",
                    cr["refunded_cents"], "CORE_RETURN", cr["id"])
    order = _order_of_core_return(cr)
    if order is not None:
        maybe_close_order(order)
    return success(ser_core_return(cr))


@bp.post("/aog/core-returns/<cid>/waive-penalty")
def waive_penalty(cid):
    require_roles("FinanceController")
    cr = get_or_404("core_returns", cid, ERR_CORE_RETURN_NOT_FOUND,
                    "CoreReturn")
    body = get_body()
    amount = as_int(req_present(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        bad("amount_cents must be positive")
    if cr["status"] not in ("OVERDUE", "RECEIVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Penalties can only be waived while OVERDUE or "
                       "RECEIVED")
    if amount > cr["penalty_cents"] - cr["penalty_waived_cents"]:
        raise ApiError(ERR_WAIVER_EXCEEDS_PENALTY, 402,
                       "Waiver exceeds the outstanding penalty")
    cr["penalty_waived_cents"] += amount
    touch(cr)
    post_ledger(cr["customer_id"], "WAIVER_CREDIT", amount, "CORE_RETURN",
                cr["id"])
    return success(ser_core_return(cr))
