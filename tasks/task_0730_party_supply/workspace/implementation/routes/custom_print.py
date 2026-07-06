from __future__ import annotations
from flask import Blueprint, request, g

from db import db, stamp_common, bump
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REVISION_LIMIT,
    ERR_FORBIDDEN,
)
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean
from services import order as osvc
from services import calc

bp = Blueprint("custom_print", __name__)


@bp.route("/orders/<id>/custom-print", methods=["POST"])
@require_roles("StoreClerk")
def attach_custom_print(id):
    order = fetch(db.orders, id)
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "custom-print attach requires DRAFT order")
    if osvc.custom_print_for(id) is not None:
        raise_error(ERR_INVALID_STATE, "Order already has CustomPrintOrder")

    body = get_body()
    art_reference = require_field(body, "art_reference")
    banner_length_ft = as_int(require_field(body, "banner_length_ft"), "banner_length_ft")
    if not isinstance(art_reference, str) or not art_reference:
        raise_error(ERR_INVALID_REQUEST, "art_reference must be non-empty string")
    if banner_length_ft < 1:
        raise_error(ERR_INVALID_REQUEST, "banner_length_ft must be >= 1")

    cp = {
        "order_id": id,
        "art_reference": art_reference,
        "banner_length_ft": banner_length_ft,
        "status": "DRAFT",
        "revision_count": 0,
        "print_fee_cents": 0,
    }
    stamp_common(cp)
    db.custom_print_orders[cp["id"]] = cp
    return created(clean(cp))


@bp.route("/custom-print-orders/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_custom_print(id):
    return ok(clean(fetch(db.custom_print_orders, id)))


@bp.route("/custom-print-orders", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def list_custom_print():
    limit, offset = parse_limit_offset()
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = list(db.custom_print_orders.values())
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


def _cp_and_parent(id):
    cp = fetch(db.custom_print_orders, id)
    order = db.orders.get(cp["order_id"])
    return cp, order


@bp.route("/custom-print-orders/<id>/send-proof", methods=["POST"])
@require_roles("StoreClerk")
def send_proof(id):
    cp, _ = _cp_and_parent(id)
    if cp["status"] not in {"DRAFT", "REVISION_REQUESTED"}:
        raise_error(ERR_INVALID_STATE, "send-proof requires DRAFT or REVISION_REQUESTED")
    if not cp.get("art_reference"):
        raise_error(ERR_INVALID_STATE, "art_reference required")
    cp["status"] = "PROOF_SENT"
    bump(cp)
    return ok(clean(cp))


@bp.route("/custom-print-orders/<id>/request-revision", methods=["POST"])
@require_roles("Customer")
def request_revision(id):
    cp, order = _cp_and_parent(id)
    # ownership for Customer role: caller must own the parent Order
    if order and order["customer_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "Customer does not own this order")

    if cp["status"] != "PROOF_SENT":
        raise_error(ERR_INVALID_STATE, "request-revision requires PROOF_SENT")
    if int(cp["revision_count"]) >= 3:
        raise_error(ERR_REVISION_LIMIT, "revision_count already at limit")
    cp["status"] = "REVISION_REQUESTED"
    cp["revision_count"] = int(cp["revision_count"]) + 1
    bump(cp)
    return ok(clean(cp))


@bp.route("/custom-print-orders/<id>/approve", methods=["POST"])
@require_roles("Customer")
def approve(id):
    cp, order = _cp_and_parent(id)
    if order and order["customer_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN, "Customer does not own this order")

    if cp["status"] != "PROOF_SENT":
        raise_error(ERR_INVALID_STATE, "approve requires PROOF_SENT")
    if not order or order["payment_status"] != "PAID":
        raise_error(ERR_INVALID_STATE, "approve requires parent Order PAID")

    cp["status"] = "APPROVED"
    cp["print_fee_cents"] = calc.custom_print_fee(
        int(cp["banner_length_ft"]), int(cp["revision_count"])
    )
    bump(cp)

    # cascade totals into Order
    if order:
        osvc.recompute_order_totals(order)
        bump(order)

    return ok(clean(cp))


@bp.route("/custom-print-orders/<id>/start-print", methods=["POST"])
@require_roles("StoreClerk")
def start_print(id):
    cp, _ = _cp_and_parent(id)
    if cp["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "start-print requires APPROVED")
    cp["status"] = "PRINTING"
    bump(cp)
    return ok(clean(cp))


@bp.route("/custom-print-orders/<id>/mark-ready", methods=["POST"])
@require_roles("StoreClerk")
def mark_ready(id):
    cp, _ = _cp_and_parent(id)
    if cp["status"] != "PRINTING":
        raise_error(ERR_INVALID_STATE, "mark-ready requires PRINTING")
    cp["status"] = "READY"
    bump(cp)
    return ok(clean(cp))


@bp.route("/custom-print-orders/<id>/cancel", methods=["POST"])
@require_roles("StoreClerk")
def cancel_cp(id):
    cp, _ = _cp_and_parent(id)
    if cp["status"] not in {"DRAFT", "PROOF_SENT", "REVISION_REQUESTED"}:
        raise_error(ERR_INVALID_STATE, "cancel requires DRAFT/PROOF_SENT/REVISION_REQUESTED")
    cp["status"] = "CANCELLED"
    bump(cp)
    return ok(clean(cp))
