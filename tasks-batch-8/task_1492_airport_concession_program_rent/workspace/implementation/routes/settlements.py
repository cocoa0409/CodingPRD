"""Rent settlement and payment endpoints (PRD sections 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_REQUEST,
                    ERR_SETTLEMENT_YEAR_DUPLICATE, ERR_SETTLEMENT_STATE_FORBIDS,
                    ERR_SETTLEMENT_NOT_INVOICABLE, ERR_SETTLEMENT_PERIOD_OPEN,
                    ERR_SETTLEMENT_NOT_PAYABLE, ERR_INVALID_AMOUNT,
                    ERR_PAYMENT_EXCEEDS_BALANCE, ERR_PAYMENT_ALREADY_VOIDED)
from middleware import require_roles, body_json, req_str, req_int, require_lease_owner
from response import ok, ok_list
from services.core import (pub, touch, parse_date, compute_settlement_amounts,
                           recalc_settlement, recompute_arrears,
                           SETTLEMENT_DUE_DAYS, SETTLEMENT_ACTIVE_STATUSES)
from services.validation import check_enum, paginate

bp = Blueprint('settlements', __name__)

SETTLEMENT_STATUSES = ('ACCRUING', 'INVOICED', 'PARTIALLY_PAID', 'OVERDUE', 'PAID')
PAYMENT_METHODS = ('ACH', 'CHECK', 'WIRE', 'CARD')


def get_settlement_or_404(sid):
    st = db.settlements.get(sid)
    if st is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Rent settlement not found')
    return st


def settlement_lease(st):
    return db.leases[st['lease_id']]


@bp.route('/concessions/settlements', methods=['POST'])
def create_settlement():
    require_roles('AirportAdmin')
    body = body_json()
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    lease_id = req_str(body, 'lease_id')
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    year = req_int(body, 'period_year')
    # Stage 7: one settlement per (lease, period_year).
    for s in db.settlements.values():
        if s['lease_id'] == lease_id and s['period_year'] == year:
            raise ApiError(ERR_SETTLEMENT_YEAR_DUPLICATE, 409,
                           'A settlement already exists for this lease and year')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'period_year': year,
        'variant_used': 'PROVISIONAL',
        'due_date': None,
        'status': 'ACCRUING',
        'amount_paid_cents': 0,
    })
    db.settlements[rec['id']] = rec
    # The first calculation runs immediately under the PROVISIONAL variant.
    rec.update(compute_settlement_amounts(lease, rec, 'PROVISIONAL'))
    return ok(pub(rec), status=201)


@bp.route('/concessions/settlements', methods=['GET'])
def list_settlements():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.settlements.values(), key=lambda s: s['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, SETTLEMENT_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [s for s in items if s['lease_id'] in own]
    if f_lease is not None:
        items = [s for s in items if s['lease_id'] == f_lease]
    if f_status is not None:
        items = [s for s in items if s['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(s) for s in page], meta)


@bp.route('/concessions/settlements/<sid>', methods=['GET'])
def get_settlement(sid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    st = get_settlement_or_404(sid)
    if g.role == 'Tenant':
        require_lease_owner(settlement_lease(st))
    return ok(pub(st))


@bp.route('/concessions/settlements/<sid>/recalculate', methods=['POST'])
def recalculate_settlement(sid):
    require_roles('ConcessionAnalyst')
    st = get_settlement_or_404(sid)
    # Manual recalculation of a PAID settlement is forbidden.
    if st['status'] == 'PAID':
        raise ApiError(ERR_SETTLEMENT_STATE_FORBIDS, 409,
                       'Manual recalculation of a PAID settlement is forbidden')
    if st['status'] not in ('ACCRUING', 'INVOICED', 'PARTIALLY_PAID', 'OVERDUE'):
        raise ApiError(ERR_SETTLEMENT_STATE_FORBIDS, 409,
                       'Settlement cannot be recalculated from its current status')
    # Recompute under the variant implied by the current status.
    recalc_settlement(st)
    recompute_arrears(settlement_lease(st))
    return ok(pub(st))


@bp.route('/concessions/settlements/<sid>/invoice', methods=['POST'])
def invoice_settlement(sid):
    require_roles('ConcessionAnalyst')
    st = get_settlement_or_404(sid)
    # Stage 6: invoice only from ACCRUING.
    if st['status'] != 'ACCRUING':
        raise ApiError(ERR_SETTLEMENT_NOT_INVOICABLE, 409,
                       'Invoice is valid only from ACCRUING')
    # Stage 8: the settlement year must have fully elapsed.
    last_day = '{0}-12-31'.format(st['period_year'])
    if not db.clock.date() > parse_date(last_day):
        raise ApiError(ERR_SETTLEMENT_PERIOD_OPEN, 422,
                       'The settlement year has not fully elapsed')
    # Final recalculation under FINAL semantics; due_date = current date + 30.
    recalc_settlement(st, variant='FINAL')
    st['due_date'] = (db.clock.date() + timedelta(days=SETTLEMENT_DUE_DAYS)).isoformat()
    st['status'] = 'INVOICED'
    recompute_arrears(settlement_lease(st))
    return ok(pub(st))


@bp.route('/concessions/settlements/<sid>/payments', methods=['POST'])
def post_payment(sid):
    require_roles('Tenant')
    st = get_settlement_or_404(sid)
    lease = settlement_lease(st)
    require_lease_owner(lease)
    body = body_json()
    amount = req_int(body, 'amount_cents')
    method = req_str(body, 'method')
    check_enum(method, PAYMENT_METHODS, 'method')
    # Stage 6: settlement must be payable.
    if st['status'] not in SETTLEMENT_ACTIVE_STATUSES:
        raise ApiError(ERR_SETTLEMENT_NOT_PAYABLE, 409,
                       'Settlement is not payable in its current status')
    # Stage 9: fiscal rules — positive, and no greater than the balance.
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, 'amount_cents must be > 0')
    if amount > st['balance_due_cents']:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, 422,
                       'Payment exceeds the settlement balance_due_cents')
    rec = base_fields()
    rec.update({
        'settlement_id': st['id'],
        'amount_cents': amount,
        'method': method,
        'status': 'POSTED',
    })
    db.payments[rec['id']] = rec
    # Recompute balances and reposition the settlement status.
    paid = sum(p['amount_cents'] for p in db.payments.values()
               if p['settlement_id'] == st['id'] and p['status'] == 'POSTED')
    st['amount_paid_cents'] = paid
    st['balance_due_cents'] = st['amount_due_cents'] - paid
    st['status'] = 'PAID' if st['balance_due_cents'] == 0 else 'PARTIALLY_PAID'
    touch(st)
    recompute_arrears(lease)
    return ok(pub(rec), status=201)


@bp.route('/concessions/settlements/<sid>/payments', methods=['GET'])
def list_payments(sid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    st = get_settlement_or_404(sid)
    if g.role == 'Tenant':
        require_lease_owner(settlement_lease(st))
    items = sorted((p for p in db.payments.values() if p['settlement_id'] == sid),
                   key=lambda p: p['_seq'])
    page, meta = paginate(items)
    return ok_list([pub(p) for p in page], meta)


@bp.route('/concessions/payments/<pid>/void', methods=['POST'])
def void_payment(pid):
    require_roles('ConcessionAnalyst')
    p = db.payments.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Payment not found')
    if p['status'] != 'POSTED':
        raise ApiError(ERR_PAYMENT_ALREADY_VOIDED, 409,
                       'Only a POSTED payment can be voided')
    p['status'] = 'VOIDED'
    touch(p)
    st = db.settlements[p['settlement_id']]
    lease = settlement_lease(st)
    # Re-derive balances and status: a void never re-applies OVERDUE.
    paid = sum(x['amount_cents'] for x in db.payments.values()
               if x['settlement_id'] == st['id'] and x['status'] == 'POSTED')
    st['amount_paid_cents'] = paid
    st['balance_due_cents'] = st['amount_due_cents'] - paid
    st['status'] = 'INVOICED' if paid == 0 else 'PARTIALLY_PAID'
    touch(st)
    recompute_arrears(lease)
    return ok(pub(p))
