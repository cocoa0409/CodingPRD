"""Fitting order endpoints: creation, lifecycle transitions, and the nested
adjustment-session + warranty-claim creation/listing under an order."""

from flask import Blueprint, request

from db import db
import serialize
import validate
import errors
from clock import clock
from timeutil import parse_iso, add_days, clock_date, parse_date
from middleware import require_auth, require_role, require_ownership, get_json_body
from response import object_response, array_response
from services.domain import get_or_404, append_ledger, recompute_consumed_allowance
from services.listing import list_page
from services import calculations as calc

bp = Blueprint("orders", __name__)

EAR_COUNTS = {1, 2}
ADJUST_REASONS = {"COMFORT", "RECALL_REPROGRAM", "GAIN_TUNE"}
CLAIM_TYPES = {"DEFECT", "LOSS", "DAMAGE"}


# ===========================================================================
# Creation + reads
# ===========================================================================
@bp.post("/clinic/orders")
def create_order():
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    body = get_json_body()
    patient_id = validate.require_str(body, "patient_id")
    evaluation_id = validate.require_str(body, "evaluation_id")
    device_model_id = validate.require_str(body, "device_model_id")
    ear_count = validate.require_in_set(body, "ear_count", EAR_COUNTS)
    allowance_benefit_id = validate.optional_str(body, "allowance_benefit_id")

    # Body FK existence, left-to-right in declared order.
    get_or_404(db.patients, patient_id)
    get_or_404(db.evaluations, evaluation_id)
    get_or_404(db.device_models, device_model_id)
    if allowance_benefit_id is not None:
        get_or_404(db.allowance_benefits, allowance_benefit_id)

    obj = {
        "patient_id": patient_id,
        "evaluation_id": evaluation_id,
        "device_model_id": device_model_id,
        "allowance_benefit_id": allowance_benefit_id,
        "ear_count": ear_count,
        "trial_started_at": None,
        "trial_deadline_at": None,
        "gross_price_cents": None,
        "allowance_applied_cents": 0,
        "patient_due_cents": None,
        "refund_cents": 0,
        "fitted_firmware_version": None,
        "status": "DRAFT",
    }
    db.stamp_create(obj)
    with db.lock:
        db.orders[obj["id"]] = obj
    return object_response(serialize.order(obj), 201)


@bp.get("/clinic/orders/<oid>")
def get_order(oid):
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin", "Patient"})
    obj = get_or_404(db.orders, oid)
    require_ownership(auth, obj["patient_id"])
    return object_response(serialize.order(obj))


@bp.get("/clinic/orders")
def list_orders():
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin"})
    a = request.args
    evaluation_id = a.get("evaluation_id")
    device_model_id = a.get("device_model_id")
    allowance_benefit_id = a.get("allowance_benefit_id")
    status = a.get("status")
    items = [o for o in db.orders.values()
             if (evaluation_id is None or o["evaluation_id"] == evaluation_id)
             and (device_model_id is None or o["device_model_id"] == device_model_id)
             and (allowance_benefit_id is None or o.get("allowance_benefit_id") == allowance_benefit_id)
             and (status is None or o["status"] == status)]
    page, limit, offset, total = list_page(a, items, serialize.order)
    return array_response(page, limit, offset, total)


# ===========================================================================
# Lifecycle transitions
# ===========================================================================
@bp.post("/clinic/orders/<oid>/start-trial")
def start_trial(oid):
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    with db.lock:
        order = get_or_404(db.orders, oid)
        if order["status"] != "DRAFT":
            raise errors.invalid_state("Order is not in DRAFT.")

        evaluation = db.evaluations.get(order["evaluation_id"])
        device = db.device_models.get(order["device_model_id"])
        # FKs were validated at creation; defensively guard.
        if evaluation is None or device is None:
            raise errors.not_found()

        # Business checks in the PRD-pinned order:
        # 1) evaluation belongs to same patient
        if evaluation["patient_id"] != order["patient_id"]:
            raise errors.ApiError(errors.ERR_EVALUATION_PATIENT_MISMATCH, 422,
                                  "Evaluation does not belong to the order's patient.")
        # 2) evaluation FINALIZED and candidate
        if evaluation["status"] != "FINALIZED" or not evaluation.get("candidate"):
            raise errors.ApiError(errors.ERR_NOT_A_CANDIDATE, 422,
                                  "Referenced evaluation is not a finalized candidate.")
        # 3) device ACTIVE and indicated
        if device["status"] != "ACTIVE" or not calc.device_indicated(device["min_severity"], evaluation["severity"]):
            raise errors.ApiError(errors.ERR_DEVICE_NOT_INDICATED, 422,
                                  "Device model is not indicated for this evaluation.")

        now = clock.now()
        order["trial_started_at"] = _iso(now)
        deadline = add_days(now, calc.TRIAL_PERIOD_DAYS)
        order["trial_deadline_at"] = _iso(deadline)
        order["status"] = "TRIAL"
        db.touch(order)
    return object_response(serialize.order(order))


