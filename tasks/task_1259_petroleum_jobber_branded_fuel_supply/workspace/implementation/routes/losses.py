from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_DEALER_STATION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_LOSS_EVENT_NOT_FOUND, ERR_STORAGE_TANK_NOT_FOUND,
                    ERR_VALIDATION_FAILED)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import (apply_filters, get_body, list_response, parse_dt_str,
                      sorted_default, validate_body)

bp = Blueprint('losses', __name__)


@bp.route('/api/loss-events', methods=['POST'])
def create_loss_event():
    uid, role = auth_context()
    require_role(role, {'DealerOperator'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'tank_id': {'type': 'str', 'required': False, 'nullable': True},
        'loss_type': {'type': 'enum', 'required': True,
                      'enum': ['DRIVE_OFF', 'SHRINKAGE', 'SPILL', 'THEFT']},
        'gallons': {'type': 'int', 'required': True, 'gt': 0},
        'occurred_at': {'type': 'datetime', 'required': True},
    })
    db.get_or_404('stations', body['station_id'],
                  ERR_DEALER_STATION_NOT_FOUND)
    tank = None
    if body.get('tank_id') is not None:
        tank = db.get_or_404('tanks', body['tank_id'],
                             ERR_STORAGE_TANK_NOT_FOUND)
    dealer_scope_check(uid, role, body['station_id'])
    if tank is not None and tank['station_id'] != body['station_id']:
        raise err(ERR_VALIDATION_FAILED,
                  'tank does not belong to the station')
    rec = {
        'id': db.new_id(),
        'station_id': body['station_id'],
        'tank_id': body.get('tank_id'),
        'reconciliation_id': None,
        'loss_type': body['loss_type'],
        'gallons': body['gallons'],
        'occurred_at': parse_dt_str(body['occurred_at']),
        'auto_generated': False,
        'status': 'REPORTED',
    }
    db.stamp_new(rec)
    db.STORE['losses'][rec['id']] = rec
    return ok_object(serializers.loss(rec), 201)


@bp.route('/api/loss-events', methods=['GET'])
def list_loss_events():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['losses'].values())
    items = scoped(items, uid, role, lambda le: le['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'tank_id': request.args.get('tank_id'),
        'reconciliation_id': request.args.get('reconciliation_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.loss)


@bp.route('/api/loss-events/<lid>', methods=['GET'])
def get_loss_event(lid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('losses', lid, ERR_LOSS_EVENT_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.loss(rec))


@bp.route('/api/loss-events/<lid>/verify', methods=['POST'])
def verify_loss_event(lid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    rec = db.get_or_404('losses', lid, ERR_LOSS_EVENT_NOT_FOUND)
    if rec['status'] not in ('REPORTED', 'DISPUTED'):
        raise err(ERR_INVALID_STATE,
                  'status must be REPORTED or DISPUTED')
    rec['status'] = 'VERIFIED'
    db.touch(rec)
    if rec['tank_id'] is not None:
        tank = db.STORE['tanks'].get(rec['tank_id'])
        if tank is not None:
            cascade.recompute_book(tank)
    cascade.recompute_open_recon(rec['station_id'])
    return ok_object(serializers.loss(rec))


@bp.route('/api/loss-events/<lid>/dispute', methods=['POST'])
def dispute_loss_event(lid):
    uid, role = auth_context()
    require_role(role, {'DealerOperator'})
    rec = db.get_or_404('losses', lid, ERR_LOSS_EVENT_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    if rec['status'] != 'REPORTED':
        raise err(ERR_INVALID_STATE, 'status must be REPORTED')
    rec['status'] = 'DISPUTED'
    db.touch(rec)
    return ok_object(serializers.loss(rec))


@bp.route('/api/loss-events/<lid>/write-off', methods=['POST'])
def write_off_loss_event(lid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    rec = db.get_or_404('losses', lid, ERR_LOSS_EVENT_NOT_FOUND)
    if rec['status'] != 'VERIFIED':
        raise err(ERR_INVALID_STATE, 'status must be VERIFIED')
    rec['status'] = 'WRITTEN_OFF'
    db.touch(rec)
    return ok_object(serializers.loss(rec))


@bp.route('/api/loss-events/<lid>/void', methods=['POST'])
def void_loss_event(lid):
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    rec = db.get_or_404('losses', lid, ERR_LOSS_EVENT_NOT_FOUND)
    if rec['status'] != 'VERIFIED':
        raise err(ERR_INVALID_STATE, 'status must be VERIFIED')
    rec['status'] = 'VOIDED'
    db.touch(rec)
    # Compensating action: restore the deducted gallons to the tank book.
    if rec['tank_id'] is not None:
        tank = db.STORE['tanks'].get(rec['tank_id'])
        if tank is not None:
            cascade.recompute_book(tank)
    cascade.recompute_open_recon(rec['station_id'])
    return ok_object(serializers.loss(rec))
