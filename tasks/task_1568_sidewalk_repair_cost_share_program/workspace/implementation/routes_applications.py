"""CostShareApplication lifecycle: create/list/read, decision, resubmit,
obligate, withdraw, reimburse — including fund movement on the cycle."""
from flask import Blueprint, g, request

from db import db, base_entity, touch
from errors import ApiError, not_found, ownership
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services import (IN_FLIGHT_APP_STATUSES, APPROVAL_EXPIRY_DAYS,
                      compute_final_award, compute_provisional_award,
                      compute_share_pct, owner_id_of_parcel,
                      ramp_trigger_for_notice, recompute_cycle_available,
                      ser_application)
from util import add_days
from validation import get_body, parse_pagination, validate

bp = Blueprint('applications', __name__)


@bp.post('/cost-share-applications')
@require_roles('PropertyOwner')
def create_application():
    vals = validate(get_body(), [
        ('notice_id', 'str', True, {}),
        ('parcel_id', 'str', True, {}),
        ('cycle_id', 'str', True, {}),
        ('estimated_qty_sqft', 'num', True, {'positive': True}),
    ])
    # priority 3 ownership needs the parcel; then priority 4 left-to-right FKs.
    parcel = db.parcels.get(vals['parcel_id'])
    if parcel is not None and parcel['owner_id'] != g.uid:
        raise ownership('Acting owner does not own this parcel')
    notice = db.notices.get(vals['notice_id'])
    if not notice:
        raise not_found('notice')
    if parcel is None:
        raise not_found('parcel')
    cycle = db.cycles.get(vals['cycle_id'])
    if not cycle:
        raise not_found('cycle')
    # priority 5 state
    if notice['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409, 'Notice is not ISSUED')
    if cycle['status'] != 'OPEN':
        raise ApiError('ERR_CYCLE_NOT_OPEN', 409, 'Cycle is not OPEN')
    # priority 7 referential
    if vals['parcel_id'] != notice['parcel_id']:
        raise ApiError('ERR_PARCEL_NOTICE_MISMATCH', 422,
                       'parcel_id does not match the notice parcel')
    # priority 10 capacity-of-one
    if any(a['notice_id'] == notice['id'] and a['review_status'] in IN_FLIGHT_APP_STATUSES
           for a in db.applications.values()):
        raise ApiError('ERR_APPLICATION_ALREADY_ACTIVE', 409,
                       'Notice already has a non-terminal application')
    owner = db.owners.get(parcel['owner_id'])
    share_pct = compute_share_pct(parcel, owner)
    ramp = ramp_trigger_for_notice(notice)
    # priority 11 fiscal (lifetime cap) happens inside compute_provisional_award
    provisional = compute_provisional_award(vals['estimated_qty_sqft'], share_pct,
                                            ramp, parcel['id'])
    a = base_entity()
    a.update({
        'notice_id': notice['id'],
        'parcel_id': parcel['id'],
        'owner_id': parcel['owner_id'],
        'cycle_id': cycle['id'],
        'estimated_qty_sqft': vals['estimated_qty_sqft'],
        'ramp_upgrade_required': ramp,
        'share_pct': share_pct,
        'provisional_award_cents': provisional,
        'final_award_cents': None,
        'approved_at': None,
        'approval_expires_at': None,
        'review_status': 'SUBMITTED',
        'payment_status': 'UNFUNDED',
    })
    db.applications[a['id']] = a
    return ok_object(ser_application(a), 201)


@bp.get('/cost-share-applications')
@require_roles(*ALL_ROLES)
def list_applications():
    rows = list(db.applications.values())
    if g.role == 'PropertyOwner':
        rows = [a for a in rows if a['owner_id'] == g.uid]
    for param in ('notice_id', 'parcel_id', 'owner_id', 'cycle_id'):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a[param] == v]
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser_application(a) for a in page], total, limit, offset)


@bp.get('/cost-share-applications/<aid>')
@require_roles(*ALL_ROLES)
def get_application(aid):
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    return ok_object(ser_application(a))


@bp.post('/cost-share-applications/<aid>/decision')
@require_roles('ProgramCoordinator')
def decide_application(aid):
    vals = validate(get_body(), [
        ('outcome', 'enum', True, {'values': ['APPROVE', 'DENY', 'RETURN']}),
        ('reviewer_note', 'str', False, {'default': None}),
    ])
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    if a['review_status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_APPLICATION_STATE', 409,
                       'Application is not SUBMITTED')
    outcome = vals['outcome']
    if outcome == 'APPROVE':
        a['review_status'] = 'APPROVED'
        a['approved_at'] = db.clock
        a['approval_expires_at'] = add_days(db.clock, APPROVAL_EXPIRY_DAYS)
    elif outcome == 'DENY':
        a['review_status'] = 'DENIED'
    else:
        a['review_status'] = 'RETURNED'
    touch(a)
    return ok_object(ser_application(a))


