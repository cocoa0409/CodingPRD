"""Bid pooling: BidBatch, BatchWorkItem, Contractor, Bid endpoints and the
award / verification cascades."""
from flask import Blueprint, g, request

from db import db, base_entity, touch
from errors import ApiError, not_found, ownership, segregation
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services import (ACTIVE_WORK_ITEM_STATUSES, CURE_BUFFER_DAYS,
                      owner_id_of_parcel, ramp_trigger_for_notice,
                      recompute_batch_estimate, recompute_segment,
                      maybe_restore_segment, ser_batch, ser_bid, ser_contractor,
                      ser_work_item, verify_notice_defects)
from datetime import timedelta

from util import dec, parse_date, rhu
from validation import get_body, parse_pagination, validate

bp = Blueprint('bidding', __name__)


def _paged(rows, serializer):
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


def _batch_items(batch_id):
    return [w for w in db.work_items.values() if w['batch_id'] == batch_id]


def _evaluated_total(bid, batch):
    items = [w for w in _batch_items(batch['id']) if w['status'] == 'POOLED']
    total_scope = sum(dec(w['scope_sqft']) for w in items)
    ramp_count = sum(1 for w in items if w['includes_ramp_upgrade'])
    return rhu(dec(bid['unit_rate_cents']) * total_scope) + \
        bid['ramp_flat_fee_cents'] * ramp_count


def _window_conflicts(contractor_id, batch):
    """Half-open window conflict against the contractor's awarded/in-progress batches."""
    s1 = parse_date(batch['work_window_start'])
    e1 = parse_date(batch['work_window_end'])
    for other in db.batches.values():
        if other['id'] == batch['id'] or other['status'] not in ('AWARDED', 'WORK_IN_PROGRESS'):
            continue
        ob = db.bids.get(other['awarded_bid_id']) if other['awarded_bid_id'] else None
        if not ob or ob['contractor_id'] != contractor_id:
            continue
        s2 = parse_date(other['work_window_start'])
        e2 = parse_date(other['work_window_end'])
        if s1 < e2 and s2 < e1:
            return True
    return False


def _bid_eligible(bid, batch):
    if bid['status'] != 'SUBMITTED':
        return False
    contractor = db.contractors.get(bid['contractor_id'])
    if not contractor or contractor['is_suspended']:
        return False
    if parse_date(contractor['insurance_valid_until']) < parse_date(batch['work_window_end']):
        return False
    if _window_conflicts(bid['contractor_id'], batch):
        return False
    return True


# ------------------------------------------------------------- batches
@bp.post('/bid-batches')
@require_roles('ProgramCoordinator')
def create_batch():
    vals = validate(get_body(), [
        ('neighborhood_code', 'str', True, {}),
        ('work_window_start', 'date', True, {}),
        ('work_window_end', 'date', True, {}),
        ('bid_deadline', 'datetime', True, {}),
    ])
    if not vals['work_window_end'] > vals['work_window_start']:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'work_window_end must be strictly after work_window_start')
    b = base_entity()
    b.update({
        'neighborhood_code': vals['neighborhood_code'],
        'work_window_start': vals['work_window_start'].isoformat(),
        'work_window_end': vals['work_window_end'].isoformat(),
        'bid_deadline': vals['bid_deadline'],
        'estimated_total_cents': 0,
        'awarded_bid_id': None,
        'awarded_total_cents': None,
        'status': 'OPEN_FOR_ITEMS',
    })
    db.batches[b['id']] = b
    return ok_object(ser_batch(b), 201)


@bp.get('/bid-batches')
@require_roles(*ALL_ROLES)
def list_batches():
    rows = list(db.batches.values())
    awarded_bid_id = request.args.get('awarded_bid_id')
    if awarded_bid_id is not None:
        rows = [b for b in rows if b['awarded_bid_id'] == awarded_bid_id]
    neighborhood_code = request.args.get('neighborhood_code')
    if neighborhood_code is not None:
        rows = [b for b in rows if b['neighborhood_code'] == neighborhood_code]
    return _paged(rows, ser_batch)


