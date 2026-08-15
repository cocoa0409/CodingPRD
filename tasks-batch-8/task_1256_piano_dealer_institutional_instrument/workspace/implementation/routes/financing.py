from flask import Blueprint, request

import calc
import db
from errors import ApiError, invalid, forbidden
from middleware import auth
from response import ok, ok_list
from util import body, require, optional, as_str, as_int, as_num, as_enum, find, serialize
from routes.orders import sell_order_instruments

bp = Blueprint('financing', __name__)

DT_FIELDS = ('activated_at',)


def ser_agreement(a):
    out = serialize(a, DT_FIELDS)
    # Derived fields are recomputed on every read/write of the agreement.
    out['missed_payments'] = calc.missed_payments(a)
    if a['program'] == 'RENT_TO_OWN':
        out['purchase_credit_cents'] = calc.purchase_credit(a)
    return out


@bp.post('/piano-dealer/financing-agreements')
def create_agreement():
    auth('FinanceOfficer')
    d = body()
    order_id = as_str(require(d, 'order_id'), 'order_id')
    program = as_enum(require(d, 'program'), 'program', ('STANDARD', 'RENT_TO_OWN'))
    principal = as_int(require(d, 'principal_cents'), 'principal_cents')
    term_months = as_int(require(d, 'term_months'), 'term_months')
    apr = optional(d, 'apr')
    if program == 'STANDARD':
        if apr is None:
            raise invalid('apr is required for STANDARD financing')
        apr = as_num(apr, 'apr')
    if term_months <= 0:
        raise invalid('term_months must be positive')
    order = find(db.stores['orders'], order_id, 'order')
    if order['payment_status'] != 'UNPAID':
        raise ApiError('ERR_ORDER_NOT_PAYABLE', 409,
                       'financing requires an UNPAID order')
    if principal != order['total_cents']:
        raise invalid('principal_cents must equal the order total_cents')
    rec = db.base_fields()
    rec.update({
        'order_id': order_id,
        'program': program,
        'principal_cents': principal,
        'apr': apr if program == 'STANDARD' else None,
        'term_months': term_months,
        'monthly_amount_cents': calc.monthly_amount(program, principal, apr, term_months),
        'payments_made': 0,
        'missed_payments': 0,
        'purchase_credit_cents': 0,
        'activated_at': None,
        'status': 'APPLIED',
    })
    db.stores['agreements'][rec['id']] = rec
    return ok(ser_agreement(rec), 201)


@bp.get('/piano-dealer/financing-agreements/<rid>')
def get_agreement(rid):
    uid, role = auth('FinanceOfficer', 'Customer')
    agreement = find(db.stores['agreements'], rid, 'financing agreement')
    if role == 'Customer':
        order = find(db.stores['orders'], agreement['order_id'], 'order')
        if order['customer_id'] != uid:
            raise forbidden('customer may only read their own agreements')
    return ok(ser_agreement(agreement))


@bp.get('/piano-dealer/financing-agreements')
def list_agreements():
    auth('FinanceOfficer')
    items = list(db.stores['agreements'].values())
    order_id = request.args.get('order_id')
    if order_id:
        items = [a for a in items if a['order_id'] == order_id]
    return ok_list(items, ser_agreement)


@bp.post('/piano-dealer/financing-agreements/<rid>/approve')
def approve_agreement(rid):
    auth('FinanceOfficer')
    agreement = find(db.stores['agreements'], rid, 'financing agreement')
    if agreement['status'] != 'APPLIED':
        raise invalid('only APPLIED agreements can be approved')
    order = find(db.stores['orders'], agreement['order_id'], 'order')
    customer = find(db.stores['customers'], order['customer_id'], 'customer')
    if agreement['principal_cents'] > customer['credit_limit_cents']:
        raise ApiError('ERR_CREDIT_LIMIT_EXCEEDED', 422,
                       'principal exceeds the customer credit limit')
    agreement['status'] = 'ACTIVE'
    agreement['activated_at'] = db.now()
    db.touch(agreement)
    order['payment_status'] = 'FINANCED_ACTIVE'
    db.touch(order)
    sell_order_instruments(order)
    return ok(ser_agreement(agreement))


@bp.post('/piano-dealer/financing-agreements/<rid>/payments')
def post_agreement_payment(rid):
    auth('FinanceOfficer')
    agreement = find(db.stores['agreements'], rid, 'financing agreement')
    d = body()
    amount = as_int(require(d, 'amount_cents'), 'amount_cents')
    if agreement['status'] != 'ACTIVE':
        raise invalid('payments require an ACTIVE agreement')
    if amount != agreement['monthly_amount_cents']:
        raise invalid('each payment must be exactly one monthly_amount_cents')
    agreement['payments_made'] += 1
    db.touch(agreement)
    if agreement['payments_made'] >= agreement['term_months']:
        agreement['status'] = 'PAID_OFF'
        db.touch(agreement)
        order = find(db.stores['orders'], agreement['order_id'], 'order')
        if order['payment_status'] == 'FINANCED_ACTIVE':
            order['payment_status'] = 'PAID_IN_FULL'
            db.touch(order)
    return ok(ser_agreement(agreement))


@bp.post('/piano-dealer/financing-agreements/<rid>/convert-to-purchase')
def convert_to_purchase(rid):
    auth('FinanceOfficer')
    agreement = find(db.stores['agreements'], rid, 'financing agreement')
    not_convertible = ApiError('ERR_AGREEMENT_NOT_CONVERTIBLE', 409,
                               'only ACTIVE RENT_TO_OWN agreements can be converted')
    if agreement['status'] != 'ACTIVE':
        raise not_convertible
    if agreement['program'] != 'RENT_TO_OWN':
        raise not_convertible
    agreement['purchase_credit_cents'] = calc.purchase_credit(agreement)
    agreement['status'] = 'CONVERTED_TO_PURCHASE'
    db.touch(agreement)
    order = find(db.stores['orders'], agreement['order_id'], 'order')
    if order['payment_status'] == 'FINANCED_ACTIVE':
        order['payment_status'] = 'PAID_IN_FULL'
        db.touch(order)
    return ok(ser_agreement(agreement))


@bp.post('/piano-dealer/financing-agreements/<rid>/declare-default')
def declare_default(rid):
    auth('FinanceOfficer')
    agreement = find(db.stores['agreements'], rid, 'financing agreement')
    if agreement['status'] != 'ACTIVE':
        raise invalid('default can only be declared on an ACTIVE agreement')
    missed = calc.missed_payments(agreement)
    agreement['missed_payments'] = missed
    if missed < calc.DEFAULT_THRESHOLD_MISSED:
        raise invalid('at least 3 missed payments are required to declare default')
    agreement['status'] = 'DEFAULTED'
    db.touch(agreement)
    order = find(db.stores['orders'], agreement['order_id'], 'order')
    if order['payment_status'] == 'FINANCED_ACTIVE':
        order['payment_status'] = 'COLLECTIONS'
        db.touch(order)
    for item in order['items']:
        inst = find(db.stores['instruments'], item['instrument_id'], 'instrument')
        if inst['status'] == 'DELIVERED':
            inst['status'] = 'REPOSSESSION_HOLD'
            db.touch(inst)
    customer = find(db.stores['customers'], order['customer_id'], 'customer')
    customer['risk_score'] = min(850, max(300, customer['risk_score'] - 150))
    db.touch(customer)
    return ok(ser_agreement(agreement))
