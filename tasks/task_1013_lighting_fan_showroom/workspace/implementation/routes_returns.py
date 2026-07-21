"""Return requests and energy rebate claims."""
from flask import Blueprint

import serializers
import services
from auth import require
from envelope import ok, created
from errors import err
from listing import list_response
from store import db, new_base, insert, touch, fetch, fk
from validation import get_body, req_enum, opt_str

bp = Blueprint("returns", __name__)

GET_ALL = ("ShowroomAssociate", "StoreManager", "Designer", "FulfillmentCoordinator")
RETURN_REASONS = {"DAMAGE", "DEFECTIVE", "CHANGED_MIND", "WARRANTY"}


# --------------------------- ReturnRequest ---------------------------
@bp.post("/return-requests")
@require("ShowroomAssociate", "StoreManager")
def create_return_request():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is None:
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    fk("orders", order_id)
    order_line_id = body.get("order_line_id")
    if order_line_id is None:
        raise err("ERR_INVALID_REQUEST", "order_line_id is required")
    fk("order_lines", order_line_id)
    reason = req_enum(body, "reason", RETURN_REASONS)
    rec = new_base()
    rec.update(
        {
            "order_id": order_id,
            "order_line_id": order_line_id,
            "reason": reason,
            "status": "REQUESTED",
            "restocking_fee_cents": None,
            "refund_cents": None,
        }
    )
    insert("return_requests", rec)
    return created(serializers.return_request(rec))


@bp.get("/return-requests/<rec_id>")
@require(*GET_ALL)
def get_return_request(rec_id):
    return ok(serializers.return_request(fetch("return_requests", rec_id)))


@bp.get("/return-requests")
@require(*GET_ALL)
def list_return_requests():
    return list_response(
        db.return_requests.values(),
        serializers.return_request,
        {"order_id": "order_id", "order_line_id": "order_line_id"},
    )


@bp.post("/return-requests/<rec_id>/approve")
@require("StoreManager")
def approve_return(rec_id):
    rec = fetch("return_requests", rec_id)
    body = get_body()
    adjudication = opt_str(body, "adjudication", "APPROVE")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Return request is not REQUESTED")
    if adjudication == "DENY":
        rec["status"] = "DENIED"
        touch(rec)
        return ok(serializers.return_request(rec))
    order = db.orders.get(rec["order_id"])
    line = db.order_lines.get(rec["order_line_id"])
    if (
        order is None
        or order["payment_status"] not in ("DEPOSIT_PAID", "SETTLED")
        or line is None
        or line["line_status"] != "ACTIVE"
    ):
        raise err("ERR_LINE_NOT_RETURNABLE", "Order payment state or line status forbids return")
    rec["restocking_fee_cents"] = services.compute_restocking_fee(line, order, rec["reason"])
    line["line_status"] = "RETURNED"
    touch(line)
    services.compute_order_pricing(order, "FINAL")
    touch(order)
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(serializers.return_request(rec))


@bp.post("/return-requests/<rec_id>/refund")
@require("StoreManager")
def refund_return(rec_id):
    rec = fetch("return_requests", rec_id)
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Return request is not APPROVED")
    line = db.order_lines.get(rec["order_line_id"])
    lv = services.line_value(line)
    rec["refund_cents"] = lv - rec["restocking_fee_cents"]
    rec["status"] = "REFUNDED"
    touch(rec)
    order = db.orders.get(rec["order_id"])
    if order is not None:
        services.maybe_bubble_order_refunded(order)
    return ok(serializers.return_request(rec))


# --------------------------- RebateClaim ---------------------------
@bp.post("/rebate-claims")
@require("ShowroomAssociate", "StoreManager")
def create_rebate_claim():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is None:
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    fk("orders", order_id)
    program_id = body.get("rebate_program_id")
    if program_id is None:
        raise err("ERR_INVALID_REQUEST", "rebate_program_id is required")
    program = fk("rebate_programs", program_id)
    claimed, eligible_count = services.compute_rebate_claimed(order_id, program)
    if eligible_count < 1:
        raise err("ERR_NO_ELIGIBLE_ITEMS", "Rebate claim has no eligible lines")
    rec = new_base()
    rec.update(
        {
            "order_id": order_id,
            "rebate_program_id": program_id,
            "claimed_cents": claimed,
            "status": "SUBMITTED",
        }
    )
    insert("rebate_claims", rec)
    return created(serializers.rebate_claim(rec))


@bp.get("/rebate-claims/<rec_id>")
@require(*GET_ALL)
def get_rebate_claim(rec_id):
    return ok(serializers.rebate_claim(fetch("rebate_claims", rec_id)))


@bp.get("/rebate-claims")
@require(*GET_ALL)
def list_rebate_claims():
    return list_response(
        db.rebate_claims.values(),
        serializers.rebate_claim,
        {"order_id": "order_id", "rebate_program_id": "rebate_program_id"},
    )


@bp.post("/rebate-claims/<rec_id>/approve")
@require("StoreManager")
def approve_rebate_claim(rec_id):
    rec = fetch("rebate_claims", rec_id)
    body = get_body()
    adjudication = opt_str(body, "adjudication", "APPROVE")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Rebate claim is not SUBMITTED")
    if adjudication == "DENY":
        rec["status"] = "DENIED"
        touch(rec)
        return ok(serializers.rebate_claim(rec))
    program = db.rebate_programs.get(rec["rebate_program_id"])
    if services.rebate_budget_remaining(program) < rec["claimed_cents"]:
        raise err("ERR_REBATE_BUDGET_EXCEEDED", "Program budget is insufficient")
    rec["status"] = "APPROVED"
    touch(rec)
    touch(program)  # budget_remaining shifts (§2.4)
    return ok(serializers.rebate_claim(rec))


@bp.post("/rebate-claims/<rec_id>/void")
@require("StoreManager")
def void_rebate_claim(rec_id):
    rec = fetch("rebate_claims", rec_id)
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Rebate claim is not APPROVED")
    rec["status"] = "VOID"
    touch(rec)
    program = db.rebate_programs.get(rec["rebate_program_id"])
    if program is not None:
        touch(program)  # budget restored (§2.4)
    return ok(serializers.rebate_claim(rec))
