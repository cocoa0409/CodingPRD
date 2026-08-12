"""Organizers, street segments, the logical clock, and test-driving hooks."""
from flask import Blueprint

from auth import auth, own_or_403, ALL_ROLES, REVIEW_ROLES
from calc import (demote_organizer, ensure_fresh, get_organizer, get_segment)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, fmt
from validate import body, req, as_str, as_int, as_bool, as_enum, as_dt, opt_int, opt_bool

bp = Blueprint('admin', __name__)

ORG_READ_ROLES = ['Organizer', 'PermitOfficer', 'CityAdmin']

JURISDICTIONS = ['CITY', 'COUNTY', 'STATE_ROUTE']
SEGMENT_KINDS = ['RESIDENTIAL', 'MIXED_USE']


@bp.route('/organizers', methods=['POST'])
def create_organizer():
    auth(['Anonymous'])
    b = body()
    org = entity(
        full_name=as_str(req(b, 'full_name'), 'full_name'),
        email=as_str(req(b, 'email'), 'email'),
        phone=as_str(req(b, 'phone'), 'phone'),
        address=as_str(req(b, 'address'), 'address'),
        standing='GOOD',
        forfeiture_count=0,
    )
    db.organizers[org['id']] = org
    return created(org)


@bp.route('/organizers/<oid>', methods=['GET'])
def get_one_organizer(oid):
    uid, role = auth(ORG_READ_ROLES)
    org = get_organizer(oid)
    own_or_403(role, uid, org['id'])
    return ok(org)


@bp.route('/organizers/<oid>/petitions', methods=['GET'])
def organizer_petitions(oid):
    uid, role = auth(ORG_READ_ROLES)
    org = get_organizer(oid)
    own_or_403(role, uid, org['id'])
    rows = [p for p in db.petitions.values() if p['organizer_id'] == oid]
    return ok_list(rows)


@bp.route('/organizers/<oid>/permit-applications', methods=['GET'])
def organizer_applications(oid):
    uid, role = auth(ORG_READ_ROLES)
    org = get_organizer(oid)
    own_or_403(role, uid, org['id'])
    rows = []
    for a in db.applications.values():
        if a['organizer_id'] == oid:
            ensure_fresh(a)
            rows.append(a)
    return ok_list(rows)


@bp.route('/_inject/organizer_forfeiture', methods=['POST'])
def inject_forfeiture():
    auth(['CityAdmin'])
    b = body()
    org = get_organizer(as_str(req(b, 'organizer_id'), 'organizer_id'))
    demote_organizer(org)
    return ok(org)


@bp.route('/street-segments', methods=['POST'])
def create_segment():
    auth(['CityAdmin'])
    b = body()
    household_count = as_int(req(b, 'household_count'), 'household_count')
    if household_count < 0:
        raise ApiError('ERR_INVALID_REQUEST', 'household_count must be >= 0', 400)
    business_count = opt_int(b, 'business_count', 0)
    if business_count < 0:
        raise ApiError('ERR_INVALID_REQUEST', 'business_count must be >= 0', 400)
    length_m = as_int(req(b, 'length_m'), 'length_m')
    if length_m <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'length_m must be > 0', 400)
    seg = entity(
        name=as_str(req(b, 'name'), 'name'),
        jurisdiction=as_enum(req(b, 'jurisdiction'), 'jurisdiction', JURISDICTIONS),
        segment_kind=as_enum(req(b, 'segment_kind'), 'segment_kind', SEGMENT_KINDS),
        household_count=household_count,
        business_count=business_count,
        intersects_arterial=opt_bool(b, 'intersects_arterial', False),
        length_m=length_m,
    )
    db.segments[seg['id']] = seg
    return created(seg)


@bp.route('/street-segments/<sid>', methods=['GET'])
def get_one_segment(sid):
    auth(ALL_ROLES)
    return ok(get_segment(sid))


@bp.route('/street-segments/<sid>/petitions', methods=['GET'])
def segment_petitions(sid):
    auth(ALL_ROLES)
    seg = get_segment(sid)
    rows = [p for p in db.petitions.values() if p['segment_id'] == seg['id']]
    return ok_list(rows)


@bp.route('/street-segments/<sid>/permit-applications', methods=['GET'])
def segment_applications(sid):
    auth(REVIEW_ROLES)
    seg = get_segment(sid)
    rows = []
    for a in db.applications.values():
        if a['segment_id'] == seg['id']:
            ensure_fresh(a)
            rows.append(a)
    return ok_list(rows)


@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    auth(['CityAdmin'])
    b = body()
    t = as_dt(req(b, 'to_iso8601'), 'to_iso8601')
    db.clock = t
    return ok({'current_utc': fmt(db.clock)})
