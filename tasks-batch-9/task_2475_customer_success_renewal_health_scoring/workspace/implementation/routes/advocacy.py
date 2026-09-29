"""Advocacy enrollments: E52-E54."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import gates, serialize
from services.lookup import account as get_account
from services.lookup import advocacy_enrollment as get_enrollment

bp = Blueprint('advocacy', __name__)

PROGRAM_TYPES = ('CAB', 'REFERENCE')
ENROLLMENT_STATES = ('NOMINATED', 'APPROVED', 'ACTIVE', 'SUSPENDED', 'GRADUATED',
                     'REVOKED')
ENROLLMENT_ACTIONS = ('APPROVE', 'ACTIVATE', 'SUSPEND', 'LOG_REFERENCE_CALL',
                      'GRADUATE', 'REVOKE')
REVOCABLE_STATES = ('NOMINATED', 'APPROVED', 'ACTIVE', 'SUSPENDED')
ACTIVATABLE_STATES = ('APPROVED', 'SUSPENDED')


@bp.route('/accounts/<account_id>/advocacy-enrollments', methods=['POST'])
def create_enrollment(account_id):
    mw.authenticate(('AdvocacyManager',))
    account = get_account(account_id)
    data = mw.body()
    program_type = mw.as_enum(data, 'program_type', PROGRAM_TYPES)

    gates.require_not_frozen(account)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'program_type': program_type,
        'state': 'NOMINATED',
        'reference_calls_used': 0,
        # snapshotted at creation and never rewritten when the account is re-banded
        'reference_calls_cap': account['reference_calls_cap'],
        'last_reference_call_at': None,
    })
    db.advocacy_enrollments[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.advocacy_enrollment, row, 201)


@bp.route('/accounts/<account_id>/advocacy-enrollments', methods=['GET'])
def list_enrollments(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'AdvocacyManager'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    state = mw.query_enum('state', ENROLLMENT_STATES)
    program_type = mw.query_enum('program_type', PROGRAM_TYPES)
    rows = store.account_enrollments(account['id'])
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    if program_type is not None:
        rows = [r for r in rows if r['program_type'] == program_type]
    return resp.collection(serialize.advocacy_enrollment, rows, limit, offset)


@bp.route('/advocacy-enrollments/<enrollment_id>/transition', methods=['POST'])
def transition_enrollment(enrollment_id):
    mw.authenticate(('AdvocacyManager',))
    enrollment = get_enrollment(enrollment_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', ENROLLMENT_ACTIONS)

    account = db.accounts.get(enrollment['account_id'])
    state = enrollment['state']

    if action == 'APPROVE':
        if state != 'NOMINATED':
            raise gates.invalid_transition(
                'Only a NOMINATED enrollment may be approved; this one is %s.'
                % state)
        if account is not None:
            gates.require_open(account)
            gates.require_health_tier(account, ('GREEN',))
        touch(enrollment)
        enrollment['state'] = 'APPROVED'
        return resp.entity(serialize.advocacy_enrollment, enrollment, 200)

    if action == 'ACTIVATE':
        if state not in ACTIVATABLE_STATES:
            raise gates.invalid_transition(
                'An enrollment in state %s may not be activated.' % state)
        if account is not None:
            gates.require_health_tier(account, ('AMBER', 'GREEN'))
        touch(enrollment)
        enrollment['state'] = 'ACTIVE'
        return resp.entity(serialize.advocacy_enrollment, enrollment, 200)

    if action == 'SUSPEND':
        if state != 'ACTIVE':
            raise gates.invalid_transition(
                'Only an ACTIVE enrollment may be suspended; this one is %s.'
                % state)
        touch(enrollment)
        enrollment['state'] = 'SUSPENDED'
        return resp.entity(serialize.advocacy_enrollment, enrollment, 200)

    if action == 'LOG_REFERENCE_CALL':
        if state != 'ACTIVE':
            raise gates.invalid_transition(
                'A reference call may only be logged against an ACTIVE '
                'enrollment; this one is %s.' % state)
        # rule 32: the programme and the remaining quota share one error code
        if (enrollment['program_type'] != 'REFERENCE'
                or enrollment['reference_calls_used']
                >= enrollment['reference_calls_cap']):
            raise ApiError('ERR_REFERENCE_CALL_CAP_REACHED',
                           'This enrollment has no reference-call quota left.')
        touch(enrollment)
        enrollment['reference_calls_used'] += 1
        enrollment['last_reference_call_at'] = db.clock_stamp()
        return resp.entity(serialize.advocacy_enrollment, enrollment, 200)

    if action == 'GRADUATE':
        if state != 'ACTIVE':
            raise gates.invalid_transition(
                'Only an ACTIVE enrollment may graduate; this one is %s.' % state)
        if (enrollment['program_type'] == 'REFERENCE'
                and enrollment['reference_calls_used'] < 1):
            raise gates.invalid_transition(
                'A REFERENCE enrollment may not graduate before giving at least '
                'one reference.')
        touch(enrollment)
        enrollment['state'] = 'GRADUATED'
        return resp.entity(serialize.advocacy_enrollment, enrollment, 200)

    # REVOKE
    if state not in REVOCABLE_STATES:
        raise gates.invalid_transition(
            'An enrollment in state %s may not be revoked.' % state)
    touch(enrollment)
    enrollment['state'] = 'REVOKED'
    return resp.entity(serialize.advocacy_enrollment, enrollment, 200)
