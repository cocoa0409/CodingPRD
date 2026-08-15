"""Inventory endpoints: property owners, parcels, segments, defects."""
from flask import Blueprint, g, request

from db import db, base_entity, touch
from errors import ApiError, not_found
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services import (classify_defect, recompute_segment, ser_defect, ser_forestry,
                      ser_owner, ser_parcel, ser_segment, owner_id_of_parcel,
                      owner_id_of_segment, owner_id_of_defect)
from validation import get_body, parse_pagination, validate

bp = Blueprint('inventory', __name__)


def _paged(rows, serializer):
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)


# ------------------------------------------------------------- owners
@bp.post('/property-owners')
@require_roles('ProgramCoordinator')
def create_owner():
    vals = validate(get_body(), [
        ('full_name', 'str', True, {}),
        ('mailing_address', 'str', True, {}),
        ('hardship_tier', 'enum', False,
         {'values': ['NONE', 'SENIOR_65', 'LOW_INCOME'], 'default': 'NONE'}),
    ])
    o = base_entity()
    o.update({'full_name': vals['full_name'],
              'mailing_address': vals['mailing_address'],
              'hardship_tier': vals['hardship_tier']})
    db.owners[o['id']] = o
    return ok_object(ser_owner(o), 201)


@bp.get('/property-owners/<oid>')
@require_roles(*ALL_ROLES)
def get_owner(oid):
    o = db.owners.get(oid)
    if not o:
        raise not_found('owner')
    return ok_object(ser_owner(o))


# ------------------------------------------------------------- parcels
@bp.post('/parcels')
@require_roles('ProgramCoordinator')
def create_parcel():
    vals = validate(get_body(), [
        ('parcel_number', 'str', True, {}),
        ('owner_id', 'str', True, {}),
        ('street_address', 'str', True, {}),
        ('street_class', 'enum', True, {'values': ['LOCAL', 'COLLECTOR', 'ARTERIAL']}),
        ('is_corner_lot', 'bool', False, {'default': False}),
        ('is_city_owned', 'bool', False, {'default': False}),
    ])
    if vals['owner_id'] not in db.owners:
        raise not_found('owner')
    if any(p['parcel_number'] == vals['parcel_number'] for p in db.parcels.values()):
        raise ApiError('ERR_DUPLICATE_PARCEL_NUMBER', 409,
                       'parcel_number already registered')
    p = base_entity()
    p.update({
        'parcel_number': vals['parcel_number'],
        'owner_id': vals['owner_id'],
        'street_address': vals['street_address'],
        'street_class': vals['street_class'],
        'is_corner_lot': vals['is_corner_lot'],
        'is_city_owned': vals['is_city_owned'],
        'owner_responsibility_pct': 0 if vals['is_city_owned'] else 100,
        'delinquency_flag': False,
    })
    db.parcels[p['id']] = p
    return ok_object(ser_parcel(p), 201)


@bp.get('/parcels')
@require_roles(*ALL_ROLES)
def list_parcels():
    rows = list(db.parcels.values())
    if g.role == 'PropertyOwner':
        rows = [p for p in rows if p['owner_id'] == g.uid]
    owner_id = request.args.get('owner_id')
    if owner_id is not None:
        rows = [p for p in rows if p['owner_id'] == owner_id]
    return _paged(rows, ser_parcel)


@bp.get('/parcels/<pid>')
@require_roles(*ALL_ROLES)
def get_parcel(pid):
    p = db.parcels.get(pid)
    if not p:
        raise not_found('parcel')
    return ok_object(ser_parcel(p))


# ------------------------------------------------------------- segments
@bp.post('/segments')
@require_roles('Inspector')
def create_segment():
    vals = validate(get_body(), [
        ('parcel_id', 'str', True, {}),
        ('segment_code', 'str', True, {}),
        ('length_ft', 'num', True, {'positive': True}),
        ('width_ft', 'num', True, {'positive': True}),
        ('is_corner_segment', 'bool', False, {'default': False}),
        ('has_existing_curb_ramp', 'bool', False, {'default': False}),
    ])
    if vals['parcel_id'] not in db.parcels:
        raise not_found('parcel')
    if any(s['segment_code'] == vals['segment_code'] for s in db.segments.values()):
        raise ApiError('ERR_DUPLICATE_SEGMENT_CODE', 409,
                       'segment_code already registered')
    s = base_entity()
    s.update({
        'segment_code': vals['segment_code'],
        'parcel_id': vals['parcel_id'],
        'length_ft': vals['length_ft'],
        'width_ft': vals['width_ft'],
        'is_corner_segment': vals['is_corner_segment'],
        'has_existing_curb_ramp': vals['has_existing_curb_ramp'],
        'open_defect_count': 0,
        'condition_screening': 0,
        'condition_area_weighted': 0.0,
        'status': 'IN_SERVICE',
    })
    db.segments[s['id']] = s
    return ok_object(ser_segment(s), 201)


