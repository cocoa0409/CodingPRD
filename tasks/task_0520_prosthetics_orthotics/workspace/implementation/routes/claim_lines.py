"""Claim Lines: L-code billing, adjudication, appeals (PRD §3.6).

Two parallel dimensions evolve on the same row: adjudication_status and
appeal_status.
"""
from flask import Blueprint, request

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import (get_json_body, require_str, require_int, optional_enum,
                        lookup, parse_pagination, paginate)
from services import touch, calc_claim_line_allowed_final, recompute_order_allowed_total
from serializers import claim_line_out

bp = Blueprint("claim_lines", __name__)

MODIFIERS = {"NONE", "KX", "GA", "GZ", "RT", "LT"}


def _has_approved_auth(order):
    for a in db.prior_auths.values():
        if a["device_order_id"] == order["id"] and a["status"] == "APPROVED":
            return True
    return False


@bp.route("/op/claim-lines", methods=["POST"])
def create_claim_line():
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    body = get_json_body()

    device_order_id = require_str(body, "device_order_id")
    # Existence (priority 3) — checked before the line-level field rules.
    order = lookup(db.device_orders, device_order_id)

    l_code = require_str(body, "l_code")
    modifier = optional_enum(body, "modifier", MODIFIERS, "NONE")
    billed_units = require_int(body, "billed_units")
    fee_schedule_cents = require_int(body, "fee_schedule_cents")

    # Billing amount validity (priority 14).
    if billed_units < 1 or fee_schedule_cents < 0:
        raise ApiError("ERR_INVALID_BILLING_AMOUNT", "billed_units must be >= 1 and fee_schedule_cents >= 0.")

    cl = base_common_fields()
    cl.update({
        "device_order_id": device_order_id,
        "l_code": l_code,
        "modifier": modifier,
        "billed_units": billed_units,
        "fee_schedule_cents": fee_schedule_cents,
        "adjudication_status": "DRAFT",
        "appeal_status": "NONE",
        "allowed_cents": 0,
    })
    db.claim_lines[cl["id"]] = cl
    return ok_object(claim_line_out(cl), 201)


@bp.route("/op/claim-lines/<rid>", methods=["GET"])
def get_claim_line(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer"})
    cl = lookup(db.claim_lines, rid)
    return ok_object(claim_line_out(cl), 200)


@bp.route("/op/claim-lines", methods=["GET"])
def list_claim_lines():
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer"})
    limit, offset = parse_pagination()

    items = list(db.claim_lines.values())
    device_order_id = request.args.get("device_order_id")
    if device_order_id is not None:
        items = [c for c in items if c["device_order_id"] == device_order_id]
    page, total = paginate(items, limit, offset)
    return ok_array([claim_line_out(c) for c in page], limit, offset, total, 200)


@bp.route("/op/claim-lines/<rid>/adjudicate", methods=["POST"])
def adjudicate(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    cl = lookup(db.claim_lines, rid)

    # State legality (priority 5).
    if cl["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "ClaimLine is not in SUBMITTED.")

    order = db.device_orders.get(cl["device_order_id"])
    # KX-without-auth (priority 11): KX requires APPROVED auth when the order
    # requires prior auth.
    if cl["modifier"] == "KX" and order["requires_prior_auth"] and not _has_approved_auth(order):
        raise ApiError("ERR_KX_WITHOUT_AUTH", "KX modifier requires a covering APPROVED prior authorization.")

    cl["adjudication_status"] = "ADJUDICATED"
    cl["allowed_cents"] = calc_claim_line_allowed_final(cl, order)
    touch(cl)
    recompute_order_allowed_total(order)
    return ok_object(claim_line_out(cl), 200)


@bp.route("/op/claim-lines/<rid>/deny", methods=["POST"])
def deny_claim_line(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    cl = lookup(db.claim_lines, rid)

    if cl["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "ClaimLine is not in SUBMITTED.")

    order = db.device_orders.get(cl["device_order_id"])
    cl["adjudication_status"] = "DENIED"
    cl["allowed_cents"] = 0
    touch(cl)
    recompute_order_allowed_total(order)
    return ok_object(claim_line_out(cl), 200)


@bp.route("/op/claim-lines/<rid>/appeal", methods=["POST"])
def appeal(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    cl = lookup(db.claim_lines, rid)

    # Appeal is filed on a DENIED line, moving appeal_status NONE->APPEALED.
    if cl["adjudication_status"] != "DENIED" or cl["appeal_status"] != "NONE":
        raise ApiError("ERR_INVALID_STATE", "Appeal can only be filed on a DENIED line with no prior appeal.")

    cl["appeal_status"] = "APPEALED"
    touch(cl)
    return ok_object(claim_line_out(cl), 200)


@bp.route("/op/claim-lines/<rid>/appeal-decision", methods=["POST"])
def appeal_decision(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    cl = lookup(db.claim_lines, rid)
    body = get_json_body()

    # State legality (priority 5): an appeal must be in flight.
    if cl["appeal_status"] != "APPEALED":
        raise ApiError("ERR_INVALID_STATE", "ClaimLine has no appeal awaiting a decision.")

    # Outcome validity.
    outcome = body.get("outcome")
    if outcome not in ("UPHELD", "OVERTURNED"):
        raise ApiError("ERR_INVALID_APPEAL_OUTCOME", "outcome must be UPHELD or OVERTURNED.")

    order = db.device_orders.get(cl["device_order_id"])
    if outcome == "UPHELD":
        cl["appeal_status"] = "APPEAL_UPHELD"
        touch(cl)
    else:
        cl["appeal_status"] = "APPEAL_OVERTURNED"
        # For a DENIED line under appeal, restore adjudication and recompute.
        if cl["adjudication_status"] == "DENIED":
            cl["adjudication_status"] = "ADJUDICATED"
            cl["allowed_cents"] = calc_claim_line_allowed_final(cl, order)
        touch(cl)
        recompute_order_allowed_total(order)

    return ok_object(claim_line_out(cl), 200)