@bp.get('/bid-batches/<bid_>')
@require_roles(*ALL_ROLES)
def get_batch(bid_):
    b = db.batches.get(bid_)
    if not b:
        raise not_found('batch')
    return ok_object(ser_batch(b))


@bp.post('/bid-batches/<bid_>/seal')
@require_roles('ProgramCoordinator')
def seal_batch(bid_):
    b = db.batches.get(bid_)
    if not b:
        raise not_found('batch')
    if b['status'] != 'OPEN_FOR_ITEMS':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not OPEN_FOR_ITEMS')
    pooled = [w for w in _batch_items(b['id']) if w['status'] == 'POOLED']
    if not pooled:
        raise ApiError('ERR_EMPTY_BATCH', 409, 'Batch has no POOLED work items')
    window_start = parse_date(b['work_window_start'])
    for item in pooled:
        notice = db.notices.get(item['notice_id'])
        if not notice:
            continue
        for did in notice['defect_ids']:
            for r in db.forestry_reviews.values():
                if (r['defect_id'] == did and r['status'] == 'CLEARED'
                        and r['work_completed_at'] is not None):
                    if window_start < (r['work_completed_at'].date()
                                       + timedelta(days=CURE_BUFFER_DAYS)):
                        raise ApiError('ERR_CURE_WINDOW_VIOLATION', 422,
                                       'work_window_start is inside the 7-day cure buffer')
    b['status'] = 'SEALED_FOR_BIDDING'
    touch(b)
    return ok_object(ser_batch(b))


@bp.post('/bid-batches/<bid_>/award')
@require_roles('ProgramCoordinator')
def award_batch(bid_):
    b = db.batches.get(bid_)
    if not b:
        raise not_found('batch')
    if b['status'] != 'SEALED_FOR_BIDDING':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not SEALED_FOR_BIDDING')
    pooled = [w for w in _batch_items(b['id']) if w['status'] == 'POOLED']
    # priority 8 safety gate: every covered forestry review must be CLEARED
    for item in pooled:
        notice = db.notices.get(item['notice_id'])
        if not notice:
            continue
        for did in notice['defect_ids']:
            for r in db.forestry_reviews.values():
                if r['defect_id'] == did and r['status'] != 'CLEARED':
                    raise ApiError('ERR_FORESTRY_NOT_CLEARED', 409,
                                   'A covered forestry review is not CLEARED')
    # priority 9 temporal
    if db.clock <= b['bid_deadline']:
        raise ApiError('ERR_BID_WINDOW_STILL_OPEN', 422,
                       'The bid deadline has not passed')
    # selector: recompute evaluated totals, filter, rank
    submitted = [x for x in db.bids.values()
                 if x['batch_id'] == b['id'] and x['status'] == 'SUBMITTED']
    for x in submitted:
        x['evaluated_total_cents'] = _evaluated_total(x, b)
    eligible = [x for x in submitted if _bid_eligible(x, b)]

    def rank_key(x):
        contractor = db.contractors.get(x['contractor_id'])
        lic = contractor['license_number'] if contractor else ''
        return (x['evaluated_total_cents'], x['submitted_at'], lic)

    eligible.sort(key=rank_key)
    if not eligible:
        raise ApiError('ERR_NO_ELIGIBLE_BIDS', 422, 'No eligible bids')
    winner = eligible[0]
    for x in submitted:
        x['status'] = 'AWARDED' if x['id'] == winner['id'] else 'NOT_AWARDED'
        touch(x)
    b['awarded_bid_id'] = winner['id']
    b['awarded_total_cents'] = winner['evaluated_total_cents']
    b['status'] = 'AWARDED'
    touch(b)
    for item in pooled:
        item['status'] = 'SCHEDULED'
        touch(item)
        notice = db.notices.get(item['notice_id'])
        if notice and notice['status'] == 'DELINQUENT':
            notice['status'] = 'CITY_REPAIR_SCHEDULED'
            touch(notice)
            for did in notice['defect_ids']:
                d = db.defects.get(did)
                if d:
                    seg = db.segments.get(d['segment_id'])
                    if seg and seg['status'] != 'REPAIR_IN_PROGRESS':
                        seg['status'] = 'REPAIR_IN_PROGRESS'
                        touch(seg)
    return ok_object(ser_batch(b))


