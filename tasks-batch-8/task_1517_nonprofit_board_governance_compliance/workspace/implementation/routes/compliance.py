"""COI disclosures, executive evaluations, succession plans, Form 990 filings,
state registrations, insurance policies."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import store
from domain import (EVAL_DIMENSIONS, EVAL_WEIGHTS, POLICY_TYPES, READINESS,
                    RESTRICTION_MAP, TARGET_ROLES, active_members,
                    adopted_bylaws, coverage_floor, current_fiscal_year,
                    disclosure_for, filing_due_date, renewal_fee,
                    ser_disclosure, ser_evaluation, ser_filing, ser_policy,
                    ser_registration, ser_succession)
from helpers import (ALL_ROLES, ApiError, add_months, apply_filters, authn,
                     check_org_membership, envelope, err400, get_body,
                     list_response, lookup, new_entity, qualified_member,
                     ref_lookup, require_role, touch, v_bool, v_dt, v_enum,
                     v_int, v_list, v_str)
from . import bp
from .core import _np_or_403_or_422

REVIEW_ROLES = ['BoardChair', 'BoardDirector', 'Treasurer']


# ---------------------------------------------------------------- COI disclosures
@bp.post('/boardgov/coi-disclosures')
def create_disclosure():
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    member_id = v_str(body, 'board_member_id')
    fy = v_int(body, 'fiscal_year')
    answers = v_list(body, 'answers', non_empty=True)
    for a in answers:
        if not isinstance(a, dict) or not isinstance(a.get('question_key'), str) \
                or not a.get('question_key') or \
                not isinstance(a.get('answer'), bool):
            raise err400('answers entries must have question_key (string) and answer (boolean)')
    # 4: self-service ownership
    if member_id != uid:
        raise ApiError('ERR_FORBIDDEN_FOR_ROLE', 403,
                       'A director discloses only as themself')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    ref_lookup(store.members, member_id, 'board_member_id', np['id'])
    if disclosure_for(member_id, fy) is not None:
        raise ApiError('ERR_DUPLICATE_DISCLOSURE', 409,
                       'Member already has a disclosure for this fiscal_year')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'board_member_id': member_id,
              'fiscal_year': fy, 'answers': list(answers),
              'has_conflict': any(a['answer'] for a in answers),
              'status': 'FILED', 'reviewer_member_id': None,
              'restriction_categories': [], 'filed_at': store.get_clock()})
    store.disclosures[e['id']] = e
    return envelope(ser_disclosure(e), status=201)


@bp.get('/boardgov/coi-disclosures/<rid>')
def get_disclosure(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    d = lookup(store.disclosures, rid)
    check_org_membership(member, role, d['nonprofit_id'])
    return envelope(ser_disclosure(d))


@bp.get('/boardgov/coi-disclosures')
def list_disclosures():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.disclosures.values()),
                          {'nonprofit_id': np_id,
                           'board_member_id': request.args.get('board_member_id'),
                           'fiscal_year': request.args.get('fiscal_year'),
                           'status': request.args.get('status'),
                           'reviewer_member_id': request.args.get('reviewer_member_id')})
    return list_response(items, ser_disclosure)


@bp.post('/boardgov/coi-disclosures/<rid>/start_review')
def start_review(rid):
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    d = lookup(store.disclosures, rid)
    check_org_membership(member, role, d['nonprofit_id'])
    if d['status'] != 'FILED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only FILED disclosures can enter review')
    # 10: segregation of duties
    if uid == d['board_member_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 409,
                       'The reviewer may not be the filer')
    # 13: reviewer qualification + compliance
    if member is None or member['status'] != 'ACTIVE' or \
            member['nonprofit_id'] != d['nonprofit_id']:
        raise ApiError('ERR_REVIEWER_NOT_QUALIFIED', 409,
                       'Reviewer must be an ACTIVE member of the same nonprofit')
    own = disclosure_for(uid, d['fiscal_year'])
    if own is None:
        raise ApiError('ERR_REVIEWER_NOT_COMPLIANT', 409,
                       'Reviewer has not filed their own disclosure for this fiscal year')
    d['status'] = 'UNDER_REVIEW'
    d['reviewer_member_id'] = uid
    touch(d)
    return envelope(ser_disclosure(d))


@bp.post('/boardgov/coi-disclosures/<rid>/clear')
def clear_disclosure(rid):
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    d = lookup(store.disclosures, rid)
    check_org_membership(member, role, d['nonprofit_id'])
    if d['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only UNDER_REVIEW disclosures can be cleared')
    if uid != d['reviewer_member_id']:
        raise ApiError('ERR_REVIEWER_MISMATCH', 409,
                       'Only the assigned reviewer may clear this disclosure')
    d['status'] = 'CLEARED'
    touch(d)
    return envelope(ser_disclosure(d))


@bp.post('/boardgov/coi-disclosures/<rid>/impose_restrictions')
def impose_restrictions(rid):
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    body = get_body()
    cats = v_list(body, 'restriction_categories', non_empty=True)
    for c in cats:
        if not isinstance(c, str) or not c:
            raise err400('restriction_categories entries must be strings')
    d = lookup(store.disclosures, rid)
    check_org_membership(member, role, d['nonprofit_id'])
    if d['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only UNDER_REVIEW disclosures can receive restrictions')
    if uid != d['reviewer_member_id']:
        raise ApiError('ERR_REVIEWER_MISMATCH', 409,
                       'Only the assigned reviewer may impose restrictions')
    d['status'] = 'RESTRICTIONS_IMPOSED'
    d['restriction_categories'] = list(cats)
    touch(d)
    # restriction chain: end appointments on mapped committee types
    blocked = set()
    for cat in cats:
        blocked |= RESTRICTION_MAP.get(cat, set())
    target_member = store.members.get(d['board_member_id'])
    if target_member is not None:
        touch(target_member)  # has_active_restrictions flipped true
        for appt in list(store.appointments.values()):
            if appt['board_member_id'] == target_member['id'] and \
                    appt['status'] == 'ACTIVE':
                committee = store.committees.get(appt['committee_id'])
                if committee is not None and committee['type'] in blocked:
                    from domain import end_appointment
                    end_appointment(appt, 'COI_RESTRICTION')
    return envelope(ser_disclosure(d))


@bp.post('/boardgov/coi-disclosures/<rid>/lift_restrictions')
def lift_restrictions(rid):
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    d = lookup(store.disclosures, rid)
    check_org_membership(member, role, d['nonprofit_id'])
    if d['status'] != 'RESTRICTIONS_IMPOSED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only RESTRICTIONS_IMPOSED disclosures can be lifted')
    if uid != d['reviewer_member_id']:
        raise ApiError('ERR_REVIEWER_MISMATCH', 409,
                       'Only the assigned reviewer may lift restrictions')
    d['status'] = 'CLEARED'
    d['restriction_categories'] = []
    touch(d)
    target_member = store.members.get(d['board_member_id'])
    if target_member is not None:
        touch(target_member)  # has_active_restrictions recomputed false
    return envelope(ser_disclosure(d))


# ---------------------------------------------------------------- evaluations
def _validate_scores(scores):
    if not isinstance(scores, list):
        raise err400('scores must be a list')
    folded = {}
    for s in scores:
        if not isinstance(s, dict):
            raise err400('scores entries must be objects')
        dim = s.get('dimension')
        score = s.get('score')
        if dim not in EVAL_DIMENSIONS:
            raise err400(f'unknown score dimension {dim!r}')
        if not isinstance(score, int) or isinstance(score, bool) or \
                not 1 <= score <= 5:
            raise err400('score must be an integer 1..5')
        folded[dim] = score
    return folded


@bp.post('/boardgov/executive-evaluations')
def create_evaluation():
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    fy = v_int(body, 'fiscal_year')
    exec_name = v_str(body, 'executive_name')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    if any(x['nonprofit_id'] == np['id'] and x['fiscal_year'] == fy
           for x in store.evaluations.values()):
        raise ApiError('ERR_DUPLICATE_EVALUATION', 409,
                       'Evaluation already exists for (nonprofit, fiscal_year)')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'fiscal_year': fy,
              'executive_name': exec_name, 'scores': [],
              'provisional_composite': None, 'final_composite': None,
              'rating': None, 'recorded_by_user_id': None,
              'ratified_by_user_id': None, 'status': 'DRAFT'})
    store.evaluations[e['id']] = e
    return envelope(ser_evaluation(e), status=201)


@bp.get('/boardgov/executive-evaluations/<rid>')
def get_evaluation(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    return envelope(ser_evaluation(e))


@bp.get('/boardgov/executive-evaluations')
def list_evaluations():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.evaluations.values()),
                          {'nonprofit_id': np_id,
                           'fiscal_year': request.args.get('fiscal_year'),
                           'status': request.args.get('status')})
    return list_response(items, ser_evaluation)


@bp.patch('/boardgov/executive-evaluations/<rid>/scores')
def patch_scores(rid):
    uid, role = authn()
    require_role(role, REVIEW_ROLES)
    member = qualified_member(uid, role)
    body = get_body()
    expected = v_int(body, 'expected_evaluation_version')
    if 'scores' not in body:
        raise err400('scores is required')
    folded = _validate_scores(body['scores'])
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    if e['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Scores can be edited only while DRAFT')
    if expected != e['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'expected_evaluation_version does not match the current version')
    if e['recorded_by_user_id'] is None:
        e['recorded_by_user_id'] = uid
    elif uid != e['recorded_by_user_id']:
        raise ApiError('ERR_EVALUATION_RECORDER_MISMATCH', 409,
                       'Score edits must come from the first recorder')
    e['scores'] = [{'dimension': d, 'score': s} for d, s in folded.items()]
    if folded:
        mean = Decimal(sum(folded.values())) / Decimal(len(folded))
        e['provisional_composite'] = float(
            mean.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    else:
        e['provisional_composite'] = None
    touch(e)
    return envelope(ser_evaluation(e))


@bp.post('/boardgov/executive-evaluations/<rid>/submit_review')
def submit_review(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    if e['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only DRAFT evaluations can be submitted for review')
    dims = {s['dimension'] for s in e['scores']}
    if set(EVAL_DIMENSIONS) - dims:
        raise ApiError('ERR_EVALUATION_INCOMPLETE', 409,
                       'All five dimensions must be scored')
    e['status'] = 'COMMITTEE_REVIEW'
    touch(e)
    return envelope(ser_evaluation(e))


@bp.post('/boardgov/executive-evaluations/<rid>/return')
def return_evaluation(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    if e['status'] != 'COMMITTEE_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only COMMITTEE_REVIEW evaluations can be returned')
    e['status'] = 'DRAFT'
    touch(e)
    return envelope(ser_evaluation(e))


@bp.post('/boardgov/executive-evaluations/<rid>/ratify')
def ratify_evaluation(rid):
    uid, role = authn()
    require_role(role, ['BoardChair', 'Treasurer'])
    member = qualified_member(uid, role)
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    if e['status'] != 'COMMITTEE_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only COMMITTEE_REVIEW evaluations can be ratified')
    if uid == e['recorded_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 409,
                       'The ratifier must differ from the score recorder')
    folded = {s['dimension']: s['score'] for s in e['scores']}
    total = sum(Decimal(folded[d]) * EVAL_WEIGHTS[d] for d in EVAL_DIMENSIONS)
    final = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if final >= Decimal('4.25'):
        rating = 'EXCEEDS'
    elif final >= Decimal('3.00'):
        rating = 'MEETS'
    elif final >= Decimal('2.00'):
        rating = 'NEEDS_IMPROVEMENT'
    else:
        rating = 'UNSATISFACTORY'
    e['final_composite'] = float(final)
    e['rating'] = rating
    e['ratified_by_user_id'] = uid
    e['status'] = 'RATIFIED'
    touch(e)
    return envelope(ser_evaluation(e))


@bp.post('/boardgov/executive-evaluations/<rid>/deliver')
def deliver_evaluation(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    e = lookup(store.evaluations, rid)
    check_org_membership(member, role, e['nonprofit_id'])
    if e['status'] != 'RATIFIED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only RATIFIED evaluations can be delivered')
    e['status'] = 'DELIVERED'
    touch(e)
    return envelope(ser_evaluation(e))


# ---------------------------------------------------------------- succession plans
@bp.post('/boardgov/succession-plans')
def create_plan():
    uid, role = authn()
    require_role(role, ['BoardChair', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    target = v_enum(body, 'target_role', TARGET_ROLES)
    readiness = v_enum(body, 'readiness', READINESS)
    designee_id = body.get('interim_designee_member_id')
    if designee_id is not None and not isinstance(designee_id, str):
        raise err400('interim_designee_member_id must be a string')
    designee_name = body.get('interim_designee_name')
    if designee_name is not None and not isinstance(designee_name, str):
        raise err400('interim_designee_name must be a string')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    if designee_id is not None:
        ref_lookup(store.members, designee_id, 'interim_designee_member_id',
                   np['id'])
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'target_role': target,
              'readiness': readiness,
              'interim_designee_member_id': designee_id,
              'interim_designee_name': designee_name, 'status': 'DRAFT'})
    store.succession_plans[e['id']] = e
    return envelope(ser_succession(e), status=201)


@bp.get('/boardgov/succession-plans/<rid>')
def get_plan(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    p = lookup(store.succession_plans, rid)
    check_org_membership(member, role, p['nonprofit_id'])
    return envelope(ser_succession(p))


@bp.get('/boardgov/succession-plans')
def list_plans():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.succession_plans.values()),
                          {'nonprofit_id': np_id,
                           'target_role': request.args.get('target_role'),
                           'status': request.args.get('status'),
                           'interim_designee_member_id': request.args.get('interim_designee_member_id')})
    return list_response(items, ser_succession)


def _plan_for_chair(rid, uid, role):
    member = qualified_member(uid, role)
    p = lookup(store.succession_plans, rid)
    check_org_membership(member, role, p['nonprofit_id'])
    return p


@bp.post('/boardgov/succession-plans/<rid>/approve')
def approve_plan(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    p = _plan_for_chair(rid, uid, role)
    if p['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DRAFT plans can be approved')
    if p['target_role'] in ('BOARD_CHAIR', 'TREASURER'):
        did = p['interim_designee_member_id']
        if not did:
            raise ApiError('ERR_DESIGNEE_REQUIRED', 409,
                           'An interim_designee_member_id is required for this target role')
        m = store.members.get(did)
        if m is None or m['nonprofit_id'] != p['nonprofit_id'] or \
                m['status'] != 'ACTIVE':
            raise ApiError('ERR_NOT_FOUND', 404,
                           'interim_designee_member_id does not resolve to an ACTIVE member')
    else:
        name = p['interim_designee_name']
        if not name or not name.strip():
            raise ApiError('ERR_DESIGNEE_REQUIRED', 409,
                           'An interim_designee_name is required for EXECUTIVE_DIRECTOR')
    for other in store.succession_plans.values():
        if other['id'] != p['id'] and other['nonprofit_id'] == p['nonprofit_id'] \
                and other['target_role'] == p['target_role'] and \
                other['status'] == 'APPROVED':
            other['status'] = 'SUPERSEDED'
            touch(other)
    p['status'] = 'APPROVED'
    touch(p)
    return envelope(ser_succession(p))


@bp.post('/boardgov/succession-plans/<rid>/revise')
def revise_plan(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    p = _plan_for_chair(rid, uid, role)
    if p['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only APPROVED plans can be revised')
    p['status'] = 'DRAFT'
    touch(p)
    return envelope(ser_succession(p))


@bp.post('/boardgov/succession-plans/<rid>/activate')
def activate_plan(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    p = _plan_for_chair(rid, uid, role)
    if p['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only APPROVED plans can be activated')
    p['status'] = 'ACTIVATED'
    touch(p)
    return envelope(ser_succession(p))


@bp.post('/boardgov/succession-plans/<rid>/stand_down')
def stand_down_plan(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    p = _plan_for_chair(rid, uid, role)
    if p['status'] != 'ACTIVATED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only ACTIVATED plans can stand down')
    p['status'] = 'APPROVED'
    touch(p)
    return envelope(ser_succession(p))


@bp.post('/boardgov/succession-plans/<rid>/discard')
def discard_plan(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    p = _plan_for_chair(rid, uid, role)
    if p['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only DRAFT plans can be discarded')
    p['status'] = 'DISCARDED'
    touch(p)
    return envelope(ser_succession(p))
