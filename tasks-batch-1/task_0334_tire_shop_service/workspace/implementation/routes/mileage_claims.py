"""Mileage-warranty claim routes (PRD §3.9).

Approval guard order (scaffold §1.4):
  7  ERR_INVALID_STATE     - claim SUBMITTED AND covered line COMMITTED
  14 ERR_MILEAGE_EXCEEDED  - miles_driven >= mileage_warranty_miles
  15 ERR_NOT_WORN_TO_BAR   - measured_tread > wear bar, or no mileage warranty
Proration uses the SYSTEM-SELECTED mileage-based variant.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MILEAGE_EXCEEDED,
    ERR_NOT_WORN_TO_BAR,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import WEAR_BAR_THRESHOLD_32NDS, mileage_proration
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    require_enum,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("mileage_claims", __name__)

PAYOUT_METHODS = {"STORE_CREDIT", "REFUND"}


@bp.post("/mileage-claims")
def create_claim():
    require_auth(["ServiceAdvisor", "Customer"])()
    body = get_json_body()
    require_fields(
        body,
        ["work_order_line_id", "tire_model_id", "measured_tread_32nds",
         "miles_driven", "payout_method", "claim_quantity"],
    )
    work_order_line_id = require_string(body["work_order_line_id"], "work_order_line_id")
    tire_model_id = require_string(body["tire_model_id"], "tire_model_id")
    measured_tread_32nds = require_int(body["measured_tread_32nds"],
                                       "measured_tread_32nds", min_value=2)
    miles_driven = require_int(body["miles_driven"], "miles_driven", min_value=0)
    payout_method = require_enum(body["payout_method"], PAYOUT_METHODS, "payout_method")
    claim_quantity = require_int(body["claim_quantity"], "claim_quantity", min_value=1)

    with db.mutation_lock:
        lookup_fk_or_404(db.work_order_lines, work_order_line_id, "WorkOrderLine")
        model = lookup_fk_or_404(db.tire_models, tire_model_id, "TireModel")
        # measured_tread_32nds must be <= the model's original_tread_32nds.
        if measured_tread_32nds > model["original_tread_32nds"]:
            raise APIError(ERR_INVALID_REQUEST, 422,
                           "measured_tread_32nds exceeds original_tread_32nds")
        claim = {
            "work_order_line_id": work_order_line_id,
            "tire_model_id": tire_model_id,
            "measured_tread_32nds": measured_tread_32nds,
            "miles_driven": miles_driven,
            "payout_method": payout_method,
            "claim_quantity": claim_quantity,
            "prorated_credit_cents": 0,
            "status": "SUBMITTED",
        }
        db.stamp_common(claim)
        db.mileage_claims[claim["id"]] = claim
        return ok_object(claim, 201)


@bp.get("/mileage-claims/<cid>")
def get_claim(cid: str):
    require_auth(["ServiceAdvisor", "Customer"])()
    claim = lookup_path_or_404(db.mileage_claims, cid, "MileageWarrantyClaim")
    return ok_object(claim, 200)


@bp.get("/mileage-claims")
def list_claims():
    require_auth(["ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.mileage_claims.values())
    if "work_order_line_id" in request.args:
        items = [c for c in items
                 if c["work_order_line_id"] == request.args["work_order_line_id"]]
    if "tire_model_id" in request.args:
        items = [c for c in items
                 if c["tire_model_id"] == request.args["tire_model_id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/mileage-claims/<cid>/approve")
def approve_claim(cid: str):
    require_auth(["ServiceAdvisor"])()
    claim = lookup_path_or_404(db.mileage_claims, cid, "MileageWarrantyClaim")
    with db.mutation_lock:
        # State (priority 7): claim SUBMITTED.
        if claim["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Claim is not SUBMITTED")
        # Cross-entity state: covered line must be COMMITTED.
        line = db.work_order_lines[claim["work_order_line_id"]]
        if line["line_status"] != "COMMITTED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Covered work order line is not COMMITTED")
        model = db.tire_models[claim["tire_model_id"]]

        # Mileage guard (priority 14).
        if not (model["mileage_warranty_miles"] > 0
                and claim["miles_driven"] < model["mileage_warranty_miles"]):
            raise APIError(ERR_MILEAGE_EXCEEDED, 422,
                           "miles_driven has reached/passed the mileage rating")
        # Wear-bar guard (priority 15).
        if not (claim["measured_tread_32nds"] <= WEAR_BAR_THRESHOLD_32NDS
                and model["mileage_warranty_miles"] > 0):
            raise APIError(ERR_NOT_WORN_TO_BAR, 422,
                           "tread above wear bar, or model has no mileage warranty")

        # Proration (mileage-based variant).
        claim["prorated_credit_cents"] = mileage_proration(
            model["unit_price_cents"],
            model["mileage_warranty_miles"],
            claim["miles_driven"],
            claim["claim_quantity"],
        )
        claim["status"] = "APPROVED"
        db.bump(claim)

        # Consume an ACTIVE road-hazard warranty on the same line.
        for w in db.road_hazard_warranties.values():
            if (w["work_order_line_id"] == claim["work_order_line_id"]
                    and w["status"] == "ACTIVE"):
                w["status"] = "CLAIMED"
                db.bump(w)
        return ok_object(claim, 200)


@bp.post("/mileage-claims/<cid>/reject")
def reject_claim(cid: str):
    require_auth(["ServiceAdvisor"])()
    claim = lookup_path_or_404(db.mileage_claims, cid, "MileageWarrantyClaim")
    with db.mutation_lock:
        if claim["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE, 409, "Claim is not SUBMITTED")
        claim["status"] = "REJECTED"
        db.bump(claim)
        return ok_object(claim, 200)


@bp.post("/mileage-claims/<cid>/pay")
def pay_claim(cid: str):
    require_auth(["ServiceAdvisor"])()
    claim = lookup_path_or_404(db.mileage_claims, cid, "MileageWarrantyClaim")
    with db.mutation_lock:
        if claim["status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE, 409, "Claim is not APPROVED")
        if claim["payout_method"] == "STORE_CREDIT":
            # Credit the customer who owns the claimed line's work order.
            line = db.work_order_lines[claim["work_order_line_id"]]
            order = db.work_orders[line["work_order_id"]]
            customer = db.customers[order["customer_id"]]
            customer["store_credit_cents"] += claim["prorated_credit_cents"]
            db.bump(customer)
        claim["status"] = "PAID"
        db.bump(claim)
        return ok_object(claim, 200)
