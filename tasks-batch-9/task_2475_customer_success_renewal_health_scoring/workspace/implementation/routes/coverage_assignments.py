"""Coverage assignments: E12-E15."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, coverage, derive, serialize
from services.lookup import account as get_account
from services.lookup import coverage_assignment as get_assignment
from services.lookup import csm as get_csm

bp = Blueprint('coverage_assignments', __name__)

ASSIGNMENT_STATES = ('QUEUED', 'COMMITTED', 'RELEASED', 'PREEMPTED')


@bp.route('/coverage-assignments', methods=['POST'])
def create_assignment():
    mw.authenticate(('CsOpsAdmin',))
    data = mw.body()
    # rule 4: body foreign keys resolve before schema validation
    account_ref = mw.raw_id(data, 'account_id')
    if account_ref is not None:
        get_account(account_ref)
    csm_ref = mw.raw_id(data, 'csm_id')
    if csm_ref is not None:
        get_csm(csm_ref)

    account_id = mw.as_id(data, 'account_id')
    expected_version = mw.as_int(data, 'expected_account_version', minimum=0)
    csm_id = mw.as_id(data, 'csm_id', required=False)

    account = db.accounts[account_id]
    if expected_version != account['version']:
        raise ApiError('ERR_STALE_ACCOUNT_VERSION',
                       'expected_account_version %s does not match the stored '
                       'version %s.' % (expected_version, account['version']))
    if account['coverage_tier'] == 'UNASSIGNED':
        raise ApiError('ERR_COVERAGE_TIER_UNASSIGNED',
                       'The account has no coverage tier yet; run segmentation '
                       'first.')

    if csm_id is not None:
        csm = db.csms[csm_id]
        if (csm['status'] != 'ACTIVE'
                or csm['coverage_specialty'] != account['coverage_tier']):
            raise ApiError('ERR_NO_ELIGIBLE_CSM',
                           'Csm %s is not an eligible manager for coverage tier '
                           '%s.' % (csm_id, account['coverage_tier']))
    else:
        csm = coverage.select_csm(account)
        if csm is None:
            raise ApiError('ERR_NO_ELIGIBLE_CSM',
                           'No ACTIVE Csm specialises in coverage tier %s.'
                           % account['coverage_tier'])

    row = base_row()
    row.update({
        'account_id': account['id'],
        'csm_id': csm['id'],
        'coverage_tier': account['coverage_tier'],
        'load_units': calc.coverage_load_units(
            account['coverage_tier'], account['segment_band'],
            account['health_tier'], account['arr_cents']),
        'state': 'QUEUED',
        'committed_at': None,
        'released_at': None,
        'release_reason': None,
        'superseded_by_assignment_id': None,
    })
    db.coverage_assignments[row['id']] = row
    mark_fresh(row)

    coverage.admit(row, csm)
    coverage.preempt_predecessors(account, row)
    coverage.sync_assigned_csm(account)
    derive.derive_coverage_posture(account)
    return resp.entity(serialize.coverage_assignment, row, 201)


@bp.route('/coverage-assignments/<assignment_id>', methods=['GET'])
def read_assignment(assignment_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    assignment = get_assignment(assignment_id)
    return resp.entity(serialize.coverage_assignment, assignment, 200)


@bp.route('/coverage-assignments', methods=['GET'])
def list_assignments():
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    limit, offset = mw.pagination()
    account_id = mw.query_value('account_id')
    csm_id = mw.query_value('csm_id')
    state = mw.query_enum('state', ASSIGNMENT_STATES)
    superseded_by = mw.query_value('superseded_by_assignment_id')
    rows = store.ordered(db.coverage_assignments)
    if account_id is not None:
        rows = [r for r in rows if r['account_id'] == account_id]
    if csm_id is not None:
        rows = [r for r in rows if r['csm_id'] == csm_id]
    if state is not None:
        rows = [r for r in rows if r['state'] == state]
    if superseded_by is not None:
        rows = [r for r in rows
                if r['superseded_by_assignment_id'] == superseded_by]
    return resp.collection(serialize.coverage_assignment, rows, limit, offset)


@bp.route('/coverage-assignments/<assignment_id>/release', methods=['POST'])
def release_assignment(assignment_id):
    mw.authenticate(('CsOpsAdmin',))
    assignment = get_assignment(assignment_id)
    data = mw.body()
    release_reason = mw.as_string(data, 'release_reason', max_len=240)
    if assignment['state'] != 'COMMITTED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only a COMMITTED coverage assignment may be released; '
                       'this one is %s.' % assignment['state'])
    touch(assignment)
    coverage.release(assignment, release_reason)
    return resp.entity(serialize.coverage_assignment, assignment, 200)
