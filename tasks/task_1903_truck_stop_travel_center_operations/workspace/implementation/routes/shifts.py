"""Shifts, drops, payouts, close/reconcile/lock (PRD 3.8, 2.8)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_COUNT_SHORTAGE_UNAPPROVED, ERR_DROP_EXCEEDS_EXPECTED,
    ERR_DROP_MISMATCH, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_PAYOUT_EXCEEDS_EXPECTED, ERR_REGISTER_NOT_AVAILABLE,
    ERR_REMAINING_BELOW_FLOAT, ERR_SHIFT_NOT_OPEN,
)
from middleware import (
    authorized, check_segregation, scope_cashier_shift,
)
from response import success_object
from routes.helpers import list_from, list_response, public
from services import pricing
from services.core import (
    find_open_shift_for_register, new_record, recompute_register_posture,
    stamp, touch, adjust_shift_expected,
)
from util import new_id
from validate import (
    get_body, query_filter, req_enum, req_int, req_str, require_path_resource,
    valid_bool, valid_int,
)

bp = Blueprint("shifts", __name__)

SHIFT_LABELS = ["DAY", "NIGHT", "GRAVEYARD"]
SHIFT_STATUSES = ["OPEN", "CLOSED", "RECONCILED", "LOCKED"]
READ_ROLES = ["GeneralManager", "ShiftManager"]


@bp.post("/sites/<sid>/shifts")
def open_shift(sid):
    caller = authorized(["ShiftManager"])
    require_path_resource("sites", sid)
    body = get_body()
    register = None
    if body.get("register_id") is not None:
        register = db["registers"].get(body["register_id"]) \
            if isinstance(body.get("register_id"), str) else None
        if register is None:
            raise_error(ERR_NOT_FOUND, "register_id does not resolve")
    # p10: the register must have no other OPEN shift
    if register is not None and find_open_shift_for_register(register["id"]) is not None:
        raise_error(ERR_REGISTER_NOT_AVAILABLE, "register already has an OPEN shift")
    if register is None:
        raise_error(ERR_INVALID_REQUEST, "register_id is required")
    cashier_id = req_str(body, "cashier_user_id")
    label = req_enum(body, "shift_label", SHIFT_LABELS)
    rec = new_record("shifts", {
        "site_id": sid,
        "register_id": register["id"],
        "cashier_user_id": cashier_id,
        "shift_label": label,
        "opened_by_manager_id": caller.user_id,
        "closed_by_manager_id": None,
        "status": "OPEN",
        "opening_float_cents": register["float_cents"],
        "expected_cash_cents": register["float_cents"],
    })
    stamp(rec, "opened_at")
    recompute_register_posture(register)
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/shifts")
def list_shifts(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", SHIFT_STATUSES),
        "register_id": query_filter("register_id"),
    }
    return list_response("shifts", filters)


@bp.get("/shifts/<rid>")
def get_shift(rid):
    authorized(READ_ROLES + ["Cashier"])
    rec = require_path_resource("shifts", rid)
    return success_object(public(rec))


@bp.post("/shifts/<rid>/drops")
def record_drop(rid):
    caller = authorized(["Cashier"])
    shift = require_path_resource("shifts", rid)
    # p3: only the owning cashier may record a drop on this shift
    scope_cashier_shift(caller, shift)
    # p9: shift must be OPEN
    if shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "shift is not OPEN")
    body = get_body()
    amount = body.get("amount_cents")
    denoms = body.get("denominations")

    def denoms_wellformed(d):
        if not isinstance(d, dict) or not d:
            return False
        for k, v in d.items():
            try:
                int(k)
            except (TypeError, ValueError):
                return False
            if not valid_int(v) or v < 0:
                return False
        return True

    # p36: denominations map must sum exactly to amount_cents
    if valid_int(amount) and amount > 0 and denoms_wellformed(denoms):
        total = sum(int(k) * v for k, v in denoms.items())
        if total != amount:
            raise_error(ERR_DROP_MISMATCH, "denominations do not sum to amount_cents")
        # p37: drawer must keep at least the float
        if amount > shift["expected_cash_cents"] - shift["opening_float_cents"]:
            raise_error(ERR_DROP_EXCEEDS_EXPECTED,
                        "drop would leave the drawer below its opening float")
    # p41: shape validation
    if not valid_int(amount) or amount <= 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    if not denoms_wellformed(denoms):
        raise_error(ERR_INVALID_REQUEST,
                    "denominations must be a non-empty map of denomination cents to counts")
    drop = new_record("cash_drops", {
        "shift_id": shift["id"],
        "register_id": shift["register_id"],
        "amount_cents": amount,
        "denominations": {str(k): v for k, v in denoms.items()},
        "status": "POSTED",
    }, ledger=True)
    adjust_shift_expected(shift, -amount)
    return success_object(public(drop), status=201)


@bp.post("/shifts/<rid>/payouts")
def approve_payout(rid):
    caller = authorized(["ShiftManager"])
    shift = require_path_resource("shifts", rid)
    # p4: the approving manager must not be the shift's cashier
    check_segregation(caller, shift["cashier_user_id"], "payout approval")
    # p9: shift must be OPEN
    if shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "shift is not OPEN")
    body = get_body()
    amount = body.get("amount_cents")
    # p38: payout may not exceed the shift's expected cash
    if valid_int(amount) and amount > 0 and amount > shift["expected_cash_cents"]:
        raise_error(ERR_PAYOUT_EXCEEDS_EXPECTED, "payout exceeds expected cash")
    if not valid_int(amount) or amount <= 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be a positive integer")
    req_str(body, "reason")
    payout = new_record("payouts", {
        "shift_id": shift["id"],
        "register_id": shift["register_id"],
        "amount_cents": amount,
        "reason": body["reason"],
        "approved_by_manager_id": caller.user_id,
    }, ledger=True)
    adjust_shift_expected(shift, -amount)
    return success_object({
        "payout_id": payout["id"],
        "amount_cents": amount,
        "expected_cash_cents": shift["expected_cash_cents"],
    }, status=201)


@bp.post("/shifts/<rid>/close")
def close_shift(rid):
    caller = authorized(["ShiftManager"])
    shift = require_path_resource("shifts", rid)
    # p4: the closer must not be the opener
    check_segregation(caller, shift["opened_by_manager_id"], "shift close")
    # p9: close requires an OPEN shift
    if shift["status"] != "OPEN":
        raise_error(ERR_SHIFT_NOT_OPEN, "shift is not OPEN")
    body = get_body()
    counted = body.get("counted_cash_cents")
    approve_variance = body.get("approve_variance")
    # p39: drawer must still hold at least the float
    if shift["expected_cash_cents"] < shift["opening_float_cents"]:
        raise_error(ERR_REMAINING_BELOW_FLOAT, "expected cash is below the opening float")
    # p40: |counted - expected| > 500 requires approve_variance: true
    if valid_int(counted):
        variance = counted - shift["expected_cash_cents"]
        if abs(variance) > pricing.VARIANCE_TOLERANCE_CENTS and approve_variance is not True:
            raise_error(ERR_COUNT_SHORTAGE_UNAPPROVED,
                        "variance above 500 cents requires approve_variance: true")
    if not valid_int(counted) or counted < 0:
        raise_error(ERR_INVALID_REQUEST, "counted_cash_cents must be a non-negative integer")
    if approve_variance is not None and not valid_bool(approve_variance):
        raise_error(ERR_INVALID_REQUEST, "approve_variance must be a boolean")

    expected = shift["expected_cash_cents"]
    variance = counted - expected
    resolution = "BALANCED" if variance == 0 else ("OVERAGE" if variance > 0 else "SHORTAGE")
    deposit_total = max(0, expected - shift["opening_float_cents"])
    new_record("reconciliations", {
        "shift_id": shift["id"],
        "expected_cash_cents": expected,
        "counted_cash_cents": counted,
        "variance_cents": variance,
        "resolution": resolution,
        "deposit_total_cents": deposit_total,
    }, ledger=True)
    if deposit_total > 0:
        new_record("safe_deposits", {
            "shift_id": shift["id"],
            "register_id": shift["register_id"],
            "amount_cents": deposit_total,
            "status": "RECORDED",
        }, ledger=True)
    shift["status"] = "CLOSED"
    shift["closed_by_manager_id"] = caller.user_id
    stamp(shift, "closed_at")
    touch(shift)
    register = db["registers"].get(shift["register_id"])
    if register is not None:
        recompute_register_posture(register)
    return success_object(public(shift))


@bp.post("/shifts/<rid>/reconcile")
def reconcile_shift(rid):
    caller = authorized(["ShiftManager"])
    shift = require_path_resource("shifts", rid)
    # p4: the reconciler must not be the closer
    check_segregation(caller, shift["closed_by_manager_id"], "shift reconcile")
    if shift["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE, "shift is not CLOSED")
    shift["status"] = "RECONCILED"
    touch(shift)
    return success_object(public(shift))


@bp.post("/shifts/<rid>/lock")
def lock_shift(rid):
    authorized(["GeneralManager"])
    shift = require_path_resource("shifts", rid)
    if shift["status"] != "RECONCILED":
        raise_error(ERR_INVALID_STATE, "shift is not RECONCILED")
    shift["status"] = "LOCKED"
    touch(shift)
    return success_object(public(shift))


# ---------------------------------------------------------------------------
# Shift-attributed subcollections
# ---------------------------------------------------------------------------

@bp.get("/shifts/<rid>/reconciliations")
def shift_reconciliations(rid):
    authorized(READ_ROLES)
    shift = require_path_resource("shifts", rid)
    recs = [r for r in db["reconciliations"].values() if r["shift_id"] == shift["id"]]
    return list_from(recs)


@bp.get("/shifts/<rid>/cash-drops")
def shift_cash_drops(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    drops = [d for d in db["cash_drops"].values() if d["shift_id"] == shift["id"]]
    return list_from(drops)


@bp.get("/shifts/<rid>/safe-deposits")
def shift_safe_deposits(rid):
    authorized(READ_ROLES)
    shift = require_path_resource("shifts", rid)
    deposits = [d for d in db["safe_deposits"].values() if d["shift_id"] == shift["id"]]
    return list_from(deposits)


@bp.get("/shifts/<rid>/fuel-sales")
def shift_fuel_sales(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    sales = [s for s in db["fuel_sales"].values() if s["shift_id"] == shift["id"]]
    return list_from(sales)


@bp.get("/shifts/<rid>/parking-reservations")
def shift_parking(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    res = [r for r in db["parking_reservations"].values() if r["shift_id"] == shift["id"]]
    return list_from(res)


@bp.get("/shifts/<rid>/service-tickets")
def shift_service_tickets(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    tickets = [t for t in db["service_tickets"].values() if t["shift_id"] == shift["id"]]
    return list_from(tickets)


@bp.get("/shifts/<rid>/scale-tickets")
def shift_scale_tickets(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    tickets = [t for t in db["scale_tickets"].values() if t["shift_id"] == shift["id"]]
    return list_from(tickets)


@bp.get("/shifts/<rid>/store-sales")
def shift_store_sales(rid):
    authorized(READ_ROLES + ["Cashier"])
    shift = require_path_resource("shifts", rid)
    sales = [s for s in db["store_sales"].values() if s["shift_id"] == shift["id"]]
    return list_from(sales)
