"""Escalation cases and remediation commitments: E36-E42."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, derive, gates, risk, serialize
from services.lookup import account as get_account
from services.lookup import escalation_case as get_case
from services.lookup import remediation_commitment as get_commitment
from services.lookup import save_play as get_play

bp = Blueprint('escalations', __name__)

SEVERITIES = ('CRITICAL', 'HIGH', 'MEDIUM')
CASE_STATES = ('OPEN', 'COMMITTED', 'DISPUTED', 'RESOLVED', 'WITHDRAWN')
CASE_ACTIONS = ('COMMIT', 'RESOLVE', 'WITHDRAW')
COMMITMENT_STATES = ('PROPOSED', 'ACCEPTED', 'REJECTED', 'DELIVERED', 'BREACHED',
                     'WITHDRAWN')
COMMITMENT_ACTIONS = ('ACCEPT', 'REJECT', 'DELIVER')
NEGOTIABLE_CASE_STATES = ('OPEN', 'DISPUTED')


@bp.route('/escalation-cases', methods=['POST'])
def create_case():
    mw.authenticate(('CsmUser', 'CsExecutive'))
    data = mw.body()
    # rule 4: body foreign keys resolve before the schema is examined
    account_ref = mw.raw_id(data, 'account_id')
    if account_ref is not None:
        get_account(account_ref)
    play_ref = mw.raw_id(data, 'save_play_id')
    if play_ref is not None:
        get_play(play_ref)

    account_id = mw.as_id(data, 'account_id')
    save_play_id = mw.as_id(data, 'save_play_id')
    severity = mw.as_enum(data, 'severity', SEVERITIES)
    summary = mw.as_string(data, 'summary')

    account = db.accounts[account_id]
    play = db.save_plays[save_play_id]
    if play['account_id'] != account['id']:
        raise ApiError('ERR_CROSS_ACCOUNT_REFERENCE',
                       'Save play %s belongs to another account.' % save_play_id)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'save_play_id': play['id'],
        'severity': severity,
        'summary': summary,
        'state': 'OPEN',
        'remediation_round': 1,
        'final_credit_cents': None,
    })
    db.escalation_cases[row['id']] = row
    mark_fresh(row)
    derive.derive_coverage_posture(account)
    return resp.entity(serialize.escalation_case, row, 201)


@bp.route('/escalation-cases/<case_id>', methods=['GET'])
def read_case(case_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    case = get_case(case_id)
    return resp.entity(serialize.escalation_case, case, 200)


@bp.route('/escalation-cases', methods=['GET'])
def list_cases():
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    limit, offset = mw.pagination()
    account_id = mw.query_value('account_id')
    save_play_id = mw.query_value('save_play_id')
    state = mw.query_enum('state', CASE_STATES)
    rows = store.ordered(db.escalation_cases)
    if account_id is not None:
        rows = [r for r in rows if r['account_id'] == account_id]
    if save_play_id is not None:
        rows = [r for r in rows if r['save_play_id'] == save_play_id]
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.escalation_case, rows, limit, offset)


@bp.route('/escalation-cases/<case_id>/transition', methods=['POST'])
def transition_case(case_id):
    mw.authenticate(('CsExecutive',))
    case = get_case(case_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', CASE_ACTIONS)
    account = db.accounts.get(case['account_id'])
    state = case['state']

    if action == 'COMMIT':
        if state not in NEGOTIABLE_CASE_STATES:
            raise gates.invalid_transition(
                'A case in state %s may not be committed.' % state)
        has_buyer = account is not None and any(
            s['status'] == 'ACTIVE' and s['is_economic_buyer']
            for s in store.account_sponsors(account['id']))
        if not has_buyer:
            raise ApiError('ERR_SPONSOR_DEPARTED',
                           'The account has no ACTIVE economic buyer to give '
                           'executive cover.')
        supported = any(c['state'] == 'ACCEPTED'
                        and c['round_index'] == case['remediation_round']
                        for c in store.case_commitments(case['id']))
        if not supported:
            raise ApiError('ERR_NO_ACCEPTED_COMMITMENT',
                           'No ACCEPTED remediation commitment exists at round %d.'
                           % case['remediation_round'])
        touch(case)
        case['state'] = 'COMMITTED'
        if account is not None:
            derive.derive_coverage_posture(account)
        return resp.entity(serialize.escalation_case, case, 200)

    if action == 'RESOLVE':
        if state != 'COMMITTED':
            raise gates.invalid_transition(
                'Only a COMMITTED case may be resolved; this one is %s.' % state)
        commitments = store.case_commitments(case['id'])
        settled_states = ('DELIVERED', 'REJECTED', 'WITHDRAWN')
        if any(c['state'] not in settled_states for c in commitments) or not any(
                c['state'] == 'DELIVERED' for c in commitments):
            raise ApiError('ERR_NO_ACCEPTED_COMMITMENT',
                           'Every commitment must be DELIVERED, REJECTED or '
                           'WITHDRAWN with at least one DELIVERED.')
        touch(case)
        risk.resolve_case(case, account)
        return resp.entity(serialize.escalation_case, case, 200)

    # WITHDRAW
    if state not in ('OPEN', 'COMMITTED', 'DISPUTED'):
        raise gates.invalid_transition(
            'A case in state %s may not be withdrawn.' % state)
    touch(case)
    risk.withdraw_case(case, account)
    return resp.entity(serialize.escalation_case, case, 200)


@bp.route('/escalation-cases/<case_id>/remediation-commitments', methods=['POST'])
def create_commitment(case_id):
    mw.authenticate(('CsExecutive',))
    case = get_case(case_id)
    data = mw.body()
    description = mw.as_string(data, 'description')
    due_date = mw.as_date(data, 'due_date')
    credit_cents = mw.as_int(data, 'credit_cents', minimum=0)
    expected_version = mw.as_int(data, 'expected_escalation_case_version',
                                 minimum=0)

    if expected_version != case['version']:
        raise ApiError('ERR_STALE_ESCALATION_VERSION',
                       'expected_escalation_case_version %s does not match the '
                       'stored version %s.' % (expected_version, case['version']))

    account = db.accounts.get(case['account_id'])
    arr_cents = account['arr_cents'] if account is not None else 0
    if not calc.credit_within_cap(credit_cents, arr_cents):
        raise ApiError('ERR_CREDIT_EXCEEDS_CAP',
                       'credit_cents exceeds %d basis points of the account ARR.'
                       % calc.COMMITMENT_CREDIT_CAP_BP)

    row = base_row()
    row.update({
        'escalation_case_id': case['id'],
        'description': description,
        'due_date': data['due_date'],
        '_due_date': due_date,
        'credit_cents': credit_cents,
        'state': 'PROPOSED',
        'round_index': case['remediation_round'],
        'accepted_by_user_id': None,
        'delivered_by_user_id': None,
    })
    db.remediation_commitments[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.remediation_commitment, row, 201)


@bp.route('/escalation-cases/<case_id>/remediation-commitments', methods=['GET'])
def list_commitments(case_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    case = get_case(case_id)
    limit, offset = mw.pagination()
    state = mw.query_enum('state', COMMITMENT_STATES)
    rows = store.case_commitments(case['id'])
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.remediation_commitment, rows, limit, offset)


@bp.route('/remediation-commitments/<commitment_id>/transition', methods=['POST'])
def transition_commitment(commitment_id):
    actor, _role = mw.authenticate(('CsExecutive', 'CsmUser'))
    commitment = get_commitment(commitment_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', COMMITMENT_ACTIONS)

    # rule 8 outranks rule 12: segregation of duties is tested before the edge
    if action == 'DELIVER' and actor == commitment['accepted_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES',
                       'The user who accepted a commitment may not deliver it.')

    case = db.escalation_cases.get(commitment['escalation_case_id'])
    account = db.accounts.get(case['account_id']) if case is not None else None
    state = commitment['state']

    if action in ('ACCEPT', 'REJECT'):
        if state != 'PROPOSED':
            raise gates.invalid_transition(
                'Only a PROPOSED commitment may be %s; this one is %s.'
                % (action.lower() + 'ed', state))
        if case is None or case['state'] not in NEGOTIABLE_CASE_STATES:
            raise gates.invalid_transition(
                'The owning case must be OPEN or DISPUTED.')
        if action == 'ACCEPT' and commitment['round_index'] != case['remediation_round']:
            raise gates.invalid_transition(
                'The commitment belongs to round %d but the case is negotiating '
                'round %d.' % (commitment['round_index'],
                               case['remediation_round']))
        touch(commitment)
        if action == 'ACCEPT':
            commitment['state'] = 'ACCEPTED'
            commitment['accepted_by_user_id'] = actor
            if account is not None:
                risk.add_outstanding(account, commitment['credit_cents'])
        else:
            commitment['state'] = 'REJECTED'
        return resp.entity(serialize.remediation_commitment, commitment, 200)

    # DELIVER
    if state != 'ACCEPTED':
        raise gates.invalid_transition(
            'Only an ACCEPTED commitment may be delivered; this one is %s.' % state)
    if case is None or case['state'] != 'COMMITTED':
        raise gates.invalid_transition(
            'The owning case must be COMMITTED to deliver a commitment.')
    touch(commitment)
    commitment['state'] = 'DELIVERED'
    commitment['delivered_by_user_id'] = actor
    return resp.entity(serialize.remediation_commitment, commitment, 200)
