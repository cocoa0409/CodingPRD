"""Trial periods, return authorizations and fit exchanges."""

from flask import Blueprint

import calc
import services as svc
from auth import (ADMIN, CARE_OPS, COMPLIANCE, PATIENT, REIMBURSEMENT, authorize,
                  require_owner)
from bodyspec import Body, raw_body
from common import field, listed
from errors import ApiError
from resp import created, ok
from routes_order import DOMES, TIPS
from store import bump, db, days, now, table_rows

bp = Blueprint("trial", __name__)

GRADES = ("RESELLABLE", "REFURBISHABLE", "DAMAGED")


def _order_of_trial(trial):
    return db.device_orders.get(trial.get("device_order_id"))


def _pool_of_order(order):
    pool = db.inventory_pools.get(order.get("_dispatched_pool_id"))
    if pool is not None:
        return pool
    return svc.pool_for(order["model"], order["dome_size"], order["tip_type"])


# ------------------------------------------------------------- TrialPeriod
@bp.get("/trial-periods")
def list_trials():
    actor = authorize(PATIENT, CARE_OPS, COMPLIANCE, ADMIN)
    svc.touch_all_trials()
    return listed(table_rows(db.trial_periods),
                  {"device_order_id": field("device_order_id"),
                   "patient_id": field("patient_id"), "status": field("status")},
                  actor=actor)


@bp.get("/trial-periods/<trial_id>")
def get_trial(trial_id):
    actor = authorize(PATIENT, CARE_OPS, COMPLIANCE, ADMIN)
    trial = svc.find(db.trial_periods, trial_id)
    require_owner(actor, trial["patient_id"])
    svc.touch_trial(trial)
    return ok(trial)


@bp.post("/trial-periods/<trial_id>/extend")
def extend_trial(trial_id):
    authorize(CARE_OPS)
    trial = svc.find(db.trial_periods, trial_id)
    body = Body()
    extension = body.integer("extension_days", minimum=0, maximum=30)
    body.finish()
    total = int(trial.get("extension_days_granted") or 0) + extension
    if total > 30:
        raise ApiError("ERR_VALIDATION", "extension_days_granted may not exceed 30")
    svc.touch_trial(trial)
    if now() > trial["effective_end_utc"]:
        raise ApiError("ERR_TRIAL_WINDOW_CLOSED")
    svc.ensure_state(trial, "status", ("ACTIVE", "PAUSED"))
    trial["extension_days_granted"] = total
    calc.trial_days_used(trial)
    bump(trial)
    return ok(trial)


# ------------------------------------------------------ ReturnAuthorization
@bp.post("/trial-periods/<trial_id>/return-authorizations")
def create_return_auth(trial_id):
    actor = authorize(PATIENT)
    trial = svc.find(db.trial_periods, trial_id)
    require_owner(actor, trial["patient_id"])
    body = Body()
    expected = body.integer("expected_trial_period_version")
    body.finish()
    if expected != int(trial["version"]):
        raise ApiError("ERR_STALE_TRIAL_VERSION")
    svc.touch_trial(trial)
    if now() > trial["effective_end_utc"]:
        raise ApiError("ERR_TRIAL_WINDOW_CLOSED")
    svc.ensure_state(trial, "status", ("ACTIVE",), "trial_periods")
    order = _order_of_trial(trial)
    device = svc.device_for_order(order["id"]) if order else None
    if device is not None:
        for repair in db.repair_orders.values():
            if repair.get("device_id") == device["id"] and \
                    repair.get("status") in ("KIT_SENT", "RECEIVED", "IN_REPAIR"):
                raise ApiError("ERR_REPAIR_IN_PROGRESS_BLOCKS_RETURN")
    for exchange in db.fit_exchanges.values():
        if exchange.get("device_order_id") == order["id"] and \
                exchange.get("status") in ("RESERVED", "SHIPPED"):
            raise ApiError("ERR_EXCHANGE_IN_PROGRESS_BLOCKS_RETURN")
    auth = svc.new_row(db.return_authorizations, trial_period_id=trial["id"],
                       rma_code=db.next_rma(), status="ISSUED",
                       days_used_at_issue=int(trial.get("days_used") or 0),
                       restocking_variant="WAIVED", inspection_grade=None,
                       restocking_fee_cents=0, non_refundable_shipping_cents=0,
                       refund_amount_cents=0, received_at=None, settled_at=None,
                       return_deadline_utc=now() + days(calc.RETURN_DEADLINE_DAYS))
    trial["status"] = "RETURN_INITIATED"
    bump(trial)
    if order is not None:
        bump(order)
    return created(auth)


