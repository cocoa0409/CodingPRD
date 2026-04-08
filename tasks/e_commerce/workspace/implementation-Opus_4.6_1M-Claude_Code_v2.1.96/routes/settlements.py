import uuid
import json
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination, check_version
from response import success_response
from money import round2

bp = Blueprint("settlements", __name__)


def _get_shop_or_404(db, shop_id):
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    return shop


def _get_settlement_or_404(db, shop_id, settlement_id):
    _get_shop_or_404(db, shop_id)
    settlement = db.execute(
        "SELECT * FROM settlements WHERE id=? AND shop_id=?", (settlement_id, shop_id)
    ).fetchone()
    if not settlement:
        raise_error("ERR_SETTLEMENT_NOT_FOUND")
    return settlement


def _compute_settlement(db, shop_id, period_start, period_end):
    # Gross: sum of total_amount for COMPLETED orders delivered in the period
    gross_row = db.execute(
        """SELECT COALESCE(SUM(total_amount), 0) as total FROM orders
           WHERE shop_id=? AND order_status='COMPLETED' AND updated_at>=? AND updated_at<?""",
        (shop_id, period_start, period_end),
    ).fetchone()
    gross_amount = round2(gross_row["total"])

    # Commission: sum of commission_amount for those orders
    commission_row = db.execute(
        """SELECT COALESCE(SUM(commission_amount), 0) as total FROM orders
           WHERE shop_id=? AND order_status='COMPLETED' AND updated_at>=? AND updated_at<?""",
        (shop_id, period_start, period_end),
    ).fetchone()
    total_commission = round2(commission_row["total"])

    # Refunds: sum of refund_amount for PROCESSED refunds in the period
    refund_row = db.execute(
        """SELECT COALESCE(SUM(r.refund_amount), 0) as total FROM refunds r
           JOIN orders o ON r.order_id = o.id
           WHERE o.shop_id=? AND r.status='PROCESSED' AND r.updated_at>=? AND r.updated_at<?""",
        (shop_id, period_start, period_end),
    ).fetchone()
    total_refunds = round2(refund_row["total"])

    net_amount = round2(gross_amount - total_commission - total_refunds)
    return gross_amount, total_commission, total_refunds, net_amount


