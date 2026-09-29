"""Executive engagements: E22-E25."""
from datetime import timedelta

from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, derive, gates, serialize
from services.lookup import account as get_account
from services.lookup import executive_engagement as get_engagement
from services.lookup import sponsor_contact as get_sponsor

bp = Blueprint('engagements', __name__)

ENGAGEMENT_TYPES = ('QBR', 'EBR', 'EXEC_SYNC')
ENGAGEMENT_STATES = ('SCHEDULED', 'HELD', 'NO_SHOW', 'CANCELLED')
OUTCOMES = ('HELD', 'NO_SHOW', 'CANCELLED')
BLOCKING_STATES = ('SCHEDULED', 'HELD')


def _conflicts(sponsor_contact_id, start_at, end_at):
    """The buffered calendar test spans every account, because a sponsor's time
    is finite regardless of which account books it."""
    buffer = timedelta(minutes=calc.EXEC_BUFFER_MINUTES)
    for other in store.sponsor_engagements(sponsor_contact_id):
        if other['state'] not in BLOCKING_STATES:
            continue
        if start_at < other['_end_at'] + buffer and end_at > other['_start_at'] - buffer:
            return other
    return None


@bp.route('/accounts/<account_id>/executive-engagements', methods=['POST'])
def create_engagement(account_id):
    mw.authenticate(('CsmUser', 'CsExecutive'))
    account = get_account(account_id)
    data = mw.body()
    # rule 4: the body foreign key is resolved before the schema is examined
    sponsor_ref = mw.raw_id(data, 'sponsor_contact_id')
    if sponsor_ref is not None:
        get_sponsor(sponsor_ref)

    sponsor_id = mw.as_id(data, 'sponsor_contact_id')
    engagement_type = mw.as_enum(data, 'engagement_type', ENGAGEMENT_TYPES)
    start_at = mw.as_datetime(data, 'start_at')
    end_at = mw.as_datetime(data, 'end_at')
    if end_at <= start_at:
        raise ApiError('ERR_INVALID_ENGAGEMENT_INTERVAL',
                       'end_at must be strictly after start_at.')

    gates.require_not_frozen(account)

    sponsor = db.sponsor_contacts[sponsor_id]
    if sponsor['status'] != 'ACTIVE':
        raise ApiError('ERR_SPONSOR_DEPARTED',
                       'Sponsor contact %s has departed.' % sponsor_id)
    if _conflicts(sponsor_id, start_at, end_at) is not None:
        raise ApiError('ERR_ENGAGEMENT_WINDOW_CONFLICT',
                       'The window conflicts with an existing engagement of this '
                       'sponsor, including the 30 minute travel buffer.')
    if sponsor['account_id'] != account['id']:
        raise ApiError('ERR_CROSS_ACCOUNT_REFERENCE',
                       'Sponsor contact %s belongs to another account.' % sponsor_id)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'sponsor_contact_id': sponsor_id,
        'engagement_type': engagement_type,
        'start_at': data['start_at'],
        '_start_at': start_at,
        'end_at': data['end_at'],
        '_end_at': end_at,
        'state': 'SCHEDULED',
        'outcome_recorded_at': None,
    })
    db.executive_engagements[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.executive_engagement, row, 201)


@bp.route('/accounts/<account_id>/executive-engagements', methods=['GET'])
def list_account_engagements(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    state = mw.query_enum('state', ENGAGEMENT_STATES)
    rows = store.account_engagements(account['id'])
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.executive_engagement, rows, limit, offset)


@bp.route('/sponsor-contacts/<sponsor_id>/executive-engagements', methods=['GET'])
def list_sponsor_engagements(sponsor_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    sponsor = get_sponsor(sponsor_id)
    limit, offset = mw.pagination()
    state = mw.query_enum('state', ENGAGEMENT_STATES)
    rows = store.sponsor_engagements(sponsor['id'])
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    return resp.collection(serialize.executive_engagement, rows, limit, offset)


@bp.route('/executive-engagements/<engagement_id>/outcome', methods=['POST'])
def record_outcome(engagement_id):
    mw.authenticate(('CsmUser', 'CsExecutive'))
    engagement = get_engagement(engagement_id)
    data = mw.body()
    outcome = mw.as_enum(data, 'outcome', OUTCOMES)

    if engagement['state'] != 'SCHEDULED':
        raise gates.invalid_transition(
            'Only a SCHEDULED engagement may record an outcome; this one is %s.'
            % engagement['state'])
    if outcome == 'HELD' and db.now() < engagement['_start_at']:
        raise gates.invalid_transition(
            'An engagement may not be recorded as HELD before it starts.')
    if outcome == 'NO_SHOW' and db.now() < engagement['_end_at']:
        raise gates.invalid_transition(
            'A no-show may only be recorded once the whole window has elapsed.')

    touch(engagement)
    engagement['state'] = outcome
    if outcome in ('HELD', 'NO_SHOW'):
        engagement['outcome_recorded_at'] = db.clock_stamp()
        account = db.accounts.get(engagement['account_id'])
        if account is not None:
            derive.recompute_exec_engagement_score(account)
            derive.recompute_health_scores(account)
            derive.recompute_renewal_likelihood(account)
            derive.derive_coverage_posture(account)
    return resp.entity(serialize.executive_engagement, engagement, 200)
