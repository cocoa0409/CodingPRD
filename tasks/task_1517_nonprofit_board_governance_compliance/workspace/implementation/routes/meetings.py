"""Meetings, motions, votes."""
from datetime import timedelta

from flask import request

import store
from domain import (BUFFER, MOTION_BASES, MOTION_CATEGORIES, MOTION_THRESHOLDS,
                    VOTE_CHOICES, active_members, adopted_bylaws,
                    committee_active_count, compliance_posture,
                    current_fiscal_year, disclosure_for, motion_tallies,
                    ser_meeting, ser_motion, ser_vote)
from helpers import (ALL_ROLES, ApiError, apply_filters, authn,
                     check_org_membership, envelope, err400, get_body, iso,
                     list_response, lookup, new_entity, qualified_member,
                     ref_lookup, require_role, touch, v_bool, v_dt, v_enum,
                     v_int, v_list, v_str, now_iso)
from . import bp
from .core import _np_or_403_or_422


# ---------------------------------------------------------------- meetings
@bp.post('/boardgov/meetings')
def create_meeting():
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    committee_id = body.get('committee_id')
    if committee_id is not None and not isinstance(committee_id, str):
        raise err400('committee_id must be a string')
    start = v_dt(body, 'scheduled_start')
    duration = v_int(body, 'duration_minutes', min_v=1)
    notice_sent = v_dt(body, 'notice_sent_at', required=False)
    notice_waived = v_bool(body, 'notice_waived', required=False, default=False)
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    if committee_id is not None:
        ref_lookup(store.committees, committee_id, 'committee_id', np['id'])
    new_end = start + timedelta(minutes=duration)
    for mt in store.meetings.values():
        if mt['nonprofit_id'] == np['id'] and mt['committee_id'] == committee_id \
                and mt['status'] != 'CANCELLED':
            m_end = mt['scheduled_start'] + timedelta(minutes=mt['duration_minutes'])
            if start < m_end + BUFFER and mt['scheduled_start'] < new_end + BUFFER:
                raise ApiError('ERR_MEETING_OVERLAP', 409,
                               'Meeting conflicts with an existing meeting of the same scope')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'committee_id': committee_id,
              'scheduled_start': start, 'duration_minutes': duration,
              'notice_sent_at': notice_sent, 'notice_waived': notice_waived,
              'status': 'SCHEDULED', 'attendance': [], 'quorum_base': None,
              'quorum_required': None, 'quorum_met': None, 'minutes_text': None,
              'minutes_recorded_by': None})
    store.meetings[e['id']] = e
    return envelope(ser_meeting(e), status=201)


@bp.get('/boardgov/meetings/<rid>')
def get_meeting(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    return envelope(ser_meeting(mt))


@bp.get('/boardgov/meetings')
def list_meetings():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.meetings.values()),
                          {'nonprofit_id': np_id,
                           'committee_id': request.args.get('committee_id'),
                           'status': request.args.get('status')})
    return list_response(items, ser_meeting)