@bp.post("/clinic/orders/<oid>/purchase")
def purchase(oid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    with db.lock:
        order = get_or_404(db.orders, oid)
        if order["status"] != "TRIAL":
            raise errors.invalid_state("Order is not in TRIAL.")

        now = clock.now()
        deadline = parse_iso(order["trial_deadline_at"])
        if deadline is not None and now > deadline:
            raise errors.ApiError(errors.ERR_TRIAL_EXPIRED, 422, "Trial window has closed.")

        benefit = None
        if order.get("allowance_benefit_id"):
            benefit = db.allowance_benefits.get(order["allowance_benefit_id"])
            if benefit is None:
                raise errors.not_found()
            # Benefit must be ACTIVE ...
            if benefit["status"] != "ACTIVE":
                raise errors.ApiError(errors.ERR_BENEFIT_INACTIVE, 422,
                                      "Allowance benefit is not ACTIVE.")
            # ... and within its period.
            period_end = parse_date(benefit["period_end"])
            if period_end is not None and clock_date(now) > period_end:
                raise errors.ApiError(errors.ERR_BENEFIT_EXPIRED, 422,
                                      "Allowance benefit period has ended.")

        device = db.device_models.get(order["device_model_id"])
        if device is None:
            raise errors.not_found()

        # Snapshot price basis.
        gross = device["list_price_cents"] * order["ear_count"]
        order["gross_price_cents"] = gross
        order["fitted_firmware_version"] = device["firmware_version"]

        # Allowance waterfall + patient due.
        allowance_applied = calc.benefit_waterfall(gross, benefit)
        order["allowance_applied_cents"] = allowance_applied
        coins = benefit["coinsurance_pct"] if benefit is not None else 0
        order["patient_due_cents"] = calc.patient_due(gross, allowance_applied, coins)

        order["status"] = "PURCHASED"
        db.touch(order)

        # Ledger: ORDER_PURCHASE (+gross), then ALLOWANCE_APPLIED (-applied) when > 0.
        append_ledger(order["patient_id"], "ORDER_PURCHASE", order["id"], gross,
                      "Device purchase")
        if allowance_applied > 0:
            append_ledger(order["patient_id"], "ALLOWANCE_APPLIED", order["id"],
                          -allowance_applied, "Allowance applied")

        # Cascade: recompute pool consumption + maybe EXHAUSTED.
        if benefit is not None:
            recompute_consumed_allowance(benefit)
    return object_response(serialize.order(order))


@bp.post("/clinic/orders/<oid>/return")
def return_order(oid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    with db.lock:
        order = get_or_404(db.orders, oid)
        if order["status"] not in ("TRIAL", "PURCHASED"):
            raise errors.invalid_state("Order cannot be returned from its current state.")

        device = db.device_models.get(order["device_model_id"])
        if device is None:
            raise errors.not_found()

        was_purchased = (order["status"] == "PURCHASED")
        now = clock.now()
        deadline = parse_iso(order["trial_deadline_at"]) if order.get("trial_deadline_at") else None
        within_window = True if deadline is None else (now <= deadline)

        if was_purchased and not within_window:
            raise errors.ApiError(errors.ERR_RETURN_WINDOW_CLOSED, 422,
                                  "Return window has closed.")

        refund = calc.return_refund(order, device, within_window, was_purchased)
        order["refund_cents"] = refund
        order["status"] = "RETURNED"
        db.touch(order)

        # Ledger: ORDER_RETURN amount = -refund.
        append_ledger(order["patient_id"], "ORDER_RETURN", order["id"], -refund,
                      "Order return")

        # Allowance release only for a purchased return.
        if was_purchased and order.get("allowance_benefit_id"):
            benefit = db.allowance_benefits.get(order["allowance_benefit_id"])
            if benefit is not None:
                recompute_consumed_allowance(benefit)
    return object_response(serialize.order(order))


@bp.post("/clinic/orders/<oid>/activate-warranty")
def activate_warranty(oid):
    auth = require_auth()
    require_role(auth, {"BillingClerk"})
    with db.lock:
        order = get_or_404(db.orders, oid)
        if order["status"] != "PURCHASED":
            raise errors.invalid_state("Order is not in PURCHASED.")
        now = clock.now()
        deadline = parse_iso(order["trial_deadline_at"]) if order.get("trial_deadline_at") else None
        if deadline is not None and now <= deadline:
            raise errors.ApiError(errors.ERR_TRIAL_NOT_CLOSED, 422,
                                  "Trial window has not yet closed.")
        order["status"] = "WARRANTY_ACTIVE"
        db.touch(order)
    return object_response(serialize.order(order))


@bp.post("/clinic/orders/<oid>/cancel")
def cancel_order(oid):
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    with db.lock:
        order = get_or_404(db.orders, oid)
        if order["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT order may be cancelled.")
        order["status"] = "CANCELLED"
        db.touch(order)
    return object_response(serialize.order(order))


# ===========================================================================
# Adjustment sessions (nested under order)
# ===========================================================================
@bp.post("/clinic/orders/<oid>/adjustments")
def create_adjustment(oid):
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    body = get_json_body()
    audiologist_user_id = validate.require_str(body, "audiologist_user_id")
    reason = validate.require_enum(body, "reason", ADJUST_REASONS)
    applied_firmware_version = validate.optional_str(body, "applied_firmware_version")
    recall_notice_id = validate.optional_str(body, "recall_notice_id")

    with db.lock:
        order = get_or_404(db.orders, oid)
        # Body FK: recall notice, when provided.
        recall = None
        if recall_notice_id is not None:
            recall = get_or_404(db.recalls, recall_notice_id)

        # State: adjustments are recorded against a WARRANTY_ACTIVE order.
        if order["status"] != "WARRANTY_ACTIVE":
            raise errors.invalid_state("Order is not WARRANTY_ACTIVE.")

        # RECALL_REPROGRAM firmware must equal the recall's target firmware.
        if reason == "RECALL_REPROGRAM":
            if recall is None:
                raise errors.ApiError(errors.ERR_FIRMWARE_MISMATCH, 422,
                                      "RECALL_REPROGRAM requires a recall_notice_id with matching firmware.")
            if applied_firmware_version != recall["target_firmware_version"]:
                raise errors.ApiError(errors.ERR_FIRMWARE_MISMATCH, 422,
                                      "applied_firmware_version must equal the recall's target_firmware_version.")

        obj = {
            "fitting_order_id": order["id"],
            "audiologist_user_id": audiologist_user_id,
            "reason": reason,
            "applied_firmware_version": applied_firmware_version,
            "recall_notice_id": recall_notice_id,
            "status": "COMPLETED",
        }
        db.stamp_create(obj)
        db.adjustments[obj["id"]] = obj
    return object_response(serialize.adjustment(obj), 201)


@bp.get("/clinic/orders/<oid>/adjustments")
def list_adjustments(oid):
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin"})
    get_or_404(db.orders, oid)
    reason = request.args.get("reason")
    status = request.args.get("status")
    items = [a for a in db.adjustments.values()
             if a["fitting_order_id"] == oid
             and (reason is None or a["reason"] == reason)
             and (status is None or a["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.adjustment)
    return array_response(page, limit, offset, total)


# ===========================================================================
# Warranty claims (creation + listing nested under order)
# ===========================================================================
@bp.post("/clinic/orders/<oid>/warranty-claims")
def create_warranty_claim(oid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "Patient"})
    order = get_or_404(db.orders, oid)
    require_ownership(auth, order["patient_id"])

    body = get_json_body()
    claim_type = validate.require_enum(body, "claim_type", CLAIM_TYPES)
    incident_date = validate.require_date(body, "incident_date")
    assessed_value = validate.require_int(body, "assessed_value_cents", minimum=1)

    with db.lock:
        # Claim is opened against a WARRANTY_ACTIVE order.
        if order["status"] != "WARRANTY_ACTIVE":
            raise errors.invalid_state("Order is not WARRANTY_ACTIVE.")
        obj = {
            "fitting_order_id": order["id"],
            "claim_type": claim_type,
            "incident_date": incident_date,
            "assessed_value_cents": assessed_value,
            "deductible_cents": None,
            "clinic_cost_cents": None,
            "status": "SUBMITTED",
        }
        db.stamp_create(obj)
        db.warranty_claims[obj["id"]] = obj
    return object_response(serialize.warranty_claim(obj), 201)


@bp.get("/clinic/orders/<oid>/warranty-claims")
def list_order_warranty_claims(oid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    order = get_or_404(db.orders, oid)
    require_ownership(auth, order["patient_id"])
    claim_type = request.args.get("claim_type")
    status = request.args.get("status")
    items = [c for c in db.warranty_claims.values()
             if c["fitting_order_id"] == oid
             and (claim_type is None or c["claim_type"] == claim_type)
             and (status is None or c["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.warranty_claim)
    return array_response(page, limit, offset, total)


def _iso(dt):
    from timeutil import now_iso
    return now_iso(dt)