@bp.post('/bid-batches/<bid_>/start-work')
@require_roles('ProgramCoordinator')
def start_work(bid_):
    b = db.batches.get(bid_)
    if not b:
        raise not_found('batch')
    if b['status'] != 'AWARDED':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not AWARDED')
    if db.clock.date() < parse_date(b['work_window_start']):
        raise ApiError('ERR_WORK_WINDOW_NOT_REACHED', 422,
                       'The work window has not started')
    b['status'] = 'WORK_IN_PROGRESS'
    touch(b)
    return ok_object(ser_batch(b))


@bp.post('/bid-batches/<bid_>/cancel')
@require_roles('ProgramCoordinator')
def cancel_batch(bid_):
    b = db.batches.get(bid_)
    if not b:
        raise not_found('batch')
    if b['status'] not in ('OPEN_FOR_ITEMS', 'SEALED_FOR_BIDDING'):
        raise ApiError('ERR_INVALID_BATCH_STATE', 409,
                       'Batch cannot be cancelled in its current state')
    was_sealed = b['status'] == 'SEALED_FOR_BIDDING'
    for item in _batch_items(b['id']):
        if item['status'] == 'POOLED':
            item['status'] = 'REMOVED'
            touch(item)
    if was_sealed:
        for x in db.bids.values():
            if x['batch_id'] == b['id'] and x['status'] == 'SUBMITTED':
                x['status'] = 'NOT_AWARDED'
                touch(x)
    b['status'] = 'CANCELLED'
    recompute_batch_estimate(b)
    touch(b)
    return ok_object(ser_batch(b))


# ------------------------------------------------------------- work items
@bp.post('/batch-work-items')
@require_roles('ProgramCoordinator')
def create_work_item():
    vals = validate(get_body(), [
        ('batch_id', 'str', True, {}),
        ('notice_id', 'str', True, {}),
        ('scope_sqft', 'num', True, {'positive': True}),
        ('engineer_unit_rate_cents', 'int', True, {'positive': True}),
    ])
    batch = db.batches.get(vals['batch_id'])
    if not batch:
        raise not_found('batch')
    notice = db.notices.get(vals['notice_id'])
    if not notice:
        raise not_found('notice')
    if batch['status'] != 'OPEN_FOR_ITEMS':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not OPEN_FOR_ITEMS')
    if notice['status'] != 'DELINQUENT':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409, 'Notice is not DELINQUENT')
    if any(w['notice_id'] == notice['id'] and w['status'] in ACTIVE_WORK_ITEM_STATUSES
           for w in db.work_items.values()):
        raise ApiError('ERR_NOTICE_ALREADY_POOLED', 422,
                       'Notice already has an active work item')
    w = base_entity()
    w.update({
        'batch_id': batch['id'],
        'notice_id': notice['id'],
        'scope_sqft': vals['scope_sqft'],
        'engineer_unit_rate_cents': vals['engineer_unit_rate_cents'],
        'includes_ramp_upgrade': ramp_trigger_for_notice(notice),
        'status': 'POOLED',
    })
    db.work_items[w['id']] = w
    recompute_batch_estimate(batch)
    touch(batch)
    return ok_object(ser_work_item(w), 201)


@bp.get('/batch-work-items')
@require_roles(*ALL_ROLES)
def list_work_items():
    rows = list(db.work_items.values())
    if g.role == 'PropertyOwner':
        rows = [w for w in rows
                if owner_id_of_parcel((db.notices.get(w['notice_id']) or {}).get('parcel_id')) == g.uid]
    batch_id = request.args.get('batch_id')
    if batch_id is not None:
        rows = [w for w in rows if w['batch_id'] == batch_id]
    notice_id = request.args.get('notice_id')
    if notice_id is not None:
        rows = [w for w in rows if w['notice_id'] == notice_id]
    return _paged(rows, ser_work_item)


