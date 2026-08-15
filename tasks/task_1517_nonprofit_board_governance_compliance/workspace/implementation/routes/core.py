"""Clock, nonprofits, bylaws, amendments, board members, board terms."""
from flask import request

import store
from domain import (BYLAWS_KNOBS, OFFICER_ROLES, SKILL_TAGS, active_members,
                    adopted_bylaws, compliance_sweep, member_chain,
                    member_departure, open_seats, ser_amendment, ser_bylaws,
                    ser_member, ser_nonprofit, ser_term)
from helpers import (ALL_ROLES, ApiError, add_years, apply_filters, authn,
                     check_org_membership, envelope, err400, get_body, iso,
                     list_response, lookup, new_entity, qualified_member,
                     ref_lookup, require_role, touch, v_bool, v_dt, v_enum,
                     v_int, v_list, v_str, now_iso)
from . import bp


def _np_or_403_or_422(np_id, role):
    """Resolve a body nonprofit_id. Entity-backed callers cannot act on a
    nonexistent org (403 identity); opaque callers get 422."""
    np = store.nonprofits.get(np_id)
    if np is None:
        if role in ('BoardChair', 'BoardDirector', 'Treasurer'):
            raise ApiError('ERR_IDENTITY_NOT_QUALIFIED', 403,
                           'X-User-ID is not an ACTIVE BoardMember of the nonprofit being acted on')
        raise ApiError('ERR_REFERENCED_NOT_FOUND', 422,
                       'nonprofit_id does not reference an existing nonprofit')
    return np


def _validate_bylaws_knobs(pf):
    if not isinstance(pf, dict) or len(pf) == 0:
        raise err400('proposed_fields must be a non-empty object')
    for k, v in pf.items():
        if k not in BYLAWS_KNOBS:
            raise err400(f'proposed_fields.{k} is not a bylaws field')
        if k == 'quorum_pct':
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 100:
                raise err400('quorum_pct must be an integer 1..100')
        elif k == 'quorum_basis':
            if v not in ('SEATED', 'AUTHORIZED'):
                raise err400('quorum_basis must be SEATED or AUTHORIZED')
        elif k == 'amendment_threshold_pct':
            if not isinstance(v, int) or isinstance(v, bool) or not 51 <= v <= 100:
                raise err400('amendment_threshold_pct must be an integer 51..100')
        elif k == 'term_length_years':
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 6:
                raise err400('term_length_years must be an integer 1..6')
        elif k == 'max_consecutive_terms':
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise err400('max_consecutive_terms must be an integer >= 1')
        elif k == 'term_cooloff_years':
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise err400('term_cooloff_years must be an integer >= 0')
        elif k == 'board_size':
            if not isinstance(v, int) or isinstance(v, bool) or v < 3:
                raise err400('board_size must be an integer >= 3')


def _read_bylaws_knobs(body):
    return {
        'quorum_pct': v_int(body, 'quorum_pct', min_v=1, max_v=100),
        'quorum_basis': v_enum(body, 'quorum_basis', ['SEATED', 'AUTHORIZED']),
        'amendment_threshold_pct': v_int(body, 'amendment_threshold_pct', min_v=51, max_v=100),
        'term_length_years': v_int(body, 'term_length_years', min_v=1, max_v=6),
        'max_consecutive_terms': v_int(body, 'max_consecutive_terms', min_v=1),
        'term_cooloff_years': v_int(body, 'term_cooloff_years', min_v=0),
        'board_size': v_int(body, 'board_size', min_v=3),
    }


# ---------------------------------------------------------------- clock
@bp.post('/boardgov/_clock/set_current_utc')
def set_current_utc():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    to = v_dt(body, 'to_iso8601')
    store.set_clock(to)
    return envelope({'current_utc': iso(to)})


# ---------------------------------------------------------------- nonprofits
@bp.post('/boardgov/nonprofits')
def create_nonprofit():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    name = v_str(body, 'name')
    ein = v_str(body, 'ein')
    state = v_str(body, 'state_of_incorporation')
    fym = v_int(body, 'fiscal_year_end_month', min_v=1, max_v=12)
    receipts = v_int(body, 'annual_gross_receipts_cents', min_v=0)
    if any(n['ein'] == ein for n in store.nonprofits.values()):
        raise ApiError('ERR_DUPLICATE_EIN', 409, 'EIN already registered')
    e = new_entity()
    e.update({'name': name, 'ein': ein, 'state_of_incorporation': state,
              'fiscal_year_end_month': fym,
              'annual_gross_receipts_cents': receipts,
              'adopted_policies': []})
    store.nonprofits[e['id']] = e
    return envelope(ser_nonprofit(e), status=201)


