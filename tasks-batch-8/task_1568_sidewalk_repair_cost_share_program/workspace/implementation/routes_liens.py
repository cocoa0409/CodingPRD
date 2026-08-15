"""LienCase lifecycle: assess, read (statement variant), payoff quote,
record, payments (per-event accrual + interest-first waterfall),
foreclosure referral."""
from flask import Blueprint, g, request

from db import db, base_entity, touch
from errors import ApiError, not_found, ownership
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services import (FORECLOSURE_MIN_DAYS, PAYOFF_GOOD_THROUGH_DAYS,
                      TERMINAL_LIEN_STATUSES, compute_lien_principal,
                      lien_day, owner_id_of_parcel, project_interest,
                      recompute_delinquency_flag, ser_lien)
from util import rhu, dec  # noqa: F401  (kept for symmetry; accrual math in services)
from validation import get_body, parse_pagination, validate

bp = Blueprint('liens', __name__)


@bp.post('/lien-cases')
@require_roles('FinanceOfficer')
def create_lien():
    vals = validate(get_body(), [
        ('notice_id', 'str', True, {}),
        ('actual_repair_cost_cents', 'int', True, {'positive': True}),
        ('interest_rate_bp', 'int', False, {'default': 800, 'positive': True}),
    ])
    notice = db.notices.get(vals['notice_id'])
    if not notice:
        raise not_found('notice')
    if notice['status'] != 'CITY_REPAIR_COMPLETED':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409,
                       'Notice is not CITY_REPAIR_COMPLETED')
    if any(l['notice_id'] == notice['id'] and l['status'] not in TERMINAL_LIEN_STATUSES
           for l in db.liens.values()):
        raise ApiError('ERR_LIEN_ALREADY_EXISTS', 409,
                       'Notice already has a non-terminal lien')
    admin_fee, city_credit, owner_principal = compute_lien_principal(
        notice, vals['actual_repair_cost_cents'])
    l = base_entity()
    l.update({
        'notice_id': notice['id'],
        'parcel_id': notice['parcel_id'],
        'actual_repair_cost_cents': vals['actual_repair_cost_cents'],
        'admin_fee_cents': admin_fee,
        'city_credit_cents': city_credit,
        'owner_principal_cents': owner_principal,
        'interest_rate_bp': vals['interest_rate_bp'],
        'assessed_at': db.clock,
        'principal_remaining_cents': owner_principal,
        'accrued_interest_cents': 0,
        'last_accrual_day': 0,
        'outstanding_balance_cents': owner_principal,
        'status': 'ASSESSED',
    })
    db.liens[l['id']] = l
    notice['status'] = 'LIENED'
    touch(notice)
    return ok_object(ser_lien(l), 201)


@bp.get('/lien-cases')
@require_roles(*ALL_ROLES)
def list_liens():
    rows = list(db.liens.values())
    if g.role == 'PropertyOwner':
        rows = [l for l in rows if owner_id_of_parcel(l['parcel_id']) == g.uid]
    notice_id = request.args.get('notice_id')
    if notice_id is not None:
        rows = [l for l in rows if l['notice_id'] == notice_id]
    parcel_id = request.args.get('parcel_id')
    if parcel_id is not None:
        rows = [l for l in rows if l['parcel_id'] == parcel_id]
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser_lien(l) for l in page], total, limit, offset)


@bp.get('/lien-cases/<lid>')
@require_roles(*ALL_ROLES)
def get_lien(lid):
    """Statement variant: stored interest plus projection to the current clock day."""
    l = db.liens.get(lid)
    if not l:
        raise not_found('lien')
    proj = project_interest(l, lien_day(l, db.clock))
    accrued = l['accrued_interest_cents'] + proj
    outstanding = l['principal_remaining_cents'] + accrued
    return ok_object(ser_lien(l, accrued=accrued, outstanding=outstanding))


