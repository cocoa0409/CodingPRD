"""Outcome goals: E26-E28."""
from decimal import Decimal as D

from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, derive, gates, serialize
from services.lookup import account as get_account
from services.lookup import outcome_goal as get_goal

bp = Blueprint('goals', __name__)

GOAL_STATUSES = ('DEFINED', 'IN_PROGRESS', 'ATTAINED', 'MISSED', 'WAIVED')
PROGRESS_STATUSES = ('IN_PROGRESS', 'ATTAINED', 'MISSED', 'WAIVED')
DEAD_LIFECYCLES = ('CHURNED', 'ARCHIVED')


def _recompute_after_create(account):
    """Goal creation carries the full chain (PRD 3.3)."""
    derive.recompute_outcome_attainment_index(account)
    derive.recompute_health_scores(account)
    derive.recompute_renewal_likelihood(account)
    derive.derive_coverage_posture(account)


def _recompute_after_progress(account):
    """A progress update recomputes the account index and both health variants
    only; the tier follows from the point-in-time variant."""
    derive.recompute_outcome_attainment_index(account)
    derive.recompute_health_scores(account)


@bp.route('/accounts/<account_id>/outcome-goals', methods=['POST'])
def create_goal(account_id):
    mw.authenticate(('CsmUser',))
    account = get_account(account_id)
    data = mw.body()
    title = mw.as_string(data, 'title')
    target_value = mw.as_decimal(data, 'target_value', exclusive_minimum=0)
    actual_value = mw.as_decimal(data, 'actual_value', required=False, minimum=0)
    if actual_value is None:
        actual_value = D('0')
    weight_bp = mw.as_int(data, 'weight_bp', minimum=1,
                          maximum=calc.MAX_TOTAL_WEIGHT_BP)

    gates.require_not_frozen(account)

    live_weight = sum(g['weight_bp'] for g in store.account_goals(account['id'])
                      if g['status'] != 'WAIVED')
    if live_weight + weight_bp > calc.MAX_TOTAL_WEIGHT_BP:
        raise ApiError('ERR_WEIGHT_TOTAL_INVALID',
                       'The account outcome weight budget of %d basis points '
                       'would be exceeded.' % calc.MAX_TOTAL_WEIGHT_BP)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'title': title,
        'target_value': target_value,
        'actual_value': actual_value,
        'weight_bp': weight_bp,
        'status': 'DEFINED',
        'attainment_pct': calc.attainment_pct(actual_value, target_value),
    })
    db.outcome_goals[row['id']] = row
    mark_fresh(row)
    _recompute_after_create(account)
    return resp.entity(serialize.outcome_goal, row, 201)


@bp.route('/accounts/<account_id>/outcome-goals', methods=['GET'])
def list_goals(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    status = mw.query_enum('status', GOAL_STATUSES)
    rows = store.account_goals(account['id'])
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return resp.collection(serialize.outcome_goal, rows, limit, offset)


@bp.route('/outcome-goals/<goal_id>/progress', methods=['POST'])
def goal_progress(goal_id):
    mw.authenticate(('CsmUser',))
    goal = get_goal(goal_id)
    data = mw.body()
    status = mw.as_enum(data, 'status', PROGRESS_STATUSES)
    actual_value = mw.as_decimal(data, 'actual_value', required=False, minimum=0)

    current = goal['status']
    account = db.accounts.get(goal['account_id'])

    if status == 'IN_PROGRESS':
        if current not in ('DEFINED', 'IN_PROGRESS'):
            raise gates.invalid_transition(
                'A goal in status %s may not record progress.' % current)
        if account is not None and account['lifecycle_state'] in DEAD_LIFECYCLES:
            raise gates.invalid_transition(
                'The account lifecycle state %s does not accept goal progress.'
                % account['lifecycle_state'])
    elif status in ('ATTAINED', 'MISSED'):
        if current != 'IN_PROGRESS':
            raise gates.invalid_transition(
                'Only an IN_PROGRESS goal may be %s; this one is %s.'
                % (status, current))
    else:  # WAIVED
        if current not in ('DEFINED', 'IN_PROGRESS'):
            raise gates.invalid_transition(
                'A goal in status %s may not be waived.' % current)

    effective = actual_value if actual_value is not None else D(goal['actual_value'])
    if status == 'ATTAINED' and effective < D(goal['target_value']):
        raise gates.invalid_transition(
            'actual_value must be at least target_value to attain a goal.')

    touch(goal)
    if actual_value is not None:
        goal['actual_value'] = actual_value
    goal['status'] = status
    goal['attainment_pct'] = calc.attainment_pct(goal['actual_value'],
                                                 goal['target_value'])
    if status == 'ATTAINED':
        goal['attainment_pct'] = D('100.00')

    if account is not None:
        _recompute_after_progress(account)
        if status == 'ATTAINED':
            goal['attainment_pct'] = D('100.00')
    return resp.entity(serialize.outcome_goal, goal, 200)