@bp.get('/boardgov/nonprofits/<rid>')
def get_nonprofit(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np = lookup(store.nonprofits, rid)
    check_org_membership(member, role, np['id'])
    return envelope(ser_nonprofit(np))


@bp.patch('/boardgov/nonprofits/<rid>')
def patch_nonprofit(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    expected = v_int(body, 'expected_nonprofit_version')
    name = v_str(body, 'name', required=False)
    state = v_str(body, 'state_of_incorporation', required=False)
    fym = v_int(body, 'fiscal_year_end_month', required=False, min_v=1, max_v=12)
    receipts = v_int(body, 'annual_gross_receipts_cents', required=False, min_v=0)
    np = lookup(store.nonprofits, rid)
    if expected != np['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_nonprofit_version does not match the current version')
    if name is not None:
        np['name'] = name
    if state is not None:
        np['state_of_incorporation'] = state
    if fym is not None:
        np['fiscal_year_end_month'] = fym
    if receipts is not None:
        np['annual_gross_receipts_cents'] = receipts
    touch(np)
    return envelope(ser_nonprofit(np))


@bp.post('/boardgov/nonprofits/<rid>/compliance_sweep')
def sweep(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'ComplianceOfficer'])
    np = lookup(store.nonprofits, rid)
    compliance_sweep(np)
    return envelope(ser_nonprofit(np))


@bp.get('/boardgov/nonprofits/<rid>/recruitment-matrix')
def recruitment_matrix(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np = lookup(store.nonprofits, rid)
    check_org_membership(member, role, np['id'])
    act = active_members(np['id'])
    by_skill = {s: sum(1 for m in act if s in m['skill_tags']) for s in SKILL_TAGS}
    uncovered = [s for s in SKILL_TAGS if by_skill[s] == 0]
    b = adopted_bylaws(np['id'])
    board_size = b['board_size'] if b else None
    seats = open_seats(np['id'])
    return envelope({'by_skill': by_skill, 'uncovered_skills': uncovered,
                     'active_members': len(act), 'board_size': board_size,
                     'open_seats': seats})


# ---------------------------------------------------------------- bylaws
@bp.post('/boardgov/bylaws')
def create_bylaws():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    knobs = _read_bylaws_knobs(body)
    np = ref_lookup(store.nonprofits, np_id, 'nonprofit_id')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'version_no': 1, 'status': 'DRAFT',
              'adopted_at': None})
    e.update(knobs)
    store.bylaws[e['id']] = e
    return envelope(ser_bylaws(e), status=201)


@bp.get('/boardgov/bylaws/<rid>')
def get_bylaws(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    b = lookup(store.bylaws, rid)
    check_org_membership(member, role, b['nonprofit_id'])
    return envelope(ser_bylaws(b))


@bp.get('/boardgov/bylaws')
def list_bylaws():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.bylaws.values()),
                          {'nonprofit_id': np_id,
                           'status': request.args.get('status')})
    return list_response(items, ser_bylaws)