@bp.get('/batch-work-items/<wid>')
@require_roles(*ALL_ROLES)
def get_work_item(wid):
    w = db.work_items.get(wid)
    if not w:
        raise not_found('work_item')
    return ok_object(ser_work_item(w))


@bp.post('/batch-work-items/<wid>/remove')
@require_roles('ProgramCoordinator')
def remove_work_item(wid):
    w = db.work_items.get(wid)
    if not w:
        raise not_found('work_item')
    if w['status'] != 'POOLED':
        raise ApiError('ERR_INVALID_WORK_ITEM_STATE', 409, 'Work item is not POOLED')
    batch = db.batches.get(w['batch_id'])
    if not batch or batch['status'] != 'OPEN_FOR_ITEMS':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not OPEN_FOR_ITEMS')
    w['status'] = 'REMOVED'
    touch(w)
    recompute_batch_estimate(batch)
    touch(batch)
    return ok_object(ser_work_item(w))


@bp.post('/batch-work-items/<wid>/complete')
@require_roles('Contractor')
def complete_work_item(wid):
    w = db.work_items.get(wid)
    if not w:
        raise not_found('work_item')
    batch = db.batches.get(w['batch_id'])
    winner = db.bids.get(batch['awarded_bid_id']) if batch and batch['awarded_bid_id'] else None
    if not winner or winner['contractor_id'] != g.uid:
        raise ownership('Only the awarded contractor may complete this item')
    if w['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_WORK_ITEM_STATE', 409, 'Work item is not SCHEDULED')
    if batch['status'] != 'WORK_IN_PROGRESS':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not WORK_IN_PROGRESS')
    w['status'] = 'WORK_COMPLETED'
    touch(w)
    return ok_object(ser_work_item(w))


@bp.post('/batch-work-items/<wid>/verify')
@require_roles('Inspector')
def verify_work_item(wid):
    w = db.work_items.get(wid)
    if not w:
        raise not_found('work_item')
    if w['status'] != 'WORK_COMPLETED':
        raise ApiError('ERR_INVALID_WORK_ITEM_STATE', 409,
                       'Work item is not WORK_COMPLETED')
    notice = db.notices.get(w['notice_id'])
    for did in (notice['defect_ids'] if notice else []):
        d = db.defects.get(did)
        if d and d['recorded_by_inspector_id'] == g.uid:
            raise segregation('Verifier recorded a defect on this notice')
    w['status'] = 'VERIFIED'
    touch(w)
    if notice:
        verify_notice_defects(notice)
        notice_items = [x for x in db.work_items.values()
                        if x['notice_id'] == notice['id']]
        if notice_items and all(x['status'] == 'VERIFIED' for x in notice_items):
            if notice['status'] == 'CITY_REPAIR_SCHEDULED':
                notice['status'] = 'CITY_REPAIR_COMPLETED'
                touch(notice)
    batch = db.batches.get(w['batch_id'])
    if batch:
        batch_items = _batch_items(batch['id'])
        if batch_items and all(x['status'] == 'VERIFIED' for x in batch_items):
            if batch['status'] == 'WORK_IN_PROGRESS':
                batch['status'] = 'COMPLETED'
                touch(batch)
    return ok_object(ser_work_item(w))


# ------------------------------------------------------------- contractors
@bp.post('/contractors')
@require_roles('ProgramCoordinator')
def create_contractor():
    vals = validate(get_body(), [
        ('company_name', 'str', True, {}),
        ('license_number', 'str', True, {}),
        ('insurance_valid_until', 'date', True, {}),
    ])
    if any(c['license_number'] == vals['license_number'] for c in db.contractors.values()):
        raise ApiError('ERR_DUPLICATE_LICENSE_NUMBER', 409,
                       'license_number already registered')
    c = base_entity()
    c.update({'company_name': vals['company_name'],
              'license_number': vals['license_number'],
              'insurance_valid_until': vals['insurance_valid_until'].isoformat(),
              'is_suspended': False})
    db.contractors[c['id']] = c
    return ok_object(ser_contractor(c), 201)


