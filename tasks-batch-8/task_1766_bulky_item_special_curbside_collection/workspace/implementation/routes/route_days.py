"""RouteDay endpoints (PRD 3.3, 3.4, 3.7)."""
from flask import Blueprint, request

import db
import response
import serializers
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_ROUTE_NOT_EMPTY, ERR_TEMPORAL_CONFLICT)
from middleware import body_json, is_int, parse_date, require_roles
from services import calc

bp = Blueprint('route_days', __name__)


def _get_route(rid):
    r = db.route_days.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, f'RouteDay {rid} not found', 404)
    return r


@bp.route('/curbside/route-days', methods=['POST'])
def create_route_day():
    require_roles('Dispatcher')
    body = body_json()
    zone = body.get('service_zone')
    route_date = body.get('route_date')
    max_load = body.get('max_load_units')
    max_stops = body.get('max_stops')
    if zone not in calc.ZONES:
        raise ApiError(ERR_INVALID_REQUEST, 'service_zone must be one of ZONE_NORTH, ZONE_SOUTH, ZONE_EAST, ZONE_WEST', 400)
    if parse_date(route_date) is None:
        raise ApiError(ERR_INVALID_REQUEST, 'route_date must be an ISO yyyy-mm-dd date', 400)
    if not is_int(max_load):
        raise ApiError(ERR_INVALID_REQUEST, 'max_load_units must be an integer', 400)
    if not is_int(max_stops):
        raise ApiError(ERR_INVALID_REQUEST, 'max_stops must be an integer', 400)
    now = db.wall_now()
    r = {
        'id': db.new_id(),
        'service_zone': zone,
        'route_date': route_date,
        'max_load_units': max_load,
        'max_stops': max_stops,
        'committed_load_units': 0,
        'committed_stops': 0,
        'status': 'OPEN',
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.route_days[r['id']] = r
    return response.ok(serializers.route_day(r), status=201)


@bp.route('/curbside/route-days/<rid>', methods=['GET'])
def get_route_day(rid):
    require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    return response.ok(serializers.route_day(_get_route(rid)))


@bp.route('/curbside/route-days', methods=['GET'])
def list_route_days():
    require_roles('Dispatcher', 'Inspector', 'Resident', 'Driver')
    zone = request.args.get('service_zone')
    rdate = request.args.get('route_date')
    status = request.args.get('status')
    rows = list(db.route_days.values())
    if zone is not None:
        rows = [r for r in rows if r['service_zone'] == zone]
    if rdate is not None:
        rows = [r for r in rows if r['route_date'] == rdate]
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda r: r['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.route_day(r) for r in page], total, limit, offset)


@bp.route('/curbside/route-days/<rid>/dispatch', methods=['POST'])
def dispatch_route(rid):
    require_roles('Dispatcher')
    r = _get_route(rid)
    if r['status'] != 'OPEN':
        raise ApiError(ERR_INVALID_STATE, 'RouteDay is not OPEN', 409)
    if db.get_clock().date() != parse_date(r['route_date']):
        raise ApiError(ERR_TEMPORAL_CONFLICT, 'Dispatch is allowed only on route_date', 422)
    if r['committed_stops'] < 1:
        raise ApiError(ERR_INVALID_STATE, 'An empty route is not dispatched', 409)
    r['status'] = 'DISPATCHED'
    calc.touch(r)
    return response.ok(serializers.route_day(r))


@bp.route('/curbside/route-days/<rid>/close', methods=['POST'])
def close_route(rid):
    require_roles('Dispatcher')
    r = _get_route(rid)
    if r['status'] != 'DISPATCHED':
        raise ApiError(ERR_INVALID_STATE, 'RouteDay is not DISPATCHED', 409)
    for req in db.pickup_requests.values():
        if req['route_day_id'] == rid and req['status'] == 'SCHEDULED':
            raise ApiError(ERR_ROUTE_NOT_EMPTY,
                           'Route cannot close while a stop is still SCHEDULED', 409)
    r['status'] = 'CLOSED'
    calc.touch(r)
    return response.ok(serializers.route_day(r))


@bp.route('/curbside/route-days/<rid>/pickup-requests', methods=['GET'])
def route_pickup_requests(rid):
    require_roles('Dispatcher', 'Inspector', 'Driver')
    _get_route(rid)
    rows = [r for r in db.pickup_requests.values() if r['route_day_id'] == rid]
    rows.sort(key=lambda r: r['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.pickup_request(r) for r in page], total, limit, offset)
