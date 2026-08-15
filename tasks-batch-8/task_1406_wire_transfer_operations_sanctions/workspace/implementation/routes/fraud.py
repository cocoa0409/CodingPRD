"""Fraud holds and the customer confirmation window (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint

from db import STORE, base_entity, iso, now, parse_dt, pub, touch
from errors import (
    ERR_FRAUD_HOLD_WINDOW_EXPIRED,
    ERR_INVALID_STATE,
    ERR_WIRE_ON_HOLD,
    ApiError,
)
from listing import list_response
from middleware import ALL_INTERNAL, get_body, require_roles, validate_body
from response import ok
from services import (
    _cancel_wire_for_fraud,
    _freeze_customer_for_fraud,
    audit,
    get_or_404,
    lazy_eval_hold,
    lazy_eval_wire,
)

bp = Blueprint("fraud", __name__, url_prefix="/wire-ops")

_REASON_CODES = {"ACCOUNT_TAKEOVER", "VELOCITY", "MULE_SUSPECT", "PHISHING"}


@bp.post("/wires/<wid>/fraud-holds")
def place_hold(wid):
    uid, role = require_roles("FraudAnalyst")
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    data = get_body()
    validate_body(data, {
        "reason_code": ("str", True, _REASON_CODES),
        "note": ("str", True, None),
    })
    if wire["status"] != "APPROVED":
        raise ApiError(*ERR_INVALID_STATE, "A fraud hold can be placed only on an APPROVED wire.")
    if wire["hold_reason_code"] is not None:
        raise ApiError(*ERR_WIRE_ON_HOLD, "The wire already carries a hold.")
    wire["hold_reason_code"] = "FRAUD_HOLD"
    touch(wire)
    placed = now()
    hold = base_entity()
    hold.update({
        "wire_id": wid,
        "reason_code": data["reason_code"],
        "note": data["note"],
        "placed_by": uid,
        "status": "OPEN",
        "confirmation_window_hours": 24,
        "expires_at": iso(placed + timedelta(hours=24)),
        "resolution": "NONE",
    })
    STORE.fraud_holds[hold["id"]] = hold
    audit("fraud.hold_place", "FraudHold", hold["id"], wid,
          "status: -> OPEN; wire hold_reason_code -> FRAUD_HOLD",
          actor_user_id=uid, actor_role=role)
    return ok(pub(hold), 201)


@bp.get("/wires/<wid>/fraud-holds")
def list_holds(wid):
    require_roles(*ALL_INTERNAL)
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    items = [h for h in STORE.fraud_holds.values() if h["wire_id"] == wid]
    return list_response(items)


@bp.get("/fraud-holds/<hid>")
def get_hold(hid):
    require_roles(*ALL_INTERNAL)
    hold = get_or_404(STORE.fraud_holds, hid, "fraud hold")
    lazy_eval_hold(hold)
    return ok(pub(hold))


@bp.post("/fraud-holds/<hid>/customer-confirm")
def customer_confirm(hid):
    uid, role = require_roles("FraudAnalyst")
    hold = get_or_404(STORE.fraud_holds, hid, "fraud hold")
    data = get_body()
    validate_body(data, {"confirmation": ("str", True, {"LEGITIMATE", "FRAUDULENT"})})
    if hold["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Only an OPEN fraud hold can be confirmed.")
    # Strict window: at or after expires_at the hold has already auto-lapsed.
    if now() >= parse_dt(hold["expires_at"]):
        lazy_eval_hold(hold)
        raise ApiError(*ERR_FRAUD_HOLD_WINDOW_EXPIRED,
                       "The customer confirmation window has expired.")
    wire = STORE.wires[hold["wire_id"]]
    if data["confirmation"] == "LEGITIMATE":
        hold["status"] = "CLEARED"
        hold["resolution"] = "CUSTOMER_CONFIRMED"
        if wire["hold_reason_code"] == "FRAUD_HOLD":
            wire["hold_reason_code"] = None
        touch(wire)
        touch(hold)
        audit("fraud.cleared", "FraudHold", hid, wire["id"],
              "status: OPEN -> CLEARED (CUSTOMER_CONFIRMED); wire remains APPROVED",
              actor_user_id=uid, actor_role=role)
    else:  # FRAUDULENT
        hold["status"] = "CONFIRMED_FRAUD"
        hold["resolution"] = "CUSTOMER_DENIED"
        touch(hold)
        _cancel_wire_for_fraud(wire)
        account = STORE.accounts[wire["ordering_account_id"]]
        customer = STORE.customers[account["customer_id"]]
        _freeze_customer_for_fraud(customer)
        audit("fraud.confirmed", "FraudHold", hid, wire["id"],
              "status: OPEN -> CONFIRMED_FRAUD (CUSTOMER_DENIED); wire CANCELLED; customer FROZEN",
              actor_user_id=uid, actor_role=role)
    return ok(pub(hold))
