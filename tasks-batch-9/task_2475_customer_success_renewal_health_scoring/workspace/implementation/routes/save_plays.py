"""Save plays: E32-E35."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import derive, gates, risk, serialize
from services.lookup import account as get_account
from services.lookup import csm as get_csm
from services.lookup import save_play as get_play

bp = Blueprint('save_plays', __name__)

RISK_CODES = ('ADOPTION_DECLINE', 'SUPPORT_ESCALATION', 'SPONSOR_LOSS',
              'OUTCOME_MISS', 'BUDGET_PRESSURE')
PLAY_TYPES = ('EXEC_ALIGNMENT', 'ENABLEMENT_SPRINT', 'COMMERCIAL_CONCESSION',
              'TECHNICAL_REMEDIATION')
PLAY_STATES = ('DRAFT', 'ACTIVE', 'SUCCEEDED', 'FAILED', 'ABANDONED')
PLAY_ACTIONS = ('ACTIVATE', 'SUCCEED', 'FAIL', 'ABANDON')
LIVE_ESCALATION_STATES = ('OPEN', 'COMMITTED', 'DISPUTED')


def _escalation_clear(play):
    for case in store.save_play_escalations(play['id']):
        if case['state'] in LIVE_ESCALATION_STATES:
            return False
    return True


@bp.route('/save-plays', methods=['POST'])
def create_save_play():
    mw.authenticate(('CsmUser',))
    data = mw.body()
    # rule 4: body foreign keys resolve before the schema is examined
    account_ref = mw.raw_id(data, 'account_id')
    if account_ref is not None:
        get_account(account_ref)
    csm_ref = mw.raw_id(data, 'owner_csm_id')
    if csm_ref is not None:
        get_csm(csm_ref)

    account_id = mw.as_id(data, 'account_id')
    owner_csm_id = mw.as_id(data, 'owner_csm_id')
    risk_code = mw.as_enum(data, 'risk_code', RISK_CODES)
    play_type = mw.as_enum(data, 'play_type', PLAY_TYPES)
    window_start = mw.as_date(data, 'window_start_date')
    window_end = mw.as_date(data, 'window_end_date')
    if window_end < window_start:
        raise ApiError('ERR_INVALID_ENGAGEMENT_INTERVAL',
                       'window_end_date must be on or after window_start_date.')

    account = db.accounts[account_id]
    gates.require_not_frozen(account)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'owner_csm_id': owner_csm_id,
        'risk_code': risk_code,
        'play_type': play_type,
        'window_start_date': data['window_start_date'],
        '_window_start_date': window_start,
        'window_end_date': data['window_end_date'],
        '_window_end_date': window_end,
        'state': 'DRAFT',
        'outcome_note': None,
    })
    db.save_plays[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.save_play, row, 201)


@bp.route('/save-plays/<play_id>', methods=['GET'])
def read_save_play(play_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    play = get_play(play_id)
    return resp.entity(serialize.save_play, play, 200)


@bp.route('/save-plays', methods=['GET'])
def list_save_plays():
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    limit, offset = mw.pagination()
    account_id = mw.query_value('account_id')
    owner_csm_id = mw.query_value('owner_csm_id')
    state = mw.query_enum('state', PLAY_STATES)
    rows = store.ordered(db.save_plays)
    if account_id is not None:
        rows = [r for r in rows if r['account_id'] == account_id]
    if owner_csm_id is not None:
        rows = [r for r in rows if r['owner_csm_id'] == owner_csm_id]
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.save_play, rows, limit, offset)


@bp.route('/save-plays/<play_id>/transition', methods=['POST'])
def transition_save_play(play_id):
    mw.authenticate(('CsmUser',))
    play = get_play(play_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', PLAY_ACTIONS)
    outcome_note = mw.as_string(data, 'outcome_note', required=False)

    account = db.accounts.get(play['account_id'])
    state = play['state']

    if action == 'ACTIVATE':
        if state != 'DRAFT':
            raise gates.invalid_transition(
                'Only a DRAFT save play may be activated; this one is %s.' % state)
        if account is not None:
            gates.require_health_tier(account, ('RED', 'AMBER'))
        owner = db.csms.get(play['owner_csm_id'])
        if owner is None or owner['status'] != 'ACTIVE':
            raise gates.invalid_transition(
                'The owning CSM must be ACTIVE to activate a save play.')
        if account is not None and not risk.save_play_day_capacity_ok(
                account['id'], play):
            raise ApiError('ERR_SAVE_PLAY_WINDOW_CAPACITY',
                           'A calendar day inside the window already carries the '
                           'maximum number of ACTIVE save plays.')
        touch(play)
        play['state'] = 'ACTIVE'
        if account is not None:
            risk.increment_open_plays(account)
            derive.derive_coverage_posture(account)
        return resp.entity(serialize.save_play, play, 200)

    if action == 'SUCCEED':
        if state != 'ACTIVE':
            raise gates.invalid_transition(
                'Only an ACTIVE save play may succeed; this one is %s.' % state)
        if not _escalation_clear(play):
            raise gates.invalid_transition(
                'An escalation case of this save play is still live.')
        touch(play)
        play['state'] = 'SUCCEEDED'
        if outcome_note is not None:
            play['outcome_note'] = outcome_note
        if account is not None:
            risk.decrement_open_plays(account)
            derive.recompute_renewal_likelihood(account)
            derive.derive_coverage_posture(account)
        return resp.entity(serialize.save_play, play, 200)

    if action == 'FAIL':
        if state != 'ACTIVE':
            raise gates.invalid_transition(
                'Only an ACTIVE save play may fail; this one is %s.' % state)
        touch(play)
        risk.fail_save_play(play, outcome_note)
        return resp.entity(serialize.save_play, play, 200)

    # ABANDON
    if state not in ('DRAFT', 'ACTIVE'):
        raise gates.invalid_transition(
            'A save play in state %s may not be abandoned.' % state)
    if state == 'ACTIVE' and not _escalation_clear(play):
        raise gates.invalid_transition(
            'An escalation case of this save play is still live.')
    was_active = state == 'ACTIVE'
    touch(play)
    play['state'] = 'ABANDONED'
    if outcome_note is not None:
        play['outcome_note'] = outcome_note
    if account is not None:
        if was_active:
            risk.decrement_open_plays(account)
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
    return resp.entity(serialize.save_play, play, 200)
