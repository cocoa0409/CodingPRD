"""Contribution and trust-statement routes (reconciliation workflows)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import roles_allowed
from dates import parse_date
from domain import (recompute_balance, recompute_posture, recompute_statement)
from envelope import success_list, success_object
from errors import (ERR_INVALID_DATE_ORDER, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_STATEMENT_PERIOD_MISMATCH, ERR_STATEMENT_PERIOD_OVERLAP,
                    raise_err)
from store import base_fields, public, store, touch
from validate import (get_body, paginate, parse_pagination, req_date, req_enum,
                      req_int, req_str, sorted_created)

bp = Blueprint('contributions', __name__)

CTYPES = ('ELECTIVE_DEFERRAL', 'EMPLOYER_MATCH', 'EMPLOYER_PROFIT_SHARING', 'ROLLOVER')
CERTS = ('CERTIFIED', 'UNCERTIFIED')


def get_contribution_or_404(cid):
    c = store.contributions.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, 'Contribution %s not found' % cid)
    return c


def get_statement_or_404(sid):
    s = store.trust_statements.get(sid)
    if s is None:
        raise_err(ERR_NOT_FOUND, 'Trust statement %s not found' % sid)
    return s


# --- contributions -------------------------------------------------------------
@bp.route('/plan-audit/contributions', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_contribution():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    participant_id = req_str(body, 'participant_id')
    ctype = req_enum(body, 'type', CTYPES)
    payroll = req_date(body, 'payroll_date')
    deposit = req_date(body, 'deposit_date')
    amount = req_int(body, 'amount_cents', 1)
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    participant = store.participants.get(participant_id)
    if participant is None or participant['engagement_id'] != engagement_id:
        raise_err(ERR_NOT_FOUND, 'Participant %s not found in this engagement' % participant_id)
    if deposit < payroll:
        raise_err(ERR_INVALID_DATE_ORDER, 'deposit_date is earlier than payroll_date')
    c = base_fields()
    c.update({
        'engagement_id': engagement_id,
        'participant_id': participant_id,
        'type': ctype,
        'payroll_date': payroll.isoformat(),
        'deposit_date': deposit.isoformat(),
        'amount_cents': amount,
        'match_status': 'UNMATCHED',
        'timeliness_status': 'PENDING',
        'trust_statement_id': None,
        'business_days_elapsed': None,
    })
    store.contributions[c['id']] = c
    return success_object(public(c), status=201)


@bp.route('/plan-audit/contributions', methods=['GET'])
@roles_allowed('Any')
def list_contributions():
    limit, offset = parse_pagination()
    items = sorted_created(store.contributions.values())
    for param, field in (('engagement_id', 'engagement_id'),
                         ('participant_id', 'participant_id'),
                         ('trust_statement_id', 'trust_statement_id'),
                         ('match_status', 'match_status'),
                         ('timeliness_status', 'timeliness_status')):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(field) == v]
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], total, limit, offset)


@bp.route('/plan-audit/contributions/<cid>', methods=['GET'])
@roles_allowed('Any')
def get_contribution(cid):
    return success_object(public(get_contribution_or_404(cid)))


@bp.route('/plan-audit/contributions/<cid>/match', methods=['POST'])
@roles_allowed('SponsorAdmin')
def match_contribution(cid):
    c = get_contribution_or_404(cid)
    body = get_body()
    stmt_id = req_str(body, 'trust_statement_id')
    stmt = store.trust_statements.get(stmt_id)
    if stmt is None:
        raise_err(ERR_NOT_FOUND, 'Trust statement %s not found' % stmt_id)
    if c['match_status'] != 'UNMATCHED':
        raise_err(ERR_INVALID_STATE, 'Contribution is already matched')
    if stmt['status'] not in ('IMPORTED', 'DISCREPANCY'):
        raise_err(ERR_INVALID_STATE,
                  'Statement in %s cannot accept matches' % stmt['status'])
    if stmt['engagement_id'] != c['engagement_id']:
        raise_err(ERR_STATEMENT_PERIOD_MISMATCH,
                  'Statement belongs to a different engagement')
    dep = parse_date(c['deposit_date'])
    if not (parse_date(stmt['period_start']) <= dep <= parse_date(stmt['period_end'])):
        raise_err(ERR_STATEMENT_PERIOD_MISMATCH,
                  'deposit_date is outside the statement period')
    c['trust_statement_id'] = stmt_id
    c['match_status'] = 'MATCHED'
    touch(c)
    recompute_statement(stmt)
    touch(stmt)
    participant = store.participants.get(c['participant_id'])
    if participant is not None:
        recompute_balance(participant)
        touch(participant)
    return success_object(public(c))


@bp.route('/plan-audit/contributions/<cid>/unmatch', methods=['POST'])
@roles_allowed('SponsorAdmin')
def unmatch_contribution(cid):
    c = get_contribution_or_404(cid)
    if c['match_status'] != 'MATCHED':
        raise_err(ERR_INVALID_STATE, 'Contribution is not matched')
    stmt = store.trust_statements.get(c.get('trust_statement_id'))
    c['trust_statement_id'] = None
    c['match_status'] = 'UNMATCHED'
    touch(c)
    if stmt is not None:
        recompute_statement(stmt)
        if stmt['status'] == 'RECONCILED' and stmt['unreconciled_deposit_cents'] != 0:
            stmt['status'] = 'DISCREPANCY'
        touch(stmt)
        eng = store.engagements.get(stmt['engagement_id'])
        if eng is not None:
            recompute_posture(eng)
    participant = store.participants.get(c['participant_id'])
    if participant is not None:
        recompute_balance(participant)
        touch(participant)
    return success_object(public(c))


# --- trust statements ------------------------------------------------------------
@bp.route('/plan-audit/trust-statements', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_statement():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    period_start = req_date(body, 'period_start')
    period_end = req_date(body, 'period_end')
    custodian = req_str(body, 'custodian')
    certification = req_enum(body, 'certification', CERTS)
    total = req_int(body, 'reported_deposit_total_cents', 0)
    if store.engagements.get(engagement_id) is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    if period_end < period_start:
        raise_err(ERR_INVALID_REQUEST, 'period_end must not be before period_start')
    for s in store.trust_statements.values():
        if s['engagement_id'] != engagement_id:
            continue
        # Closed-interval overlap; adjacency (next.start == prev.end + 1 day) allowed.
        if period_start <= parse_date(s['period_end']) and parse_date(s['period_start']) <= period_end:
            raise_err(ERR_STATEMENT_PERIOD_OVERLAP,
                      'Statement period overlaps an existing statement of this engagement')
    s = base_fields()
    s.update({
        'engagement_id': engagement_id,
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'custodian': custodian,
        'certification': certification,
        'reported_deposit_total_cents': total,
        'matched_contribution_cents': 0,
        'adjustment_cents': 0,
        'unreconciled_deposit_cents': total,
        'status': 'IMPORTED',
    })
    store.trust_statements[s['id']] = s
    recompute_posture(store.engagements[engagement_id])
    return success_object(public(s), status=201)


@bp.route('/plan-audit/trust-statements', methods=['GET'])
@roles_allowed('Any')
def list_statements():
    limit, offset = parse_pagination()
    items = sorted_created(store.trust_statements.values())
    engagement_id = request.args.get('engagement_id')
    status = request.args.get('status')
    if engagement_id is not None:
        items = [s for s in items if s['engagement_id'] == engagement_id]
    if status is not None:
        items = [s for s in items if s['status'] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(s) for s in page], total, limit, offset)


@bp.route('/plan-audit/trust-statements/<sid>', methods=['GET'])
@roles_allowed('Any')
def get_statement(sid):
    return success_object(public(get_statement_or_404(sid)))


def _certified_coverage_gapless(eng):
    """True when the union of the engagement's statements covers
    [plan_year_start, plan_year_end - 1 day] without gaps."""
    cover_start = parse_date(eng['plan_year_start'])
    cover_end = parse_date(eng['plan_year_end']) - timedelta(days=1)
    intervals = sorted(
        (parse_date(s['period_start']), parse_date(s['period_end']))
        for s in store.trust_statements.values()
        if s['engagement_id'] == eng['id'])
    cursor = cover_start
    for start, end in intervals:
        if end < cursor:
            continue
        if start > cursor:  # gap before this interval (adjacent days are contiguous)
            break
        cursor = max(cursor, end + timedelta(days=1))
        if cursor > cover_end:
            return True
    return cursor > cover_end


@bp.route('/plan-audit/trust-statements/<sid>/reconcile', methods=['POST'])
@roles_allowed('TPASpecialist')
def reconcile_statement(sid):
    s = get_statement_or_404(sid)
    if s['status'] not in ('IMPORTED', 'DISCREPANCY'):
        raise_err(ERR_INVALID_STATE,
                  'Statement in %s cannot be reconciled' % s['status'])
    recompute_statement(s)
    eng = store.engagements.get(s['engagement_id'])
    if s['unreconciled_deposit_cents'] == 0:
        # Certified statements additionally demand gapless full-plan-year coverage.
        if s['certification'] == 'CERTIFIED' and eng is not None \
                and not _certified_coverage_gapless(eng):
            s['status'] = 'DISCREPANCY'
        else:
            s['status'] = 'RECONCILED'
    else:
        s['status'] = 'DISCREPANCY'
    touch(s)
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(s))


@bp.route('/plan-audit/trust-statements/<sid>/resolve', methods=['POST'])
@roles_allowed('EngagementManager')
def resolve_statement(sid):
    s = get_statement_or_404(sid)
    if s['status'] != 'DISCREPANCY':
        raise_err(ERR_INVALID_STATE, 'Only a DISCREPANCY statement can be resolved')
    body = get_body()
    adjustment = req_int(body, 'adjustment_cents')
    note = req_str(body, 'note')
    s['adjustment_cents'] = adjustment
    s['status'] = 'RESOLVED'
    recompute_statement(s)
    touch(s)
    eng = store.engagements.get(s['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(s))
