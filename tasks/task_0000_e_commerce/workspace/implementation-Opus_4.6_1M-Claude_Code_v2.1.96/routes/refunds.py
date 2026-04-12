import uuid
import json
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination
from response import success_response
from money import round2, to_decimal, TWO_PLACES

bp = Blueprint("refunds", __name__)


def _get_order_or_404(db, order_id):
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise_error("ERR_ORDER_NOT_FOUND")
    return order


@bp.route("/orders/<order_id>/refunds", methods=["POST"])
def create_refund(order_id):
    user_id, _ = require_role("Customer")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["customer_id"] != user_id:
        raise_error("ERR_NOT_ORDER_OWNER")
    if order["payment_status"] not in ("PAID", "PARTIAL_REFUND"):
        raise_error("ERR_ORDER_NOT_PAID")

    data = request.get_json(force=True, silent=True) or {}
    reason = data.get("reason", "")
    refund_type = data.get("refund_type")
    if refund_type not in ("FULL", "PARTIAL"):
        raise_error("ERR_INVALID_REQUEST", "refund_type must be FULL or PARTIAL.")

    refund_items = []
    if refund_type == "PARTIAL":
        refund_items = data.get("refund_items", [])
        if not refund_items:
            raise_error("ERR_INVALID_REQUEST", "refund_items required for partial refund.")
        # Validate order items exist
        for ri in refund_items:
            oi = db.execute(
                "SELECT * FROM order_items WHERE id=? AND order_id=?", (ri["order_item_id"], order_id)
            ).fetchone()
            if not oi:
                raise_error("ERR_ORDER_ITEM_NOT_FOUND")

    refund_id = str(uuid.uuid4())
    ts = now_iso()
    db.execute(
        """INSERT INTO refunds (id, order_id, reason, refund_type, refund_items, refund_amount,
           refund_subtotal, refund_discount_share, status, inventory_restored, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, 0, 0, 0, 'REQUESTED', 0, ?, ?, 1)""",
        (refund_id, order_id, reason, refund_type, json.dumps(refund_items), ts, ts),
    )
    db.commit()
    refund = row_to_dict(db.execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone())
    return success_response(refund, 201)


@bp.route("/orders/<order_id>/refunds", methods=["GET"])
def list_refunds(order_id):
    get_auth()
    db = get_db()
    _get_order_or_404(db, order_id)
    limit, offset = parse_pagination(request.args)
    total = db.execute("SELECT COUNT(*) as cnt FROM refunds WHERE order_id=?", (order_id,)).fetchone()["cnt"]
    rows = db.execute(
        "SELECT * FROM refunds WHERE order_id=? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (order_id, limit, offset),
    ).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/orders/<order_id>/refunds/<refund_id>", methods=["GET"])
def get_refund(order_id, refund_id):
    get_auth()
    db = get_db()
    _get_order_or_404(db, order_id)
    refund = db.execute("SELECT * FROM refunds WHERE id=? AND order_id=?", (refund_id, order_id)).fetchone()
    if not refund:
        raise_error("ERR_REFUND_NOT_FOUND")
    return success_response(row_to_dict(refund))


