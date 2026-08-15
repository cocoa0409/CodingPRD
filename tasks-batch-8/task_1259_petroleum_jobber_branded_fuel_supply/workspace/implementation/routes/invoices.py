from flask import Blueprint, request

import db
import serializers
from errors import err, ERR_INVALID_STATE, ERR_INVOICE_NOT_FOUND
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import apply_filters, list_response, sorted_default

bp = Blueprint('invoices', __name__)


@bp.route('/api/invoices', methods=['GET'])
def list_invoices():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['invoices'].values())
    items = scoped(items, uid, role, lambda i: i['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'drop_id': request.args.get('drop_id'),
        'product_id': request.args.get('product_id'),
        'status': request.args.get('status'),
    })
    return list_response(items, serializers.invoice)


@bp.route('/api/invoices/<iid>', methods=['GET'])
def get_invoice(iid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('invoices', iid, ERR_INVOICE_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.invoice(rec))


@bp.route('/api/invoices/<iid>/void', methods=['POST'])
def void_invoice(iid):
    uid, role = auth_context()
    require_role(role, {'CreditManager'})
    rec = db.get_or_404('invoices', iid, ERR_INVOICE_NOT_FOUND)
    if rec['status'] not in ('ISSUED', 'OVERDUE'):
        raise err(ERR_INVALID_STATE,
                  'status must be ISSUED or OVERDUE')
    rec['status'] = 'VOID'
    db.touch(rec)
    station = db.STORE['stations'][rec['station_id']]
    # Compensating action: exposure recompute + band re-evaluation.
    cascade.recompute_exposure(station)
    # Any SCHEDULED draft for this invoice is cancelled in the same request.
    for d in db.STORE['drafts'].values():
        if d['invoice_id'] == rec['id'] and d['status'] == 'SCHEDULED':
            d['status'] = 'CANCELLED'
            db.touch(d)
    return ok_object(serializers.invoice(rec))