@bp.route("/shops/<shop_id>/settlements", methods=["POST"])
def create_settlement(shop_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")

    data = request.get_json(force=True, silent=True) or {}
    period_start = data.get("period_start")
    period_end = data.get("period_end")
    if not period_start or not period_end:
        raise_error("ERR_INVALID_REQUEST", "period_start and period_end are required.")

    # Check overlap with non-terminal settlements
    overlap = db.execute(
        """SELECT id FROM settlements WHERE shop_id=? AND status NOT IN ('PAID', 'CANCELLED')
           AND period_start < ? AND period_end > ?""",
        (shop_id, period_end, period_start),
    ).fetchone()
    if overlap:
        raise_error("ERR_SETTLEMENT_PERIOD_OVERLAP")

    gross_amount, total_commission, total_refunds, net_amount = _compute_settlement(
        db, shop_id, period_start, period_end
    )

    settlement_id = str(uuid.uuid4())
    ts = now_iso()
    db.execute(
        """INSERT INTO settlements (id, shop_id, period_start, period_end, gross_amount, total_commission,
           total_refunds, net_amount, status, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, 1)""",
        (settlement_id, shop_id, period_start, period_end, gross_amount, total_commission,
         total_refunds, net_amount, ts, ts),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement, 201)


@bp.route("/shops/<shop_id>/settlements", methods=["GET"])
def list_settlements(shop_id):
    user_id, user_role = require_role("Seller", "PlatformAdmin")
    db = get_db()
    _get_shop_or_404(db, shop_id)
    if user_role == "Seller":
        shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
        if shop["owner_id"] != user_id:
            raise_error("ERR_NOT_SHOP_OWNER")

    limit, offset = parse_pagination(request.args)
    total = db.execute("SELECT COUNT(*) as cnt FROM settlements WHERE shop_id=?", (shop_id,)).fetchone()["cnt"]
    rows = db.execute(
        "SELECT * FROM settlements WHERE shop_id=? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (shop_id, limit, offset),
    ).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/shops/<shop_id>/settlements/<settlement_id>", methods=["GET"])
def get_settlement(shop_id, settlement_id):
    user_id, user_role = require_role("Seller", "PlatformAdmin")
    db = get_db()
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if user_role == "Seller":
        shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
        if shop["owner_id"] != user_id:
            raise_error("ERR_NOT_SHOP_OWNER")
    return success_response(row_to_dict(settlement))


@bp.route("/shops/<shop_id>/settlements/<settlement_id>/submit", methods=["POST"])
def submit_settlement(shop_id, settlement_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if settlement["status"] != "DRAFT":
        raise_error("ERR_SETTLEMENT_NOT_DRAFT")
    if settlement["net_amount"] <= 0:
        raise_error("ERR_SETTLEMENT_ZERO_AMOUNT")

    ts = now_iso()
    db.execute(
        "UPDATE settlements SET status='PENDING_APPROVAL', updated_at=?, version=version+1 WHERE id=?",
        (ts, settlement_id),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement)


@bp.route("/shops/<shop_id>/settlements/<settlement_id>/approve", methods=["POST"])
def approve_settlement(shop_id, settlement_id):
    require_role("PlatformAdmin")
    db = get_db()
    _get_shop_or_404(db, shop_id)
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if settlement["status"] != "PENDING_APPROVAL":
        raise_error("ERR_SETTLEMENT_NOT_PENDING")

    # Reconciliation check
    expected_net = round2(settlement["gross_amount"] - settlement["total_commission"] - settlement["total_refunds"])
    if round2(settlement["net_amount"]) != expected_net:
        raise_error("ERR_SETTLEMENT_RECONCILIATION_MISMATCH")

    ts = now_iso()
    db.execute(
        "UPDATE settlements SET status='APPROVED', updated_at=?, version=version+1 WHERE id=?",
        (ts, settlement_id),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement)


@bp.route("/shops/<shop_id>/settlements/<settlement_id>/mark-paid", methods=["POST"])
def mark_paid(shop_id, settlement_id):
    require_role("PlatformAdmin")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if settlement["status"] != "APPROVED":
        raise_error("ERR_SETTLEMENT_NOT_APPROVED")

    ts = now_iso()
    db.execute(
        "UPDATE settlements SET status='PAID', updated_at=?, version=version+1 WHERE id=?",
        (ts, settlement_id),
    )
    db.execute(
        "UPDATE shops SET settlement_balance=settlement_balance-?, updated_at=?, version=version+1 WHERE id=?",
        (settlement["net_amount"], ts, shop_id),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement)


@bp.route("/shops/<shop_id>/settlements/<settlement_id>/dispute", methods=["POST"])
def dispute_settlement(shop_id, settlement_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if settlement["status"] != "PENDING_APPROVAL":
        raise_error("ERR_SETTLEMENT_NOT_PENDING")

    ts = now_iso()
    db.execute(
        "UPDATE settlements SET status='DISPUTED', updated_at=?, version=version+1 WHERE id=?",
        (ts, settlement_id),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement)


@bp.route("/shops/<shop_id>/settlements/<settlement_id>/resolve-dispute", methods=["POST"])
def resolve_dispute(shop_id, settlement_id):
    require_role("PlatformAdmin")
    db = get_db()
    _get_shop_or_404(db, shop_id)
    settlement = _get_settlement_or_404(db, shop_id, settlement_id)
    if settlement["status"] != "DISPUTED":
        raise_error("ERR_SETTLEMENT_NOT_DISPUTED_STATE")

    # Recalculate settlement amounts
    gross_amount, total_commission, total_refunds, net_amount = _compute_settlement(
        db, shop_id, settlement["period_start"], settlement["period_end"]
    )

    ts = now_iso()
    db.execute(
        """UPDATE settlements SET gross_amount=?, total_commission=?, total_refunds=?, net_amount=?,
           status='PENDING_APPROVAL', updated_at=?, version=version+1 WHERE id=?""",
        (gross_amount, total_commission, total_refunds, net_amount, ts, settlement_id),
    )
    db.commit()
    settlement = row_to_dict(db.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone())
    return success_response(settlement)