@bp.get("/trial-periods/<trial_id>/return-authorizations")
def list_trial_return_auths(trial_id):
    actor = authorize(PATIENT, CARE_OPS, COMPLIANCE, ADMIN)
    trial = svc.find(db.trial_periods, trial_id)
    require_owner(actor, trial["patient_id"])
    rows = [a for a in table_rows(db.return_authorizations)
            if a["trial_period_id"] == trial["id"]]
    for row in rows:
        svc.touch_return_auth(row)
    return listed(rows, {"status": field("status")}, owner_field=None)


def _auth_patient(auth):
    trial = db.trial_periods.get(auth.get("trial_period_id"))
    return trial.get("patient_id") if trial else None


@bp.get("/return-authorizations/<auth_id>")
def get_return_auth(auth_id):
    actor = authorize(PATIENT, CARE_OPS, COMPLIANCE, REIMBURSEMENT, ADMIN)
    auth = svc.find(db.return_authorizations, auth_id)
    require_owner(actor, _auth_patient(auth))
    svc.touch_return_auth(auth)
    return ok(auth)


@bp.post("/return-authorizations/<auth_id>/receive")
def receive_return(auth_id):
    authorize(CARE_OPS)
    auth = svc.find(db.return_authorizations, auth_id)
    svc.ensure_state(auth, "status", ("IN_TRANSIT",), "return_authorizations")
    if now() > auth["return_deadline_utc"]:
        raise ApiError("ERR_RETURN_DEADLINE_PASSED")
    auth["status"] = "RECEIVED"
    auth["received_at"] = now()
    bump(auth)
    return ok(auth)


@bp.post("/return-authorizations/<auth_id>/inspect")
def inspect_return(auth_id):
    authorize(CARE_OPS)
    auth = svc.find(db.return_authorizations, auth_id)
    body = Body()
    grade = body.enum("inspection_grade", GRADES)
    body.finish()
    svc.ensure_state(auth, "status", ("RECEIVED",), "return_authorizations")
    trial = db.trial_periods.get(auth["trial_period_id"])
    order = _order_of_trial(trial)
    auth["inspection_grade"] = grade
    calc.return_refund_settlement(auth, order, svc.pinned_policy(order))
    auth["status"] = "INSPECTED"
    bump(auth)
    if grade == "RESELLABLE":
        pool = _pool_of_order(order)
        if pool is not None:
            pool["dispatched_units"] = max(0, int(pool["dispatched_units"]) - 1)
            pool["on_hand_units"] = int(pool["on_hand_units"]) + 1
            bump(pool)
    return ok(auth)


@bp.post("/return-authorizations/<auth_id>/settle")
def settle_return(auth_id):
    authorize(CARE_OPS)
    auth = svc.find(db.return_authorizations, auth_id)
    svc.ensure_state(auth, "status", ("INSPECTED",), "return_authorizations")
    trial = db.trial_periods.get(auth["trial_period_id"])
    order = _order_of_trial(trial)
    if order is None or order["payment_status"] != "CAPTURED":
        raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    auth["status"] = "REFUND_SETTLED"
    auth["settled_at"] = now()
    bump(auth)
    svc.cascade_return_settlement(auth, trial, order)
    return ok(auth)


@bp.post("/return-authorizations/<auth_id>/void")
def void_return(auth_id):
    authorize(CARE_OPS)
    auth = svc.find(db.return_authorizations, auth_id)
    Body().string("reason_note", required=False, min_len=1)
    svc.ensure_state(auth, "status", ("ISSUED",), "return_authorizations")
    trial = db.trial_periods.get(auth["trial_period_id"])
    if trial is not None:
        calc.trial_days_used(trial)
        if now() > trial["effective_end_utc"]:
            raise ApiError("ERR_TRIAL_WINDOW_CLOSED")
    auth["status"] = "VOIDED"
    auth["restocking_fee_cents"] = 0
    auth["non_refundable_shipping_cents"] = 0
    auth["refund_amount_cents"] = 0
    bump(auth)
    if trial is not None and trial["status"] == "RETURN_INITIATED":
        trial["status"] = "ACTIVE"
        bump(trial)
    return ok(auth)


