"""QualityClaim endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import (
    err_invalid_quantity,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_sod_self_adjudication,
    err_warp_below_threshold,
)
from middleware import require_roles
from response import success_object
from services.calcs import bump, FREIGHT_REIMB_CAP
from services.serialize import serialize_quality_claim
from util import D, is_int, is_num, new_id, round2, round4, utcnow_iso
from ._helpers import get_json_body, require_fields

bp = Blueprint("quality_claims", __name__)

CLAIM_TYPES = {"TRANSIT_DAMAGE", "BOARD_WARP"}
OUTCOMES = {"CREDIT", "REJECTED"}


@bp.route("/api/quality-claims", methods=["POST"])
@require_roles("CustomerService")
def create_claim(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["box_order_id", "claim_type", "defective_qty_claimed"])

    box_order_id = body["box_order_id"]
    claim_type = body["claim_type"]
    defective_qty_claimed = body["defective_qty_claimed"]
    measured_warp_pct = body.get("measured_warp_pct")

    # Well-formedness
    if claim_type not in CLAIM_TYPES:
        raise err_invalid_request("claim_type must be TRANSIT_DAMAGE or BOARD_WARP")
    if not is_int(defective_qty_claimed) or defective_qty_claimed <= 0:
        raise err_invalid_request("defective_qty_claimed must be an integer > 0")

    # Existence
    order = db.box_orders.get(box_order_id)
    if order is None:
        raise err_not_found("box order not found")

    # State: order must be INVOICED
    if order["status"] != "INVOICED":
        raise err_invalid_state("order is not INVOICED")

    # Warp threshold (priority 5)
    if claim_type == "BOARD_WARP":
        if measured_warp_pct is None:
            raise err_warp_below_threshold("BOARD_WARP claim requires measured_warp_pct")
        if not is_num(measured_warp_pct):
            raise err_invalid_request("measured_warp_pct must be numeric")
        if D(measured_warp_pct) < Decimal("2.0"):
            raise err_warp_below_threshold("measured_warp_pct must be >= 2.0")
    # TRANSIT_DAMAGE: measured_warp_pct ignored if present (but keep value)

    # Snapshot per_box_price_dollars = invoice_merchandise_dollars / produced_qty at 4dp
    inv_merch = D(order["invoice_merchandise_dollars"])
    produced = order["produced_qty"]
    if produced is None or produced <= 0:
        raise err_invalid_state("order has no produced_qty")
    per_box = round4(inv_merch / Decimal(produced))

    provisional = round2(Decimal(defective_qty_claimed) * per_box)

    now = utcnow_iso()
    cid = new_id()
    claim = {
        "id": cid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "box_order_id": box_order_id,
        "claim_type": claim_type,
        "defective_qty_claimed": defective_qty_claimed,
        "measured_warp_pct": D(measured_warp_pct) if measured_warp_pct is not None else None,
        "per_box_price_dollars": per_box,
        "provisional_credit_dollars": provisional,
        "defective_qty_verified": None,
        "actual_return_freight_dollars": None,
        "final_credit_dollars": None,
        "filed_by_user_id": _user_id,
        "adjudicated_by_user_id": None,
        "status": "OPEN",
    }
    db.quality_claims[cid] = claim
    return success_object(serialize_quality_claim(claim), 201)


def _get_claim_or_404(cid):
    c = db.quality_claims.get(cid)
    if c is None:
        raise err_not_found("quality claim not found")
    return c


@bp.route("/api/quality-claims/<cid>/start-review", methods=["POST"])
@require_roles("ClaimsAdjuster")
def start_review(cid, _user_id, _role):
    c = _get_claim_or_404(cid)
    if c["status"] != "OPEN":
        raise err_invalid_state("claim is not OPEN")
    c["status"] = "UNDER_REVIEW"
    bump(c)
    return success_object(serialize_quality_claim(c), 200)


@bp.route("/api/quality-claims/<cid>/resolve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def resolve_claim(cid, _user_id, _role):
    c = _get_claim_or_404(cid)
    body = get_json_body()
    require_fields(body, ["outcome"])

    outcome = body["outcome"]
    defective_qty_verified = body.get("defective_qty_verified")
    actual_return_freight = body.get("actual_return_freight_dollars")

    if outcome not in OUTCOMES:
        raise err_invalid_request("outcome must be CREDIT or REJECTED")

    # State check
    if c["status"] != "UNDER_REVIEW":
        raise err_invalid_state("claim is not UNDER_REVIEW")

    # Segregation of duties: resolving user != filer
    if _user_id == c["filed_by_user_id"]:
        raise err_sod_self_adjudication("resolving user id equals the claim's filed_by_user_id")

    if outcome == "CREDIT":
        # defective_qty_verified present and 0 <= v <= produced_qty
        if defective_qty_verified is None:
            raise err_invalid_quantity("defective_qty_verified is required for CREDIT outcome")
        if not is_int(defective_qty_verified):
            raise err_invalid_quantity("defective_qty_verified must be an integer")
        order = db.box_orders.get(c["box_order_id"])
        if order is None:
            raise err_not_found("box order not found")
        produced = order["produced_qty"]
        if produced is None:
            raise err_invalid_state("order has no produced_qty")
        if defective_qty_verified < 0 or defective_qty_verified > produced:
            raise err_invalid_quantity(
                f"defective_qty_verified must be in [0, {produced}]"
            )
        if actual_return_freight is not None and not is_num(actual_return_freight):
            raise err_invalid_request("actual_return_freight_dollars must be numeric")
        freight_d = D(actual_return_freight) if actual_return_freight is not None else Decimal("0")
        reimb = freight_d if freight_d < FREIGHT_REIMB_CAP else FREIGHT_REIMB_CAP
        credit_part = round2(Decimal(defective_qty_verified) * c["per_box_price_dollars"])
        final = credit_part + reimb
        c["defective_qty_verified"] = defective_qty_verified
        c["actual_return_freight_dollars"] = D(actual_return_freight) if actual_return_freight is not None else None
        c["final_credit_dollars"] = final
        c["status"] = "RESOLVED_CREDIT"
    else:  # REJECTED
        c["final_credit_dollars"] = Decimal("0.00")
        c["status"] = "RESOLVED_REJECTED"

    c["adjudicated_by_user_id"] = _user_id
    bump(c)
    return success_object(serialize_quality_claim(c), 200)
