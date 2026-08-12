from flask import Blueprint, request

import calc
import db
from errors import ApiError, invalid
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_int, as_list, find, serialize

bp = Blueprint('bids', __name__)


def _not_actionable(message='bid is not in the required state'):
    return ApiError('ERR_BID_NOT_ACTIONABLE', 409, message)


def _validate_lines(d):
    lines = as_list(require(d, 'lines'), 'lines')
    out = []
    for line in lines:
        if not isinstance(line, dict):
            raise invalid('each line must be an object')
        out.append({
            'instrument_id': as_str(require(line, 'instrument_id'), 'instrument_id'),
            'unit_price_cents': as_int(require(line, 'unit_price_cents'), 'unit_price_cents'),
        })
    return out


def _resolve_line_instruments(lines):
    for line in lines:
        find(db.stores['instruments'], line['instrument_id'], 'instrument')


@bp.post('/piano-dealer/bid-packages')
def create_bid():
    uid, role = auth('InstitutionalBidOfficer')
    d = body()
    customer_id = as_str(require(d, 'customer_id'), 'customer_id')
    lines = _validate_lines(d)
    customer = find(db.stores['customers'], customer_id, 'customer')
    _resolve_line_instruments(lines)
    if customer['customer_type'] != 'INSTITUTIONAL':
        raise invalid('bid packages require an INSTITUTIONAL customer')
    pricing = calc.bid_pricing(lines, customer)
    rec = db.base_fields()
    rec.update({
        'customer_id': customer_id,
        'prepared_by_user_id': uid,
        'lines': lines,
        'revision_number': 1,
        'status': 'DRAFT',
    })
    rec.update(pricing)
    db.stores['bids'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/bid-packages/<rid>')
def get_bid(rid):
    auth('InstitutionalBidOfficer', 'ComplianceOfficer')
    return ok(serialize(find(db.stores['bids'], rid, 'bid package')))


@bp.get('/piano-dealer/bid-packages')
def list_bids():
    auth('InstitutionalBidOfficer', 'ComplianceOfficer')
    items = list(db.stores['bids'].values())
    customer_id = request.args.get('customer_id')
    if customer_id:
        items = [b for b in items if b['customer_id'] == customer_id]
    return ok_list(items, serialize)


@bp.post('/piano-dealer/bid-packages/<rid>/submit')
def submit_bid(rid):
    auth('InstitutionalBidOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    if bid['status'] != 'DRAFT':
        raise _not_actionable('only DRAFT bids can be submitted')
    floor_sum = sum(find(db.stores['instruments'], l['instrument_id'], 'instrument')['floor_price_cents']
                    for l in bid['lines'])
    if bid['total_cents'] < floor_sum:
        raise ApiError('ERR_BID_BELOW_FLOOR', 422,
                       'bid total is below the sum of line floor prices')
    bid['status'] = 'SUBMITTED'
    db.touch(bid)
    return ok(serialize(bid))


@bp.post('/piano-dealer/bid-packages/<rid>/compliance-approve')
def compliance_approve(rid):
    uid, role = auth('ComplianceOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    # Segregation of duties (priority 3): approver must differ from preparer.
    if uid == bid['prepared_by_user_id']:
        raise ApiError('ERR_SOD_SELF_APPROVAL', 403,
                       'compliance officer may not approve a bid they prepared')
    if bid['status'] != 'SUBMITTED':
        raise _not_actionable('only SUBMITTED bids can be approved')
    bid['status'] = 'APPROVED'
    db.touch(bid)
    return ok(serialize(bid))


@bp.post('/piano-dealer/bid-packages/<rid>/return-for-revision')
def return_for_revision(rid):
    auth('ComplianceOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    if bid['status'] != 'SUBMITTED':
        raise _not_actionable('only SUBMITTED bids can be returned for revision')
    bid['status'] = 'DRAFT'
    db.touch(bid)
    return ok(serialize(bid))


@bp.post('/piano-dealer/bid-packages/<rid>/record-outcome')
def record_outcome(rid):
    auth('InstitutionalBidOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    d = body()
    outcome = require(d, 'outcome')
    if outcome not in ('AWARDED', 'LOST'):
        raise invalid('outcome must be AWARDED or LOST')
    if bid['status'] != 'APPROVED':
        raise _not_actionable('only APPROVED bids can record an outcome')
    bid['status'] = outcome
    db.touch(bid)
    return ok(serialize(bid))


@bp.post('/piano-dealer/bid-packages/<rid>/withdraw')
def withdraw_bid(rid):
    auth('InstitutionalBidOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    if bid['status'] not in ('DRAFT', 'SUBMITTED'):
        raise _not_actionable('only DRAFT or SUBMITTED bids can be withdrawn')
    bid['status'] = 'WITHDRAWN'
    db.touch(bid)
    return ok(serialize(bid))


@bp.post('/piano-dealer/bid-packages/<rid>/revisions')
def revise_bid(rid):
    auth('InstitutionalBidOfficer')
    bid = find(db.stores['bids'], rid, 'bid package')
    d = body()
    expected = as_int(require(d, 'expected_bid_version'), 'expected_bid_version')
    lines = _validate_lines(d)
    _resolve_line_instruments(lines)
    if bid['status'] != 'SUBMITTED':
        raise _not_actionable('only SUBMITTED bids can be revised')
    if expected != bid['version']:
        raise ApiError('ERR_STALE_VERSION', 412, 'expected_bid_version is stale')
    customer = find(db.stores['customers'], bid['customer_id'], 'customer')
    pricing = calc.bid_pricing(lines, customer)
    bid['lines'] = lines
    for k, v in pricing.items():
        bid[k] = v
    bid['revision_number'] += 1
    db.touch(bid)
    return ok(serialize(bid))