@bp.post("/return-authorizations/<auth_id>/waive-restocking")
def waive_restocking(auth_id):
    authorize(COMPLIANCE)
    auth = svc.find(db.return_authorizations, auth_id)
    Body().string("reason_note", required=False, min_len=1)
    if auth["status"] != "REFUND_SETTLED":
        raise ApiError("ERR_INVALID_STATE")
    if int(auth["restocking_fee_cents"]) <= 0:
        raise ApiError("ERR_INVALID_STATE")
    if auth.get("settled_at") is None or now() > auth["settled_at"] + days(30):
        raise ApiError("ERR_RESTOCKING_WAIVE_WINDOW_CLOSED")
    trial = db.trial_periods.get(auth["trial_period_id"])
    order = _order_of_trial(trial)
    auth["restocking_variant"] = "WAIVED"
    auth["restocking_fee_cents"] = 0
    auth["non_refundable_shipping_cents"] = 0
    auth["refund_amount_cents"] = int(order["captured_cents"]) if order else 0
    bump(auth)
    if order is not None:
        order["refunded_cents"] = int(order["captured_cents"])
        order["retained_cents"] = 0
        order["payment_status"] = "REFUNDED"
        svc.recompute_order_cash(order)
        bump(order)
    return ok(auth)


# --------------------------------------------------------------- FitExchange
@bp.post("/device-orders/<order_id>/fit-exchanges")
def create_fit_exchange(order_id):
    actor = authorize(PATIENT)
    order = svc.find(db.device_orders, order_id)
    require_owner(actor, order["patient_id"])
    data = raw_body()
    target = None
    to_dome = data.get("to_dome_size")
    to_tip = data.get("to_tip_type")
    if isinstance(to_dome, str) and isinstance(to_tip, str) and to_dome in DOMES \
            and to_tip in TIPS:
        target = svc.pool_for(order["model"], to_dome, to_tip)
        if target is None:
            raise ApiError("ERR_INVENTORY_POOL_NOT_FOUND")
    body = Body(data)
    to_dome = body.enum("to_dome_size", DOMES)
    to_tip = body.enum("to_tip_type", TIPS)
    expected = body.integer("expected_device_order_version")
    allow_backorder = body.boolean("allow_backorder", required=False, default=False)
    body.finish()
    if target is None:
        target = svc.pool_for(order["model"], to_dome, to_tip)
        if target is None:
            raise ApiError("ERR_INVENTORY_POOL_NOT_FOUND")
    if expected != int(order["version"]):
        raise ApiError("ERR_STALE_ORDER_VERSION")
    svc.ensure_state(order, "fulfillment_status", ("DELIVERED",), "device_orders")
    if to_dome == order["dome_size"] and to_tip == order["tip_type"]:
        raise ApiError("ERR_SAME_FIT_CONFIGURATION")
    if target.get("is_discontinued"):
        raise ApiError("ERR_POOL_DISCONTINUED")

    trial = svc.trial_for_order(order["id"])
    if trial is not None:
        svc.touch_trial(trial)
    plan = svc.plan_for_order(order["id"])
    source = _pool_of_order(order)
    trial_ok = trial is not None and trial.get("status") in ("ACTIVE", "PAUSED")
    plan_ok = plan is not None and plan.get("status") in ("ACTIVE", "PAST_DUE")
    ordinal, fee = calc.fit_exchange_fee(order, trial, plan)

    def rejected(reason):
        return created(svc.new_row(
            db.fit_exchanges, device_order_id=order["id"],
            from_inventory_pool_id=source["id"] if source else None,
            to_inventory_pool_id=None, to_dome_size=to_dome, to_tip_type=to_tip,
            status="REJECTED", exchange_ordinal=ordinal, exchange_fee_cents=0,
            rejection_reason=reason))

    if not trial_ok and not plan_ok:
        return rejected("TRIAL_NOT_ACTIVE")
    if int(target["on_hand_units"]) < 1:
        if not allow_backorder:
            raise ApiError("ERR_INVENTORY_POOL_DEPLETED")
        return rejected("POOL_DEPLETED")

    exchange = svc.new_row(db.fit_exchanges, device_order_id=order["id"],
                           from_inventory_pool_id=source["id"] if source else None,
                           to_inventory_pool_id=target["id"], to_dome_size=to_dome,
                           to_tip_type=to_tip, status="RESERVED", exchange_ordinal=ordinal,
                           exchange_fee_cents=fee, rejection_reason=None)
    target["on_hand_units"] = int(target["on_hand_units"]) - 1
    target["reserved_units"] = int(target["reserved_units"]) + 1
    bump(target)
    if fee:
        svc.charge_plan(plan, fee)
    bump(order)
    return created(exchange)


