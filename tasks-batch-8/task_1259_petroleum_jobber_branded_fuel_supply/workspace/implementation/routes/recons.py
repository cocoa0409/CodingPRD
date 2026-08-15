from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_DEALER_STATION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_INVENTORY_RECONCILIATION_NOT_FOUND,
                    ERR_LINKED_LOSS_NOT_WRITTEN_OFF,
                    ERR_RECONCILIATION_OPEN_EXISTS, ERR_SEGREGATION_OF_DUTIES,
                    ERR_VALIDATION_FAILED)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import calc, cascade
from validate import (apply_filters, get_body, list_response, parse_date_str,
                      sorted_default, validate_body)

bp = Blueprint('recons', __name__)


@bp.route('/api/inventory-reconciliations', methods=['POST'])
def create_recon():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'period_start': {'type': 'date', 'required': True},
        'period_end': {'type': 'date', 'required': True},
        'threshold_gallons': {'type': 'int', 'required': False, 'gt': 0},
    })
    if not (parse_date_str(body['period_end'])
            >= parse_date_str(body['period_start'])):
        raise err(ERR_VALIDATION_FAILED,
                  'period_end must be on or after period_start')
    db.get_or_404('stations', body['station_id'],
                  ERR_DEALER_STATION_NOT_FOUND)
    if any(r['station_id'] == body['station_id']
           and r['status'] in ('OPEN', 'VARIANCE_FLAGGED')
           for r in db.STORE['recons'].values()):
        raise err(ERR_RECONCILIATION_OPEN_EXISTS,
                  'Station already has an open reconciliation')
    rec = {
        'id': db.new_id(),
        'station_id': body['station_id'],
        'period_start': body['period_start'],
        'period_end': body['period_end'],
        'threshold_gallons': body.get('threshold_gallons', 130),
        'book_gallons': 0,
        'physical_gross_gallons': 0,
        'variance_gross_gallons': 0,
        'variance_net_gallons': 0,
        'status': 'OPEN',
        'opener_user_id': uid,
        'resolver_user_id': None,
        'resolution_note': None,
    }
    db.stamp_new(rec)
    db.STORE['recons'][rec['id']] = rec
    # Initial variance compute; may open directly in VARIANCE_FLAGGED.
    figs = calc.recon_figures(rec['station_id'])
    rec.update(figs)
    if abs(figs['variance_net_gallons']) > rec['threshold_gallons']:
        rec['status'] = 'VARIANCE_FLAGGED'
        cascade._create_auto_loss(rec, figs['variance_net_gallons'])
    return ok_object(serializers.recon(rec), 201)


@bp.route('/api/inventory-reconciliations', methods=['GET'])
def list_recons():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['recons'].values())
    items = scoped(items, uid, role, lambda r: r['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.recon)


@bp.route('/api/inventory-reconciliations/<rid>', methods=['GET'])
def get_recon(rid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('recons', rid,
                        ERR_INVENTORY_RECONCILIATION_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.recon(rec))


@bp.route('/api/inventory-reconciliations/<rid>/resolve', methods=['POST'])
def resolve_recon(rid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'resolution_note': {'type': 'str', 'required': True},
    })
    rec = db.get_or_404('recons', rid,
                        ERR_INVENTORY_RECONCILIATION_NOT_FOUND)
    if rec['status'] not in ('OPEN', 'VARIANCE_FLAGGED'):
        raise err(ERR_INVALID_STATE,
                  'status must be OPEN or VARIANCE_FLAGGED')
    if uid == rec['opener_user_id']:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  'Resolver must differ from the opener')
    for le in db.STORE['losses'].values():
        if (le['reconciliation_id'] == rec['id']
                and le['status'] not in ('WRITTEN_OFF', 'VOIDED')):
            raise err(ERR_LINKED_LOSS_NOT_WRITTEN_OFF,
                      'A linked loss event is not yet WRITTEN_OFF or VOIDED')
    rec['status'] = 'RESOLVED'
    rec['resolver_user_id'] = uid
    rec['resolution_note'] = body['resolution_note']
    db.touch(rec)
    return ok_object(serializers.recon(rec))
