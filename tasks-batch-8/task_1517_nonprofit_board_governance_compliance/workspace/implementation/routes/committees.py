"""Committees and committee appointments."""
from flask import request

import store
from domain import (COMMITTEE_TYPES, RESTRICTION_MAP, adopted_bylaws,
                    committee_active_count, current_fiscal_year,
                    disclosure_for, end_appointment, ser_appointment,
                    ser_committee)
from helpers import (ALL_ROLES, ApiError, apply_filters, authn,
                     check_org_membership, envelope, err400, get_body,
                     list_response, lookup, new_entity, qualified_member,
                     ref_lookup, require_role, touch, v_bool, v_enum, v_int,
                     v_str)
from . import bp
from .core import _np_or_403_or_422


@bp.post('/boardgov/committees')
def create_committee():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    name = v_str(body, 'name')
    ctype = v_enum(body, 'type', COMMITTEE_TYPES)
    min_members = v_int(body, 'min_members', min_v=1)
    authorized = v_int(body, 'authorized_size')
    if authorized < min_members:
        raise err400('authorized_size must be >= min_members')
    rai = v_bool(body, 'requires_all_independent', required=False, default=False)
    if ctype == 'AUDIT':
        rai = True
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    if any(c['nonprofit_id'] == np['id'] and c['name'] == name and
           c['status'] != 'DISSOLVED' for c in store.committees.values()):
        raise ApiError('ERR_DUPLICATE_COMMITTEE_NAME', 409,
                       'A non-DISSOLVED committee with this name exists')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'name': name, 'type': ctype,
              'min_members': min_members, 'authorized_size': authorized,
              'requires_all_independent': rai, 'status': 'CHARTERED'})
    store.committees[e['id']] = e
    return envelope(ser_committee(e), status=201)


@bp.get('/boardgov/committees/<rid>')
def get_committee(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    c = lookup(store.committees, rid)
    check_org_membership(member, role, c['nonprofit_id'])
    return envelope(ser_committee(c))


@bp.get('/boardgov/committees')
def list_committees():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.committees.values()),
                          {'nonprofit_id': np_id,
                           'status': request.args.get('status'),
                           'type': request.args.get('type')})
    return list_response(items, ser_committee)


@bp.post('/boardgov/committees/<rid>/activate')
def activate_committee(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    c = lookup(store.committees, rid)
    check_org_membership(member, role, c['nonprofit_id'])
    if c['status'] != 'CHARTERED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only CHARTERED committees can be activated')
    appts = [a for a in store.appointments.values()
             if a['committee_id'] == c['id'] and a['status'] == 'ACTIVE']
    if len(appts) < c['min_members']:
        raise ApiError('ERR_COMMITTEE_BELOW_MIN', 409,
                       'active_member_count is below min_members')
    if c['requires_all_independent']:
        for a in appts:
            m = store.members.get(a['board_member_id'])
            if m is None or not m['is_independent']:
                raise ApiError('ERR_COMMITTEE_NOT_INDEPENDENT', 409,
                               'All appointees must be independent')
    np = store.nonprofits.get(c['nonprofit_id'])
    cfy = current_fiscal_year(np)
    for a in appts:
        d = disclosure_for(a['board_member_id'], cfy)
        if d is None or d['status'] not in ('CLEARED', 'RESTRICTIONS_IMPOSED'):
            raise ApiError('ERR_COI_REVIEW_REQUIRED', 409,
                           'Every appointee must hold a reviewed current-fiscal-year disclosure')
    c['status'] = 'ACTIVE'
    touch(c)
    return envelope(ser_committee(c))


@bp.post('/boardgov/committees/<rid>/dissolve')
def dissolve_committee(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    c = lookup(store.committees, rid)
    check_org_membership(member, role, c['nonprofit_id'])
    if c['status'] == 'DISSOLVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Committee is already DISSOLVED')
    prior = c['status']
    c['status'] = 'DISSOLVED'
    touch(c)
    if prior in ('CHARTERED', 'ACTIVE'):
        for a in list(store.appointments.values()):
            if a['committee_id'] == c['id'] and a['status'] == 'ACTIVE':
                a['status'] = 'ENDED'
                a['ended_reason'] = 'COMMITTEE_DISSOLVED'
                touch(a)
    for mt in store.meetings.values():
        if mt['committee_id'] == c['id'] and mt['status'] == 'SCHEDULED':
            mt['status'] = 'CANCELLED'
            touch(mt)
    return envelope(ser_committee(c))