@bp.get("/fit-exchanges")
def list_fit_exchanges():
    actor = authorize(PATIENT, CARE_OPS, ADMIN)
    rows = table_rows(db.fit_exchanges)
    if actor.is_patient:
        rows = [x for x in rows
                if (db.device_orders.get(x["device_order_id"]) or {}).get("patient_id")
                == actor.user_id]
    return listed(rows,
                  {"device_order_id": field("device_order_id"),
                   "from_inventory_pool_id": field("from_inventory_pool_id"),
                   "to_inventory_pool_id": field("to_inventory_pool_id"),
                   "status": field("status")},
                  owner_field=None)


def _exchange_patient(exchange):
    order = db.device_orders.get(exchange["device_order_id"])
    return order.get("patient_id") if order else None


@bp.get("/fit-exchanges/<exchange_id>")
def get_fit_exchange(exchange_id):
    actor = authorize(PATIENT, CARE_OPS, ADMIN)
    exchange = svc.find(db.fit_exchanges, exchange_id)
    require_owner(actor, _exchange_patient(exchange))
    return ok(exchange)


@bp.post("/fit-exchanges/<exchange_id>/ship")
def ship_fit_exchange(exchange_id):
    authorize(CARE_OPS)
    exchange = svc.find(db.fit_exchanges, exchange_id)
    svc.ensure_state(exchange, "status", ("RESERVED",), "fit_exchanges")
    exchange["status"] = "SHIPPED"
    bump(exchange)
    return ok(exchange)


@bp.post("/fit-exchanges/<exchange_id>/confirm")
def confirm_fit_exchange(exchange_id):
    actor = authorize(PATIENT)
    exchange = svc.find(db.fit_exchanges, exchange_id)
    require_owner(actor, _exchange_patient(exchange))
    svc.ensure_state(exchange, "status", ("SHIPPED",), "fit_exchanges")
    order = db.device_orders.get(exchange["device_order_id"])
    target = db.inventory_pools.get(exchange.get("to_inventory_pool_id"))
    source = db.inventory_pools.get(exchange.get("from_inventory_pool_id"))
    exchange["status"] = "COMPLETED"
    bump(exchange)
    if order is not None:
        order["dome_size"] = exchange["to_dome_size"]
        order["tip_type"] = exchange["to_tip_type"]
        if target is not None:
            order["_dispatched_pool_id"] = target["id"]
        bump(order)
    if target is not None:
        target["reserved_units"] = max(0, int(target["reserved_units"]) - 1)
        target["dispatched_units"] = int(target["dispatched_units"]) + 1
        bump(target)
    if source is not None and source is not target:
        source["dispatched_units"] = max(0, int(source["dispatched_units"]) - 1)
        source["on_hand_units"] = int(source["on_hand_units"]) + 1
        bump(source)
    return ok(exchange)


@bp.post("/fit-exchanges/<exchange_id>/cancel")
def cancel_fit_exchange(exchange_id):
    actor = authorize(PATIENT, CARE_OPS)
    exchange = svc.find(db.fit_exchanges, exchange_id)
    require_owner(actor, _exchange_patient(exchange))
    Body().string("reason_note", required=False, min_len=1)
    # §3.6: cancellation is "available to the patient from RESERVED and to a care
    # operator from SHIPPED".
    allowed = ("RESERVED",) if actor.is_patient else ("SHIPPED",)
    svc.ensure_state(exchange, "status", allowed, "fit_exchanges")
    order = db.device_orders.get(exchange["device_order_id"])
    if exchange["status"] == "SHIPPED":
        trial = svc.trial_for_order(order["id"]) if order else None
        if trial is not None and trial.get("status") == "RETURN_SETTLED":
            raise ApiError("ERR_DEPENDENT_STATE_NOT_READY")
    target = db.inventory_pools.get(exchange.get("to_inventory_pool_id"))
    exchange["status"] = "CANCELLED"
    bump(exchange)
    if target is not None:
        target["reserved_units"] = max(0, int(target["reserved_units"]) - 1)
        target["on_hand_units"] = int(target["on_hand_units"]) + 1
        bump(target)
    fee = int(exchange.get("exchange_fee_cents") or 0)
    if fee and order is not None:
        svc.credit_plan(svc.plan_for_order(order["id"]), fee)
    return ok(exchange)