@bp.get('/contractors')
@require_roles(*ALL_ROLES)
def list_contractors():
    return _paged(list(db.contractors.values()), ser_contractor)


@bp.post('/contractors/<cid>/suspend')
@require_roles('ProgramCoordinator')
def suspend_contractor(cid):
    c = db.contractors.get(cid)
    if not c:
        raise not_found('contractor')
    if not c['is_suspended']:
        c['is_suspended'] = True
        touch(c)
    return ok_object(ser_contractor(c))


# ------------------------------------------------------------- bids
@bp.post('/bids')
@require_roles('Contractor')
def create_bid():
    vals = validate(get_body(), [
        ('batch_id', 'str', True, {}),
        ('unit_rate_cents', 'int', True, {'positive': True}),
        ('ramp_flat_fee_cents', 'int', True, {'nonnegative': True}),
        ('expected_batch_version', 'int', True, {}),
    ])
    batch = db.batches.get(vals['batch_id'])
    if not batch:
        raise not_found('batch')
    if batch['status'] != 'SEALED_FOR_BIDDING':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not SEALED_FOR_BIDDING')
    if vals['expected_batch_version'] != batch['version']:
        raise ApiError('ERR_STALE_BATCH_VERSION', 412,
                       'expected_batch_version does not match current version')
    if db.clock > batch['bid_deadline']:
        raise ApiError('ERR_BID_DEADLINE_PASSED', 422, 'The bid deadline has passed')
    contractor = db.contractors.get(g.uid)
    if contractor['is_suspended']:
        raise ApiError('ERR_CONTRACTOR_SUSPENDED', 403, 'Contractor is suspended')
    if parse_date(contractor['insurance_valid_until']) < parse_date(batch['work_window_end']):
        raise ApiError('ERR_INSURANCE_INVALID', 422,
                       'Insurance does not cover the full work window')
    for prior in db.bids.values():
        if (prior['batch_id'] == batch['id'] and prior['contractor_id'] == g.uid
                and prior['status'] == 'SUBMITTED'):
            prior['status'] = 'SUPERSEDED'
            touch(prior)
    x = base_entity()
    x.update({
        'batch_id': batch['id'],
        'contractor_id': g.uid,
        'unit_rate_cents': vals['unit_rate_cents'],
        'ramp_flat_fee_cents': vals['ramp_flat_fee_cents'],
        'submitted_at': db.clock,
        'evaluated_total_cents': 0,
        'status': 'SUBMITTED',
    })
    x['evaluated_total_cents'] = _evaluated_total(x, batch)
    db.bids[x['id']] = x
    touch(batch)  # each accepted bid creation increments BidBatch.version
    return ok_object(ser_bid(x), 201)


@bp.get('/bids')
@require_roles(*ALL_ROLES)
def list_bids():
    rows = list(db.bids.values())
    batch_id = request.args.get('batch_id')
    if batch_id is not None:
        rows = [b for b in rows if b['batch_id'] == batch_id]
    contractor_id = request.args.get('contractor_id')
    if contractor_id is not None:
        rows = [b for b in rows if b['contractor_id'] == contractor_id]
    return _paged(rows, ser_bid)


@bp.get('/bids/<xid>')
@require_roles(*ALL_ROLES)
def get_bid(xid):
    x = db.bids.get(xid)
    if not x:
        raise not_found('bid')
    return ok_object(ser_bid(x))


@bp.post('/bids/<xid>/withdraw')
@require_roles('Contractor')
def withdraw_bid(xid):
    x = db.bids.get(xid)
    if not x:
        raise not_found('bid')
    if x['contractor_id'] != g.uid:
        raise ownership('Only the submitting contractor may withdraw this bid')
    if x['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_BID_STATE', 409, 'Bid is not SUBMITTED')
    batch = db.batches.get(x['batch_id'])
    if not batch or batch['status'] != 'SEALED_FOR_BIDDING':
        raise ApiError('ERR_INVALID_BATCH_STATE', 409, 'Batch is not SEALED_FOR_BIDDING')
    x['status'] = 'WITHDRAWN'
    touch(x)
    return ok_object(ser_bid(x))
