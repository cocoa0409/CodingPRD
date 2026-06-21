"""PaymentPlan endpoints, OCC, schedule, and state machine (PRD §2.7, §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CLAIM_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PATIENT_NOT_FOUND,
    ERR_PAYMENT_PLAN_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
)
from middleware import ROLE_BILLING, ROLE_FRONT_DESK, ROLE_PATIENT
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import calculations, common

bp = Blueprint("payment_plans", __name__)


@bp.post("/payment-plans")
def create_payment_plan():
    guard([ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, ["patient_id", "claim_id", "installment_count", "expected_claim_version"])
    # existence (body FKs)
    patient_id = common.require_string(body, "patient_id")
    common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    claim_id = common.require_string(body, "claim_id")
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)

    # body well-formedness
    installment_count = common.require_int(body, "installment_count")
    if not (1 <= installment_count <= 60):
        raise APIError(ERR_VALIDATION, 422, "installment_count must be in 1..60")
    expected_version = common.require_int(body, "expected_claim_version")

    # OCC (priority 5) — runs after body validation, before state/business (§2.8).
    if expected_version != claim["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "expected_claim_version does not match claim version")

    # principal snapshot (must be > 0)
    principal = claim["patient_responsibility_cents"]
    if principal <= 0:
        raise APIError(ERR_VALIDATION, 422, "principal_cents (claim patient responsibility) must be > 0")

    installment_amount, final_installment = calculations.payment_plan_schedule(
        principal, installment_count
    )

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "claim_id": claim_id,
        "principal_cents": principal,
        "installment_count": installment_count,
        "installment_amount_cents": installment_amount,
        "final_installment_cents": final_installment,
        "amount_posted_cents": 0,
        "remaining_balance_cents": principal,
        "status": "ACTIVE",
    })
    db.payment_plans[rec["id"]] = rec

    # Creating a payment plan increments the target claim's version by one (PRD §2.7).
    common.touch(claim)

    calculations.recompute_patient_balance(patient_id)
    if db.patients.get(patient_id) is not None:
        common.touch(db.patients[patient_id])

    return ok_object(common.serialize(rec), 201)


@bp.get("/payment-plans")
def list_payment_plans():
    guard([ROLE_BILLING, ROLE_FRONT_DESK])
    records = apply_filters(list(db.payment_plans.values()), {
        "patient_id": request.args.get("patient_id"),
        "claim_id": request.args.get("claim_id"),
        "status": request.args.get("status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/payment-plans/<plan_id>")
def get_payment_plan(plan_id):
    guard([ROLE_BILLING, ROLE_FRONT_DESK, ROLE_PATIENT])
    rec = common.resolve(db.payment_plans, plan_id, ERR_PAYMENT_PLAN_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


def _recompute_remaining(plan):
    plan["remaining_balance_cents"] = plan["principal_cents"] - plan["amount_posted_cents"]


@bp.post("/payment-plans/<plan_id>/post-installment")
def post_installment(plan_id):
    guard([ROLE_BILLING])
    plan = common.resolve(db.payment_plans, plan_id, ERR_PAYMENT_PLAN_NOT_FOUND)
    body = common.get_json_body()
    common.require_fields(body, ["amount_cents"])
    amount = common.require_int(body, "amount_cents")

    plan["amount_posted_cents"] += amount
    _recompute_remaining(plan)
    # PAID_OFF the moment amount_posted >= principal (PRD §3.7).
    if plan["amount_posted_cents"] >= plan["principal_cents"]:
        plan["status"] = "PAID_OFF"
        plan["remaining_balance_cents"] = 0
    common.touch(plan)

    calculations.recompute_patient_balance(plan["patient_id"])
    if db.patients.get(plan["patient_id"]) is not None:
        common.touch(db.patients[plan["patient_id"]])
    return ok_object(common.serialize(plan), 200)


@bp.post("/payment-plans/<plan_id>/reverse-installment")
def reverse_installment(plan_id):
    guard([ROLE_BILLING])
    plan = common.resolve(db.payment_plans, plan_id, ERR_PAYMENT_PLAN_NOT_FOUND)
    body = common.get_json_body()
    common.require_fields(body, ["amount_cents"])
    amount = common.require_int(body, "amount_cents")

    was_paid_off = plan["status"] == "PAID_OFF"
    plan["amount_posted_cents"] -= amount
    _recompute_remaining(plan)
    # If it was PAID_OFF and the reversal drops amount_posted below principal -> ACTIVE.
    if was_paid_off and plan["amount_posted_cents"] < plan["principal_cents"]:
        plan["status"] = "ACTIVE"
    common.touch(plan)

    calculations.recompute_patient_balance(plan["patient_id"])
    if db.patients.get(plan["patient_id"]) is not None:
        common.touch(db.patients[plan["patient_id"]])
    return ok_object(common.serialize(plan), 200)


@bp.post("/payment-plans/<plan_id>/default")
def default_payment_plan(plan_id):
    guard([ROLE_BILLING])
    plan = common.resolve(db.payment_plans, plan_id, ERR_PAYMENT_PLAN_NOT_FOUND)
    if plan["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Payment plan must be ACTIVE to default")
    plan["status"] = "DEFAULTED"
    common.touch(plan)

    calculations.recompute_patient_balance(plan["patient_id"])
    if db.patients.get(plan["patient_id"]) is not None:
        common.touch(db.patients[plan["patient_id"]])
    return ok_object(common.serialize(plan), 200)
