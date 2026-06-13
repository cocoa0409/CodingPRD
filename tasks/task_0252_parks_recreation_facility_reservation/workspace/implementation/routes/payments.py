"""Payment + refund read endpoints (PRD §3.4)."""
from flask import Blueprint, request

import errors
import serializers
from db import db, stamp_create
from helpers import parse_body, require_fields, require_int, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from routes.permits import get_permit_or_404

bp = Blueprint("payments", __name__)


@bp.post("/permits/<permit_id>/payments")
def create_payment(permit_id):
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator"})
    permit = get_permit_or_404(permit_id)
    body = parse_body()
    require_fields(body, ["fee_component_cents", "deposit_component_cents"])
    fee = require_int(body, "fee_component_cents", minimum=0)
    deposit = require_int(body, "deposit_component_cents", minimum=0)

    rec = {
        "permit_id": permit_id,
        "fee_component_cents": fee,
        "deposit_component_cents": deposit,
        "status": "CAPTURED",
    }
    stamp_create(rec)
    db.payments[rec["id"]] = rec
    return success(serializers.payment(rec), status=201)


@bp.get("/permits/<permit_id>/payments")
def list_permit_payments(permit_id):
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    get_permit_or_404(permit_id)
    items = [p for p in db.payments.values() if p["permit_id"] == permit_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.payment(p) for p in page], pagination=meta)


@bp.get("/payments/<payment_id>")
def get_payment(payment_id):
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    p = db.payments.get(payment_id)
    if p is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Payment not found")
    return success(serializers.payment(p))


@bp.get("/payments")
def list_payments():
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    items = list(db.payments.values())
    permit_id = request.args.get("permit_id")
    if permit_id:
        items = [p for p in items if p["permit_id"] == permit_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.payment(p) for p in page], pagination=meta)


@bp.get("/refunds/<refund_id>")
def get_refund(refund_id):
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    r = db.refunds.get(refund_id)
    if r is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Refund not found")
    return success(serializers.refund(r))


@bp.get("/permits/<permit_id>/refunds")
def list_permit_refunds(permit_id):
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    get_permit_or_404(permit_id)
    items = [r for r in db.refunds.values() if r["permit_id"] == permit_id]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.refund(r) for r in page], pagination=meta)


@bp.get("/refunds")
def list_refunds():
    _, role = get_identity()
    require_roles(role, {"FinanceClerk", "RecCoordinator", "Patron"})
    items = list(db.refunds.values())
    payment_id = request.args.get("payment_id")
    if payment_id:
        items = [r for r in items if r["payment_id"] == payment_id]
    permit_id = request.args.get("permit_id")
    if permit_id:
        items = [r for r in items if r["permit_id"] == permit_id]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.refund(r) for r in page], pagination=meta)