@bp.post('/boardgov/bylaws/<rid>/adopt')
def adopt_bylaws(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    b = lookup(store.bylaws, rid)
    if b['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DRAFT bylaws can be adopted')
    if adopted_bylaws(b['nonprofit_id']) is not None:
        raise ApiError('ERR_BYLAWS_ALREADY_ADOPTED', 409,
                       'Another bylaws document is already ADOPTED for this nonprofit')
    b['status'] = 'ADOPTED'
    b['adopted_at'] = store.get_clock()
    touch(b)
    return envelope(ser_bylaws(b))


@bp.post('/boardgov/bylaws/<rid>/discard')
def discard_bylaws(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    b = lookup(store.bylaws, rid)
    if b['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DRAFT bylaws can be discarded')
    b['status'] = 'DISCARDED'
    touch(b)
    return envelope(ser_bylaws(b))


# ---------------------------------------------------------------- amendments
@bp.post('/boardgov/bylaws-amendments')
def create_amendment():
    uid, role = authn()
    require_role(role, ['BoardChair', 'BoardDirector', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    base_id = v_str(body, 'base_bylaws_id')
    title = v_str(body, 'title')
    pf = body.get('proposed_fields')
    _validate_bylaws_knobs(pf)
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    base = ref_lookup(store.bylaws, base_id, 'base_bylaws_id', np['id'])
    if base['status'] != 'ADOPTED':
        raise ApiError('ERR_BYLAWS_NOT_ADOPTED', 409,
                       'base_bylaws_id must reference an ADOPTED bylaws')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'base_bylaws_id': base['id'],
              'title': title, 'proposed_fields': dict(pf), 'motion_id': None,
              'status': 'DRAFT'})
    store.amendments[e['id']] = e
    return envelope(ser_amendment(e), status=201)


@bp.get('/boardgov/bylaws-amendments/<rid>')
def get_amendment(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    a = lookup(store.amendments, rid)
    check_org_membership(member, role, a['nonprofit_id'])
    return envelope(ser_amendment(a))


@bp.get('/boardgov/bylaws-amendments')
def list_amendments():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.amendments.values()),
                          {'nonprofit_id': np_id,
                           'base_bylaws_id': request.args.get('base_bylaws_id'),
                           'status': request.args.get('status'),
                           'motion_id': request.args.get('motion_id')})
    return list_response(items, ser_amendment)


def _get_amendment_for_chair(rid, uid, role):
    member = qualified_member(uid, role)
    a = lookup(store.amendments, rid)
    check_org_membership(member, role, a['nonprofit_id'])
    return a


@bp.post('/boardgov/bylaws-amendments/<rid>/propose')
def propose_amendment(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    a = _get_amendment_for_chair(rid, uid, role)
    if a['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DRAFT amendments can be proposed')
    base = store.bylaws.get(a['base_bylaws_id'])
    if base is None or base['status'] != 'ADOPTED':
        raise ApiError('ERR_BYLAWS_NOT_ADOPTED', 409,
                       'base bylaws must be ADOPTED')
    if not a['proposed_fields']:
        raise err400('proposed_fields must be non-empty')
    a['status'] = 'PROPOSED'
    touch(a)
    return envelope(ser_amendment(a))


@bp.post('/boardgov/bylaws-amendments/<rid>/revise')
def revise_amendment(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    a = _get_amendment_for_chair(rid, uid, role)
    if a['status'] != 'DEFEATED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DEFEATED amendments can be revised')
    a['status'] = 'DRAFT'
    touch(a)
    return envelope(ser_amendment(a))


@bp.post('/boardgov/bylaws-amendments/<rid>/withdraw')
def withdraw_amendment(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    a = _get_amendment_for_chair(rid, uid, role)
    if a['status'] not in ('DRAFT', 'PROPOSED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only DRAFT or PROPOSED amendments can be withdrawn')
    if a['status'] == 'PROPOSED':
        open_ref = any(mo.get('bylaws_amendment_id') == a['id'] and
                       mo['status'] in ('INTRODUCED', 'VOTING_OPEN', 'TABLED')
                       for mo in store.motions.values())
        if open_ref:
            raise ApiError('ERR_AMENDMENT_HAS_OPEN_MOTION', 409,
                           'A non-terminal motion references this amendment')
    a['status'] = 'WITHDRAWN'
    touch(a)
    return envelope(ser_amendment(a))


# ---------------------------------------------------------------- board members
@bp.post('/boardgov/board-members')
def create_member():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    full_name = v_str(body, 'full_name')
    email = v_str(body, 'email')
    skill_tags = v_list(body, 'skill_tags')
    for s in skill_tags:
        if s not in SKILL_TAGS:
            raise err400(f'skill_tags contains unknown skill {s!r}')
    officer = v_enum(body, 'officer_role', OFFICER_ROLES, required=False, default='NONE')
    indep = v_bool(body, 'is_independent', required=False, default=True)
    np = ref_lookup(store.nonprofits, np_id, 'nonprofit_id')
    if any(m['nonprofit_id'] == np['id'] and m['email'] == email
           for m in store.members.values()):
        raise ApiError('ERR_DUPLICATE_MEMBER_EMAIL', 409,
                       'Email already used by another member of the nonprofit')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'full_name': full_name, 'email': email,
              'skill_tags': list(skill_tags), 'officer_role': officer,
              'is_independent': indep, 'status': 'PROPOSED'})
    store.members[e['id']] = e
    return envelope(ser_member(e), status=201)


@bp.get('/boardgov/board-members/<rid>')
def get_member(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    m = lookup(store.members, rid)
    check_org_membership(member, role, m['nonprofit_id'])
    return envelope(ser_member(m))


@bp.get('/boardgov/board-members')
def list_members():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.members.values()),
                          {'nonprofit_id': np_id,
                           'status': request.args.get('status')})
    skill = request.args.get('skill')
    if skill is not None:
        items = [m for m in items if skill in m['skill_tags']]
    return list_response(items, ser_member)


