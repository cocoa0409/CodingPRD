"""Form 990 filings, state registrations, insurance policies."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import store
from domain import (POLICY_TYPES, active_members, adopted_bylaws,
                    coverage_floor, filing_due_date, renewal_fee, ser_filing,
                    ser_policy, ser_registration)
from helpers import (ALL_ROLES, ApiError, add_months, apply_filters, authn,
                     check_org_membership, envelope, err400, get_body,
                     list_response, lookup, new_entity, qualified_member,
                     ref_lookup, require_role, touch, v_bool, v_dt, v_enum,
                     v_int, v_str)
from . import bp
from .core import _np_or_403_or_422


# ---------------------------------------------------------------- form 990
@bp.post('/boardgov/form990-filings')
def create_filing():
    uid, role = authn()
    require_role(role, ['Treasurer', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    fy = v_int(body, 'fiscal_year')
    revenue = v_int(body, 'total_revenue_cents', min_v=0)
    expenses = v_int(body, 'total_expenses_cents', min_v=0)
    contributions = v_int(body, 'contributions_cents', min_v=0)
    program_rev = v_int(body, 'program_service_revenue_cents', min_v=0)
    preparer = v_str(body, 'preparer_user_id')
    supersedes = body.get('supersedes_filing_id')
    if supersedes is not None and not isinstance(supersedes, str):
        raise err400('supersedes_filing_id must be a string')
    np = _np_or_403_or_422(np_id, role)
    check_org_membership(member, role, np['id'])
    target = None
    if supersedes is not None:
        target = ref_lookup(store.filings, supersedes, 'supersedes_filing_id',
                            np['id'])
        if target['status'] not in ('FILED', 'PUBLIC_DISCLOSED'):
            raise ApiError('ERR_INVALID_STATE', 409,
                           'Amendment target must be FILED or PUBLIC_DISCLOSED')
    else:
        if any(f['nonprofit_id'] == np['id'] and f['fiscal_year'] == fy and
               f['supersedes_filing_id'] is None
               for f in store.filings.values()):
            raise ApiError('ERR_DUPLICATE_FILING', 409,
                           'A root filing already exists for (nonprofit, fiscal_year)')
    ratio = Decimal(0) if revenue == 0 else (
        Decimal(contributions) / Decimal(revenue)).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP)
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'fiscal_year': fy,
              'supersedes_filing_id': supersedes,
              'total_revenue_cents': revenue, 'total_expenses_cents': expenses,
              'contributions_cents': contributions,
              'program_service_revenue_cents': program_rev,
              'net_change_cents': revenue - expenses,
              'public_support_ratio': ratio,
              'preparer_user_id': preparer, 'approved_by_user_id': None,
              'reviewed_by_member_ids': [], 'review_required_count': None,
              'filing_due_date': filing_due_date(np, fy),
              'filed_on': None, 'filed_late': False,
              'public_disclosure_posted_at': None, 'status': 'DRAFT'})
    store.filings[e['id']] = e
    return envelope(ser_filing(e), status=201)


@bp.get('/boardgov/form990-filings/<rid>')
def get_filing(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    return envelope(ser_filing(f))


@bp.get('/boardgov/form990-filings')
def list_filings():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.filings.values()),
                          {'nonprofit_id': np_id,
                           'fiscal_year': request.args.get('fiscal_year'),
                           'status': request.args.get('status'),
                           'supersedes_filing_id': request.args.get('supersedes_filing_id')})
    return list_response(items, ser_filing)


@bp.post('/boardgov/form990-filings/<rid>/submit_for_review')
def submit_for_review(rid):
    uid, role = authn()
    require_role(role, ['Treasurer', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    if f['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only DRAFT filings can be submitted for review')
    b = adopted_bylaws(f['nonprofit_id'])
    if b is None:
        raise ApiError('ERR_BYLAWS_NOT_ADOPTED', 409,
                       'An ADOPTED bylaws is required to measure review coverage')
    active_count = len(active_members(f['nonprofit_id']))
    f['review_required_count'] = (b['quorum_pct'] * active_count + 99) // 100
    f['status'] = 'IN_BOARD_REVIEW'
    touch(f)
    return envelope(ser_filing(f))


@bp.post('/boardgov/form990-filings/<rid>/record_review')
def record_review(rid):
    uid, role = authn()
    require_role(role, ['BoardDirector', 'BoardChair', 'Treasurer'])
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    if f['status'] != 'IN_BOARD_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Reviews can be recorded only while IN_BOARD_REVIEW')
    if uid in f['reviewed_by_member_ids']:
        raise ApiError('ERR_DUPLICATE_REVIEW', 409,
                       'Member already recorded a review of this filing')
    f['reviewed_by_member_ids'].append(uid)
    touch(f)
    return envelope(ser_filing(f))


@bp.post('/boardgov/form990-filings/<rid>/approve')
def approve_filing(rid):
    uid, role = authn()
    require_role(role, ['BoardChair'])
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    if f['status'] != 'IN_BOARD_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only IN_BOARD_REVIEW filings can be approved')
    if uid == f['preparer_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 409,
                       'The approver must differ from the preparer')
    # Reviews count only from members still ACTIVE at approve time.
    count = 0
    for mid in f['reviewed_by_member_ids']:
        m = store.members.get(mid)
        if m is not None and m['status'] == 'ACTIVE':
            count += 1
    if count < (f['review_required_count'] or 0):
        raise ApiError('ERR_REVIEW_COVERAGE_INSUFFICIENT', 409,
                       'Recorded reviews fall below review_required_count')
    f['approved_by_user_id'] = uid
    f['status'] = 'APPROVED'
    touch(f)
    return envelope(ser_filing(f))


@bp.post('/boardgov/form990-filings/<rid>/mark_filed')
def mark_filed(rid):
    uid, role = authn()
    require_role(role, ['Treasurer', 'GovernanceAdmin'])
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    if f['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only APPROVED filings can be marked filed')
    t = store.get_clock()
    f['filed_on'] = t
    f['filed_late'] = t.date() > f['filing_due_date'].date()
    f['status'] = 'FILED'
    touch(f)
    if f['supersedes_filing_id']:
        target = store.filings.get(f['supersedes_filing_id'])
        if target is not None and target['status'] in ('FILED', 'PUBLIC_DISCLOSED'):
            target['status'] = 'SUPERSEDED'
            touch(target)
    return envelope(ser_filing(f))


@bp.post('/boardgov/form990-filings/<rid>/post_public_disclosure')
def post_public_disclosure(rid):
    uid, role = authn()
    require_role(role, ['GovernanceAdmin', 'ComplianceOfficer'])
    f = lookup(store.filings, rid)
    if f['status'] != 'FILED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only FILED filings can be posted for public disclosure')
    f['public_disclosure_posted_at'] = store.get_clock()
    f['status'] = 'PUBLIC_DISCLOSED'
    touch(f)
    return envelope(ser_filing(f))


@bp.post('/boardgov/form990-filings/<rid>/discard')
def discard_filing(rid):
    uid, role = authn()
    require_role(role, ['Treasurer'])
    member = qualified_member(uid, role)
    f = lookup(store.filings, rid)
    check_org_membership(member, role, f['nonprofit_id'])
    if f['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only DRAFT filings can be discarded')
    f['status'] = 'DISCARDED'
    touch(f)
    return envelope(ser_filing(f))


# ---------------------------------------------------------------- registrations
@bp.post('/boardgov/state-registrations')
def create_registration():
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    state_code = v_str(body, 'state_code')
    cycle = v_int(body, 'renewal_cycle_months', required=False, default=12, min_v=1)
    period_end = v_dt(body, 'current_period_end')
    contributions = v_int(body, 'contributions_in_state_cents', required=False,
                          min_v=0)
    np = ref_lookup(store.nonprofits, np_id, 'nonprofit_id')
    if any(r['nonprofit_id'] == np['id'] and r['state_code'] == state_code
           for r in store.registrations.values()):
        raise ApiError('ERR_DUPLICATE_REGISTRATION', 409,
                       'Registration already exists for (nonprofit, state_code)')
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'state_code': state_code,
              'renewal_cycle_months': cycle, 'current_period_end': period_end,
              'contributions_in_state_cents': contributions,
              'renewal_fee_cents': None, 'status': 'REGISTERED'})
    store.registrations[e['id']] = e
    return envelope(ser_registration(e), status=201)


@bp.get('/boardgov/state-registrations/<rid>')
def get_registration(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    r = lookup(store.registrations, rid)
    check_org_membership(member, role, r['nonprofit_id'])
    return envelope(ser_registration(r))


@bp.get('/boardgov/state-registrations')
def list_registrations():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.registrations.values()),
                          {'nonprofit_id': np_id,
                           'state_code': request.args.get('state_code'),
                           'status': request.args.get('status')})
    return list_response(items, ser_registration)


@bp.post('/boardgov/state-registrations/<rid>/submit_renewal')
def submit_renewal(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    body = get_body()
    paid = v_int(body, 'paid_fee_cents', min_v=0)
    contributions = v_int(body, 'contributions_in_state_cents', required=False,
                          min_v=0)
    reg = lookup(store.registrations, rid)
    if reg['status'] not in ('REGISTERED', 'RENEWAL_DUE'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Renewal can be submitted only from REGISTERED or RENEWAL_DUE')
    t = store.get_clock()
    if reg['status'] == 'REGISTERED' and \
            t < reg['current_period_end'] - timedelta(days=90):
        raise ApiError('ERR_RENEWAL_TOO_EARLY', 409,
                       'Renewal window opens 90 days before current_period_end')
    np = store.nonprofits.get(reg['nonprofit_id'])
    fee = renewal_fee(np, contributions, lapsed=False)
    if paid != fee:
        raise ApiError('ERR_RENEWAL_FEE_MISMATCH', 409,
                       f'paid_fee_cents must equal the computed fee {fee}')
    if contributions is not None:
        reg['contributions_in_state_cents'] = contributions
    reg['renewal_fee_cents'] = fee
    reg['status'] = 'RENEWAL_SUBMITTED'
    touch(reg)
    return envelope(ser_registration(reg))


@bp.post('/boardgov/state-registrations/<rid>/confirm_renewal')
def confirm_renewal(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    reg = lookup(store.registrations, rid)
    if reg['status'] != 'RENEWAL_SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only RENEWAL_SUBMITTED registrations can be confirmed')
    reg['current_period_end'] = add_months(reg['current_period_end'],
                                           reg['renewal_cycle_months'])
    reg['status'] = 'REGISTERED'
    touch(reg)
    return envelope(ser_registration(reg))


@bp.post('/boardgov/state-registrations/<rid>/reinstate')
def reinstate(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    body = get_body()
    paid = v_int(body, 'paid_fee_cents', min_v=0)
    contributions = v_int(body, 'contributions_in_state_cents', required=False,
                          min_v=0)
    reg = lookup(store.registrations, rid)
    if reg['status'] != 'LAPSED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only LAPSED registrations can be reinstated')
    np = store.nonprofits.get(reg['nonprofit_id'])
    fee = renewal_fee(np, contributions, lapsed=True)
    if paid != fee:
        raise ApiError('ERR_RENEWAL_FEE_MISMATCH', 409,
                       f'paid_fee_cents must equal the computed fee {fee} (incl. late fee)')
    if contributions is not None:
        reg['contributions_in_state_cents'] = contributions
    reg['renewal_fee_cents'] = fee
    reg['current_period_end'] = add_months(store.get_clock(),
                                           reg['renewal_cycle_months'])
    reg['status'] = 'REGISTERED'
    touch(reg)
    return envelope(ser_registration(reg))


# ---------------------------------------------------------------- insurance
@bp.post('/boardgov/insurance-policies')
def create_policy():
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    body = get_body()
    np_id = v_str(body, 'nonprofit_id')
    ptype = v_enum(body, 'policy_type', POLICY_TYPES)
    carrier = v_str(body, 'carrier')
    limit = v_int(body, 'coverage_limit_cents', min_v=0)
    premium = v_int(body, 'premium_cents', min_v=0)
    start = v_dt(body, 'policy_start_date')
    end = v_dt(body, 'policy_end_date')
    if end <= start:
        raise err400('policy_end_date must be after policy_start_date')
    prior_id = body.get('prior_policy_id')
    if prior_id is not None and not isinstance(prior_id, str):
        raise err400('prior_policy_id must be a string')
    ack_gap = v_bool(body, 'acknowledge_gap', required=False, default=False)
    np = ref_lookup(store.nonprofits, np_id, 'nonprofit_id')
    gap_days = 0
    if prior_id is not None:
        prior = ref_lookup(store.policies, prior_id, 'prior_policy_id', np['id'])
        gap_days = (start - prior['policy_end_date']).days
    e = new_entity()
    e.update({'nonprofit_id': np['id'], 'prior_policy_id': prior_id,
              'policy_type': ptype, 'carrier': carrier,
              'coverage_limit_cents': limit, 'premium_cents': premium,
              'policy_start_date': start, 'policy_end_date': end,
              'acknowledge_gap': ack_gap, 'gap_days': gap_days,
              'status': 'QUOTED'})
    store.policies[e['id']] = e
    return envelope(ser_policy(e), status=201)


@bp.get('/boardgov/insurance-policies/<rid>')
def get_policy(rid):
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    p = lookup(store.policies, rid)
    check_org_membership(member, role, p['nonprofit_id'])
    return envelope(ser_policy(p))


@bp.get('/boardgov/insurance-policies')
def list_policies():
    uid, role = authn()
    require_role(role, ALL_ROLES)
    member = qualified_member(uid, role)
    np_id = request.args.get('nonprofit_id')
    check_org_membership(member, role, np_id)
    items = apply_filters(list(store.policies.values()),
                          {'nonprofit_id': np_id,
                           'policy_type': request.args.get('policy_type'),
                           'status': request.args.get('status'),
                           'prior_policy_id': request.args.get('prior_policy_id')})
    return list_response(items, ser_policy)


@bp.post('/boardgov/insurance-policies/<rid>/bind')
def bind_policy(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    p = lookup(store.policies, rid)
    if p['status'] != 'QUOTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only QUOTED policies can be bound')
    # 18: interval rules — renewal gap first, then same-type overlap
    if p['prior_policy_id'] is not None:
        prior = store.policies.get(p['prior_policy_id'])
        if prior is not None:
            gap = (p['policy_start_date'] - prior['policy_end_date']).days
            p['gap_days'] = gap
            if gap < 0:
                raise ApiError('ERR_POLICY_OVERLAP', 409,
                               'Renewal starts before the prior policy ended')
            if gap > 0 and p['acknowledge_gap'] is not True:
                raise ApiError('ERR_COVERAGE_GAP', 409,
                               'A coverage gap requires acknowledge_gap=true')
    for q in store.policies.values():
        if q['id'] == p['id'] or q['nonprofit_id'] != p['nonprofit_id'] or \
                q['policy_type'] != p['policy_type'] or \
                q['status'] not in ('QUOTED', 'BOUND', 'ACTIVE'):
            continue
        if p['policy_start_date'] < q['policy_end_date'] and \
                q['policy_start_date'] < p['policy_end_date']:
            raise ApiError('ERR_POLICY_OVERLAP', 409,
                           'Policy overlaps a non-terminal same-type policy')
    # 20: money checks
    np = store.nonprofits.get(p['nonprofit_id'])
    if p['coverage_limit_cents'] < coverage_floor(np):
        raise ApiError('ERR_COVERAGE_BELOW_FLOOR', 409,
                       'coverage_limit_cents is below the 25% receipts floor')
    p['status'] = 'BOUND'
    touch(p)
    return envelope(ser_policy(p))


@bp.post('/boardgov/insurance-policies/<rid>/activate')
def activate_policy(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    p = lookup(store.policies, rid)
    if p['status'] != 'BOUND':
        raise ApiError('ERR_INVALID_STATE', 409, 'Only BOUND policies can be activated')
    if store.get_clock() < p['policy_start_date']:
        raise ApiError('ERR_POLICY_NOT_YET_EFFECTIVE', 409,
                       'Policy cannot be activated before policy_start_date')
    p['status'] = 'ACTIVE'
    touch(p)
    return envelope(ser_policy(p))


@bp.post('/boardgov/insurance-policies/<rid>/cancel')
def cancel_policy(rid):
    uid, role = authn()
    require_role(role, ['ComplianceOfficer'])
    p = lookup(store.policies, rid)
    if p['status'] not in ('QUOTED', 'BOUND', 'ACTIVE'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only QUOTED, BOUND, or ACTIVE policies can be cancelled')
    p['status'] = 'CANCELLED'
    touch(p)
    return envelope(ser_policy(p))
