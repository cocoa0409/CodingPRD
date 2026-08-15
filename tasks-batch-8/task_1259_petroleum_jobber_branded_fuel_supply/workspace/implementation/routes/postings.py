from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_EFFECTIVE_DATE_IN_PAST, ERR_INVALID_STATE,
                    ERR_PRICE_POSTING_CONFLICT, ERR_PRODUCT_NOT_FOUND,
                    ERR_RACK_PRICE_POSTING_NOT_FOUND, ERR_STALE_VERSION,
                    ERR_VALIDATION_FAILED)
from middleware import (ALL_ROLES, auth_context, require_role)
from response import ok_object
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('postings', __name__)


@bp.route('/api/rack-price-postings', methods=['POST'])
def create_posting():
    uid, role = auth_context()
    require_role(role, {'PricingDesk'})
    body = validate_body(get_body(), {
        'terminal_code': {'type': 'str', 'required': True},
        'product_id': {'type': 'str', 'required': True},
        'effective_date': {'type': 'date', 'required': True},
        'price_tc_per_gal': {'type': 'int', 'required': True, 'gt': 0},
    })
    db.get_or_404('products', body['product_id'], ERR_PRODUCT_NOT_FOUND)
    if body['effective_date'] < db.clock_date_str():
        raise err(ERR_EFFECTIVE_DATE_IN_PAST,
                  'effective_date is before the current clock date')
    rec = {
        'id': db.new_id(),
        'terminal_code': body['terminal_code'],
        'product_id': body['product_id'],
        'effective_date': body['effective_date'],
        'price_tc_per_gal': body['price_tc_per_gal'],
        'status': 'DRAFT',
    }
    db.stamp_new(rec)
    db.STORE['postings'][rec['id']] = rec
    return ok_object(serializers.posting(rec), 201)


@bp.route('/api/rack-price-postings', methods=['GET'])
def list_postings():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['postings'].values())
    items = apply_filters(items, {
        'terminal_code': request.args.get('terminal_code'),
        'product_id': request.args.get('product_id'),
        'effective_date': request.args.get('effective_date'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.posting)


@bp.route('/api/rack-price-postings/<pid>', methods=['GET'])
def get_posting(pid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('postings', pid, ERR_RACK_PRICE_POSTING_NOT_FOUND)
    return ok_object(serializers.posting(rec))


@bp.route('/api/rack-price-postings/<pid>/post', methods=['POST'])
def post_posting(pid):
    uid, role = auth_context()
    require_role(role, {'PricingDesk'})
    rec = db.get_or_404('postings', pid, ERR_RACK_PRICE_POSTING_NOT_FOUND)
    if rec['status'] != 'DRAFT':
        raise err(ERR_INVALID_STATE, 'status must be DRAFT')
    for other in db.STORE['postings'].values():
        if (other['id'] != rec['id'] and other['status'] == 'POSTED'
                and other['terminal_code'] == rec['terminal_code']
                and other['product_id'] == rec['product_id']
                and other['effective_date'] == rec['effective_date']):
            raise err(ERR_PRICE_POSTING_CONFLICT,
                      'A POSTED posting already exists for this triple')
    rec['status'] = 'POSTED'
    db.touch(rec)
    return ok_object(serializers.posting(rec))


@bp.route('/api/rack-price-postings/<pid>/supersede', methods=['POST'])
def supersede_posting(pid):
    uid, role = auth_context()
    require_role(role, {'PricingDesk'})
    body = validate_body(get_body(), {
        'expected_superseded_posting_version': {'type': 'int',
                                                'required': True},
        'new_price_tc_per_gal': {'type': 'int', 'required': True, 'gt': 0},
        'effective_date': {'type': 'date', 'required': True},
    })
    rec = db.get_or_404('postings', pid, ERR_RACK_PRICE_POSTING_NOT_FOUND)
    if rec['status'] != 'POSTED':
        raise err(ERR_INVALID_STATE, 'status must be POSTED')
    if body['expected_superseded_posting_version'] != rec['version']:
        raise err(ERR_STALE_VERSION, 'Stale posting version')
    if body['effective_date'] != rec['effective_date']:
        raise err(ERR_VALIDATION_FAILED,
                  'effective_date must equal the superseded posting date')
    rec['status'] = 'SUPERSEDED'
    db.touch(rec)
    replacement = {
        'id': db.new_id(),
        'terminal_code': rec['terminal_code'],
        'product_id': rec['product_id'],
        'effective_date': rec['effective_date'],
        'price_tc_per_gal': body['new_price_tc_per_gal'],
        'status': 'POSTED',
    }
    db.stamp_new(replacement)
    db.STORE['postings'][replacement['id']] = replacement
    return ok_object(serializers.posting(rec))


@bp.route('/api/rack-price-postings/<pid>/discard', methods=['POST'])
def discard_posting(pid):
    uid, role = auth_context()
    require_role(role, {'PricingDesk'})
    rec = db.get_or_404('postings', pid, ERR_RACK_PRICE_POSTING_NOT_FOUND)
    if rec['status'] != 'DRAFT':
        raise err(ERR_INVALID_STATE, 'status must be DRAFT')
    rec['status'] = 'DISCARDED'
    db.touch(rec)
    return ok_object(serializers.posting(rec))
