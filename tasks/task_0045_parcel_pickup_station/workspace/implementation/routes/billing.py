"""Billing period, Bill, payment, dispute routes."""
from flask import Blueprint, request
from response import ok_object, ok_array, error_response
from middleware import require_roles, get_auth
from services.common import parse_pagination, sort_by_created
from services.billing import (
    create_or_fetch_period, get_period_by_yyyymm, get_period, get_bill,
    close_billing_period, pay_bill, dispute_bill, resolve_dispute, write_off_bill,
)
from services.station import get_station
from services.serialize import billing_period as ser_bp, bill as ser_bill
from db import store


bp = Blueprint("billing", __name__)


@bp.post("/stations/<station_id>/billing-periods")
@require_roles("Manager", "PlatformAdmin")
def post_billing_period(station_id):
    body = request.get_json(silent=True, force=True) or {}
    period, created = create_or_fetch_period(station_id, body)
    status = 201 if created else 200
    return ok_object(ser_bp(period), status=status)


@bp.post("/stations/<station_id>/billing-periods/<period_yyyymm>/close")
@require_roles("Manager")
def post_close_period(station_id, period_yyyymm):
    user_id, role = get_auth()
    p = close_billing_period(station_id, period_yyyymm, role, user_id)
    return ok_object(ser_bp(p))


@bp.get("/stations/<station_id>/billing-periods/<period_yyyymm>")
@require_roles("Manager", "PlatformAdmin")
def read_period_by_yyyymm(station_id, period_yyyymm):
    get_station(station_id)
    p = get_period_by_yyyymm(station_id, period_yyyymm)
    return ok_object(ser_bp(p))


@bp.get("/billing-periods/<billing_period_id>/bills")
@require_roles("Manager", "PlatformAdmin", "CourierCompany", "Recipient")
def list_bills(billing_period_id):
    get_period(billing_period_id)
    limit, offset = parse_pagination(request.args)
    payer_kind = request.args.get("payer_kind")
    status_f = request.args.get("status")
    items = [b for b in store.bills.values() if b["billing_period_id"] == billing_period_id]
    if payer_kind:
        items = [b for b in items if b["payer_kind"] == payer_kind]
    if status_f:
        items = [b for b in items if b["status"] == status_f]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([ser_bill(i) for i in page], limit, offset, total)


@bp.get("/bills/<bill_id>")
@require_roles("Manager", "PlatformAdmin", "CourierCompany", "Recipient")
def read_bill(bill_id):
    b = get_bill(bill_id)
    return ok_object(ser_bill(b))


@bp.post("/bills/<bill_id>/payments")
@require_roles("PaymentSystem")
def post_payment(bill_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    kind, bill = pay_bill(bill_id, body, role, user_id)
    if kind == "replay":
        # Synthetic ERR_IDEMPOTENCY_REPLAY at HTTP 200
        return error_response("ERR_IDEMPOTENCY_REPLAY",
                              "Idempotency key replay; returning prior result", 200)
    return ok_object(ser_bill(bill))


@bp.post("/bills/<bill_id>/dispute")
@require_roles("Recipient", "CourierCompany")
def post_dispute(bill_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    b = dispute_bill(bill_id, body, role, user_id)
    return ok_object(ser_bill(b))


@bp.post("/bills/<bill_id>/resolve-dispute")
@require_roles("Manager")
def post_resolve_dispute(bill_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    b = resolve_dispute(bill_id, body, role, user_id)
    return ok_object(ser_bill(b))


@bp.post("/bills/<bill_id>/write-off")
@require_roles("Manager")
def post_write_off(bill_id):
    user_id, role = get_auth()
    body = request.get_json(silent=True, force=True) or {}
    b = write_off_bill(bill_id, body, role, user_id)
    return ok_object(ser_bill(b))
