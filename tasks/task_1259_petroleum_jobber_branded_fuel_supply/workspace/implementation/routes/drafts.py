from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_DRAFT_ALREADY_SCHEDULED,
                    ERR_DRAFT_NOT_EXECUTABLE, ERR_EFT_DRAFT_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_INVOICE_NOT_FOUND)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('drafts', __name__)


@bp.route('/api/eft-drafts', methods=['POST'])
def create_draft():
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    body = validate_body(get_body(), {
        'invoice_id': {'type': 'str', 'required': True},
        'scheduled_date': {'type': 'date', 'required': True},
    })
    invoice = db.get_or_404('invoices', body['invoice_id'],
                            ERR_INVOICE_NOT_FOUND)
    if invoice['status'] not in ('ISSUED', 'OVERDUE'):
        raise err(ERR_INVALID_STATE,
                  'Invoice must be ISSUED or OVERDUE to schedule a draft')
    if any(d['invoice_id'] == invoice['id'] and d['status'] == 'SCHEDULED'
           for d in db.STORE['drafts'].values()):
        raise err(ERR_DRAFT_ALREADY_SCHEDULED,
                  'Invoice already has a SCHEDULED draft')
    rec = {
        'id': db.new_id(),
        'invoice_id': invoice['id'],
        'station_id': invoice['station_id'],
        'scheduled_date': body['scheduled_date'],
        'amount_cents': invoice['total_cents'],
        'attempts': 0,
        'status': 'SCHEDULED',
    }
    db.stamp_new(rec)
    db.STORE['drafts'][rec['id']] = rec
    return ok_object(serializers.draft(rec), 201)


@bp.route('/api/eft-drafts', methods=['GET'])
def list_drafts():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['drafts'].values())
    items = scoped(items, uid, role, lambda d: d['station_id'])
    items = apply_filters(items, {
        'invoice_id': request.args.get('invoice_id'),
        'station_id': request.args.get('station_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.draft)


@bp.route('/api/eft-drafts/<did>', methods=['GET'])
def get_draft(did):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('drafts', did, ERR_EFT_DRAFT_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.draft(rec))


@bp.route('/api/eft-drafts/<did>/execute', methods=['POST'])
def execute_draft(did):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    body = validate_body(get_body(), {
        'outcome': {'type': 'enum', 'required': True,
                    'enum': ['SUCCEEDED', 'FAILED']},
    })
    rec = db.get_or_404('drafts', did, ERR_EFT_DRAFT_NOT_FOUND)
    if rec['status'] != 'SCHEDULED':
        raise err(ERR_INVALID_STATE, 'Draft must be SCHEDULED to execute')
    if db.clock_date_str() < rec['scheduled_date']:
        raise err(ERR_DRAFT_NOT_EXECUTABLE,
                  'Clock date is before scheduled_date')
    rec['attempts'] += 1
    invoice = db.STORE['invoices'][rec['invoice_id']]
    station = db.STORE['stations'][rec['station_id']]
    if body['outcome'] == 'SUCCEEDED':
        rec['status'] = 'SETTLED'
        db.touch(rec)
        invoice['status'] = 'PAID'
        db.touch(invoice)
        cascade.recompute_exposure(station)
    else:
        rec['status'] = 'FAILED'
        db.touch(rec)
        # EFT failure drives the station to HOLD regardless of the band.
        if station['credit_status'] != 'HOLD':
            station['credit_status'] = 'HOLD'
            db.touch(station)
    return ok_object(serializers.draft(rec))


@bp.route('/api/eft-drafts/<did>/retry', methods=['POST'])
def retry_draft(did):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    body = validate_body(get_body(), {
        'scheduled_date': {'type': 'date', 'required': True},
    })
    rec = db.get_or_404('drafts', did, ERR_EFT_DRAFT_NOT_FOUND)
    if rec['status'] != 'FAILED':
        raise err(ERR_INVALID_STATE, 'status must be FAILED')
    rec['status'] = 'SCHEDULED'
    rec['scheduled_date'] = body['scheduled_date']
    db.touch(rec)
    return ok_object(serializers.draft(rec))


@bp.route('/api/eft-drafts/<did>/cancel', methods=['POST'])
def cancel_draft(did):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    rec = db.get_or_404('drafts', did, ERR_EFT_DRAFT_NOT_FOUND)
    if rec['status'] != 'SCHEDULED':
        raise err(ERR_INVALID_STATE, 'status must be SCHEDULED')
    rec['status'] = 'CANCELLED'
    db.touch(rec)
    return ok_object(serializers.draft(rec))