@bp.post('/cost-share-applications/<aid>/resubmit')
@require_roles('PropertyOwner')
def resubmit_application(aid):
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    if a['owner_id'] != g.uid:
        raise ownership('Acting owner does not own this application')
    if a['review_status'] != 'RETURNED':
        raise ApiError('ERR_INVALID_APPLICATION_STATE', 409,
                       'Application is not RETURNED')
    a['review_status'] = 'SUBMITTED'
    touch(a)
    return ok_object(ser_application(a))


@bp.post('/cost-share-applications/<aid>/obligate')
@require_roles('FinanceOfficer')
def obligate_application(aid):
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    if a['review_status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_APPLICATION_STATE', 409,
                       'Application is not APPROVED')
    cycle = db.cycles.get(a['cycle_id'])
    if not cycle or cycle['status'] != 'OPEN':
        raise ApiError('ERR_CYCLE_NOT_OPEN', 409, 'Cycle is not OPEN')
    if db.clock > a['approval_expires_at']:
        raise ApiError('ERR_APPLICATION_EXPIRED', 422,
                       'Approval has expired')
    if cycle['committed_cents'] + a['provisional_award_cents'] > cycle['appropriation_cents']:
        raise ApiError('ERR_PROGRAM_CAP_EXCEEDED', 402,
                       'Obligation would exceed the program appropriation')
    a['review_status'] = 'OBLIGATED'
    a['payment_status'] = 'RESERVED'
    touch(a)
    cycle['committed_cents'] += a['provisional_award_cents']
    recompute_cycle_available(cycle)
    touch(cycle)
    return ok_object(ser_application(a))


@bp.post('/cost-share-applications/<aid>/withdraw')
@require_roles('PropertyOwner')
def withdraw_application(aid):
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    if a['owner_id'] != g.uid:
        raise ownership('Acting owner does not own this application')
    if a['review_status'] not in IN_FLIGHT_APP_STATUSES:
        raise ApiError('ERR_INVALID_APPLICATION_STATE', 409,
                       'Application cannot be withdrawn from its current state')
    was_obligated = a['review_status'] == 'OBLIGATED'
    a['review_status'] = 'WITHDRAWN'
    touch(a)
    if was_obligated:
        a['payment_status'] = 'RELEASED'
        cycle = db.cycles.get(a['cycle_id'])
        if cycle:
            cycle['committed_cents'] -= a['provisional_award_cents']
            recompute_cycle_available(cycle)
            touch(cycle)
    return ok_object(ser_application(a))


@bp.post('/cost-share-applications/<aid>/reimburse')
@require_roles('FinanceOfficer')
def reimburse_application(aid):
    vals = validate(get_body(), [
        ('final_repair_cost_cents', 'int', True, {'nonnegative': True}),
        ('ramp_receipt_cents', 'int', False, {'default': None, 'nonnegative': True}),
    ])
    a = db.applications.get(aid)
    if not a:
        raise not_found('application')
    if (not a['ramp_upgrade_required']) and vals['ramp_receipt_cents']:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'ramp_receipt_cents supplied without a ramp upgrade')
    if a['review_status'] != 'OBLIGATED':
        raise ApiError('ERR_INVALID_APPLICATION_STATE', 409,
                       'Application is not OBLIGATED')
    notice = db.notices.get(a['notice_id'])
    if not notice or notice['status'] != 'COMPLIANT':
        raise ApiError('ERR_NOTICE_NOT_COMPLIANT', 409,
                       'Source notice is not COMPLIANT')
    final_award = compute_final_award(vals['final_repair_cost_cents'],
                                      vals['ramp_receipt_cents'] or 0, a)
    cycle = db.cycles.get(a['cycle_id'])
    if (cycle['committed_cents'] - a['provisional_award_cents']
            + cycle['disbursed_cents'] + final_award) > cycle['appropriation_cents']:
        raise ApiError('ERR_PROGRAM_CAP_EXCEEDED', 402,
                       'Reimbursement would exceed the program appropriation')
    a['final_award_cents'] = final_award
    a['review_status'] = 'REIMBURSED'
    a['payment_status'] = 'DISBURSED'
    touch(a)
    cycle['committed_cents'] -= a['provisional_award_cents']
    cycle['disbursed_cents'] += final_award
    recompute_cycle_available(cycle)
    touch(cycle)
    return ok_object(ser_application(a))