@bp.post('/boardgov/meetings/<rid>/call_to_order')
def call_to_order(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    attendance = v_list(body, 'attendance')
    for a in attendance:
        if not isinstance(a, str):
            raise err400('attendance entries must be member id strings')
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    # 7: state
    if mt['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only SCHEDULED meetings can be called to order')
    # 9: committee must be ACTIVE for committee meetings
    committee = None
    if mt['committee_id'] is not None:
        committee = store.committees.get(mt['committee_id'])
        if committee is None or committee['status'] != 'ACTIVE':
            raise ApiError('ERR_COMMITTEE_NOT_ACTIVE', 409,
                           'Committee meeting requires an ACTIVE committee')
    # 19: window rules
    t = store.get_clock()
    if t < mt['scheduled_start']:
        raise ApiError('ERR_MEETING_TOO_EARLY', 409,
                       'Cannot call to order before scheduled_start')
    if not mt['notice_waived']:
        ns = mt['notice_sent_at']
        if ns is None or ns > mt['scheduled_start'] - timedelta(days=7):
            raise ApiError('ERR_NOTICE_INSUFFICIENT', 409,
                           'Notice must be sent at least 7 days before the meeting')
    # quorum determination
    np = store.nonprofits.get(mt['nonprofit_id'])
    b = adopted_bylaws(mt['nonprofit_id'])
    if b is None:
        raise ApiError('ERR_BYLAWS_NOT_ADOPTED', 409,
                       'An ADOPTED bylaws is required to determine quorum')
    if committee is None:
        scope_ids = {m['id'] for m in active_members(mt['nonprofit_id'])}
        base = len(scope_ids) if b['quorum_basis'] == 'SEATED' else b['board_size']
    else:
        scope_ids = set()
        for a in store.appointments.values():
            if a['committee_id'] == committee['id'] and a['status'] == 'ACTIVE':
                m = store.members.get(a['board_member_id'])
                if m is not None and m['status'] == 'ACTIVE':
                    scope_ids.add(m['id'])
        base = len(scope_ids) if b['quorum_basis'] == 'SEATED' \
            else committee['authorized_size']
    present = len(set(attendance) & scope_ids)
    required = (b['quorum_pct'] * base + 99) // 100  # ceil
    met = present >= required
    # 21: aggregate threshold
    if not met:
        raise ApiError('ERR_QUORUM_NOT_MET', 409,
                       f'Present {present} below quorum_required {required}')
    mt['attendance'] = list(attendance)
    mt['quorum_base'] = base
    mt['quorum_required'] = required
    mt['quorum_met'] = True
    mt['status'] = 'IN_SESSION'
    touch(mt)
    return envelope(ser_meeting(mt))


@bp.post('/boardgov/meetings/<rid>/adjourn')
def adjourn_meeting(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    if mt['status'] != 'IN_SESSION':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only IN_SESSION meetings can be adjourned')
    mt['status'] = 'ADJOURNED'
    touch(mt)
    for mo in store.motions.values():
        if mo['meeting_id'] == mt['id'] and mo['status'] == 'VOTING_OPEN':
            mo['status'] = 'TABLED'
            touch(mo)
    return envelope(ser_meeting(mt))


@bp.post('/boardgov/meetings/<rid>/cancel')
def cancel_meeting(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'BoardChair'])
    member = qualified_member(uid, role)
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    if mt['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only SCHEDULED meetings can be cancelled')
    mt['status'] = 'CANCELLED'
    touch(mt)
    return envelope(ser_meeting(mt))


@bp.post('/boardgov/meetings/<rid>/minutes')
def record_minutes(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin'])
    body = get_body()
    expected = v_int(body, 'expected_meeting_version')
    text = v_str(body, 'minutes_text')
    mt = lookup(store.meetings, rid)
    if mt['status'] not in ('ADJOURNED', 'MINUTES_DRAFTED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Minutes can be recorded only for ADJOURNED or MINUTES_DRAFTED meetings')
    if expected != mt['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_meeting_version does not match the current version')
    mt['minutes_text'] = text
    mt['minutes_recorded_by'] = uid
    mt['status'] = 'MINUTES_DRAFTED'
    touch(mt)
    return envelope(ser_meeting(mt))


def _validate_approval_meeting(mt, other_id, field):
    other = store.meetings.get(other_id) if isinstance(other_id, str) else None
    if other is None or other['id'] == mt['id'] or \
            other['nonprofit_id'] != mt['nonprofit_id'] or \
            other['committee_id'] != mt['committee_id'] or \
            other['status'] != 'IN_SESSION':
        raise ApiError('ERR_MINUTES_APPROVAL_MEETING_INVALID', 409,
                       f'{field} must reference a different same-scope meeting that is IN_SESSION')


@bp.post('/boardgov/meetings/<rid>/approve_minutes')
def approve_minutes(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    approving_id = v_str(body, 'approving_meeting_id')
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    if mt['status'] != 'MINUTES_DRAFTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only MINUTES_DRAFTED meetings can be approved')
    if uid == mt['minutes_recorded_by']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 409,
                       'The minutes recorder cannot approve their own minutes')
    _validate_approval_meeting(mt, approving_id, 'approving_meeting_id')
    mt['status'] = 'MINUTES_APPROVED'
    touch(mt)
    return envelope(ser_meeting(mt))


@bp.post('/boardgov/meetings/<rid>/reject_minutes')
def reject_minutes(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    rejecting_id = v_str(body, 'rejecting_meeting_id')
    mt = lookup(store.meetings, rid)
    check_org_membership(member, role, mt['nonprofit_id'])
    if mt['status'] != 'MINUTES_DRAFTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only MINUTES_DRAFTED meetings can be rejected')
    _validate_approval_meeting(mt, rejecting_id, 'rejecting_meeting_id')
    mt['status'] = 'ADJOURNED'
    mt['minutes_text'] = None
    mt['minutes_recorded_by'] = None
    touch(mt)
    return envelope(ser_meeting(mt))


# ---------------------------------------------------------------- motions
@bp.post('/boardgov/motions')
def create_motion():
    uid, role = authn()
    require_role(role, ['BoardChair', 'BoardDirector'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    meeting_id = v_str(body, 'meeting_id')
    title = v_str(body, 'title')
    category = v_enum(body, 'category', MOTION_CATEGORIES)
    threshold = v_enum(body, 'threshold', MOTION_THRESHOLDS, required=False,
                       default='SIMPLE_MAJORITY')
    basis = v_enum(body, 'threshold_basis', MOTION_BASES, required=False,
                   default='PRESENT_AND_VOTING')
    amendment_id = body.get('bylaws_amendment_id')
    policy_title = body.get('policy_title')
    if category == 'BYLAWS':
        if not amendment_id or not isinstance(amendment_id, str):
            raise err400('bylaws_amendment_id is required for BYLAWS motions')
    if category == 'POLICY':
        if not policy_title or not isinstance(policy_title, str) or not policy_title.strip():
            raise err400('policy_title is required for POLICY motions')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    mt = ref_lookup(store.meetings, meeting_id, 'meeting_id', np['id'])
    amendment = None
    if amendment_id is not None:
        amendment = ref_lookup(store.amendments, amendment_id,
                               'bylaws_amendment_id', np['id'])
    # 9: cross-entity gates
    if category == 'BYLAWS':
        if amendment['status'] != 'PROPOSED':
            raise ApiError('ERR_AMENDMENT_NOT_PROPOSED', 409,
                           'A BYLAWS motion requires a PROPOSED amendment')
        if any(mo.get('bylaws_amendment_id') == amendment['id'] and
               mo['status'] in ('INTRODUCED', 'VOTING_OPEN', 'TABLED')
               for mo in store.motions.values()):
            raise ApiError('ERR_AMENDMENT_HAS_OPEN_MOTION', 409,
                           'A non-terminal motion already references this amendment')
    # 12: compliance posture gate
    if category == 'FUNDRAISING' and compliance_posture(np) == 'NON_COMPLIANT':
        raise ApiError('ERR_NONCOMPLIANT_POSTURE_BLOCKS', 409,
                       'FUNDRAISING motions are blocked while NON_COMPLIANT')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'meeting_id': mt['id'],
              'bylaws_amendment_id': amendment['id'] if amendment else None,
              'policy_title': policy_title if category == 'POLICY' else
              (policy_title if isinstance(policy_title, str) else None),
              'title': title, 'category': category, 'threshold': threshold,
              'threshold_basis': basis, 'required_votes': None,
              'status': 'INTRODUCED'})
    store.motions[e['id']] = e
    if amendment is not None:
        amendment['motion_id'] = e['id']
        touch(amendment)
    return envelope(ser_motion(e), status=201)


@bp.get('/boardgov/motions/<rid>')
def get_motion(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    mo = lookup(store.motions, rid)
    check_org_membership(member, role, mo['nonprofit_id'])
    return envelope(ser_motion(mo))


@bp.get('/boardgov/motions')
def list_motions():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.motions.values()),
                          {'nonprofit_id': np_id,
                           'meeting_id': request.args.get('meeting_id'),
                           'category': request.args.get('category'),
                           'status': request.args.get('status'),
                           'bylaws_amendment_id': request.args.get('bylaws_amendment_id')})
    return list_response(items, ser_motion)


