"""Safety: gear inspections, incidents, weather restrictions."""
from flask import Blueprint, request

from db import store, new_id, stamp_new, stamp_new_immutable, touch
from errors import ApiError
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_str, get_num, get_enum, get_dt,
    parse_pagination, check_enum_filter, page_slice,
)
from calc import (
    ser_inspection, ser_incident, ser_restriction,
    apply_gear_inspection_cascade, apply_incident_cascade,
    apply_incident_resolve_cascade, apply_restriction_created,
    apply_restriction_lifted,
)

bp = Blueprint('safety', __name__)

INSPECTION_ITEMS = {'TOWING_HOOK', 'TOW_LINE', 'WINCH', 'BITTS'}
INSPECTION_OUTCOMES = {'PASSED', 'FAILED'}
INCIDENT_TYPES = {'GEAR_FAILURE', 'CONTACT_DAMAGE', 'POLLUTION', 'PERSONAL_INJURY'}
SEVERITIES = {'MINOR', 'MAJOR', 'CRITICAL'}
INCIDENT_STATUSES = {'REPORTED', 'UNDER_INVESTIGATION', 'RESOLVED'}
RESTRICTION_TYPES = {'WIND', 'CURRENT', 'VISIBILITY'}
RESTRICTION_STATUSES = {'ACTIVE', 'LIFTED'}


# ------------------------------------------------------------------ gear

@bp.route('/api/gear-inspections', methods=['POST'])
def create_inspection():
    _, role = authenticate()
    require_roles(role, ('MarineSurveyor',))
    body = json_body()
    c = Check()
    raw_tug = body.get('tug_id')
    tug = None
    if raw_tug is None or not isinstance(raw_tug, str):
        c.bad_request = True
    else:
        tug = store.tugs.get(raw_tug)
        if tug is None:
            not_found('tug')
    item = get_enum(body, 'inspection_item', INSPECTION_ITEMS, c)
    outcome = get_enum(body, 'outcome', INSPECTION_OUTCOMES, c)
    inspected_at = get_dt(body, 'inspected_at', c)
    next_due = get_dt(body, 'next_due_at', c)
    notes = get_str(body, 'deficiency_notes', c, required=False)
    c.raise_deferred()
    rec = {
        'id': new_id(), 'tug_id': raw_tug, 'inspection_item': item,
        'outcome': outcome, 'inspected_at': inspected_at,
        'next_due_at': next_due, 'deficiency_notes': notes,
    }
    stamp_new_immutable(rec)
    store.gear_inspections[rec['id']] = rec
    apply_gear_inspection_cascade(rec)
    return ok_object(ser_inspection(rec), 201)


@bp.route('/api/gear-inspections', methods=['GET'])
def list_inspections():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    outcome = check_enum_filter('outcome', INSPECTION_OUTCOMES, c)
    tug_id = request.args.get('tug_id')
    c.raise_deferred()
    recs = [g for g in store.gear_inspections.values()
            if (outcome is None or g['outcome'] == outcome)
            and (tug_id is None or g['tug_id'] == tug_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_inspection(g) for g in page], limit, offset, total)


@bp.route('/api/gear-inspections/<gid>', methods=['GET'])
def get_inspection(gid):
    authenticate()
    g = store.gear_inspections.get(gid)
    if g is None:
        not_found('gear inspection')
    return ok_object(ser_inspection(g))


# ------------------------------------------------------------------ incidents

@bp.route('/api/incidents', methods=['POST'])
def create_incident():
    uid, role = authenticate()
    require_roles(role, ('TugCaptain',))
    body = json_body()
    c = Check()
    # Ownership (stage 3): the reported tug_id must equal X-User-ID.
    raw_tug = body.get('tug_id')
    if raw_tug is None or not isinstance(raw_tug, str):
        c.bad_request = True
    elif raw_tug != uid:
        raise ApiError('ERR_ASSIGNMENT_NOT_OWNED', 403,
                       'TugCaptain may only report incidents for their own tug')
    tug = None
    if isinstance(raw_tug, str):
        tug = store.tugs.get(raw_tug)
        if tug is None:
            not_found('tug')
    raw_job = body.get('job_order_id')
    if raw_job is not None:
        if not isinstance(raw_job, str):
            c.bad_request = True
        elif raw_job not in store.job_orders:
            not_found('job order')
    itype = get_enum(body, 'incident_type', INCIDENT_TYPES, c)
    severity = get_enum(body, 'severity', SEVERITIES, c)
    occurred_at = get_dt(body, 'occurred_at', c)
    description = get_str(body, 'description', c)
    c.raise_deferred()
    rec = {
        'id': new_id(), 'tug_id': raw_tug, 'job_order_id': raw_job,
        'incident_type': itype, 'severity': severity,
        'occurred_at': occurred_at, 'description': description,
        'resolution_notes': None, 'status': 'REPORTED',
    }
    stamp_new(rec)
    store.incidents[rec['id']] = rec
    apply_incident_cascade(rec)
    return ok_object(ser_incident(rec), 201)


