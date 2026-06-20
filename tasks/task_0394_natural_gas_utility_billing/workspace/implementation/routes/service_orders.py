"""Service order endpoints (PRD §3.3, §3.9, §3.10)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_INVALID_STATE,
    ERR_ORDER_NOT_DUE,
    ERR_MISSING_COMPLETION_INDEX,
    ERR_INDEX_ROLLBACK,
    ERR_WINTER_MORATORIUM,
    ERR_EMERGENCY_HOLD,
    ERR_RECONNECT_BALANCE_DUE,
    ERR_RECONNECT_DEPOSIT_REQUIRED,
    ERR_INVALID_REQUEST,
    err,
)
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    require_enum,
    optional_number,
    attach_common_fields,
    attach_event_fields,
    bump,
    parse_dt,
    to_iso,
    paginate,
)
from services.serialize import view_service_order
from services import lookup, calc

bp = Blueprint("service_orders", __name__)


@bp.route("/service-orders", methods=["POST"])
def create_order():
    principal = authenticate()
    require_role(principal, {"CustomerService", "FieldTech"})
    with store.lock:
        body = get_body()
        require_fields(body, ["account_id", "order_type"])
        account_id = require_string(body, "account_id")
        order_type = require_enum(body, "order_type", {"METER_SET", "SHUTOFF", "RECONNECT"})

        account = lookup.get_account(account_id)

        premise_meter_id = body.get("premise_meter_id")
        if premise_meter_id is not None:
            if not isinstance(premise_meter_id, str):
                raise err(ERR_INVALID_REQUEST, "premise_meter_id must be a string")
            lookup.get_meter(premise_meter_id)

        scheduled_date = body.get("scheduled_date")
        if scheduled_date is not None:
            scheduled_date = to_iso(parse_dt(scheduled_date))
        else:
            scheduled_date = store.clock["current_utc"]

        rec = {
            "account_id": account_id,
            "premise_meter_id": premise_meter_id,
            "order_type": order_type,
            "status": "SCHEDULED",
            "scheduled_date": scheduled_date,
            "completed_index": None,
        }
        attach_common_fields(rec)
        store.service_orders[rec["id"]] = rec
        return success(view_service_order(rec), 201)


@bp.route("/service-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    order = lookup.get_service_order(order_id)
    require_account_ownership(principal, order["account_id"])
    return success(view_service_order(order), 200)


@bp.route("/service-orders", methods=["GET"])
def list_orders():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    account_id = request.args.get("account_id")
    premise_meter_id = request.args.get("premise_meter_id")
    records = list(store.service_orders.values())
    if account_id is not None:
        records = [o for o in records if o["account_id"] == account_id]
    if premise_meter_id is not None:
        records = [o for o in records if o.get("premise_meter_id") == premise_meter_id]
    if principal.role == "Account":
        records = [o for o in records if o["account_id"] == principal.user_id]
    page, list_meta = paginate(records)
    return success([view_service_order(o) for o in page], 200, list_meta=list_meta)


@bp.route("/service-orders/<order_id>/dispatch", methods=["POST"])
def dispatch_order(order_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        order = lookup.get_service_order(order_id)
        if order["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Order is not SCHEDULED")
        # scheduled_date must be reached relative to the clock.
        if parse_dt(order["scheduled_date"]) > calc.clock_now():
            raise err(ERR_ORDER_NOT_DUE, "Order scheduled_date not yet reached")
        order["status"] = "DISPATCHED"
        bump(order)
        return success(view_service_order(order), 200)


@bp.route("/service-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        order = lookup.get_service_order(order_id)
        if order["status"] not in ("SCHEDULED", "DISPATCHED"):
            raise err(ERR_INVALID_STATE, "Order cannot be cancelled from its current state")
        order["status"] = "CANCELLED"
        bump(order)
        return success(view_service_order(order), 200)


@bp.route("/service-orders/<order_id>/complete", methods=["POST"])
def complete_order(order_id):
    principal = authenticate()
    require_role(principal, {"FieldTech"})
    with store.lock:
        order = lookup.get_service_order(order_id)
        body = get_body()
        completed_index = optional_number(body, "completed_index", minimum=0)
        order_type = order["order_type"]

        # Request well-formedness (priority 4): completed_index required for
        # METER_SET and SHUTOFF (PRD §3.3 -> ERR_MISSING_COMPLETION_INDEX, 400).
        if order_type in ("METER_SET", "SHUTOFF") and completed_index is None:
            raise err(ERR_MISSING_COMPLETION_INDEX, "completed_index is required")

        # State check (priority 6): must be DISPATCHED.
        if order["status"] != "DISPATCHED":
            raise err(ERR_INVALID_STATE, "Order is not DISPATCHED")

        if order_type == "METER_SET":
            _complete_meter_set(order, completed_index)
        elif order_type == "SHUTOFF":
            _complete_shutoff(order, completed_index)
        elif order_type == "RECONNECT":
            _complete_reconnect(order)

        order["status"] = "COMPLETED"
        order["completed_index"] = completed_index
        bump(order)
        return success(view_service_order(order), 200)


def _complete_meter_set(order, completed_index):
    meter = lookup.get_meter(order["premise_meter_id"])
    if meter["status"] != "PENDING_SET":
        raise err(ERR_INVALID_STATE, "Meter is not PENDING_SET")
    # Index rollback (priority 9): completed_index >= install_index.
    if completed_index < meter["install_index"]:
        raise err(ERR_INDEX_ROLLBACK, "completed_index below install_index")
    meter["status"] = "SET"
    meter["install_index"] = completed_index
    bump(meter)


def _complete_shutoff(order, completed_index):
    account = lookup.get_account(order["account_id"])
    if account["service_status"] != "SHUTOFF_PENDING":
        raise err(ERR_INVALID_STATE, "Account is not SHUTOFF_PENDING")
    # Emergency hold (priority 7) then winter moratorium (priority 8).
    if lookup.account_has_active_emergency(account["id"]):
        raise err(ERR_EMERGENCY_HOLD, "Live hazard on the account blocks shutoff")
    if calc.winter_moratorium_in_effect():
        raise err(ERR_WINTER_MORATORIUM, "Winter moratorium in effect")

    meter = lookup.get_meter(order["premise_meter_id"]) if order.get("premise_meter_id") else None

    account["service_status"] = "DISCONNECTED"
    bump(account)
    if meter is not None:
        meter["status"] = "LOCKED"
        bump(meter)
        # Post a final ACTUAL read from the captured completion index.
        _post_final_read(meter, completed_index)


def _post_final_read(meter, reading_index):
    read_dt = calc.clock_now()
    ccf, therms, raw_delta = calc.compute_consumption(meter, reading_index, read_dt)
    if raw_delta < 0:
        # Index rollback already guarded for METER_SET; for the final shutoff
        # read, clamp to non-negative consumption rather than reject after the
        # state transition committed.
        ccf = max(0, ccf)
        therms = max(0.0, therms)
    rec = {
        "premise_meter_id": meter["id"],
        "account_id": meter["account_id"],
        "read_date": to_iso(read_dt),
        "reading_index": reading_index,
        "read_type": "ACTUAL",
        "status": "POSTED",
        "ccf_consumed": ccf,
        "therms_consumed": therms,
        "bill_id": None,
    }
    attach_event_fields(rec)
    store.meter_reads[rec["id"]] = rec


def _complete_reconnect(order):
    account = lookup.get_account(order["account_id"])
    if account["service_status"] != "DISCONNECTED":
        raise err(ERR_INVALID_STATE, "Account is not DISCONNECTED")
    # Reconnect prerequisites (priority 12).
    if calc.account_past_due_cents(account["id"]) != 0:
        raise err(ERR_RECONNECT_BALANCE_DUE, "Past-due balance must be cleared before reconnect")
    has_deposit = any(
        d["account_id"] == account["id"] and d["reason"] == "RECONNECT"
        and d["status"] in ("HELD", "WAIVED")
        for d in store.deposits.values()
    )
    if not has_deposit:
        raise err(ERR_RECONNECT_DEPOSIT_REQUIRED, "A HELD or WAIVED reconnect deposit is required")

    meter = lookup.get_meter(order["premise_meter_id"]) if order.get("premise_meter_id") else None
    account["service_status"] = "ACTIVE"
    bump(account)
    account["consecutive_ontime_payments"] = 0
    if meter is not None and meter["status"] == "LOCKED":
        meter["status"] = "SET"
        bump(meter)
