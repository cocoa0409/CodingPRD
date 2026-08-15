from datetime import timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_INVALID_STATE, ERR_TAX_PERIOD_ALREADY_FILED,
                    ERR_TAX_REMITTANCE_NOT_FOUND, ERR_VALIDATION_FAILED)
from middleware import ALL_ROLES, auth_context, require_role
from response import ok_object
from services import calc
from validate import (apply_filters, get_body, list_response, parse_date_str,
                      sorted_default, validate_body)

bp = Blueprint('taxes', __name__)


@bp.route('/api/tax-remittances', methods=['POST'])
def create_remittance():
    uid, role = auth_context()
    require_role(role, {'TaxAccountant'})
    body = validate_body(get_body(), {
        'state_code': {'type': 'str', 'required': True},
        'period_start': {'type': 'date', 'required': True},
        'period_end': {'type': 'date', 'required': True},
    })
    if not (parse_date_str(body['period_end'])
            >= parse_date_str(body['period_start'])):
        raise err(ERR_VALIDATION_FAILED,
                  'period_end must be on or after period_start')
    # Closed-interval overlap against existing remittances in any status.
    for other in db.STORE['taxes'].values():
        if other['state_code'] != body['state_code']:
            continue
        if (body['period_start'] <= other['period_end']
                and other['period_start'] <= body['period_end']):
            raise err(ERR_TAX_PERIOD_ALREADY_FILED,
                      'An overlapping remittance exists for this state')
    due = (parse_date_str(body['period_end'])
           + timedelta(days=calc.DUE_DATE_LAG_DAYS)).isoformat()
    rec = {
        'id': db.new_id(),
        'state_code': body['state_code'],
        'period_start': body['period_start'],
        'period_end': body['period_end'],
        'due_date': due,
        'gasoline_gallons': None,
        'diesel_gallons': None,
        'tax_amount_cents': None,
        'late_penalty_cents': None,
        'total_due_cents': None,
        'filed_at': None,
        'status': 'ACCRUING',
    }
    db.stamp_new(rec)
    db.STORE['taxes'][rec['id']] = rec
    return ok_object(serializers.tax_remittance(rec), 201)


@bp.route('/api/tax-remittances', methods=['GET'])
def list_remittances():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['taxes'].values())
    items = apply_filters(items, {
        'state_code': request.args.get('state_code'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.tax_remittance)


@bp.route('/api/tax-remittances/<tid>', methods=['GET'])
def get_remittance(tid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('taxes', tid, ERR_TAX_REMITTANCE_NOT_FOUND)
    return ok_object(serializers.tax_remittance(rec))


@bp.route('/api/tax-remittances/<tid>/file', methods=['POST'])
def file_remittance(tid):
    uid, role = auth_context()
    require_role(role, {'TaxAccountant'})
    rec = db.get_or_404('taxes', tid, ERR_TAX_REMITTANCE_NOT_FOUND)
    if rec['status'] != 'ACCRUING':
        raise err(ERR_INVALID_STATE, 'status must be ACCRUING')
    rec.update(calc.tax_remittance_figures(rec))
    rec['filed_at'] = db.clock_now()
    rec['status'] = 'FILED'
    db.touch(rec)
    return ok_object(serializers.tax_remittance(rec))


@bp.route('/api/tax-remittances/<tid>/pay', methods=['POST'])
def pay_remittance(tid):
    uid, role = auth_context()
    require_role(role, {'TaxAccountant'})
    rec = db.get_or_404('taxes', tid, ERR_TAX_REMITTANCE_NOT_FOUND)
    if rec['status'] != 'FILED':
        raise err(ERR_INVALID_STATE, 'status must be FILED')
    rec['status'] = 'PAID'
    db.touch(rec)
    return ok_object(serializers.tax_remittance(rec))
