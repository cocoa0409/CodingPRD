from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES, AGENT_ROLE_MAP
from response import ok
from services import calc
from services.lifecycle import order_tariff
from services.store import new_entity, touch, crew_view
from util import get_body, check_body, get_path, apply_list, now, midnight

bp = Blueprint('crews', __name__)


def _crew_identity(auth, crew):
    if crew['agent_id'] != auth.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'the acting agent must be the sourcing agent of the crew assignment')


@bp.post('/orders/<oid>/crew-assignments')
def create_crew(oid):
    auth = authenticate()
    authorize(auth, ['OriginAgent', 'DestinationAgent'])
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [
        ('service_end', 'enum', True, ('ORIGIN', 'DESTINATION')),
        ('service_date', 'datetime', True, None),
        ('start_hour', 'int', True, (0, 23)),
        ('end_hour', 'int', True, (1, 24)),
        ('crew_size', 'int', True, (1, None)),
    ])
    if vals['end_hour'] <= vals['start_hour']:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'end_hour must be > start_hour')
    vals['service_date'] = midnight(vals['service_date'])  # PRD 2.5 day precision
    # ownership scope: the caller must hold the order assignment matching both its
    # declared role and the requested service_end
    want = AGENT_ROLE_MAP[auth.role]
    ok_scope = any(
        a for a in db.assignments.values()
        if a['order_id'] == oid and a['agent_id'] == auth.user_id
        and a['role'] == want == vals['service_end'])
    if not ok_scope:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'service_end must match the role the agent holds on the order')
    # service-date window applies once the order is BOOKED or beyond
    if order['status'] != 'REGISTERED' and order['latest_delivery_date'] is not None:
        sd = vals['service_date']
        if sd < order['pickup_date'] or sd > order['latest_delivery_date'] + timedelta(
                days=calc.CREW_WINDOW_EXTRA_DAYS):
            raise ApiError('ERR_SERVICE_DATE_OUT_OF_WINDOW', 422,
                           'service_date must fall within [pickup_date, latest_delivery_date + 30 days]')
    tariff = order_tariff(order)
    labor_hours, invoice = calc.crew_invoice(
        tariff['hourly_labor_rate_cents'], vals['start_hour'], vals['end_hour'], vals['crew_size'])
    crew = new_entity()
    crew.update({
        'order_id': oid,
        'agent_id': auth.user_id,
        'service_end': vals['service_end'],
        'service_date': vals['service_date'],
        'start_hour': vals['start_hour'],
        'end_hour': vals['end_hour'],
        'crew_size': vals['crew_size'],
        'labor_hours': labor_hours,
        'invoice_amount_cents': invoice,
        'status': 'REQUESTED',
    })
    db.crews[crew['id']] = crew
    return ok(crew_view(crew), 201)


@bp.post('/crew-assignments/<cid>/confirm')
def confirm_crew(cid):
    auth = authenticate()
    authorize(auth, ['OriginAgent', 'DestinationAgent'])
    crew = get_path(db.crews, cid)
    _crew_identity(auth, crew)
    check_body(get_body(), [])
    if crew['status'] != 'REQUESTED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'crew assignment is not REQUESTED')
    for c in db.crews.values():
        if (c['id'] != cid and c['agent_id'] == crew['agent_id']
                and c['status'] == 'CONFIRMED'
                and c['service_date'] == crew['service_date']
                and c['start_hour'] < crew['end_hour']
                and crew['start_hour'] < c['end_hour']):
            raise ApiError('ERR_CREW_SCHEDULE_CONFLICT', 409,
                           'overlaps another CONFIRMED crew of the same agent on that date')
    crew['status'] = 'CONFIRMED'
    touch(crew)
    return ok(crew_view(crew))


@bp.post('/crew-assignments/<cid>/complete')
def complete_crew(cid):
    auth = authenticate()
    authorize(auth, ['OriginAgent', 'DestinationAgent'])
    crew = get_path(db.crews, cid)
    _crew_identity(auth, crew)
    check_body(get_body(), [])
    if crew['status'] != 'CONFIRMED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'crew assignment is not CONFIRMED')
    order = db.orders[crew['order_id']]
    if order['status'] in ('REGISTERED', 'CANCELLED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'order must be beyond REGISTERED and not CANCELLED')
    crew['status'] = 'COMPLETED'
    touch(crew)
    return ok(crew_view(crew))


@bp.post('/crew-assignments/<cid>/cancel')
def cancel_crew(cid):
    auth = authenticate()
    authorize(auth, ['OriginAgent', 'DestinationAgent', 'BookingAgent'])
    crew = get_path(db.crews, cid)
    check_order_scope(auth, crew['order_id'])
    check_body(get_body(), [])
    if crew['status'] not in ('REQUESTED', 'CONFIRMED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'crew assignment is not REQUESTED or CONFIRMED')
    crew['status'] = 'CANCELLED'
    touch(crew)
    return ok(crew_view(crew))


@bp.get('/crew-assignments')
def list_crews():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'agent_id', 'service_end', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda c, p=param, v=v: c[p] == v)
    return apply_list(db.crews, filters, crew_view)


@bp.get('/crew-assignments/<cid>')
def get_crew(cid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(crew_view(get_path(db.crews, cid)))
