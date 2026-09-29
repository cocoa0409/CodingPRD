"""Test purchases: ordering, serial capture and outcome confirmation (PRD §3.8)."""

from flask import Blueprint

import lookup
from auth import ROLE_MONITORING_ANALYST, STAFF_AND_DISTRIBUTOR, authenticate
from calc import refresh_review_required
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_dt, now_iso, parse_iso, serialize, store, touch
from validate import body, req_dt, req_enum, req_int, req_str

bp = Blueprint("test_purchases", __name__)

OUTCOMES = ["UNAUTHORIZED", "AUTHORIZED"]
TRACEABLE_STATUSES = ("SHIPPED_TO_DISTRIBUTOR", "SHIPPED_TO_RESELLER")


@bp.post("/test-purchases")
def order_test_purchase():
    ctx = authenticate([ROLE_MONITORING_ANALYST])
    b = body()
    observation_id = req_str(b, "observation_id")
    ordered_at = req_dt(b, "ordered_at")
    purchase_price_cents = req_int(b, "purchase_price_cents", 1, None)
    if parse_iso(ordered_at) > now_dt():
        fail("ERR_VALIDATION", "ordered_at must be at or before the current logical clock.")
    lookup.observation(observation_id)

    row = new_row({
        "observation_id": observation_id,
        "ordered_at": ordered_at,
        "purchase_price_cents": purchase_price_cents,
        "purchaser_user_id": ctx.user_id,
        "status": "ORDERED",
        "captured_serial_number": None,
        "traced_serial_unit_id": None,
        "outcome_reason": None,
    })
    store.test_purchases[row["id"]] = row
    return created(serialize(row))


@bp.post("/test-purchases/<test_purchase_id>/serial-capture")
def serial_capture(test_purchase_id):
    authenticate([ROLE_MONITORING_ANALYST])
    b = body()
    serial_number = req_str(b, "serial_number", 1, 40)
    purchase = lookup.test_purchase(test_purchase_id)

    unit = None
    for candidate in store.serial_units.values():
        if candidate["serial_number"] == serial_number:
            unit = candidate
            break
    if unit is None:
        fail("ERR_SERIAL_NOT_REGISTERED", "The submitted serial matches no registered unit.")
    if purchase["status"] != "ORDERED":
        fail("ERR_INVALID_STATE", "Only an ORDERED test purchase may record a serial.")
    if unit["status"] not in TRACEABLE_STATUSES:
        fail("ERR_SERIAL_NOT_TRACEABLE", "The named unit is not in a traceable custody state.")

    purchase["status"] = "SERIAL_CAPTURED"
    purchase["captured_serial_number"] = serial_number
    purchase["traced_serial_unit_id"] = unit["id"]
    touch(purchase)
    return ok(serialize(purchase))


@bp.post("/test-purchases/<test_purchase_id>/confirm-outcome")
def confirm_outcome(test_purchase_id):
    authenticate([ROLE_MONITORING_ANALYST])
    b = body()
    outcome = req_enum(b, "outcome", OUTCOMES)
    outcome_reason = req_str(b, "outcome_reason", 1, None)
    purchase = lookup.test_purchase(test_purchase_id)
    if purchase["status"] != "SERIAL_CAPTURED":
        fail("ERR_INVALID_STATE", "Only a SERIAL_CAPTURED test purchase may be confirmed.")

    if outcome == "AUTHORIZED":
        purchase["status"] = "CLEARED"
        purchase["outcome_reason"] = outcome_reason
        touch(purchase)
        return ok(serialize(purchase))

    if not purchase.get("traced_serial_unit_id"):
        fail("ERR_INVALID_STATE",
             "An unauthorized finding requires a traced serialized unit.")
    purchase["status"] = "CONFIRMED_UNAUTHORIZED"
    purchase["outcome_reason"] = outcome_reason
    touch(purchase)

    observation = store.observations.get(purchase["observation_id"])
    if observation is not None:
        observation["unauthorized_seller_confirmed"] = True
        touch(observation)
    unit = store.serial_units.get(purchase["traced_serial_unit_id"])
    if unit is not None:
        unit["status"] = "TRACED_UNAUTHORIZED"
        unit["traced_at"] = now_iso()
        touch(unit)
        reseller = store.resellers.get(unit.get("downstream_reseller_id"))
        if reseller is not None:
            refresh_review_required(reseller)
    return ok(serialize(purchase))


@bp.get("/test-purchases/<test_purchase_id>")
def read_test_purchase(test_purchase_id):
    authenticate(STAFF_AND_DISTRIBUTOR)
    return ok(serialize(lookup.test_purchase(test_purchase_id)))


@bp.get("/test-purchases")
def list_test_purchases():
    authenticate(STAFF_AND_DISTRIBUTOR)
    rows = lookup.filtered("test_purchases", {
        "observation_id": "observation_id",
        "traced_serial_unit_id": "traced_serial_unit_id",
        "status": "status",
    })
    return ok_list(rows)
