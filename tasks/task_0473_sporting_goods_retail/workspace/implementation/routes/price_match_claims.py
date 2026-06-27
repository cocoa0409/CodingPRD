"""Price-match-claim routes: submit, get, list/filter, approve, reject (PRD §3.7)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_int, as_str
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404, require_owner
from services import serializers, pricing

bp = Blueprint("price_match_claims", __name__)


def _touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


@bp.route("/price-match-claims", methods=["POST"])
@require_roles("Customer")
def submit_claim():
    body = get_body()
    order_id = as_str(body, "order_id", required=True)
    order_line_id = as_str(body, "order_line_id", required=True)
    competitor_price_cents = as_int(body, "competitor_price_cents", required=True, minimum=0)

    order = get_or_404(db.orders, order_id)
    # Ownership: claim must be on the customer's own order (priority 3).
    require_owner(order["customer_id"])
    line = get_or_404(db.order_lines, order_line_id)
    if line["order_id"] != order_id:
        raise errors.not_found()

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "order_id": order_id,
        "order_line_id": order_line_id,
        "competitor_price_cents": competitor_price_cents,
        "status": "SUBMITTED",
        "approved_unit_price_cents": None,
    }
    db.price_match_claims[rid] = rec
    return success(serializers.price_match_claim(rec), 201)


@bp.route("/price-match-claims/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "Customer")
def get_claim(rid):
    rec = get_or_404(db.price_match_claims, rid)
    return success(serializers.price_match_claim(rec), 200)


@bp.route("/price-match-claims", methods=["GET"])
@require_roles("PlatformAdmin", "PriceAdmin", "Customer")
def list_claims():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    order_line_id = request.args.get("order_line_id")
    items = list(db.price_match_claims.values())
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if order_line_id is not None:
        items = [c for c in items if c["order_line_id"] == order_line_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.price_match_claim(c) for c in page], limit, offset, total)


@bp.route("/price-match-claims/<rid>/approve", methods=["POST"])
@require_roles("PriceAdmin")
def approve_claim(rid):
    claim = get_or_404(db.price_match_claims, rid)
    # State (priority 6): only SUBMITTED claims may be approved.
    if claim["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not in SUBMITTED state")

    order = db.orders[claim["order_id"]]
    line = db.order_lines[claim["order_line_id"]]

    # Order must be pre-fulfillment (§3.7).
    if order["fulfillment_status"] not in ("DRAFT", "RESERVED", "READY"):
        raise errors.ApiError(errors.ERR_ORDER_NOT_MATCHABLE, 409,
                              "Referenced order is not in a matchable state")
    # Genuineness: competitor strictly less than the line's captured unit_price.
    if not (claim["competitor_price_cents"] < line["unit_price_cents"]):
        raise errors.ApiError(errors.ERR_PRICE_MATCH_NOT_LOWER, 422,
                              "competitor_price_cents must be strictly below the line's unit_price_cents")

    claim["approved_unit_price_cents"] = pricing.approved_unit_price(
        line["unit_price_cents"], claim["competitor_price_cents"])
    claim["status"] = "APPROVED"
    _touch(claim)

    # Bump the referenced order's version so a stale fulfill is rejected (§2.6, §3.7).
    order["updated_at"] = now_ts()
    order["version"] += 1

    return success(serializers.price_match_claim(claim), 200)


@bp.route("/price-match-claims/<rid>/reject", methods=["POST"])
@require_roles("PriceAdmin")
def reject_claim(rid):
    claim = get_or_404(db.price_match_claims, rid)
    if claim["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not in SUBMITTED state")
    claim["status"] = "REJECTED"
    _touch(claim)
    return success(serializers.price_match_claim(claim), 200)