@bp.route("/orders/<order_id>/refunds/<refund_id>/approve", methods=["POST"])
def approve_refund(order_id, refund_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["payment_status"] not in ("PAID", "PARTIAL_REFUND"):
        raise_error("ERR_ORDER_NOT_PAID")
    refund = db.execute("SELECT * FROM refunds WHERE id=? AND order_id=?", (refund_id, order_id)).fetchone()
    if not refund:
        raise_error("ERR_REFUND_NOT_FOUND")
    if refund["status"] != "REQUESTED":
        raise_error("ERR_REFUND_NOT_REQUESTED")

    refund_items = refund["refund_items"]
    if isinstance(refund_items, str):
        refund_items = json.loads(refund_items)

    if refund["refund_type"] == "PARTIAL":
        # Validate quantities don't exceed remaining
        for ri in refund_items:
            oi_id = ri["order_item_id"]
            oi = db.execute("SELECT * FROM order_items WHERE id=?", (oi_id,)).fetchone()
            if not oi:
                raise_error("ERR_ORDER_ITEM_NOT_FOUND")

            # Get previously refunded quantity for this order item
            processed_refunds = db.execute(
                "SELECT refund_items FROM refunds WHERE order_id=? AND status='PROCESSED' AND id!=?",
                (order_id, refund_id),
            ).fetchall()
            already_refunded = 0
            for pr in processed_refunds:
                pr_items = pr["refund_items"]
                if isinstance(pr_items, str):
                    pr_items = json.loads(pr_items)
                for pri in pr_items:
                    if pri["order_item_id"] == oi_id:
                        already_refunded += pri["quantity"]

            remaining = oi["quantity"] - already_refunded
            if ri["quantity"] > remaining:
                raise_error("ERR_REFUND_EXCEEDS_REMAINING")

    ts = now_iso()
    db.execute(
        "UPDATE refunds SET status='APPROVED', updated_at=?, version=version+1 WHERE id=?",
        (ts, refund_id),
    )
    db.commit()
    refund = row_to_dict(db.execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone())
    return success_response(refund)


@bp.route("/orders/<order_id>/refunds/<refund_id>/reject", methods=["POST"])
def reject_refund(order_id, refund_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    _get_order_or_404(db, order_id)
    refund = db.execute("SELECT * FROM refunds WHERE id=? AND order_id=?", (refund_id, order_id)).fetchone()
    if not refund:
        raise_error("ERR_REFUND_NOT_FOUND")
    if refund["status"] != "REQUESTED":
        raise_error("ERR_REFUND_NOT_REQUESTED")

    ts = now_iso()
    db.execute(
        "UPDATE refunds SET status='REJECTED', updated_at=?, version=version+1 WHERE id=?",
        (ts, refund_id),
    )
    db.commit()
    refund = row_to_dict(db.execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone())
    return success_response(refund)


@bp.route("/orders/<order_id>/refunds/<refund_id>/process", methods=["POST"])
def process_refund(order_id, refund_id):
    require_role("PlatformAdmin")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    refund = db.execute("SELECT * FROM refunds WHERE id=? AND order_id=?", (refund_id, order_id)).fetchone()
    if not refund:
        raise_error("ERR_REFUND_NOT_FOUND")
    if refund["status"] != "APPROVED":
        raise_error("ERR_REFUND_NOT_APPROVED")

    ts = now_iso()
    order_items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    order_items = [dict(oi) for oi in order_items]

    # Calculate previously refunded total
    processed_refunds = db.execute(
        "SELECT refund_amount FROM refunds WHERE order_id=? AND status='PROCESSED'", (order_id,)
    ).fetchall()
    previously_refunded = sum(r["refund_amount"] for r in processed_refunds)

    refund_items = refund["refund_items"]
    if isinstance(refund_items, str):
        refund_items = json.loads(refund_items)

    if refund["refund_type"] == "FULL":
        refund_amount = round2(order["total_amount"] - previously_refunded)
    else:
        # Partial refund calculation
        subtotal = to_decimal(order["subtotal"])
        discount_amount = to_decimal(order["discount_amount"])

        refund_subtotal = Decimal("0")
        refund_items_detail = []

        for ri in refund_items:
            oi = next((o for o in order_items if o["id"] == ri["order_item_id"]), None)
            if not oi:
                raise_error("ERR_ORDER_ITEM_NOT_FOUND")
            item_refund_subtotal = to_decimal(oi["unit_price"]) * Decimal(str(ri["quantity"]))
            refund_subtotal += item_refund_subtotal
            refund_items_detail.append((ri, oi, item_refund_subtotal))

        refund_subtotal = refund_subtotal.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        # Calculate proportional discount share
        total_refund_discount = Decimal("0")
        allocated = Decimal("0")

        sorted_detail = sorted(refund_items_detail, key=lambda x: x[0]["order_item_id"])
        for i, (ri, oi, item_sub) in enumerate(sorted_detail):
            if i < len(sorted_detail) - 1:
                proportion = item_sub / subtotal
                share = (proportion * discount_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                allocated += share
            else:
                # Last item gets remainder
                # Calculate total expected discount share for all refund items
                total_expected = Decimal("0")
                for ri2, oi2, is2 in sorted_detail:
                    total_expected += (is2 / subtotal * discount_amount)
                total_expected = total_expected.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                share = total_expected - allocated

            total_refund_discount += share

        refund_discount_share = total_refund_discount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        refund_amount = float((refund_subtotal - refund_discount_share).quantize(TWO_PLACES, rounding=ROUND_HALF_UP))

        db.execute(
            "UPDATE refunds SET refund_subtotal=?, refund_discount_share=? WHERE id=?",
            (float(refund_subtotal), float(refund_discount_share), refund_id),
        )

    # Check cumulative doesn't exceed total
    if round2(previously_refunded + refund_amount) > round2(order["total_amount"]):
        raise_error("ERR_REFUND_EXCEEDS_ORDER_TOTAL")

    # Create payment record
    payment_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO payments (id, order_id, payment_type, amount, status, created_at)
           VALUES (?, ?, 'REFUND', ?, 'SUCCESS', ?)""",
        (payment_id, order_id, refund_amount, ts),
    )

    # Restore inventory
    if refund["refund_type"] == "FULL":
        for oi in order_items:
            db.execute(
                "UPDATE products SET inventory_count=inventory_count+?, available_count=available_count+?, updated_at=?, version=version+1 WHERE id=?",
                (oi["quantity"], oi["quantity"], ts, oi["product_id"]),
            )
    else:
        for ri in refund_items:
            oi = next((o for o in order_items if o["id"] == ri["order_item_id"]), None)
            db.execute(
                "UPDATE products SET inventory_count=inventory_count+?, available_count=available_count+?, updated_at=?, version=version+1 WHERE id=?",
                (ri["quantity"], ri["quantity"], ts, oi["product_id"]),
            )

    # Update refund status
    db.execute(
        "UPDATE refunds SET refund_amount=?, status='PROCESSED', inventory_restored=1, updated_at=?, version=version+1 WHERE id=?",
        (refund_amount, ts, refund_id),
    )

    # Determine new payment status
    cumulative = round2(previously_refunded + refund_amount)
    is_full = cumulative >= round2(order["total_amount"])

    if is_full or refund["refund_type"] == "FULL":
        new_payment_status = "FULL_REFUND"
    else:
        new_payment_status = "PARTIAL_REFUND"

    db.execute(
        "UPDATE orders SET payment_status=?, updated_at=?, version=version+1 WHERE id=?",
        (new_payment_status, ts, order_id),
    )

    # Update shop settlement_balance and monthly_gmv for full refunds
    shop = db.execute("SELECT * FROM shops WHERE id=?", (order["shop_id"],)).fetchone()
    if is_full or refund["refund_type"] == "FULL":
        # Reverse full: net revenue = total_amount - commission
        net_revenue = round2(order["total_amount"] - order["commission_amount"])
        db.execute(
            """UPDATE shops SET settlement_balance=settlement_balance-?, monthly_gmv=monthly_gmv-?,
               updated_at=?, version=version+1 WHERE id=?""",
            (net_revenue, order["total_amount"], ts, order["shop_id"]),
        )
    else:
        # Partial refund: proportional commission reversal
        if order["total_amount"] > 0:
            proportion = to_decimal(refund_amount) / to_decimal(order["total_amount"])
            commission_reversal = (proportion * to_decimal(order["commission_amount"])).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            net_reversal = (to_decimal(refund_amount) - commission_reversal).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            gmv_reversal = to_decimal(refund_amount)
            db.execute(
                """UPDATE shops SET settlement_balance=settlement_balance-?, monthly_gmv=monthly_gmv-?,
                   updated_at=?, version=version+1 WHERE id=?""",
                (float(net_reversal), float(gmv_reversal), ts, order["shop_id"]),
            )

    db.commit()
    refund = row_to_dict(db.execute("SELECT * FROM refunds WHERE id=?", (refund_id,)).fetchone())
    return success_response(refund)
