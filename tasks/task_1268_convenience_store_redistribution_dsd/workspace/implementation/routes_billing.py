"""Invoices, payments (apply/reverse), and credit memos (create/post/void)."""
from flask import Blueprint, request

from db import STORE, new_record, touch, public
from errors import (
    ApiError, not_found, invalid_state, forbidden,
    ERR_PAYMENT_EXCEEDS_BALANCE, ERR_MEMO_EXCEEDS_INVOICE,
)
from middleware import (
    authenticate, require_role, check_store_ownership, parse_body,
    req_int, req_enum, parse_pagination, list_page,
)
from response import ok_object, ok_list
from services import refresh_retailer, OPEN_INVOICE_STATUSES

bp = Blueprint('billing', __name__)

INVOICE_READ_ROLES = ('WholesaleAdmin', 'CreditManager', 'StoreManager')
PAYMENT_METHODS = ('CASH_ON_DELIVERY', 'CHECK', 'ACH')
MEMO_ORIGINS = ('SHORT', 'DAMAGE', 'MANUAL')


def get_invoice_or_404(iid):
    rec = STORE['invoices'].get(iid)
    if rec is None:
        raise not_found('invoice %s does not exist' % iid)
    return rec


def get_payment_or_404(pid):
    rec = STORE['payments'].get(pid)
    if rec is None:
        raise not_found('payment %s does not exist' % pid)
    return rec


def get_memo_or_404(mid):
    rec = STORE['credit_memos'].get(mid)
    if rec is None:
        raise not_found('credit memo %s does not exist' % mid)
    return rec


def applied_payments_total(invoice_id):
    return sum(p['amount_cents'] for p in STORE['payments'].values()
               if p['invoice_id'] == invoice_id and p['status'] == 'APPLIED')


# ------------------------------------------------------------------ invoices

@bp.get('/invoices')
def list_invoices():
    uid, role = authenticate()
    require_role(role, INVOICE_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(STORE['invoices'].values())
    if role == 'StoreManager':
        requested = request.args.get('retailer_id')
        if requested is not None and requested != uid:
            raise forbidden('store manager may only list their own invoices')
        items = [i for i in items if i['retailer_id'] == uid]
    for param in ('order_id', 'retailer_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/invoices/<iid>')
def get_invoice(iid):
    uid, role = authenticate()
    require_role(role, INVOICE_READ_ROLES)
    rec = get_invoice_or_404(iid)
    check_store_ownership(uid, role, rec['retailer_id'])
    return ok_object(public(rec))


# ------------------------------------------------------------------ payments

@bp.post('/invoices/<iid>/payments')
def apply_payment(iid):
    uid, role = authenticate()
    body = parse_body()
    amount = req_int(body, 'amount_cents', minimum=1)
    method = req_enum(body, 'method', PAYMENT_METHODS)
    require_role(role, ('CreditManager',))
    invoice = get_invoice_or_404(iid)

    if invoice['status'] not in OPEN_INVOICE_STATUSES:
        raise invalid_state('invoice is not open for payment application')
    if amount > invoice['balance_cents']:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, 422,
                       'payment amount exceeds invoice balance_cents')

    payment = new_record()
    payment.update({
        'invoice_id': invoice['id'],
        'amount_cents': amount,
        'method': method,
        'status': 'APPLIED',
    })
    STORE['payments'][payment['id']] = payment

    invoice['balance_cents'] = invoice['balance_cents'] - amount
    if invoice['balance_cents'] == 0:
        invoice['status'] = 'PAID'
    else:
        invoice['status'] = 'PARTIALLY_PAID'
    touch(invoice)
    refresh_retailer(STORE['retailers'][invoice['retailer_id']])
    return ok_object(public(payment), 201)


