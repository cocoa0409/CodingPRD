"""Expansion opportunities and the sales handoff: E48-E51."""
from decimal import Decimal as D

from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, gates, serialize
from services.lookup import account as get_account
from services.lookup import expansion_opportunity as get_opportunity

bp = Blueprint('expansion', __name__)

SOURCE_SIGNALS = ('SEAT_SATURATION', 'FEATURE_DEPTH', 'EXEC_REQUEST',
                  'OUTCOME_OVERACHIEVEMENT')
OPPORTUNITY_STATES = ('IDENTIFIED', 'HANDED_OFF', 'ACCEPTED', 'REJECTED',
                      'RECYCLED', 'EXPIRED')
OPPORTUNITY_ACTIONS = ('HANDOFF', 'ACCEPT', 'REJECT', 'RECYCLE')


def _score(account):
    """The qualification score always reads the trailing health figure."""
    return calc.qualification_score(account['trended_health_score'],
                                    account['adoption_index'],
                                    account['arr_cents'])


def _new_opportunity(account, estimated_value_cents, source_signal,
                     recycled_from_opportunity_id=None):
    row = base_row()
    row.update({
        'account_id': account['id'],
        'recycled_from_opportunity_id': recycled_from_opportunity_id,
        'estimated_value_cents': estimated_value_cents,
        'source_signal': source_signal,
        'qualification_score': _score(account),
        'state': 'IDENTIFIED',
        'handoff_ae_user_id': None,
        'rejection_reason': None,
        'identified_at': db.clock_stamp(),
        '_identified_at': db.now(),
    })
    db.expansion_opportunities[row['id']] = row
    mark_fresh(row)
    return row


@bp.route('/expansion-opportunities', methods=['POST'])
def create_opportunity():
    mw.authenticate(('CsmUser',))
    data = mw.body()
    # rule 4: the body foreign key resolves before the schema is examined
    account_ref = mw.raw_id(data, 'account_id')
    if account_ref is not None:
        get_account(account_ref)

    account_id = mw.as_id(data, 'account_id')
    estimated_value_cents = mw.as_int(data, 'estimated_value_cents', minimum=1)
    source_signal = mw.as_enum(data, 'source_signal', SOURCE_SIGNALS)

    account = db.accounts[account_id]
    gates.require_not_frozen(account)

    row = _new_opportunity(account, estimated_value_cents, source_signal)
    return resp.entity(serialize.expansion_opportunity, row, 201)


@bp.route('/expansion-opportunities/<opportunity_id>', methods=['GET'])
def read_opportunity(opportunity_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'SalesAccountExecutive'))
    opportunity = get_opportunity(opportunity_id)
    return resp.entity(serialize.expansion_opportunity, opportunity, 200)


@bp.route('/expansion-opportunities', methods=['GET'])
def list_opportunities():
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'SalesAccountExecutive'))
    limit, offset = mw.pagination()
    account_id = mw.query_value('account_id')
    recycled_from = mw.query_value('recycled_from_opportunity_id')
    state = mw.query_enum('state', OPPORTUNITY_STATES)
    rows = store.ordered(db.expansion_opportunities)
    if account_id is not None:
        rows = [r for r in rows if r['account_id'] == account_id]
    if recycled_from is not None:
        rows = [r for r in rows
                if r['recycled_from_opportunity_id'] == recycled_from]
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.expansion_opportunity, rows, limit, offset)


@bp.route('/expansion-opportunities/<opportunity_id>/transition', methods=['POST'])
def transition_opportunity(opportunity_id):
    actor, _role = mw.authenticate(('CsmUser', 'SalesAccountExecutive'))
    opportunity = get_opportunity(opportunity_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', OPPORTUNITY_ACTIONS)
    handoff_ae_user_id = mw.as_id(data, 'handoff_ae_user_id',
                                  required=(action == 'HANDOFF'))
    rejection_reason = mw.as_string(data, 'rejection_reason',
                                    required=(action == 'REJECT'))

    # rule 7 outranks rule 12: ownership of a handoff is tested before the edge
    if action in ('ACCEPT', 'REJECT') and actor != opportunity['handoff_ae_user_id']:
        raise ApiError('ERR_NOT_HANDOFF_OWNER',
                       'Only the account executive named in handoff_ae_user_id may '
                       'dispose of this opportunity.')

    state = opportunity['state']
    if action == 'HANDOFF' and state != 'IDENTIFIED':
        raise gates.invalid_transition(
            'Only an IDENTIFIED opportunity may be handed off; this one is %s.'
            % state)
    if action in ('ACCEPT', 'REJECT') and state != 'HANDED_OFF':
        raise gates.invalid_transition(
            'Only a HANDED_OFF opportunity may be %sed; this one is %s.'
            % (action.lower(), state))
    if action == 'RECYCLE' and state != 'REJECTED':
        raise gates.invalid_transition(
            'Only a REJECTED opportunity may be recycled; this one is %s.' % state)

    account = db.accounts.get(opportunity['account_id'])
    if account is not None:
        # rule 13 applies to every action of this endpoint
        gates.require_not_frozen(account)

    if action == 'HANDOFF':
        if account is not None:
            gates.require_open(account)
            gates.require_health_tier(account, ('AMBER', 'GREEN'))
        if D(opportunity['qualification_score']) < calc.EXPANSION_HANDOFF_FLOOR:
            raise ApiError('ERR_QUALIFICATION_SCORE_TOO_LOW',
                           'The qualification score %s is below the handoff floor '
                           'of %s.' % (opportunity['qualification_score'],
                                       calc.EXPANSION_HANDOFF_FLOOR))
        touch(opportunity)
        opportunity['state'] = 'HANDED_OFF'
        opportunity['handoff_ae_user_id'] = handoff_ae_user_id
        return resp.entity(serialize.expansion_opportunity, opportunity, 200)

    if action == 'ACCEPT':
        touch(opportunity)
        opportunity['state'] = 'ACCEPTED'
        return resp.entity(serialize.expansion_opportunity, opportunity, 200)

    if action == 'REJECT':
        touch(opportunity)
        opportunity['state'] = 'REJECTED'
        opportunity['rejection_reason'] = rejection_reason
        return resp.entity(serialize.expansion_opportunity, opportunity, 200)

    # RECYCLE: the predecessor becomes terminal and a freshly scored successor is
    # created in the same request; the response carries the predecessor.
    touch(opportunity)
    opportunity['state'] = 'RECYCLED'
    if account is not None:
        _new_opportunity(account, opportunity['estimated_value_cents'],
                         opportunity['source_signal'],
                         recycled_from_opportunity_id=opportunity['id'])
    return resp.entity(serialize.expansion_opportunity, opportunity, 200)
