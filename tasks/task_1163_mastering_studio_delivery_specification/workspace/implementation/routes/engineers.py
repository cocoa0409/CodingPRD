from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_ENGINEER_NOT_ASSIGNED
from middleware import (
    auth, require_roles, body, req_field, as_str, as_int, as_enum,
    pagination_args, get_or_404,
)
from response import success, success_list

bp = Blueprint('engineers', __name__)

TIERS = ('JUNIOR', 'STAFF', 'SENIOR', 'MASTER')
AVAILABILITY = ('AVAILABLE', 'ON_LEAVE', 'INACTIVE')


@bp.post('/studio/engineers')
def create_engineer():
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    data = body()
    display_name = as_str(req_field(data, 'display_name'), 'display_name')
    tier = as_enum(req_field(data, 'tier'), 'tier', TIERS)
    rate = as_int(req_field(data, 'hourly_rate_cents'), 'hourly_rate_cents')
    if rate <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'hourly_rate_cents must be > 0')
    capacity = as_int(req_field(data, 'capacity_minutes_per_day'), 'capacity_minutes_per_day')
    if capacity < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'capacity_minutes_per_day must be >= 0')
    rec = db.new_record()
    rec.update({
        'display_name': display_name,
        'tier': tier,
        'hourly_rate_cents': rate,
        'capacity_minutes_per_day': capacity,
        'availability_status': 'AVAILABLE',
        'active_project_count': 0,
    })
    db.engineers[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/engineers')
def list_engineers():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'QAChecker'))
    limit, offset = pagination_args()
    tier = request.args.get('tier')
    avail = request.args.get('availability_status')
    items = list(db.engineers.values())
    if tier is not None:
        items = [e for e in items if e['tier'] == tier]
    if avail is not None:
        items = [e for e in items if e['availability_status'] == avail]
    items.sort(key=lambda e: e['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/engineers/<eid>')
def get_engineer(eid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Engineer', 'QAChecker'))
    eng = get_or_404(db.engineers, eid)
    return success(db.public(eng), 200)


@bp.post('/studio/engineers/<eid>/set-availability')
def set_availability(eid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Engineer'))
    eng = get_or_404(db.engineers, eid)
    if role == 'Engineer' and uid != eid:
        raise ApiError(ERR_ENGINEER_NOT_ASSIGNED, 403,
                       'Engineer may only change their own availability')
    data = body()
    status = as_enum(req_field(data, 'availability_status'), 'availability_status', AVAILABILITY)
    eng['availability_status'] = status
    db.touch(eng)
    return success(db.public(eng), 200)
