from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES, OPAQUE_ROLES
from response import ok
from services import calc
from services.lifecycle import (statement_for_order, apply_chargeback,
                                settle_claim_cascade)
from services.store import new_entity, touch, statement_view, claim_view, dispute_view
from util import get_body, check_body, get_path, apply_list, now

bp = Blueprint('settlement', __name__)

OPEN_DISPUTE_STATES = ('OPENED', 'RESPONSE_FILED', 'ARBITRATION_DOCKETED', 'DECIDED')
AGENT_FILER_ROLES = ('BookingAgent', 'OriginAgent', 'HaulingAgent', 'DestinationAgent')


# ---------------------------------------------------------------------------
# Revenue statements
# ---------------------------------------------------------------------------

@bp.get('/revenue-statements')
def list_statements():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda s, p=param, v=v: s[p] == v)
    return apply_list(db.statements, filters, statement_view)


@bp.get('/revenue-statements/<sid>')
def get_statement(sid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(statement_view(get_path(db.statements, sid)))


@bp.post('/revenue-statements/<sid>/finalize')
def finalize_statement(sid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    stmt = get_path(db.statements, sid)
    check_body(get_body(), [])
    if stmt['status'] != 'PROVISIONAL':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'statement is not PROVISIONAL')
    order = db.orders[stmt['order_id']]
    if order['status'] != 'DELIVERED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'order is not DELIVERED')
    stmt['status'] = 'FINAL'
    touch(stmt)
    order['status'] = 'SETTLED'
    touch(order)
    for c in db.crews.values():
        if c['order_id'] == order['id'] and c['status'] == 'COMPLETED':
            c['status'] = 'INVOICED'
            touch(c)
    return ok(statement_view(stmt))


@bp.post('/revenue-statements/<sid>/chargebacks')
def post_chargeback(sid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    stmt = get_path(db.statements, sid)
    vals = check_body(get_body(), [
        ('amount_cents', 'int', True, (1, None)),
        ('reason', 'str', True, None),
    ])
    if stmt['status'] != 'FINAL':
        raise ApiError('ERR_STATEMENT_NOT_FINAL', 409, 'statement is not FINAL')
    apply_chargeback(stmt['order_id'], vals['amount_cents'])
    return ok(statement_view(stmt))


@bp.post('/revenue-statements/<sid>/reconcile')
def reconcile_statement(sid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    stmt = get_path(db.statements, sid)
    check_body(get_body(), [])
    if stmt['status'] != 'FINAL':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'statement is not FINAL')
    for d in db.disputes.values():
        if d.get('revenue_statement_id') == sid and d['status'] in OPEN_DISPUTE_STATES:
            raise ApiError('ERR_OPEN_DISPUTES_EXIST', 409,
                           'an open dispute references this statement')
    stmt['status'] = 'RECONCILED'
    touch(stmt)
    return ok(statement_view(stmt))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/claims')
def create_claim(oid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [
        ('description', 'str', True, None),
        ('claimed_amount_cents', 'int', True, (1, None)),
        ('claimed_item_weight_lbs', 'int', True, (1, None)),
    ])
    if order['status'] not in ('DELIVERED', 'SETTLED', 'CLOSED'):
        raise ApiError('ERR_ORDER_NOT_DELIVERED', 409,
                       'claims may be filed only after delivery')
    if order['delivered_at'] is not None and now() > order['delivered_at'] + timedelta(
            days=calc.CLAIM_WINDOW_DAYS):
        raise ApiError('ERR_CLAIM_WINDOW_EXPIRED', 422,
                       'claim filed more than 270 days after delivery')
    locked = None
    for c in db.coverages.values():
        if c['order_id'] == oid and c['status'] == 'LOCKED':
            locked = c
            break
    claim = new_entity()
    claim.update({
        'order_id': oid,
        'valuation_coverage_id': locked['id'] if locked else None,
        'filed_at': now(),
        'description': vals['description'],
        'claimed_amount_cents': vals['claimed_amount_cents'],
        'claimed_item_weight_lbs': vals['claimed_item_weight_lbs'],
        'offer_amount_cents': None,
        'offered_by_user_id': None,
        'settled_amount_cents': None,
        'round_count': 0,
        'status': 'FILED',
    })
    db.claims[claim['id']] = claim
    return ok(claim_view(claim), 201)


@bp.get('/claims')
def list_claims():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'valuation_coverage_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda c, p=param, v=v: c[p] == v)
    return apply_list(db.claims, filters, claim_view)


@bp.get('/claims/<cid>')
def get_claim(cid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(claim_view(get_path(db.claims, cid)))


@bp.post('/claims/<cid>/offer')
def offer_claim(cid):
    auth = authenticate()
    authorize(auth, ['ClaimsAdjuster'])
    claim = get_path(db.claims, cid)
    vals = check_body(get_body(), [('offer_amount_cents', 'int', True, (0, None))])
    if claim['status'] not in ('FILED', 'DISPUTED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'claim must be FILED or DISPUTED to make an offer')
    coverage = db.coverages.get(claim['valuation_coverage_id'])
    cap = calc.claim_settlement_cap(claim, coverage) if coverage else claim['claimed_amount_cents']
    if vals['offer_amount_cents'] > cap:
        raise ApiError('ERR_OFFER_EXCEEDS_VALUATION_CAP', 422,
                       'offer exceeds the claim settlement cap')
    claim['offer_amount_cents'] = vals['offer_amount_cents']
    claim['offered_by_user_id'] = auth.user_id
    claim['status'] = 'OFFER_MADE'
    touch(claim)
    return ok(claim_view(claim))


@bp.post('/claims/<cid>/accept')
def accept_claim(cid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    claim = get_path(db.claims, cid)
    check_order_scope(auth, claim['order_id'])
    check_body(get_body(), [])
    if claim['status'] != 'OFFER_MADE':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'claim is not OFFER_MADE')
    settle_claim_cascade(claim, claim['offer_amount_cents'], claim['offered_by_user_id'])
    return ok(claim_view(claim))


@bp.post('/claims/<cid>/reject-offer')
def reject_claim(cid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    claim = get_path(db.claims, cid)
    check_order_scope(auth, claim['order_id'])
    check_body(get_body(), [])
    if claim['status'] != 'OFFER_MADE':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'claim is not OFFER_MADE')
    if claim['round_count'] >= calc.MAX_CLAIM_ROUNDS:
        raise ApiError('ERR_CLAIM_ROUNDS_EXHAUSTED', 409,
                       'negotiation rounds exhausted; use the arbitration program')
    claim['round_count'] += 1
    claim['status'] = 'DISPUTED'
    touch(claim)
    return ok(claim_view(claim))


@bp.post('/claims/<cid>/pay')
def pay_claim(cid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    claim = get_path(db.claims, cid)
    check_body(get_body(), [])
    if claim['status'] != 'ACCEPTED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'claim is not ACCEPTED')
    if auth.user_id == claim['offered_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'the payer must differ from the offering adjuster')
    claim['status'] = 'PAID'
    touch(claim)
    for d in db.disputes.values():
        if d.get('claim_id') == cid and d['status'] in OPEN_DISPUTE_STATES:
            d['status'] = 'CLOSED'
            touch(d)
    return ok(claim_view(claim))


@bp.post('/claims/<cid>/withdraw')
def withdraw_claim(cid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    claim = get_path(db.claims, cid)
    check_order_scope(auth, claim['order_id'])
    check_body(get_body(), [])
    if claim['status'] not in ('FILED', 'OFFER_MADE', 'DISPUTED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'claim must be FILED, OFFER_MADE, or DISPUTED')
    claim['status'] = 'WITHDRAWN'
    touch(claim)
    return ok(claim_view(claim))


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@bp.post('/disputes')
def create_dispute():
    auth = authenticate()
    authorize(auth, ['Customer'] + list(AGENT_FILER_ROLES))
    body = get_body()
    vals = check_body(body, [
        ('claim_id', 'str', False, None),
        ('revenue_statement_id', 'str', False, None),
        ('subject_amount_cents', 'int', True, (1, None)),
    ])
    has_claim = 'claim_id' in vals
    has_stmt = 'revenue_statement_id' in vals
    if has_claim == has_stmt:
        raise ApiError('ERR_DISPUTE_SUBJECT_INVALID', 422,
                       'exactly one of claim_id / revenue_statement_id must be present')
    if has_claim:
        subject = db.claims.get(vals['claim_id'])
        if subject is None:
            raise ApiError('ERR_NOT_FOUND', 404, 'claim_id not found')
        if subject['status'] != 'DISPUTED' or subject['round_count'] < 1:
            raise ApiError('ERR_DISPUTE_SUBJECT_INVALID', 422,
                           'claim must be DISPUTED with at least one rejected round')
    else:
        subject = db.statements.get(vals['revenue_statement_id'])
        if subject is None:
            raise ApiError('ERR_NOT_FOUND', 404, 'revenue_statement_id not found')
        if subject['status'] != 'FINAL':
            raise ApiError('ERR_STATEMENT_NOT_FINAL', 409, 'statement is not FINAL')
    for d in db.disputes.values():
        if d['status'] in OPEN_DISPUTE_STATES:
            if has_claim and d.get('claim_id') == vals['claim_id']:
                raise ApiError('ERR_DISPUTE_ALREADY_OPEN', 409,
                               'an open dispute already exists on this claim')
            if has_stmt and d.get('revenue_statement_id') == vals['revenue_statement_id']:
                raise ApiError('ERR_DISPUTE_ALREADY_OPEN', 409,
                               'an open dispute already exists on this statement')
    disp = new_entity()
    disp.update({
        'claim_id': vals.get('claim_id'),
        'revenue_statement_id': vals.get('revenue_statement_id'),
        'opened_by_role': 'CUSTOMER' if auth.role == 'Customer' else 'AGENT',
        'filer_user_id': auth.user_id,
        'subject_amount_cents': vals['subject_amount_cents'],
        'responded_at': None,
        'responded_by_user_id': None,
        'escalated_at': None,
        'filing_fee_cents': None,
        'decision_amount_cents': None,
        'fee_allocated_to': None,
        'decided_by_user_id': None,
        'status': 'OPENED',
    })
    db.disputes[disp['id']] = disp
    return ok(dispute_view(disp), 201)


@bp.get('/disputes')
def list_disputes():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('claim_id', 'revenue_statement_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda d, p=param, v=v: d[p] == v)
    return apply_list(db.disputes, filters, dispute_view)


@bp.get('/disputes/<did>')
def get_dispute(did):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(dispute_view(get_path(db.disputes, did)))


@bp.post('/disputes/<did>/respond')
def respond_dispute(did):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    disp = get_path(db.disputes, did)
    check_body(get_body(), [('response_note', 'str', False, None)])
    if disp['status'] != 'OPENED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'dispute is not OPENED')
    disp['responded_at'] = now()
    disp['responded_by_user_id'] = auth.user_id
    disp['status'] = 'RESPONSE_FILED'
    touch(disp)
    return ok(dispute_view(disp))


@bp.post('/disputes/<did>/escalate-to-arbitration')
def escalate_dispute(did):
    auth = authenticate()
    authorize(auth, ['Customer'] + list(AGENT_FILER_ROLES))
    disp = get_path(db.disputes, did)
    if auth.user_id != disp['filer_user_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'only the filer may escalate the dispute')
    check_body(get_body(), [])
    if disp['status'] != 'RESPONSE_FILED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'dispute is not RESPONSE_FILED')
    if disp['responded_at'] is not None and now() < disp['responded_at'] + timedelta(
            days=calc.MEDIATION_COOLING_OFF_DAYS):
        raise ApiError('ERR_MEDIATION_PERIOD_NOT_ELAPSED', 422,
                       'the 14-day mediation cooling-off period has not elapsed')
    disp['filing_fee_cents'] = calc.ARBITRATION_FILING_FEE_CENTS
    disp['escalated_at'] = now()
    disp['status'] = 'ARBITRATION_DOCKETED'
    touch(disp)
    return ok(dispute_view(disp))


@bp.post('/disputes/<did>/decide')
def decide_dispute(did):
    auth = authenticate()
    authorize(auth, ['Arbitrator'])
    disp = get_path(db.disputes, did)
    vals = check_body(get_body(), [('decision_amount_cents', 'int', True, None)])
    if disp['status'] != 'ARBITRATION_DOCKETED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'dispute is not ARBITRATION_DOCKETED')
    if auth.user_id == disp['responded_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'the decider must differ from the responder')
    if vals['decision_amount_cents'] < 0 or vals['decision_amount_cents'] > disp['subject_amount_cents']:
        raise ApiError('ERR_DECISION_OUT_OF_RANGE', 422,
                       'decision_amount_cents must be within [0, subject_amount_cents]')
    disp['decision_amount_cents'] = vals['decision_amount_cents']
    disp['fee_allocated_to'] = calc.arbitration_fee_allocation(
        vals['decision_amount_cents'], disp['subject_amount_cents'])
    disp['decided_by_user_id'] = auth.user_id
    disp['status'] = 'DECIDED'
    touch(disp)
    if disp.get('claim_id'):
        claim = db.claims.get(disp['claim_id'])
        if claim is not None and claim['status'] in ('FILED', 'DISPUTED', 'OFFER_MADE'):
            settle_claim_cascade(claim, vals['decision_amount_cents'], auth.user_id)
    elif disp.get('revenue_statement_id'):
        stmt = db.statements.get(disp['revenue_statement_id'])
        if stmt is not None:
            apply_chargeback(stmt['order_id'], vals['decision_amount_cents'])
    return ok(dispute_view(disp))


@bp.post('/disputes/<did>/close')
def close_dispute(did):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    disp = get_path(db.disputes, did)
    check_body(get_body(), [])
    if disp['status'] != 'DECIDED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'dispute is not DECIDED')
    if disp.get('claim_id'):
        claim = db.claims.get(disp['claim_id'])
        if claim is None or claim['status'] != 'PAID':
            raise ApiError('ERR_CLAIM_NOT_PAID', 409,
                           'the referenced claim must be PAID before closing')
    disp['status'] = 'CLOSED'
    touch(disp)
    return ok(dispute_view(disp))


@bp.post('/disputes/<did>/withdraw')
def withdraw_dispute(did):
    auth = authenticate()
    authorize(auth, ['Customer'] + list(AGENT_FILER_ROLES))
    disp = get_path(db.disputes, did)
    if auth.user_id != disp['filer_user_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'only the filer may withdraw the dispute')
    check_body(get_body(), [])
    if disp['status'] not in ('OPENED', 'RESPONSE_FILED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'dispute must be OPENED or RESPONSE_FILED')
    disp['status'] = 'WITHDRAWN'
    touch(disp)
    return ok(dispute_view(disp))
