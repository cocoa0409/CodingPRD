"""Claim routes — the billing ledger (PRD §2.7/§2.10/§3.12)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import calculations as calc

bp = Blueprint("claims", __name__)

READ_ROLES = ["Biller", "MedicalDirector"]


def _compute_figures(order, drug, plan, billed_days):
    """Compute the money figures for a given billed-day basis. Returns a dict."""
    per_diem = calc.per_diem_line(plan, drug, billed_days)
    drug_allowed = calc.drug_line_allowed(order, drug, plan, billed_days)
    allowed_total = per_diem + drug_allowed
    patient_resp, plan_paid, ded_applied = calc.copay_waterfall(plan, allowed_total)
    return {
        "billed_days": billed_days,
        "per_diem_cents": per_diem,
        "drug_allowed_cents": drug_allowed,
        "allowed_total_cents": allowed_total,
        "patient_responsibility_cents": patient_resp,
        "plan_paid_cents": plan_paid,
        "_ded_applied": ded_applied,
    }


@bp.route("/claims", methods=["POST"])
def create_claim():
    require(["Biller"])
    body = helpers.get_body()
    # (3) existence before (4) other body validity (PRD §2.8)
    order_id = helpers.as_str(body, "order_id")
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    order = db.infusion_orders[order_id]

    expected_order_version = helpers.as_int(body, "expected_order_version")

    # (5) state legality: order must be ACTIVE, COMPLETED, or DISCONTINUED
    if order["status"] not in ("ACTIVE", "COMPLETED", "DISCONTINUED"):
        raise errors.invalid_state("Order must be ACTIVE, COMPLETED, or DISCONTINUED")

    # (14) OCC on expected_order_version
    if expected_order_version != order["version"]:
        raise errors.ApiError(errors.ERR_STALE_ORDER_VERSION, 412,
                              "expected_order_version does not match current order version")

    drug = db.drug_catalog.get(order["drug_id"])
    patient = db.patients.get(order["patient_id"])
    plan = db.payer_plans.get(patient["payer_plan_id"]) if patient else None

    # ESTIMATE variant: billed_days = scheduled_days; reads but does NOT debit accumulators.
    figures = _compute_figures(order, drug, plan, order["scheduled_days"])

    claim = stamp_create({
        "order_id": order_id,
        "payer_plan_id": patient["payer_plan_id"] if patient else None,
        "expected_order_version": expected_order_version,
        "billed_days": figures["billed_days"],
        "per_diem_cents": figures["per_diem_cents"],
        "drug_allowed_cents": figures["drug_allowed_cents"],
        "allowed_total_cents": figures["allowed_total_cents"],
        "patient_responsibility_cents": figures["patient_responsibility_cents"],
        "plan_paid_cents": figures["plan_paid_cents"],
        "variant": "ESTIMATE",
        "status": "DRAFT",
        # bookkeeping for accumulator reversal on void (not serialized)
        "_posted_ded_applied": 0,
        "_posted_patient_resp": 0,
    })
    db.claims[claim["id"]] = claim
    return object_response(claim, 201)


@bp.route("/claims/<id>", methods=["GET"])
def get_claim(id):
    require(READ_ROLES)
    claim = db.claims.get(id)
    if claim is None:
        raise errors.not_found("Claim not found")
    return object_response(claim, 200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.claims.values())
    order_id = request.args.get("order_id")
    payer_plan_id = request.args.get("payer_plan_id")
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if payer_plan_id is not None:
        items = [c for c in items if c["payer_plan_id"] == payer_plan_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/claims/<id>/post", methods=["POST"])
def post_claim(id):
    require(["Biller"])
    claim = db.claims.get(id)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "DRAFT":
        raise errors.invalid_state("Claim is not in DRAFT state")

    order = db.infusion_orders.get(claim["order_id"])
    drug = db.drug_catalog.get(order["drug_id"])
    patient = db.patients.get(order["patient_id"])
    plan = db.payer_plans.get(patient["payer_plan_id"]) if patient else None

    # FINAL variant: billed_days = administered_days; debit accumulators.
    figures = _compute_figures(order, drug, plan, order["administered_days"])

    claim["billed_days"] = figures["billed_days"]
    claim["per_diem_cents"] = figures["per_diem_cents"]
    claim["drug_allowed_cents"] = figures["drug_allowed_cents"]
    claim["allowed_total_cents"] = figures["allowed_total_cents"]
    claim["patient_responsibility_cents"] = figures["patient_responsibility_cents"]
    claim["plan_paid_cents"] = figures["plan_paid_cents"]
    claim["variant"] = "FINAL"
    claim["status"] = "POSTED"

    # debit accumulators by the deductible portion applied and patient responsibility
    ded_applied = figures["_ded_applied"]
    patient_resp = figures["patient_responsibility_cents"]
    plan["deductible_remaining_cents"] -= ded_applied
    plan["oop_max_remaining_cents"] -= patient_resp
    touch(plan)

    claim["_posted_ded_applied"] = ded_applied
    claim["_posted_patient_resp"] = patient_resp
    touch(claim)
    return object_response(claim, 200)


@bp.route("/claims/<id>/void", methods=["POST"])
def void_claim(id):
    require(["Biller"])
    claim = db.claims.get(id)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "POSTED":
        raise errors.invalid_state("Claim is not in POSTED state")

    order = db.infusion_orders.get(claim["order_id"])
    patient = db.patients.get(order["patient_id"])
    plan = db.payer_plans.get(patient["payer_plan_id"]) if patient else None

    # credit accumulators back by exactly the amounts the post debited
    plan["deductible_remaining_cents"] += claim["_posted_ded_applied"]
    plan["oop_max_remaining_cents"] += claim["_posted_patient_resp"]
    touch(plan)

    claim["status"] = "VOID"
    touch(claim)
    return object_response(claim, 200)