@bp.get('/invoices/<iid>/payments')
def list_payments(iid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager'))
    limit, offset = parse_pagination()
    invoice = get_invoice_or_404(iid)
    items = [p for p in STORE['payments'].values() if p['invoice_id'] == invoice['id']]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post('/payments/<pid>/reverse')
def reverse_payment(pid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('CreditManager',))
    payment = get_payment_or_404(pid)
    if payment['status'] != 'APPLIED':
        raise invalid_state('only an APPLIED payment may be reversed')
    payment['status'] = 'REVERSED'
    touch(payment)

    invoice = STORE['invoices'][payment['invoice_id']]
    invoice['balance_cents'] = invoice['balance_cents'] + payment['amount_cents']
    if invoice['status'] == 'PAID':
        # the reversed payment closed (or helped close) the invoice
        invoice['status'] = 'OPEN' if applied_payments_total(invoice['id']) == 0 \
            else 'PARTIALLY_PAID'
    elif invoice['status'] == 'PARTIALLY_PAID':
        if invoice['balance_cents'] == invoice['invoiced_total_cents']:
            invoice['status'] = 'OPEN'
    touch(invoice)
    refresh_retailer(STORE['retailers'][invoice['retailer_id']])
    return ok_object(public(payment))


# --------------------------------------------------------------- credit memos

@bp.post('/invoices/<iid>/credit-memos')
def create_credit_memo(iid):
    uid, role = authenticate()
    body = parse_body()
    origin = req_enum(body, 'origin', MEMO_ORIGINS)
    amount = req_int(body, 'amount_cents', minimum=1)
    require_role(role, ('CreditManager',))
    invoice = get_invoice_or_404(iid)

    if amount > invoice['balance_cents']:
        raise ApiError(ERR_MEMO_EXCEEDS_INVOICE, 422,
                       'credit memo amount exceeds invoice balance_cents')

    memo = new_record()
    memo.update({
        'invoice_id': invoice['id'],
        'exception_id': None,
        'origin': origin,
        'amount_cents': amount,
        'status': 'DRAFT',
    })
    STORE['credit_memos'][memo['id']] = memo
    return ok_object(public(memo), 201)


@bp.get('/invoices/<iid>/credit-memos')
def list_invoice_credit_memos(iid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager'))
    limit, offset = parse_pagination()
    invoice = get_invoice_or_404(iid)
    items = [m for m in STORE['credit_memos'].values()
             if m['invoice_id'] == invoice['id']]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/credit-memos')
def list_credit_memos():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager'))
    limit, offset = parse_pagination()
    items = list(STORE['credit_memos'].values())
    for param in ('invoice_id', 'exception_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/credit-memos/<mid>')
def get_credit_memo(mid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager'))
    rec = get_memo_or_404(mid)
    return ok_object(public(rec))


@bp.post('/credit-memos/<mid>/post')
def post_credit_memo(mid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('CreditManager',))
    memo = get_memo_or_404(mid)
    if memo['status'] != 'DRAFT':
        raise invalid_state('only a DRAFT credit memo may be posted')
    invoice = STORE['invoices'][memo['invoice_id']]
    if invoice['status'] not in OPEN_INVOICE_STATUSES:
        raise invalid_state('invoice is not open for credit posting')
    if memo['amount_cents'] > invoice['balance_cents']:
        raise ApiError(ERR_MEMO_EXCEEDS_INVOICE, 422,
                       'credit memo amount exceeds invoice balance_cents')

    memo['status'] = 'POSTED'
    touch(memo)
    invoice['balance_cents'] = invoice['balance_cents'] - memo['amount_cents']
    if invoice['balance_cents'] == 0:
        invoice['status'] = 'PAID'
    elif invoice['status'] == 'OPEN':
        invoice['status'] = 'PARTIALLY_PAID'
    touch(invoice)
    refresh_retailer(STORE['retailers'][invoice['retailer_id']])
    return ok_object(public(memo))


@bp.post('/credit-memos/<mid>/void')
def void_credit_memo(mid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('CreditManager',))
    memo = get_memo_or_404(mid)
    if memo['status'] != 'POSTED':
        raise invalid_state('only a POSTED credit memo may be voided')

    memo['status'] = 'VOIDED'
    touch(memo)
    invoice = STORE['invoices'][memo['invoice_id']]
    invoice['balance_cents'] = invoice['balance_cents'] + memo['amount_cents']
    if invoice['status'] == 'PAID':
        # invoice had reached PAID only because of this credit: fall back per
        # remaining payments
        invoice['status'] = 'PARTIALLY_PAID' if applied_payments_total(invoice['id']) > 0 \
            else 'OPEN'
    touch(invoice)
    refresh_retailer(STORE['retailers'][invoice['retailer_id']])
    return ok_object(public(memo))
