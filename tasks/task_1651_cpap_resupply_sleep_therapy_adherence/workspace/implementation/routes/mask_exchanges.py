"""Mask fit exchange endpoints (PRD 3.6): window-anchored no-cost exchanges,
window + count checks on approval, and completion that resets the mask clock."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_FK_NOT_FOUND,
    ERR_EXCHANGE_NOT_REQUESTED,
    ERR_EXCHANGE_WINDOW_EXPIRED,
    ERR_EXCHANGE_LIMIT_REACHED,
    ERR_EXCHANGE_NOT_APPROVED,
    ERR_EXCHANGE_NOT_SHIPPED,
)
from middleware import authorized, ROLE_INTAKE, ROLE_RT
from response import success_object
from routes.helpers import get_one, list_response
from services.core import (
    new_record,
    public,
    touch,
    payer_for_patient,
    select_window_anchor,
    completed_exchanges_in_window,
)
from util import today, parse_date, add_days
from validate import get_body, require_path_resource, fk_if_present

bp = Blueprint("mask_exchanges", __name__, url_prefix="/sleep-therapy")

REASON_CODES = {"FIT_LEAK", "SKIN_IRRITATION", "WRONG_SIZE", "PRESSURE_INTOLERANCE"}


@bp.post("/mask-exchanges")
def create_mask_exchange():
    authorized([ROLE_INTAKE])
    body = get_body()

    # Priority 4: body FK existence (patient_id, device_enrollment_id, original_mask_plan_id).
    patient_id = body.get("patient_id")
    enrollment_id = body.get("device_enrollment_id")
    plan_id = body.get("original_mask_plan_id")
    patient = fk_if_present("patients", patient_id)
    if patient_id is not None and patient is None:
        raise_error(ERR_FK_NOT_FOUND, f"patient_id does not resolve: {patient_id}")
    enrollment = fk_if_present("device_enrollments", enrollment_id)
    if enrollment_id is not None and enrollment is None:
        raise_error(ERR_FK_NOT_FOUND, f"device_enrollment_id does not resolve: {enrollment_id}")
    plan = fk_if_present("component_supply_plans", plan_id)
    if plan_id is not None and plan is None:
        raise_error(ERR_FK_NOT_FOUND, f"original_mask_plan_id does not resolve: {plan_id}")

    if patient_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: patient_id")
    if enrollment_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: device_enrollment_id")
    if plan_id is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: original_mask_plan_id")
    reason = body.get("reason_code")
    if not isinstance(reason, str) or reason not in REASON_CODES:
        raise_error(ERR_INVALID_REQUEST, "missing or invalid enum field: reason_code")

    payer = payer_for_patient(patient)
    anchor = select_window_anchor(patient, enrollment, payer) if payer is not None else None

    rec = new_record("mask_exchanges", {
        "patient_id": patient_id,
        "device_enrollment_id": enrollment_id,
        "original_mask_plan_id": plan_id,
        "superseded_by_exchange_id": None,
        "reason_code": reason,
        "exchange_status": "REQUESTED",
        "window_anchor_on": anchor,
        "completed_on": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/mask-exchanges")
def list_mask_exchanges():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "device_enrollment_id": request.args.get("device_enrollment_id"),
        "original_mask_plan_id": request.args.get("original_mask_plan_id"),
        "superseded_by_exchange_id": request.args.get("superseded_by_exchange_id"),
        "exchange_status": request.args.get("exchange_status"),
    }
    return list_response("mask_exchanges", filters)


@bp.get("/mask-exchanges/<rid>")
def get_mask_exchange(rid):
    return get_one("mask_exchanges", rid)


@bp.post("/mask-exchanges/<rid>/approve")
def approve_exchange(rid):
    authorized([ROLE_RT])
    exchange = require_path_resource("mask_exchanges", rid)
    if exchange["exchange_status"] != "REQUESTED":
        raise_error(ERR_EXCHANGE_NOT_REQUESTED, "exchange must be in REQUESTED to approve")
    patient = db["patients"].get(exchange["patient_id"])
    payer = payer_for_patient(patient)
    # Window check first (inclusive: approval ON anchor + window days is valid).
    anchor = exchange.get("window_anchor_on")
    window_days = int(payer["mask_exchange_window_days"]) if payer else 0
    if anchor is None or today() > add_days(parse_date(anchor), window_days):
        raise_error(ERR_EXCHANGE_WINDOW_EXPIRED, "the no-cost exchange window has expired")
    # Count check: strict less-than on COMPLETED exchanges sharing this window.
    completed = completed_exchanges_in_window(exchange["patient_id"], anchor, exchange["id"])
    if payer is not None and len(completed) >= int(payer["max_exchanges_per_window"]):
        raise_error(ERR_EXCHANGE_LIMIT_REACHED,
                    "maximum no-cost exchanges for this window reached")
    exchange["exchange_status"] = "APPROVED"
    touch(exchange)
    return success_object(public(exchange))


@bp.post("/mask-exchanges/<rid>/ship")
def ship_exchange(rid):
    authorized([ROLE_INTAKE])
    exchange = require_path_resource("mask_exchanges", rid)
    if exchange["exchange_status"] != "APPROVED":
        raise_error(ERR_EXCHANGE_NOT_APPROVED, "exchange must be in APPROVED to ship")
    exchange["exchange_status"] = "SHIPPED"
    touch(exchange)
    return success_object(public(exchange))


@bp.post("/mask-exchanges/<rid>/complete")
def complete_exchange(rid):
    authorized([ROLE_INTAKE])
    exchange = require_path_resource("mask_exchanges", rid)
    if exchange["exchange_status"] != "SHIPPED":
        raise_error(ERR_EXCHANGE_NOT_SHIPPED, "exchange must be in SHIPPED to complete")

    current = today()
    exchange["exchange_status"] = "COMPLETED"
    exchange["completed_on"] = current.isoformat()
    touch(exchange)

    # An exchange resets the mask resupply clock.
    patient = db["patients"].get(exchange["patient_id"])
    payer = payer_for_patient(patient)
    plan = db["component_supply_plans"].get(exchange["original_mask_plan_id"])
    if plan is not None and payer is not None:
        plan["last_dispensed_on"] = current.isoformat()
        plan["next_eligible_on"] = add_days(
            current, int(payer["mask_cadence_days"])
        ).isoformat()
        touch(plan)

    # Supersession: the most recent prior un-superseded exchange points at this one.
    priors = [
        e for e in db["mask_exchanges"].values()
        if e["patient_id"] == exchange["patient_id"]
        and e["id"] != exchange["id"]
        and e.get("superseded_by_exchange_id") is None
    ]
    if priors:
        priors.sort(key=lambda e: e["_seq"], reverse=True)
        priors[0]["superseded_by_exchange_id"] = exchange["id"]
        touch(priors[0])

    # A mask-exchange completion advances the patient record (PRD 2.6).
    if patient is not None:
        touch(patient)
    return success_object(public(exchange))


@bp.post("/mask-exchanges/<rid>/deny")
def deny_exchange(rid):
    authorized([ROLE_RT])
    exchange = require_path_resource("mask_exchanges", rid)
    if exchange["exchange_status"] != "REQUESTED":
        raise_error(ERR_EXCHANGE_NOT_REQUESTED, "exchange must be in REQUESTED to deny")
    exchange["exchange_status"] = "DENIED"
    touch(exchange)
    return success_object(public(exchange))


@bp.post("/mask-exchanges/<rid>/cancel")
def cancel_exchange(rid):
    authorized([ROLE_INTAKE])
    exchange = require_path_resource("mask_exchanges", rid)
    if exchange["exchange_status"] not in ("REQUESTED", "APPROVED"):
        raise_error(ERR_EXCHANGE_NOT_REQUESTED,
                    "only REQUESTED or APPROVED exchanges can be cancelled")
    exchange["exchange_status"] = "CANCELLED"
    touch(exchange)
    return success_object(public(exchange))