@bp.route('/api/incidents', methods=['GET'])
def list_incidents():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', INCIDENT_STATUSES, c)
    tug_id = request.args.get('tug_id')
    job_id = request.args.get('job_order_id')
    c.raise_deferred()
    recs = [i for i in store.incidents.values()
            if (status is None or i['status'] == status)
            and (tug_id is None or i['tug_id'] == tug_id)
            and (job_id is None or i.get('job_order_id') == job_id)]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_incident(i) for i in page], limit, offset, total)


@bp.route('/api/incidents/<iid>', methods=['GET'])
def get_incident(iid):
    authenticate()
    inc = store.incidents.get(iid)
    if inc is None:
        not_found('incident')
    return ok_object(ser_incident(inc))


@bp.route('/api/incidents/<iid>/resolve', methods=['POST'])
def resolve_incident(iid):
    _, role = authenticate()
    require_roles(role, ('MarineSurveyor',))
    inc = store.incidents.get(iid)
    if inc is None:
        not_found('incident')
    if inc['status'] == 'RESOLVED':
        raise ApiError('ERR_ALREADY_TERMINAL', 409, 'Incident is already RESOLVED')
    body = json_body()
    c = Check()
    notes = get_str(body, 'resolution_notes', c)
    c.raise_deferred()
    inc['resolution_notes'] = notes
    inc['status'] = 'RESOLVED'
    touch(inc)
    apply_incident_resolve_cascade(inc)
    return ok_object(ser_incident(inc))


# ------------------------------------------------------------------ weather

@bp.route('/api/weather-restrictions', methods=['POST'])
def create_restriction():
    _, role = authenticate()
    require_roles(role, ('PortAdmin',))
    body = json_body()
    c = Check()
    rtype = get_enum(body, 'restriction_type', RESTRICTION_TYPES, c)
    threshold = get_num(body, 'threshold_value', c)
    port_area = get_str(body, 'port_area', c)
    start = get_dt(body, 'effective_start', c)
    end = get_dt(body, 'effective_end', c)
    # Temporal (18): window shape before request-shape (stage 9 < stage 27).
    if start is not None and end is not None and end <= start:
        raise ApiError('ERR_WEATHER_WINDOW_INVALID', 422,
                       'effective_end must be strictly after effective_start')
    c.raise_deferred()
    rec = {
        'id': new_id(), 'restriction_type': rtype, 'threshold_value': threshold,
        'port_area': port_area, 'effective_start': start, 'effective_end': end,
        'status': 'ACTIVE',
    }
    stamp_new(rec)
    store.weather_restrictions[rec['id']] = rec
    apply_restriction_created(rec)
    return ok_object(ser_restriction(rec), 201)


@bp.route('/api/weather-restrictions', methods=['GET'])
def list_restrictions():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('status', RESTRICTION_STATUSES, c)
    c.raise_deferred()
    recs = [r for r in store.weather_restrictions.values()
            if status is None or r['status'] == status]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_restriction(r) for r in page], limit, offset, total)


@bp.route('/api/weather-restrictions/<rid>/lift', methods=['POST'])
def lift_restriction(rid):
    _, role = authenticate()
    require_roles(role, ('PortAdmin',))
    r = store.weather_restrictions.get(rid)
    if r is None:
        not_found('weather restriction')
    if r['status'] == 'LIFTED':
        raise ApiError('ERR_ALREADY_TERMINAL', 409,
                       'Weather restriction is already LIFTED')
    r['status'] = 'LIFTED'
    touch(r)
    apply_restriction_lifted()
    return ok_object(ser_restriction(r))