@bp.get('/segments')
@require_roles(*ALL_ROLES)
def list_segments():
    rows = list(db.segments.values())
    if g.role == 'PropertyOwner':
        rows = [s for s in rows if owner_id_of_segment(s) == g.uid]
    parcel_id = request.args.get('parcel_id')
    if parcel_id is not None:
        rows = [s for s in rows if s['parcel_id'] == parcel_id]
    return _paged(rows, ser_segment)


@bp.get('/segments/<sid>')
@require_roles(*ALL_ROLES)
def get_segment(sid):
    s = db.segments.get(sid)
    if not s:
        raise not_found('segment')
    return ok_object(ser_segment(s))


# ------------------------------------------------------------- defects
_OFFSET_REQUIRED = {'VERTICAL_SEPARATION', 'HORIZONTAL_OPENING', 'TREE_ROOT_UPHEAVAL'}
_DEFECT_TYPES = _OFFSET_REQUIRED | {'SPALLING', 'SETTLEMENT', 'CRUMBLED_JOINT'}


@bp.post('/defects')
@require_roles('Inspector')
def create_defect():
    body = get_body()
    vals = validate(body, [
        ('segment_id', 'str', True, {}),
        ('defect_type', 'enum', True, {'values': sorted(_DEFECT_TYPES)}),
        ('measured_offset_inches', 'num', False, {'default': None, 'nonnegative': True}),
        ('area_sqft', 'num', True, {'positive': True}),
        ('city_tree_involved', 'bool', False, {'default': False}),
    ])
    if vals['defect_type'] in _OFFSET_REQUIRED and vals['measured_offset_inches'] is None:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'measured_offset_inches is required for this defect_type')
    seg = db.segments.get(vals['segment_id'])
    if not seg:
        raise not_found('segment')
    d = base_entity()
    d.update({
        'segment_id': seg['id'],
        'defect_type': vals['defect_type'],
        'measured_offset_inches': vals['measured_offset_inches'],
        'area_sqft': vals['area_sqft'],
        'city_tree_involved': vals['city_tree_involved'],
        'severity_class': classify_defect(vals['defect_type'],
                                          vals['measured_offset_inches'],
                                          vals['area_sqft']),
        'recorded_by_inspector_id': g.uid,
        'status': 'OPEN',
    })
    db.defects[d['id']] = d
    if vals['defect_type'] == 'TREE_ROOT_UPHEAVAL' and vals['city_tree_involved']:
        d['status'] = 'AWAITING_FORESTRY'
        r = base_entity()
        r.update({'defect_id': d['id'], 'decision': 'PENDING',
                  'decided_by_user_id': None, 'work_completed_at': None,
                  'status': 'PENDING'})
        db.forestry_reviews[r['id']] = r
    if seg['status'] == 'IN_SERVICE':
        seg['status'] = 'FLAGGED'
    recompute_segment(seg)
    touch(seg)
    return ok_object(ser_defect(d), 201)


@bp.get('/defects')
@require_roles(*ALL_ROLES)
def list_defects():
    rows = list(db.defects.values())
    if g.role == 'PropertyOwner':
        rows = [d for d in rows if owner_id_of_defect(d) == g.uid]
    segment_id = request.args.get('segment_id')
    if segment_id is not None:
        rows = [d for d in rows if d['segment_id'] == segment_id]
    status = request.args.get('status')
    if status is not None:
        rows = [d for d in rows if d['status'] == status]
    return _paged(rows, ser_defect)


@bp.get('/defects/<did>')
@require_roles(*ALL_ROLES)
def get_defect(did):
    d = db.defects.get(did)
    if not d:
        raise not_found('defect')
    return ok_object(ser_defect(d))


@bp.get('/defects/<did>/forestry-reviews')
@require_roles(*ALL_ROLES)
def list_defect_forestry(did):
    d = db.defects.get(did)
    if not d:
        raise not_found('defect')
    rows = [r for r in db.forestry_reviews.values() if r['defect_id'] == did]
    if g.role == 'PropertyOwner' and owner_id_of_defect(d) != g.uid:
        rows = []
    return _paged(rows, ser_forestry)