def _motion_for_chair(rid, uid, role):
    member = qualified_member(uid, role)
    mo = lookup(store.motions, rid)
    check_org_membership(member, role, mo['nonprofit_id'])
    return mo


def _meeting_in_session(mo):
    mt = store.meetings.get(mo['meeting_id'])
    if mt is None or mt['status'] != 'IN_SESSION':
        raise ApiError('ERR_MEETING_NOT_IN_SESSION', 409,
                       "The motion's meeting is not IN_SESSION")


@bp.post('/boardgov/motions/<rid>/open_voting')
def open_voting(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    mo = _motion_for_chair(rid, uid, role)
    if mo['status'] != 'INTRODUCED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only INTRODUCED motions can open voting')
    _meeting_in_session(mo)
    mo['status'] = 'VOTING_OPEN'
    touch(mo)
    return envelope(ser_motion(mo))


@bp.post('/boardgov/motions/<rid>/close_voting')
def close_voting(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    mo = _motion_for_chair(rid, uid, role)
    if mo['status'] != 'VOTING_OPEN':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only VOTING_OPEN motions can be closed')
    _meeting_in_session(mo)
    np = store.nonprofits.get(mo['nonprofit_id'])
    F, N, A, R = motion_tallies(mo['id'])
    if mo['category'] == 'BYLAWS':
        # amendment_adoption_threshold: basis forced FULL_BOARD-flavored
        amendment = store.amendments.get(mo['bylaws_amendment_id'])
        b = adopted_bylaws(mo['nonprofit_id'])
        if b is None and amendment is not None:
            b = store.bylaws.get(amendment['base_bylaws_id'])
        active_count = len(active_members(mo['nonprofit_id']))
        depleted_line = (3 * b['board_size'] + 3) // 4  # ceil(0.75 * board_size)
        basis = active_count if active_count >= depleted_line else b['board_size']
        required = max(2, (b['amendment_threshold_pct'] * basis + 99) // 100)
        passed = F >= required
    else:
        if mo['threshold_basis'] == 'PRESENT_AND_VOTING':
            basis = F + N
        elif mo['threshold_basis'] == 'FULL_QUORUM':
            mt = store.meetings.get(mo['meeting_id'])
            basis = mt['quorum_required'] if mt and mt['quorum_required'] is not None else 0
        else:  # FULL_BOARD
            basis = len(active_members(mo['nonprofit_id'])) - R
        if mo['threshold'] == 'SIMPLE_MAJORITY':
            required = basis // 2 + 1
        elif mo['threshold'] == 'TWO_THIRDS':
            required = (2 * basis + 2) // 3  # ceil(2/3 * basis)
        else:  # UNANIMOUS
            required = basis
        passed = F >= required
        if mo['threshold'] == 'UNANIMOUS':
            passed = passed and N == 0 and A == 0
    mo['required_votes'] = required
    mo['status'] = 'PASSED' if passed else 'FAILED'
    touch(mo)
    # passage cascades
    if mo['category'] == 'BYLAWS':
        amendment = store.amendments.get(mo['bylaws_amendment_id'])
        if amendment is not None:
            if passed:
                amendment['status'] = 'ADOPTED'
                touch(amendment)
                base = store.bylaws.get(amendment['base_bylaws_id'])
                if base is not None:
                    succ = new_entity()
                    fields = {k: base[k] for k in
                              ('quorum_pct', 'quorum_basis', 'amendment_threshold_pct',
                               'term_length_years', 'max_consecutive_terms',
                               'term_cooloff_years', 'board_size')}
                    fields.update(amendment['proposed_fields'])
                    succ.update({'nonprofit_id': base['nonprofit_id'],
                                 'version_no': base['version_no'] + 1,
                                 'status': 'ADOPTED',
                                 'adopted_at': store.get_clock()})
                    succ.update(fields)
                    store.bylaws[succ['id']] = succ
                    if base['status'] == 'ADOPTED':
                        base['status'] = 'SUPERSEDED'
                        touch(base)
                touch(np)
            else:
                amendment['status'] = 'DEFEATED'
                amendment['motion_id'] = None
                touch(amendment)
    elif mo['category'] == 'POLICY' and passed:
        np['adopted_policies'].append({
            'policy_title': mo['policy_title'], 'motion_id': mo['id'],
            'adopted_at': now_iso()})
        touch(np)
    return envelope(ser_motion(mo))


@bp.post('/boardgov/motions/<rid>/table')
def table_motion(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    mo = _motion_for_chair(rid, uid, role)
    if mo['status'] not in ('INTRODUCED', 'VOTING_OPEN'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only INTRODUCED or VOTING_OPEN motions can be tabled')
    mo['status'] = 'TABLED'
    touch(mo)
    return envelope(ser_motion(mo))


@bp.post('/boardgov/motions/<rid>/resume')
def resume_motion(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    mo = _motion_for_chair(rid, uid, role)
    if mo['status'] != 'TABLED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only TABLED motions can be resumed')
    _meeting_in_session(mo)
    mo['status'] = 'VOTING_OPEN'
    touch(mo)
    return envelope(ser_motion(mo))


@bp.post('/boardgov/motions/<rid>/withdraw')
def withdraw_motion(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    mo = _motion_for_chair(rid, uid, role)
    if mo['status'] not in ('INTRODUCED', 'TABLED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only INTRODUCED or TABLED motions can be withdrawn')
    mo['status'] = 'WITHDRAWN'
    touch(mo)
    if mo['category'] == 'BYLAWS' and mo['bylaws_amendment_id']:
        amendment = store.amendments.get(mo['bylaws_amendment_id'])
        if amendment is not None and amendment['motion_id'] == mo['id']:
            amendment['motion_id'] = None
            touch(amendment)
    return envelope(ser_motion(mo))


# ---------------------------------------------------------------- votes
@bp.post('/boardgov/votes')
def cast_vote():
    uid, role = authn()
    require_role(role, ['BoardDirector', 'BoardChair', 'Treasurer'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    motion_id = v_str(body, 'motion_id')
    member_id = v_str(body, 'board_member_id')
    choice = v_enum(body, 'choice', VOTE_CHOICES)
    # 4: self-service ownership
    if member_id != uid:
        raise ApiError('ERR_FORBIDDEN_FOR_ROLE', 403,
                       'A director votes only as themself')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    mo = ref_lookup(store.motions, motion_id, 'motion_id', np['id'])
    ref_lookup(store.members, member_id, 'board_member_id', np['id'])
    # 9: motion open, meeting in session, voter eligible
    if mo['status'] != 'VOTING_OPEN':
        raise ApiError('ERR_MOTION_NOT_OPEN', 409,
                       'Votes can be cast only while the motion is VOTING_OPEN')
    _meeting_in_session(mo)
    mt = store.meetings[mo['meeting_id']]
    eligible = member['status'] == 'ACTIVE' and uid in mt['attendance']
    if eligible and mt['committee_id'] is not None:
        eligible = any(a['committee_id'] == mt['committee_id'] and
                       a['board_member_id'] == uid and a['status'] == 'ACTIVE'
                       for a in store.appointments.values())
    if not eligible:
        raise ApiError('ERR_VOTER_NOT_ELIGIBLE', 409,
                       'Voter is not an eligible attendee of this meeting')
    # 11: recusal enforcement
    cfy = current_fiscal_year(np)
    d = disclosure_for(uid, cfy)
    if d is not None and d['status'] == 'RESTRICTIONS_IMPOSED' and \
            mo['category'] in d['restriction_categories'] and choice != 'RECUSED':
        raise ApiError('ERR_MEMBER_RECUSED', 409,
                       'A recused member must cast RECUSED on this category')
    # 14: one vote per (motion, member)
    if any(v['motion_id'] == mo['id'] and v['board_member_id'] == uid
           for v in store.votes.values()):
        raise ApiError('ERR_DUPLICATE_VOTE', 409,
                       'Member has already voted on this motion')
    e = {'id': new_entity()['id'], 'created_at': now_iso(),
         '_seq': store.next_seq(),
         'nonprofit_id': np['id'], 'motion_id': mo['id'],
         'board_member_id': uid, 'choice': choice}
    store.votes[e['id']] = e
    return envelope(ser_vote(e), status=201)


@bp.get('/boardgov/votes/<rid>')
def get_vote(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    v = lookup(store.votes, rid)
    check_org_membership(member, role, v['nonprofit_id'])
    return envelope(ser_vote(v))


@bp.get('/boardgov/votes')
def list_votes():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.votes.values()),
                          {'nonprofit_id': np_id,
                           'motion_id': request.args.get('motion_id'),
                           'board_member_id': request.args.get('board_member_id')})
    return list_response(items, ser_vote)
