from flask import Blueprint, request

import db
import serializers
from errors import err, ERR_BRAND_AUDIT_NOT_FOUND, ERR_DEALER_STATION_NOT_FOUND
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('audits', __name__)


@bp.route('/api/brand-compliance-audits', methods=['POST'])
def create_audit():
    uid, role = auth_context()
    require_role(role, {'BrandInspector'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'audit_date': {'type': 'date', 'required': True},
        'score': {'type': 'int', 'required': True, 'ge': 0, 'le': 100},
        'deficiencies': {'type': 'array', 'required': False},
    })
    station = db.get_or_404('stations', body['station_id'],
                            ERR_DEALER_STATION_NOT_FOUND)
    result = 'PASS' if body['score'] >= 70 else 'FAIL'
    rec = {
        'id': db.new_id(),
        'station_id': station['id'],
        'audit_date': body['audit_date'],
        'score': body['score'],
        'deficiencies': body.get('deficiencies', []),
        'result': result,
        'created_at': db.fmt_ts(db.wall_now()),
        '_seq': db.next_seq(),
    }
    db.STORE['audits'][rec['id']] = rec
    # Audit outcomes drive the station compliance dimension.
    if result == 'FAIL':
        if station['compliance_status'] == 'COMPLIANT':
            station['compliance_status'] = 'CURE_PERIOD'
            station['cure_started_at'] = db.clock_now()
            db.touch(station)
        elif station['compliance_status'] == 'CURE_PERIOD':
            cascade.station_default_cascade(station)
    elif result == 'PASS':
        if station['compliance_status'] == 'CURE_PERIOD':
            station['compliance_status'] = 'COMPLIANT'
            station['cure_started_at'] = None
            db.touch(station)
    return ok_object(serializers.audit(rec), 201)


@bp.route('/api/brand-compliance-audits', methods=['GET'])
def list_audits():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['audits'].values())
    items = scoped(items, uid, role, lambda a: a['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'result': request.args.get('result'),
    })
    return list_response(items, serializers.audit)


@bp.route('/api/brand-compliance-audits/<aid>', methods=['GET'])
def get_audit(aid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('audits', aid, ERR_BRAND_AUDIT_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.audit(rec))