# ---------------------------------------------------------------- appointments
@bp.post('/boardgov/committee-appointments')
def create_appointment():
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    committee_id = v_str(body, 'committee_id')
    member_id = v_str(body, 'board_member_id')
    crole = v_enum(body, 'committee_role', ['CHAIR', 'MEMBER'], required=False,
                   default='MEMBER')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    c = ref_lookup(store.committees, committee_id, 'committee_id', np['id'])
    m = ref_lookup(store.members, member_id, 'board_member_id', np['id'])
    # 7: committee not DISSOLVED
    if c['status'] == 'DISSOLVED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Cannot appoint to a DISSOLVED committee')
    # 14: uniqueness
    if any(a['committee_id'] == c['id'] and a['board_member_id'] == m['id'] and
           a['status'] == 'ACTIVE' for a in store.appointments.values()):
        raise ApiError('ERR_DUPLICATE_APPOINTMENT', 409,
                       'Member already holds an ACTIVE appointment on this committee')
    if crole == 'CHAIR' and any(
            a['committee_id'] == c['id'] and a['status'] == 'ACTIVE' and
            a['committee_role'] == 'CHAIR' for a in store.appointments.values()):
        raise ApiError('ERR_DUPLICATE_COMMITTEE_CHAIR', 409,
                       'Committee already has an ACTIVE CHAIR appointment')
    # 16: composition gates
    if m['status'] != 'ACTIVE':
        raise ApiError('ERR_MEMBER_NOT_ELIGIBLE', 409,
                       'Appointee must be an ACTIVE member')
    if committee_active_count(c['id']) >= c['authorized_size']:
        raise ApiError('ERR_COMMITTEE_FULL', 409,
                       'Committee has reached its authorized_size')
    if c['requires_all_independent'] and not m['is_independent']:
        raise ApiError('ERR_COMMITTEE_NOT_INDEPENDENT', 409,
                       'Appointee must be independent for this committee')
    cfy = current_fiscal_year(np)
    d = disclosure_for(m['id'], cfy)
    if d is None or d['status'] not in ('CLEARED', 'RESTRICTIONS_IMPOSED'):
        raise ApiError('ERR_COI_REVIEW_REQUIRED', 409,
                       'Appointee lacks a reviewed current-fiscal-year disclosure')
    if d['status'] == 'RESTRICTIONS_IMPOSED':
        blocked = set()
        for cat in d['restriction_categories']:
            blocked |= RESTRICTION_MAP.get(cat, set())
        if c['type'] in blocked:
            raise ApiError('ERR_COI_REVIEW_REQUIRED', 409,
                           'Appointee restrictions map onto this committee type')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'committee_id': c['id'],
              'board_member_id': m['id'], 'committee_role': crole,
              'status': 'ACTIVE', 'ended_reason': None})
    store.appointments[e['id']] = e
    if c['status'] == 'DORMANT' and committee_active_count(c['id']) >= c['min_members']:
        c['status'] = 'ACTIVE'
        touch(c)
    return envelope(ser_appointment(e), status=201)


@bp.get('/boardgov/committee-appointments/<rid>')
def get_appointment(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    a = lookup(store.appointments, rid)
    check_org_membership(member, role, a['nonprofit_id'])
    return envelope(ser_appointment(a))


@bp.get('/boardgov/committee-appointments')
def list_appointments():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.appointments.values()),
                          {'nonprofit_id': np_id,
                           'committee_id': request.args.get('committee_id'),
                           'board_member_id': request.args.get('board_member_id'),
                           'status': request.args.get('status')})
    return list_response(items, ser_appointment)


@bp.post('/boardgov/committee-appointments/<rid>/end')
def end_appointment_ep(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    a = lookup(store.appointments, rid)
    check_org_membership(member, role, a['nonprofit_id'])
    if a['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'Appointment is not ACTIVE')
    end_appointment(a, 'MANUAL')
    return envelope(ser_appointment(a))
