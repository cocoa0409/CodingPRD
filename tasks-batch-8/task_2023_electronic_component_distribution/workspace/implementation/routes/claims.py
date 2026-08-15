"""ShipAndDebitClaim endpoints."""

from flask import Blueprint, request

import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    get_claim_or_404,
    get_json_body,
    paginate,
    pagination_params,
    serialize_claim,
    stamp_now,
)

bp = Blueprint("claims", __name__)


def _restore_registration_qty(claim):
    reg = db.design_registrations.get(claim["registration_id"])
    if reg is None:
        return
    reg["registered_qty_remaining"] += claim["qty"]
    if reg["status"] == "EXHAUSTED" and reg["registered_qty_remaining"] > 0:
        reg["status"] = "APPROVED"
    reg["updated_at"] = stamp_now()
    reg["version"] += 1


def _claim_manufacturer_line(claim):
    line_ref = db.order_lines.get(claim["order_line_id"])
    if line_ref is None:
        return None
    part = db.parts.get(line_ref["part_id"])
    if part is None:
        return None
    return db.manufacturer_lines.get(part["manufacturer_line_id"])


@bp.get("/claims")
def list_claims():
    require_auth()
    limit, offset = pagination_params()
    registration_id = request.args.get("registration_id")
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")
    items = list(db.claims.values())
    if registration_id is not None:
        items = [c for c in items if c["registration_id"] == registration_id]
    if order_line_id is not None:
        items = [c for c in items if c["order_line_id"] == order_line_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_claim(c) for c in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/claims/<claimId>")
def get_claim(claimId):
    require_auth()
    claim = get_claim_or_404(claimId)
    return success(serialize_claim(claim), status=200)


@bp.post("/claims/<claimId>/supplier-decision")
def supplier_decision(claimId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SupplierAdmin"})
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT", "DISPUTE"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "decision must be APPROVE, REJECT, or DISPUTE.")
    audited_cost_cents = None
    if "audited_cost_cents" in body and body["audited_cost_cents"] is not None:
        v = body["audited_cost_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "audited_cost_cents must be an integer.")
        audited_cost_cents = v
    claim = get_claim_or_404(claimId)

    if decision == "APPROVE":
        if claim["status"] != "SUBMITTED":
            raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUBMITTED.")
        if audited_cost_cents is None:
            audited_cost_cents = claim["registered_cost_cents"]
        claim["audited_cost_cents"] = audited_cost_cents
        claim["amount_final_cents"] = claim["qty"] * (
            claim["standard_cost_cents"] - audited_cost_cents
        )
        claim["status"] = "SUPPLIER_APPROVED"
    elif decision == "REJECT":
        if claim["status"] not in ("SUBMITTED", "DISPUTED"):
            raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUBMITTED or DISPUTED.")
        claim["status"] = "SUPPLIER_REJECTED"
        _restore_registration_qty(claim)
    else:  # DISPUTE
        if claim["status"] != "SUBMITTED":
            raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUBMITTED.")
        claim["status"] = "DISPUTED"

    claim["updated_at"] = stamp_now()
    claim["version"] += 1
    return success(serialize_claim(claim), status=200)


@bp.post("/claims/<claimId>/resubmit")
def resubmit_claim(claimId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep"})
    claim = get_claim_or_404(claimId)
    if claim["status"] != "DISPUTED":
        raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not DISPUTED.")
    claim["status"] = "SUBMITTED"
    claim["updated_at"] = stamp_now()
    claim["version"] += 1
    return success(serialize_claim(claim), status=200)


@bp.post("/claims/<claimId>/settle")
def settle_claim(claimId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SupplierAdmin"})
    claim = get_claim_or_404(claimId)
    if claim["status"] != "SUPPLIER_APPROVED":
        raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not SUPPLIER_APPROVED.")
    mline = _claim_manufacturer_line(claim)
    if mline is not None:
        mline["open_debit_balance_cents"] += claim["amount_final_cents"]
        mline["updated_at"] = stamp_now()
        mline["version"] += 1
    claim["status"] = "SETTLED"
    claim["updated_at"] = stamp_now()
    claim["version"] += 1
    return success(serialize_claim(claim), status=200)


@bp.post("/claims/<claimId>/reverse")
def reverse_claim(claimId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SupplierAdmin"})
    claim = get_claim_or_404(claimId)
    if claim["status"] != "SETTLED":
        raise ApiError(E.ERR_CLAIM_INVALID_STATE, 409, "Claim is not SETTLED.")
    mline = _claim_manufacturer_line(claim)
    if mline is not None:
        mline["open_debit_balance_cents"] -= claim["amount_final_cents"]
        mline["updated_at"] = stamp_now()
        mline["version"] += 1
    _restore_registration_qty(claim)
    claim["status"] = "REVERSED"
    claim["updated_at"] = stamp_now()
    claim["version"] += 1
    return success(serialize_claim(claim), status=200)