@bp.patch('/boardgov/board-members/<rid>')
def patch_member(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    full_name = v_str(body, 'full_name', required=False)
    skill_tags = v_list(body, 'skill_tags', required=False)
    if skill_tags is not None:
        for s in skill_tags:
            if s not in SKILL_TAGS:
                raise err400(f'skill_tags contains unknown skill {s!r}')
    officer = v_enum(body, 'officer_role', OFFICER_ROLES, required=False)
    indep = v_bool(body, 'is_independent', required=False)
    m = lookup(store.members, rid)
    if full_name is not None:
        m['full_name'] = full_name
    if skill_tags is not None:
        m['skill_tags'] = list(skill_tags)
    if officer is not None:
        m['officer_role'] = officer
    if indep is not None:
        m['is_independent'] = indep
    touch(m)
    return envelope(ser_member(m))


@bp.post('/boardgov/board-members/<rid>/resign')
def resign_member(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'BoardChair', 'BoardDirector', 'Treasurer'])
    member = qualified_member(uid, role)
    # Partial self-service: entity-backed directors/treasurers resign only
    # themselves; GovernanceAdmin/BoardChair may resign anyone.
    if role in ('BoardDirector', 'Treasurer') and uid != rid:
        raise ApiError('ERR_FORBIDDEN_FOR_ROLE', 403,
                       'A director may resign only for themself')
    m = lookup(store.members, rid)
    check_org_membership(member, role, m['nonprofit_id'])
    if m['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only ACTIVE members can resign')
    member_departure(m, 'RESIGNED', 'RESIGNED')
    return envelope(ser_member(m))


@bp.post('/boardgov/board-members/<rid>/remove')
def remove_member(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    reason = v_str(body, 'reason')
    m = lookup(store.members, rid)
    check_org_membership(member, role, m['nonprofit_id'])
    if m['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only ACTIVE members can be removed')
    member_departure(m, 'REMOVED', 'REMOVED')
    return envelope(ser_member(m))


# ---------------------------------------------------------------- board terms
@bp.post('/boardgov/board-terms')
def create_term():
    uid, role = authn()
    require_role(role, ['BoardChair', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    member_id = v_str(body, 'board_member_id')
    start = v_dt(body, 'start_date')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    m = ref_lookup(store.members, member_id, 'board_member_id', np['id'])
    # 9: adopted bylaws required
    b = adopted_bylaws(np['id'])
    if b is None:
        raise ApiError('ERR_BYLAWS_NOT_ADOPTED', 409,
                       'An ADOPTED bylaws is required for election')
    # 15: eligibility — status, term-limit chain, seat availability
    if m['status'] not in ('PROPOSED', 'PAST', 'TERM_LIMITED_OUT', 'ACTIVE'):
        raise ApiError('ERR_MEMBER_NOT_ELIGIBLE', 409,
                       'RESIGNED or REMOVED members cannot be elected')
    chain = member_chain(m['id'])
    chain_len = len(chain)
    if chain_len >= b['max_consecutive_terms']:
        chain_end = chain[-1]['end_date']
        if start < add_years(chain_end, b['term_cooloff_years']):
            raise ApiError('ERR_TERM_LIMIT_EXCEEDED', 409,
                           'Consecutive-term limit reached and cool-off has not elapsed')
    if m['status'] != 'ACTIVE' and open_seats(np['id']) < 1:
        raise ApiError('ERR_NO_SEATS_AVAILABLE', 409, 'No open board seats')
    # 18: half-open overlap vs non-VACATED terms
    end = add_years(start, b['term_length_years'])
    for t in store.terms.values():
        if t['board_member_id'] == m['id'] and t['status'] != 'VACATED':
            if start < t['end_date'] and t['start_date'] < end:
                raise ApiError('ERR_TERM_OVERLAP', 409,
                               'Term overlaps an existing non-VACATED term')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'board_member_id': m['id'],
              'bylaws_id': b['id'], 'start_date': start, 'end_date': end,
              'status': 'SCHEDULED' if start > store.get_clock() else 'ACTIVE'})
    store.terms[e['id']] = e
    if m['status'] != 'ACTIVE':
        m['status'] = 'ACTIVE'
        touch(m)
    return envelope(ser_term(e), status=201)


@bp.get('/boardgov/board-terms/<rid>')
def get_term(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    t = lookup(store.terms, rid)
    check_org_membership(member, role, t['nonprofit_id'])
    return envelope(ser_term(t))


@bp.get('/boardgov/board-terms')
def list_terms():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.terms.values()),
                          {'nonprofit_id': np_id,
                           'board_member_id': request.args.get('board_member_id'),
                           'status': request.args.get('status'),
                           'bylaws_id': request.args.get('bylaws_id')})
    return list_response(items, ser_term)
