"""Booth application routes: create, approve/reject, payments, assign, cancel."""
from flask import Blueprint, request

from db import STORE, new_id, now_iso
from errors import raise_err
from middleware import require_roles, check_vendor_owns
from response import success_object, success_list
from util import body, get_field, get_int, get_pagination, paginate
from services import domain, calculations
from services.serializers import booth_json, payment_json

bp = Blueprint('booths', __name__)

TIERS = ('SINGLE', 'DOUBLE', 'SPONSOR')
TIER_SPACES = {'SINGLE': 1, 'DOUBLE': 2, 'SPONSOR': 3}


def _get_app_or_404(app_id):
    app = STORE.booth_applications.get(app_id)
    if app is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Booth application not found')
    return app


@bp.route('/booth-applications', methods=['POST'])
def create_booth_application():
    require_roles('Organizer')
    data = body()
    event_id = get_field(data, 'event_id', type_=str)
    business_name = get_field(data, 'business_name', type_=str)
    contact_email = get_field(data, 'contact_email', type_=str)
    booth_tier = get_field(data, 'booth_tier', type_=str)
    if booth_tier not in TIERS:
        raise_err(('ERR_VALIDATION', 400), 'booth_tier must be SINGLE, DOUBLE, or SPONSOR')
    power_requested = get_field(data, 'power_requested', required=False,
                                default=False, type_=bool)
    ev = STORE.events.get(event_id)
    if ev is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Event not found')
    now = now_iso()
    app = {
        'id': new_id(),
        'event_id': event_id,
        'business_name': business_name,
        'contact_email': contact_email,
        'booth_tier': booth_tier,
        'power_requested': power_requested,
        'status': 'SUBMITTED',
        'fee_cents': 0,
        'paid_cents': 0,
        'assigned_zone_id': None,
        'assigned_spaces': [],
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.booth_applications[app['id']] = app
    return success_object(booth_json(app), status=201)


@bp.route('/booth-applications', methods=['GET'])
def list_booth_applications():
    user_id, role = require_roles('Organizer', 'Vendor', 'RegistrationDesk')
    limit, offset = get_pagination()
    items = domain.sorted_created(list(STORE.booth_applications.values()))
    if role == 'Vendor':
        items = [a for a in items if a['id'] == user_id]
    for param in ('event_id', 'assigned_zone_id', 'status'):
        val = request.args.get(param)
        if val:
            items = [a for a in items if str(a.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([booth_json(a) for a in page], limit, offset, total)


@bp.route('/booth-applications/<app_id>', methods=['GET'])
def get_booth_application(app_id):
    user_id, role = require_roles('Organizer', 'Vendor', 'RegistrationDesk')
    app = _get_app_or_404(app_id)
    check_vendor_owns(user_id, role, app['id'])
    return success_object(booth_json(app))


@bp.route('/booth-applications/<app_id>/approve', methods=['POST'])
def approve_booth(app_id):
    require_roles('Organizer')
    app = _get_app_or_404(app_id)
    if app['status'] != 'SUBMITTED':
        raise_err(('ERR_INVALID_BOOTH_STATE', 409),
                  'Only a SUBMITTED application can be approved')
    ev = STORE.events[app['event_id']]
    if ev['lifecycle_status'] == 'CLOSED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Cannot approve booths for a CLOSED event')
    app['fee_cents'] = calculations.compute_booth_fee(app['booth_tier'],
                                                      app['power_requested'])
    app['status'] = 'APPROVED'
    domain.touch_entity(app)
    return success_object(booth_json(app))


@bp.route('/booth-applications/<app_id>/reject', methods=['POST'])
def reject_booth(app_id):
    require_roles('Organizer')
    app = _get_app_or_404(app_id)
    if app['status'] != 'SUBMITTED':
        raise_err(('ERR_INVALID_BOOTH_STATE', 409),
                  'Only a SUBMITTED application can be rejected')
    app['status'] = 'REJECTED'
    domain.touch_entity(app)
    return success_object(booth_json(app))


@bp.route('/booth-applications/<app_id>/payments', methods=['POST'])
def record_booth_payment(app_id):
    user_id, role = require_roles('Vendor', 'Organizer')
    app = _get_app_or_404(app_id)
    check_vendor_owns(user_id, role, app['id'])
    data = body()
    amount_cents = get_int(data, 'amount_cents')
    method = get_field(data, 'method', type_=str)
    if method not in ('CASH', 'CARD', 'CHECK'):
        raise_err(('ERR_VALIDATION', 400), 'method must be CASH, CARD, or CHECK')
    if app['status'] != 'APPROVED':
        raise_err(('ERR_INVALID_BOOTH_STATE', 409),
                  'Booth fee payment requires APPROVED status')
    if amount_cents != app['fee_cents']:
        raise_err(('ERR_PAYMENT_AMOUNT_MISMATCH', 422),
                  'amount_cents must equal the computed fee_cents')
    pay = domain.create_payment(None, app['id'], 'BOOTH_FEE', amount_cents,
                                method, user_id)
    app['status'] = 'PAID'
    domain.touch_entity(app)
    return success_object(payment_json(pay), status=201)


@bp.route('/booth-applications/<app_id>/payments', methods=['GET'])
def list_booth_payments(app_id):
    user_id, role = require_roles('Vendor', 'Organizer')
    app = _get_app_or_404(app_id)
    check_vendor_owns(user_id, role, app['id'])
    limit, offset = get_pagination()
    items = domain.sorted_created([p for p in STORE.payments.values()
                                   if p.get('booth_application_id') == app_id])
    page, total = paginate(items, limit, offset)
    return success_list([payment_json(p) for p in page], limit, offset, total)


@bp.route('/booth-applications/<app_id>/assign', methods=['POST'])
def assign_booth(app_id):
    require_roles('Organizer')
    app = _get_app_or_404(app_id)
    data = body()
    zone_id = get_field(data, 'zone_id', type_=str)
    spaces = get_field(data, 'spaces', type_=list)
    for s in spaces:
        if not isinstance(s, int) or isinstance(s, bool):
            raise_err(('ERR_VALIDATION', 400), 'spaces must be integers')

    if app['status'] != 'PAID':
        raise_err(('ERR_INVALID_BOOTH_STATE', 409),
                  'Application must be PAID before assignment')
    zone = STORE.zones.get(zone_id)
    if zone is None or zone['event_id'] != app['event_id']:
        raise_err(('ERR_NOT_FOUND', 404), 'Zone not found')
    if zone['zone_type'] != 'VENDOR_ROW':
        raise_err(('ERR_ZONE_TYPE_INELIGIBLE', 422),
                  'Booths may be assigned only into VENDOR_ROW zones')
    if app['power_requested'] and not zone['has_power']:
        raise_err(('ERR_POWER_NOT_AVAILABLE', 422),
                  'Requested power but the zone has no power')
    need = TIER_SPACES[app['booth_tier']]
    if len(spaces) != need or len(set(spaces)) != need:
        raise_err(('ERR_BOOTH_SPACES_NOT_CONTIGUOUS', 422),
                  f'{app["booth_tier"]} requires exactly {need} distinct spaces')
    ordered = sorted(spaces)
    if ordered != list(range(ordered[0], ordered[0] + need)):
        raise_err(('ERR_BOOTH_SPACES_NOT_CONTIGUOUS', 422),
                  'Spaces must be contiguous ascending integers')
    for n in spaces:
        if n < 1 or n > zone['capacity']:
            raise_err(('ERR_BOOTH_SPACES_NOT_CONTIGUOUS', 422),
                      'Space numbers must fall within 1..zone capacity')
    requested = set(spaces)
    for other in STORE.booth_applications.values():
        if (other['id'] != app['id'] and other['status'] == 'ASSIGNED'
                and other.get('assigned_zone_id') == zone_id):
            if requested & set(other['assigned_spaces']):
                raise_err(('ERR_BOOTH_SPACE_CONFLICT', 409),
                          'Requested spaces intersect another ASSIGNED application')

    app['assigned_zone_id'] = zone_id
    app['assigned_spaces'] = list(spaces)
    app['status'] = 'ASSIGNED'
    domain.touch_entity(app)
    return success_object(booth_json(app))


@bp.route('/booth-applications/<app_id>/cancel', methods=['POST'])
def cancel_booth(app_id):
    user_id, role = require_roles('Organizer', 'Vendor')
    app = _get_app_or_404(app_id)
    check_vendor_owns(user_id, role, app['id'])
    body()  # optional reason
    if app['status'] not in ('APPROVED', 'PAID', 'ASSIGNED'):
        raise_err(('ERR_INVALID_BOOTH_STATE', 409),
                  'Only APPROVED, PAID, or ASSIGNED applications can be cancelled')
    if app['paid_cents'] > 0:
        domain.create_payment(None, app['id'], 'REFUND', app['paid_cents'],
                              'CASH', user_id)
    app['assigned_zone_id'] = None
    app['assigned_spaces'] = []
    app['status'] = 'CANCELLED'
    domain.touch_entity(app)
    return success_object(booth_json(app))
