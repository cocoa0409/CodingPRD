"""Onboarding milestones: E29-E31."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import derive, gates, lifecycle, serialize
from services.lookup import account as get_account
from services.lookup import onboarding_milestone as get_milestone

bp = Blueprint('milestones', __name__)

MILESTONE_CODES = ('KICKOFF', 'DATA_INTEGRATION', 'FIRST_VALUE', 'GO_LIVE')
MILESTONE_STATES = ('PENDING', 'OVERDUE', 'BLOCKED', 'COMPLETED', 'WAIVED')
MILESTONE_ACTIONS = ('COMPLETE', 'WAIVE')
COMPLETABLE_STATES = ('PENDING', 'OVERDUE')
WAIVABLE_STATES = ('PENDING', 'OVERDUE', 'BLOCKED')


@bp.route('/accounts/<account_id>/onboarding-milestones', methods=['POST'])
def create_milestone(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    account = get_account(account_id)
    data = mw.body()
    milestone_code = mw.as_enum(data, 'milestone_code', MILESTONE_CODES)
    sequence_index = mw.as_int(data, 'sequence_index', minimum=1, maximum=4)
    due_date = mw.as_date(data, 'due_date')

    gates.require_not_frozen(account)

    for other in store.account_milestones(account['id']):
        if other['state'] == 'WAIVED':
            continue
        if other['milestone_code'] == milestone_code:
            raise ApiError('ERR_MILESTONE_CODE_DUPLICATE',
                           'milestone_code %s already exists on this account.'
                           % milestone_code)
        if other['sequence_index'] == sequence_index:
            raise ApiError('ERR_MILESTONE_CODE_DUPLICATE',
                           'sequence_index %d already exists on this account.'
                           % sequence_index)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'milestone_code': milestone_code,
        'sequence_index': sequence_index,
        'due_date': data['due_date'],
        '_due_date': due_date,
        'completed_date': None,
        '_completed_date': None,
        'state': 'PENDING',
        'days_late': None,
    })
    db.onboarding_milestones[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.onboarding_milestone, row, 201)


@bp.route('/accounts/<account_id>/onboarding-milestones', methods=['GET'])
def list_milestones(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    state = mw.query_enum('state', MILESTONE_STATES)
    rows = store.account_milestones(account['id'])
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.onboarding_milestone, rows, limit, offset)


@bp.route('/onboarding-milestones/<milestone_id>/transition', methods=['POST'])
def transition_milestone(milestone_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    milestone = get_milestone(milestone_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', MILESTONE_ACTIONS)
    completed_date = None
    if action == 'COMPLETE':
        completed_date = mw.as_date(data, 'completed_date')

    account = db.accounts.get(milestone['account_id'])

    if action == 'COMPLETE':
        if milestone['state'] not in COMPLETABLE_STATES:
            raise gates.invalid_transition(
                'A milestone in state %s may not be completed.' % milestone['state'])
        if account is not None:
            gates.require_not_frozen(account)
            for other in store.account_milestones(account['id']):
                if other['sequence_index'] >= milestone['sequence_index']:
                    continue
                if other['state'] not in ('COMPLETED', 'WAIVED'):
                    raise ApiError('ERR_MILESTONE_SEQUENCE_VIOLATION',
                                   'Milestone %s at sequence %d is still %s.'
                                   % (other['milestone_code'],
                                      other['sequence_index'], other['state']))
        touch(milestone)
        milestone['state'] = 'COMPLETED'
        milestone['completed_date'] = data['completed_date']
        milestone['_completed_date'] = completed_date
        late = (completed_date - milestone['_due_date']).days
        milestone['days_late'] = late if late > 0 else 0
    else:
        if milestone['state'] not in WAIVABLE_STATES:
            raise gates.invalid_transition(
                'A milestone in state %s may not be waived.' % milestone['state'])
        touch(milestone)
        milestone['state'] = 'WAIVED'

    if account is not None:
        derive.recompute_ttv(account)
        lifecycle.evaluate_onboarding_completion(account)
    return resp.entity(serialize.onboarding_milestone, milestone, 200)
