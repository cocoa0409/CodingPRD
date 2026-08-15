"""Slotting / new-item authorization requests and the logical clock endpoint."""
from flask import Blueprint, request

from db import (
    STORE, new_record, touch, public, set_logical_now, logical_now,
    logical_now_iso,
)
from errors import ApiError, not_found, invalid_state
from middleware import (
    authenticate, require_role, parse_body, req_str, req_int, opt_int,
    parse_datetime_str, parse_pagination, list_page,
)
from response import ok_object, ok_list
from services import slotting_fee, apply_past_due
from routes_retailers import get_retailer_or_404
from routes_catalog import get_product_or_404, _publish_price_record

bp = Blueprint('requests', __name__)

REQUEST_READ_ROLES = ('WholesaleAdmin', 'SalesRep')


def get_request_or_404(nid):
    rec = STORE['new_item_requests'].get(nid)
    if rec is None:
        raise not_found('new item request %s does not exist' % nid)
    return rec


@bp.post('/new-item-requests')
def create_new_item_request():
    uid, role = authenticate()
    body = parse_body()
    retailer_id = req_str(body, 'retailer_id')
    product_id = req_str(body, 'product_id')
    proposed_price = req_int(body, 'proposed_shelf_price_cents')
    require_role(role, ('SalesRep',))

    get_retailer_or_404(retailer_id)
    get_product_or_404(product_id)

    rec = new_record()
    rec.update({
        'retailer_id': retailer_id,
        'product_id': product_id,
        'proposed_shelf_price_cents': proposed_price,
        'slotting_fee_cents': 0,
        'revision_notes': None,
        'status': 'SUBMITTED',
    })
    STORE['new_item_requests'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/new-item-requests')
def list_new_item_requests():
    uid, role = authenticate()
    require_role(role, REQUEST_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(STORE['new_item_requests'].values())
    for param in ('retailer_id', 'product_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/new-item-requests/<nid>')
def get_new_item_request(nid):
    uid, role = authenticate()
    require_role(role, REQUEST_READ_ROLES)
    rec = get_request_or_404(nid)
    return ok_object(public(rec))


@bp.post('/new-item-requests/<nid>/start-review')
def start_review(nid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('WholesaleAdmin',))
    rec = get_request_or_404(nid)
    if rec['status'] != 'SUBMITTED':
        raise invalid_state('only a SUBMITTED request may move to UNDER_REVIEW')
    product = STORE['products'][rec['product_id']]
    rec['slotting_fee_cents'] = slotting_fee(product)
    rec['status'] = 'UNDER_REVIEW'
    touch(rec)
    return ok_object(public(rec))


@bp.post('/new-item-requests/<nid>/request-revision')
def request_revision(nid):
    uid, role = authenticate()
    body = parse_body()
    notes = req_str(body, 'revision_notes')
    require_role(role, ('WholesaleAdmin',))
    rec = get_request_or_404(nid)
    if rec['status'] != 'UNDER_REVIEW':
        raise invalid_state('only an UNDER_REVIEW request may be sent back for revision')
    rec['revision_notes'] = notes
    rec['status'] = 'REVISION_REQUESTED'
    touch(rec)
    return ok_object(public(rec))


@bp.post('/new-item-requests/<nid>/resubmit')
def resubmit_request(nid):
    uid, role = authenticate()
    body = parse_body()
    new_price = opt_int(body, 'proposed_shelf_price_cents')
    require_role(role, ('SalesRep',))
    rec = get_request_or_404(nid)
    if rec['status'] != 'REVISION_REQUESTED':
        raise invalid_state('only a REVISION_REQUESTED request may be resubmitted')
    if new_price is not None:
        rec['proposed_shelf_price_cents'] = new_price
    rec['revision_notes'] = None
    rec['status'] = 'SUBMITTED'
    touch(rec)
    return ok_object(public(rec))


@bp.post('/new-item-requests/<nid>/authorize')
def authorize_request(nid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('WholesaleAdmin',))
    rec = get_request_or_404(nid)
    if rec['status'] != 'UNDER_REVIEW':
        raise invalid_state('only an UNDER_REVIEW request may be authorized')
    product = STORE['products'][rec['product_id']]
    if product['status'] != 'ACTIVE':
        raise invalid_state('product is not ACTIVE')

    # append to the store's ACTIVE order guide
    guides = sorted(
        (g for g in STORE['order_guides'].values()
         if g['retailer_id'] == rec['retailer_id'] and g['status'] == 'ACTIVE'),
        key=lambda g: g['_seq'])
    if guides:
        guide = guides[0]
        guide['lines'].append({'product_id': rec['product_id'], 'par_cases': 0})
        touch(guide)

    # publish the retail price record, superseding any ACTIVE record
    effective_start = logical_now().date().isoformat()
    _publish_price_record(rec['retailer_id'], rec['product_id'],
                          rec['proposed_shelf_price_cents'], effective_start, None)

    rec['status'] = 'AUTHORIZED'
    touch(rec)
    return ok_object(public(rec))


@bp.post('/new-item-requests/<nid>/reject')
def reject_request(nid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('WholesaleAdmin',))
    rec = get_request_or_404(nid)
    if rec['status'] != 'UNDER_REVIEW':
        raise invalid_state('only an UNDER_REVIEW request may be rejected')
    rec['status'] = 'REJECTED'
    touch(rec)
    return ok_object(public(rec))


# ------------------------------------------------------------- logical clock

@bp.post('/_clock/set_current_utc')
def set_clock():
    uid, role = authenticate()
    body = parse_body()
    to_iso8601 = req_str(body, 'to_iso8601')
    target = parse_datetime_str(to_iso8601, 'to_iso8601')
    require_role(role, ('WholesaleAdmin',))
    set_logical_now(target)
    apply_past_due(target)
    return ok_object({'current_utc': logical_now_iso()})