@bp.get('/lien-cases/<lid>/payoff-quote')
@require_roles(*ALL_ROLES)
def payoff_quote(lid):
    """Payoff variant: interest projected through current clock day + 15 days."""
    l = db.liens.get(lid)
    if not l:
        raise not_found('lien')
    today = lien_day(l, db.clock)
    projected = project_interest(l, today + PAYOFF_GOOD_THROUGH_DAYS)
    total = l['principal_remaining_cents'] + l['accrued_interest_cents'] + projected
    from datetime import timedelta
    good_through = (db.clock.date() + timedelta(days=PAYOFF_GOOD_THROUGH_DAYS)).isoformat()
    return ok_object({
        'principal_remaining_cents': l['principal_remaining_cents'],
        'accrued_interest_cents': l['accrued_interest_cents'],
        'projected_interest_cents': projected,
        'good_through_date': good_through,
        'payoff_total_cents': total,
    })


@bp.post('/lien-cases/<lid>/record')
@require_roles('FinanceOfficer')
def record_lien(lid):
    l = db.liens.get(lid)
    if not l:
        raise not_found('lien')
    if l['status'] != 'ASSESSED':
        raise ApiError('ERR_INVALID_LIEN_STATE', 409, 'Lien is not ASSESSED')
    l['status'] = 'RECORDED'
    touch(l)
    return ok_object(ser_lien(l))


@bp.post('/lien-cases/<lid>/payments')
@require_roles('PropertyOwner')
def pay_lien(lid):
    vals = validate(get_body(), [('amount_cents', 'int', True, {'positive': True})])
    l = db.liens.get(lid)
    if not l:
        raise not_found('lien')
    if owner_id_of_parcel(l['parcel_id']) != g.uid:
        raise ownership('Acting owner does not own this lien\'s parcel')
    if l['status'] not in ('RECORDED', 'PARTIALLY_PAID'):
        raise ApiError('ERR_INVALID_LIEN_STATE', 409,
                       'Lien is not open to payments')
    # pinned per-event accrual, then interest-first waterfall
    day = lien_day(l, db.clock)
    interest_due = project_interest(l, day)
    l['accrued_interest_cents'] += interest_due
    l['last_accrual_day'] = day
    outstanding = l['principal_remaining_cents'] + l['accrued_interest_cents']
    amount = vals['amount_cents']
    if amount > outstanding:
        raise ApiError('ERR_PAYMENT_EXCEEDS_BALANCE', 422,
                       'Payment exceeds the outstanding balance')
    if amount >= l['accrued_interest_cents']:
        amount -= l['accrued_interest_cents']
        l['accrued_interest_cents'] = 0
        l['principal_remaining_cents'] -= amount
    else:
        l['accrued_interest_cents'] -= amount
    l['outstanding_balance_cents'] = (l['principal_remaining_cents']
                                      + l['accrued_interest_cents'])
    if l['outstanding_balance_cents'] == 0:
        l['status'] = 'SATISFIED'
        notice = db.notices.get(l['notice_id'])
        if notice and notice['status'] == 'LIENED':
            notice['status'] = 'CLOSED'
            touch(notice)
        parcel = db.parcels.get(l['parcel_id'])
        if parcel:
            recompute_delinquency_flag(parcel)
    else:
        l['status'] = 'PARTIALLY_PAID'
    touch(l)
    return ok_object(ser_lien(l))


@bp.post('/lien-cases/<lid>/foreclosure-referral')
@require_roles('FinanceOfficer')
def foreclose_lien(lid):
    l = db.liens.get(lid)
    if not l:
        raise not_found('lien')
    if l['status'] not in ('RECORDED', 'PARTIALLY_PAID'):
        raise ApiError('ERR_INVALID_LIEN_STATE', 409,
                       'Lien is not eligible for foreclosure referral')
    if lien_day(l, db.clock) < FORECLOSURE_MIN_DAYS:
        raise ApiError('ERR_FORECLOSURE_TOO_EARLY', 422,
                       '90 days have not elapsed since assessment')
    outstanding = (l['principal_remaining_cents'] + l['accrued_interest_cents']
                   + project_interest(l, lien_day(l, db.clock)))
    if outstanding <= 0:
        raise ApiError('ERR_INVALID_LIEN_STATE', 409,
                       'No outstanding balance to foreclose')
    l['status'] = 'FORECLOSURE_REFERRED'
    touch(l)
    return ok_object(ser_lien(l))
