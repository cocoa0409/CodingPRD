"""PickupRequest + PickupItem endpoints and lifecycle transitions (PRD 3.2-3.4)."""
from datetime import datetime, time, timezone

from flask import Blueprint, request as freq

import db
import response
import serializers
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_PROHIBITED_ITEM, ERR_PREPARATION_NOT_ACKED,
                    ERR_HOUSEHOLD_SUSPENDED, ERR_ZONE_MISMATCH, ERR_TEMPORAL_CONFLICT,
                    ERR_DUPLICATE_PICKUP_DATE, ERR_ROUTE_CAPACITY_EXCEEDED,
                    ERR_ROUTE_LOCKED, ERR_STALE_ROUTE_VERSION,
                    ERR_STALE_REQUEST_VERSION)
from middleware import (body_json, is_bool, is_int, parse_date,
                        require_own_household, require_roles)
from services import calc

bp = Blueprint('pickup_requests', __name__)


def _get_request(rid):
    r = db.pickup_requests.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, f'PickupRequest {rid} not found', 404)
    return r


def _own(uid, role, req):
    if role == 'Resident':
        require_own_household(uid, req['household_id'])


def _touch_items(req_id):
    for it in calc.request_items(req_id):
        calc.touch(it)


@bp.route('/curbside/pickup-requests', methods=['POST'])
def create_request():
    uid, role = require_roles('Resident')
    body = body_json()
    household_id = body.get('household_id')
    if not isinstance(household_id, str) or not household_id:
        raise ApiError(ERR_INVALID_REQUEST, 'household_id is required', 400)
    require_own_household(uid, household_id)
    household = db.households.get(household_id)
    if household is None:
        raise ApiError(ERR_NOT_FOUND, f'Household {household_id} not found', 404)
    if household['status'] != 'ACTIVE':
        raise ApiError(ERR_HOUSEHOLD_SUSPENDED, 'Household is SUSPENDED', 409)
    now = db.wall_now()
    r = {
        'id': db.new_id(),
        'household_id': household_id,
        'route_day_id': None,
        'status': 'DRAFT',
        'scheduled_date': None,
        'load_units': 0,
        'provisional_total_cents': 0,
        'final_total_cents': None,
        'amnesty_applied': False,
        'refusal_reason_code': None,
        'missed_reason_code': None,
        'setout_classification': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.pickup_requests[r['id']] = r
    return response.ok(serializers.pickup_request(r), status=201)


@bp.route('/curbside/pickup-requests/<rid>', methods=['GET'])
def get_request(rid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    r = _get_request(rid)
    _own(uid, role, r)
    return response.ok(serializers.pickup_request(r))


@bp.route('/curbside/pickup-requests', methods=['GET'])
def list_requests():
    require_roles('Dispatcher', 'Inspector', 'Driver')
    household_id = freq.args.get('household_id')
    route_day_id = freq.args.get('route_day_id')
    status = freq.args.get('status')
    scheduled_date = freq.args.get('scheduled_date')
    rows = list(db.pickup_requests.values())
    if household_id is not None:
        rows = [r for r in rows if r['household_id'] == household_id]
    if route_day_id is not None:
        rows = [r for r in rows if r['route_day_id'] == route_day_id]
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    if scheduled_date is not None:
        rows = [r for r in rows if r['scheduled_date'] == scheduled_date]
    rows.sort(key=lambda r: r['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.pickup_request(r) for r in page], total, limit, offset)


# ---------------- Items ----------------

@bp.route('/curbside/pickup-requests/<rid>/items', methods=['POST'])
def add_item(rid):
    uid, role = require_roles('Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    if r['status'] != 'DRAFT':
        raise ApiError(ERR_INVALID_STATE, 'Items may be added only while the request is DRAFT', 409)
    body = body_json()
    seq = body.get('sequence_no')
    category = body.get('category')
    is_oversize = body.get('is_oversize', False)
    preparation_ack = body.get('preparation_ack')
    if not is_int(seq) or seq < 1:
        raise ApiError(ERR_INVALID_REQUEST, 'sequence_no must be an integer >= 1', 400)
    if category not in calc.CATEGORIES:
        raise ApiError(ERR_INVALID_REQUEST, 'category must be a declared enum member', 400)
    if not is_bool(is_oversize):
        raise ApiError(ERR_INVALID_REQUEST, 'is_oversize must be a boolean', 400)
    if not is_bool(preparation_ack):
        raise ApiError(ERR_INVALID_REQUEST, 'preparation_ack is required and must be a boolean', 400)
    for it in calc.request_items(rid):
        if it['sequence_no'] == seq:
            raise ApiError(ERR_INVALID_REQUEST, 'sequence_no must be unique within the request', 400)
    now = db.wall_now()
    it = {
        'id': db.new_id(),
        'pickup_request_id': rid,
        'sequence_no': seq,
        'category': category,
        'is_oversize': is_oversize,
        'preparation_ack': preparation_ack,
        'item_fee_cents': 0,
        'within_allowance': False,
        'disposition_route': None,
        '_ledger_counted': False,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.items[it['id']] = it
    r['load_units'] = calc.compute_load_units(rid)
    calc.touch(r)
    return response.ok(serializers.pickup_item(it), status=201)


@bp.route('/curbside/pickup-requests/<rid>/items/<item_id>', methods=['DELETE'])
def delete_item(rid, item_id):
    uid, role = require_roles('Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    it = db.items.get(item_id)
    if it is None or it['pickup_request_id'] != rid:
        raise ApiError(ERR_NOT_FOUND, f'PickupItem {item_id} not found', 404)
    if r['status'] != 'DRAFT':
        raise ApiError(ERR_INVALID_STATE, 'Items may be removed only while the request is DRAFT', 409)
    del db.items[item_id]
    r['load_units'] = calc.compute_load_units(rid)
    calc.touch(r)
    return '', 204


@bp.route('/curbside/pickup-requests/<rid>/items', methods=['GET'])
def list_items(rid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    r = _get_request(rid)
    _own(uid, role, r)
    rows = calc.request_items(rid)
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.pickup_item(i) for i in page], total, limit, offset)


# ---------------- Lifecycle: submit ----------------

@bp.route('/curbside/pickup-requests/<rid>/submit', methods=['POST'])
def submit_request(rid):
    uid, role = require_roles('Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    if r['status'] != 'DRAFT':
        raise ApiError(ERR_INVALID_STATE, 'Only a DRAFT request may be submitted', 409)
    items = calc.request_items(rid)
    # Priority 6: prohibition scan first, preparation scan second.
    for it in items:
        if it['category'] == 'PROHIBITED':
            raise ApiError(ERR_PROHIBITED_ITEM, 'Request contains a PROHIBITED item', 422)
    for it in items:
        if not it['preparation_ack']:
            raise ApiError(ERR_PREPARATION_NOT_ACKED,
                           'Every item requires preparation_ack == true at submit', 422)
    household = db.households.get(r['household_id'])
    if household is not None and household['status'] != 'ACTIVE':
        raise ApiError(ERR_HOUSEHOLD_SUSPENDED, 'Household is SUSPENDED', 409)
    if len(items) < 1:
        raise ApiError(ERR_INVALID_REQUEST, 'Request must contain at least one item at submit', 400)
    calc.run_quote(r, 'provisional')
    _touch_items(rid)
    calc.create_assessment(rid, r['household_id'], 'PROVISIONAL_QUOTE', r['provisional_total_cents'])
    r['status'] = 'SUBMITTED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


# ---------------- Lifecycle: schedule ----------------

@bp.route('/curbside/pickup-requests/<rid>/schedule', methods=['POST'])
def schedule_request(rid):
    uid, role = require_roles('Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    if r['status'] not in ('SUBMITTED', 'REFUSED'):
        raise ApiError(ERR_INVALID_STATE,
                       'Schedule is allowed only from SUBMITTED or REFUSED', 409)
    if r['status'] == 'REFUSED' and r['refusal_reason_code'] == 'EXCEEDS_DECLARED_ITEMS':
        raise ApiError(ERR_INVALID_STATE,
                       'Refusal for EXCEEDS_DECLARED_ITEMS requires cancel and redraft', 409)
    body = body_json()
    route_day_id = body.get('route_day_id')
    if not isinstance(route_day_id, str) or not route_day_id:
        raise ApiError(ERR_INVALID_REQUEST, 'route_day_id is required', 400)
    route = db.route_days.get(route_day_id)
    if route is None:
        raise ApiError(ERR_NOT_FOUND, f'RouteDay {route_day_id} not found', 404)
    if route['status'] != 'OPEN':
        raise ApiError(ERR_ROUTE_LOCKED, 'RouteDay is not OPEN', 409)
    expected = body.get('expected_route_day_version')
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 'expected_route_day_version is required', 400)
    if expected != route['version']:
        raise ApiError(ERR_STALE_ROUTE_VERSION,
                       'expected_route_day_version does not match RouteDay.version', 412)
    household = db.households.get(r['household_id'])
    if household is not None and household['status'] != 'ACTIVE':
        raise ApiError(ERR_HOUSEHOLD_SUSPENDED, 'Household is SUSPENDED', 409)
    if household is not None and route['service_zone'] != household['service_zone']:
        raise ApiError(ERR_ZONE_MISMATCH,
                       'RouteDay.service_zone differs from Household.service_zone', 422)
    if parse_date(route['route_date']) < db.get_clock().date():
        raise ApiError(ERR_TEMPORAL_CONFLICT, 'Cannot schedule into the past', 422)
    for other in db.pickup_requests.values():
        if (other['id'] != r['id'] and other['household_id'] == r['household_id']
                and other['status'] == 'SCHEDULED'
                and other['scheduled_date'] == route['route_date']):
            raise ApiError(ERR_DUPLICATE_PICKUP_DATE,
                           'Household already holds a SCHEDULED request on this route_date', 409)
    if (route['committed_load_units'] + r['load_units'] > route['max_load_units']
            or route['committed_stops'] + 1 > route['max_stops']):
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED, 'Route capacity exceeded', 409)
    # ---- side effects (atomic) ----
    r['route_day_id'] = route['id']
    r['scheduled_date'] = route['route_date']
    r['amnesty_applied'] = calc.amnesty_applies(route['route_date'])
    if household is not None:
        calc.consume_allowance(household, r)
    calc.run_quote(r, 'scheduled')
    _touch_items(rid)
    route['committed_load_units'] += r['load_units']
    route['committed_stops'] += 1
    calc.touch(route)
    calc.emit_notification(
        rid, 'SCHEDULE_CONFIRMATION', None,
        f"Pickup scheduled for {r['scheduled_date']} on route {route['id']} ({route['service_zone']}).")
    r['status'] = 'SCHEDULED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


# ---------------- Lifecycle: cancel ----------------

@bp.route('/curbside/pickup-requests/<rid>/cancel', methods=['POST'])
def cancel_request(rid):
    uid, role = require_roles('Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    if r['status'] not in ('SUBMITTED', 'SCHEDULED', 'MISSED', 'REFUSED'):
        raise ApiError(ERR_INVALID_STATE,
                       'Cancel is allowed only from SUBMITTED, SCHEDULED, MISSED, or REFUSED', 409)
    route = db.route_days.get(r['route_day_id']) if r['route_day_id'] else None
    if r['status'] == 'SCHEDULED' and route is not None and route['status'] != 'OPEN':
        raise ApiError(ERR_ROUTE_LOCKED,
                       'RouteDay is locked; schedule/cancel mutations are closed', 409)
    body = body_json()
    expected = body.get('expected_request_version')
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 'expected_request_version is required', 400)
    if expected != r['version']:
        raise ApiError(ERR_STALE_REQUEST_VERSION,
                       'expected_request_version does not match PickupRequest.version', 412)
    if r['status'] == 'SCHEDULED':
        sched = parse_date(r['scheduled_date'])
        midnight = datetime.combine(sched, time.min, tzinfo=timezone.utc)
        if not (db.get_clock() < midnight):
            raise ApiError(ERR_TEMPORAL_CONFLICT,
                           'Cancellation cutoff is midnight at the start of the pickup day', 422)
    # ---- side effects ----
    from_status = r['status']
    if from_status == 'SCHEDULED':
        if route is not None:
            route['committed_load_units'] -= r['load_units']
            route['committed_stops'] -= 1
            calc.touch(route)
        calc.release_allowance(r)
        _touch_items(rid)
        calc.waive_pending_quote(rid)
    elif from_status == 'SUBMITTED':
        calc.waive_pending_quote(rid)
    elif from_status == 'REFUSED':
        calc.release_allowance(r)
        _touch_items(rid)
        calc.waive_pending_quote(rid)
    # MISSED: route and allowance were already released by the miss.
    calc.emit_notification(rid, 'CANCELLATION_NOTICE', None, 'Pickup request cancelled.')
    r['status'] = 'CANCELLED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


# ---------------- Lifecycle: driver actions ----------------

def _driver_gate(rid):
    """Shared preconditions for refuse/miss. Returns (request, route)."""
    require_roles('Driver')
    r = _get_request(rid)
    if r['status'] != 'SCHEDULED':
        raise ApiError(ERR_INVALID_STATE, 'Stop must be SCHEDULED', 409)
    route = db.route_days.get(r['route_day_id']) if r['route_day_id'] else None
    if route is None or route['status'] != 'DISPATCHED':
        raise ApiError(ERR_INVALID_STATE, 'RouteDay must be DISPATCHED', 409)
    sched = parse_date(r['scheduled_date'])
    if sched is None or db.get_clock().date() != sched:
        raise ApiError(ERR_TEMPORAL_CONFLICT,
                       'Driver actions are allowed only on the scheduled_date', 422)
    return r, route


def _release_route(route, r):
    route['committed_load_units'] -= r['load_units']
    route['committed_stops'] -= 1
    calc.touch(route)


@bp.route('/curbside/pickup-requests/<rid>/complete', methods=['POST'])
def complete_request(rid):
    require_roles('Driver')
    r = _get_request(rid)
    body = body_json()
    # Existence of item ids (priority 3) precedes the state gate (priority 4).
    raw_ids = body.get('improper_preparation_item_ids', [])
    if not isinstance(raw_ids, list):
        raise ApiError(ERR_INVALID_REQUEST, 'improper_preparation_item_ids must be a list', 400)
    flagged = []
    for iid in raw_ids:
        it = db.items.get(iid) if isinstance(iid, str) else None
        if it is None or it['pickup_request_id'] != rid:
            raise ApiError(ERR_NOT_FOUND, f'PickupItem {iid} not found', 404)
        if iid not in flagged:
            flagged.append(iid)
    if r['status'] != 'SCHEDULED':
        raise ApiError(ERR_INVALID_STATE, 'Stop must be SCHEDULED', 409)
    route = db.route_days.get(r['route_day_id']) if r['route_day_id'] else None
    if route is None or route['status'] != 'DISPATCHED':
        raise ApiError(ERR_INVALID_STATE, 'RouteDay must be DISPATCHED', 409)
    sched = parse_date(r['scheduled_date'])
    if sched is None or db.get_clock().date() != sched:
        raise ApiError(ERR_TEMPORAL_CONFLICT,
                       'Driver actions are allowed only on the scheduled_date', 422)
    # ---- side effects ----
    r['final_total_cents'] = calc.final_invoice_amount(r, flagged)
    calc.create_assessment(rid, r['household_id'], 'FINAL_INVOICE', r['final_total_cents'])
    calc.waive_pending_quote(rid)
    for it in calc.request_items(rid):
        it['disposition_route'] = calc.ROUTE_BY_CATEGORY[it['category']]
        calc.touch(it)
    r['status'] = 'COMPLETED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


@bp.route('/curbside/pickup-requests/<rid>/refuse', methods=['POST'])
def refuse_request(rid):
    r, route = _driver_gate(rid)
    body = body_json()
    code = body.get('refusal_reason_code')
    if code not in calc.REFUSAL_REASON_CODES:
        raise ApiError(ERR_INVALID_REQUEST, 'refusal_reason_code must be a declared enum member', 400)
    # ---- side effects: allowance is NOT released on refusal ----
    r['refusal_reason_code'] = code
    _release_route(route, r)
    calc.waive_pending_quote(rid)
    calc.emit_notification(rid, 'REFUSAL_NOTICE', code, calc.refusal_message(rid, code))
    r['status'] = 'REFUSED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


@bp.route('/curbside/pickup-requests/<rid>/miss', methods=['POST'])
def miss_request(rid):
    r, route = _driver_gate(rid)
    body = body_json()
    code = body.get('missed_reason_code')
    if code not in calc.MISSED_REASON_CODES:
        raise ApiError(ERR_INVALID_REQUEST, 'missed_reason_code must be a declared enum member', 400)
    # ---- side effects: no set-out made, so allowance IS released ----
    r['missed_reason_code'] = code
    _release_route(route, r)
    calc.release_allowance(r)
    _touch_items(rid)
    calc.waive_pending_quote(rid)
    calc.emit_notification(rid, 'MISSED_NOTICE', code, f'Pickup missed: {code}.')
    r['status'] = 'MISSED'
    calc.touch(r)
    return response.ok(serializers.pickup_request(r))


# ---------------- Reverse-reachable sublists ----------------

@bp.route('/curbside/pickup-requests/<rid>/fee-assessments', methods=['GET'])
def request_assessments(rid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident')
    r = _get_request(rid)
    _own(uid, role, r)
    rows = [a for a in db.assessments.values() if a['pickup_request_id'] == rid]
    rows.sort(key=lambda a: a['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.fee_assessment(a) for a in page], total, limit, offset)


@bp.route('/curbside/pickup-requests/<rid>/notifications', methods=['GET'])
def request_notifications(rid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    r = _get_request(rid)
    _own(uid, role, r)
    rows = [n for n in db.notifications.values() if n['pickup_request_id'] == rid]
    rows.sort(key=lambda n: n['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.notification(n) for n in page], total, limit, offset)


@bp.route('/curbside/pickup-requests/<rid>/dumping-reports', methods=['GET'])
def request_dumping_reports(rid):
    require_roles('Dispatcher', 'Inspector')
    _get_request(rid)
    rows = [rep for rep in db.reports.values() if rep['pickup_request_id'] == rid]
    rows.sort(key=lambda rep: rep['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.dumping_report(rep) for rep in page], total, limit, offset)
