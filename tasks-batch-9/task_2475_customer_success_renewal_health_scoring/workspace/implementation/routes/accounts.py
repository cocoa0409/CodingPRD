"""Accounts: E1-E8."""
from decimal import Decimal as D

from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, derive, lifecycle, serialize
from services.lookup import account as get_account

bp = Blueprint('accounts', __name__)

SEGMENT_BANDS = ('ENTERPRISE', 'MIDMARKET', 'SMB')
LIFECYCLE_STATES = ('ONBOARDING', 'ADOPTING', 'STEADY', 'AT_RISK', 'RENEWED',
                    'CHURNED', 'WIN_BACK_TARGETED', 'ARCHIVED')
COVERAGE_TIERS = ('UNASSIGNED', 'HIGH_TOUCH', 'LOW_TOUCH', 'DIGITAL')
RENEWAL_LIKELIHOODS = ('COMMIT', 'UPSIDE', 'AT_RISK', 'OMIT')
HEALTH_TIERS = ('RED', 'AMBER', 'GREEN')


@bp.route('/accounts', methods=['POST'])
def create_account():
    mw.authenticate(('CsOpsAdmin',))
    data = mw.body()
    name = mw.as_string(data, 'name', max_len=120)
    arr_cents = mw.as_int(data, 'arr_cents', minimum=0)
    segment_band = mw.as_enum(data, 'segment_band', SEGMENT_BANDS)
    contract_start = mw.as_date(data, 'contract_start_date')
    contract_end = mw.as_date(data, 'contract_end_date')
    if contract_end <= contract_start:
        raise ApiError('ERR_INVALID_ENGAGEMENT_INTERVAL',
                       'contract_end_date must be strictly after '
                       'contract_start_date.')

    row = base_row()
    row.update({
        'name': name,
        'arr_cents': arr_cents,
        'segment_band': segment_band,
        'contract_start_date': data['contract_start_date'],
        '_contract_start_date': contract_start,
        'contract_end_date': data['contract_end_date'],
        '_contract_end_date': contract_end,
        'lifecycle_state': 'ONBOARDING',
        'adoption_index': D('0.00'),
        'support_risk_penalty': D('0.00'),
        'exec_engagement_score': D('0.00'),
        'outcome_attainment_index': D('0.00'),
        'snapshot_health_score': D('0.00'),
        'trended_health_score': D('0.00'),
        'health_tier': 'RED',
        'coverage_tier': 'UNASSIGNED',
        'coverage_posture': 'RESTRICTED',
        'assigned_csm_id': None,
        'open_save_play_count': 0,
        'ttv_breach_flag': False,
        'contractual_ttv_days': None,
        'activation_ttv_days': None,
        'renewal_likelihood': 'AT_RISK',
        'churn_root_cause_code': None,
        'win_back_offer_bp': None,
        'remediation_credit_outstanding_cents': 0,
        'remediation_credit_settled_cents': 0,
        'reference_calls_cap': calc.REFERENCE_CALL_CAP[segment_band],
    })
    db.accounts[row['id']] = row
    mark_fresh(row)
    derive.recompute_all_components(row)
    derive.recompute_renewal_likelihood(row)
    derive.derive_coverage_posture(row)
    return resp.entity(serialize.account, row, 201)


@bp.route('/accounts/<account_id>', methods=['GET'])
def read_account(account_id):
    mw.authenticate(mw.ALL_ROLES)
    account = get_account(account_id)
    return resp.entity(serialize.account, account, 200)


@bp.route('/accounts', methods=['GET'])
def list_accounts():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    assigned_csm_id = mw.query_value('assigned_csm_id')
    health_tier = mw.query_enum('health_tier', HEALTH_TIERS)
    coverage_tier = mw.query_enum('coverage_tier', COVERAGE_TIERS)
    lifecycle_state = mw.query_enum('lifecycle_state', LIFECYCLE_STATES)
    renewal = mw.query_enum('renewal_likelihood', RENEWAL_LIKELIHOODS)
    rows = store.ordered(db.accounts)
    if assigned_csm_id is not None:
        rows = [r for r in rows if r['assigned_csm_id'] == assigned_csm_id]
    if health_tier is not None:
        rows = [r for r in rows if r['health_tier'] == health_tier]
    if coverage_tier is not None:
        rows = [r for r in rows if r['coverage_tier'] == coverage_tier]
    if lifecycle_state is not None:
        rows = [r for r in rows if r['lifecycle_state'] == lifecycle_state]
    if renewal is not None:
        rows = [r for r in rows if r['renewal_likelihood'] == renewal]
    return resp.collection(serialize.account, rows, limit, offset)


@bp.route('/accounts/<account_id>', methods=['PATCH'])
def patch_account(account_id):
    mw.authenticate(('CsOpsAdmin',))
    account = get_account(account_id)
    data = mw.body()
    name = mw.as_string(data, 'name', required=False, max_len=120)
    arr_cents = mw.as_int(data, 'arr_cents', required=False, minimum=0)
    segment_band = mw.as_enum(data, 'segment_band', SEGMENT_BANDS, required=False)
    contract_end = mw.as_date(data, 'contract_end_date', required=False)
    if contract_end is not None and contract_end <= db.today():
        raise ApiError('ERR_CONTRACT_END_IN_PAST',
                       'contract_end_date must be strictly after the current '
                       'logical date.')

    touch(account)
    previous_end = account['_contract_end_date']
    if name is not None:
        account['name'] = name
    if arr_cents is not None:
        account['arr_cents'] = arr_cents
    segment_changed = False
    if segment_band is not None and segment_band != account['segment_band']:
        account['segment_band'] = segment_band
        segment_changed = True
    elif segment_band is not None:
        account['segment_band'] = segment_band
    if contract_end is not None:
        account['contract_end_date'] = data['contract_end_date']
        account['_contract_end_date'] = contract_end
    if segment_changed:
        derive.recompute_reference_calls_cap(account)
    derive.recompute_renewal_likelihood(account)
    if (account['lifecycle_state'] == 'RENEWED' and contract_end is not None
            and contract_end > previous_end):
        account['lifecycle_state'] = 'STEADY'
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
    return resp.entity(serialize.account, account, 200)


@bp.route('/accounts/<account_id>/lifecycle', methods=['POST'])
def account_lifecycle(account_id):
    mw.authenticate(('CsOpsAdmin',))
    account = get_account(account_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', lifecycle.LIFECYCLE_ACTIONS)
    churn_code = None
    win_back_offer_bp = None
    new_end = None
    if action == 'CHURN':
        churn_code = mw.as_enum(data, 'churn_root_cause_code',
                                lifecycle.CHURN_ROOT_CAUSE_CODES)
    elif action == 'WIN_BACK_TARGET':
        win_back_offer_bp = mw.as_int(data, 'win_back_offer_bp', minimum=0,
                                      maximum=5000)
    elif action == 'REACTIVATE':
        new_end = mw.as_date(data, 'new_contract_end_date')

    touch(account)
    lifecycle.apply_action(
        account, action,
        churn_root_cause_code=churn_code,
        win_back_offer_bp=win_back_offer_bp,
        new_contract_end_date=new_end,
        new_contract_end_raw=data.get('new_contract_end_date'))
    return resp.entity(serialize.account, account, 200)


@bp.route('/accounts/<account_id>/health-recompute', methods=['POST'])
def health_recompute(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    account = get_account(account_id)
    touch(account)
    derive.recompute_all_components(account)
    derive.recompute_renewal_likelihood(account)
    lifecycle.evaluate_health_lifecycle_edges(account)
    derive.derive_coverage_posture(account)
    return resp.entity(serialize.account, account, 200)


@bp.route('/accounts/<account_id>/segmentation', methods=['POST'])
def account_segmentation(account_id):
    mw.authenticate(('CsOpsAdmin',))
    account = get_account(account_id)
    touch(account)
    derive.recompute_coverage_tier(account)
    return resp.entity(serialize.account, account, 200)


@bp.route('/accounts/<account_id>/health-summary', methods=['GET'])
def health_summary(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    usage_rows = derive.usage_rows_recent_first(account['id'])
    considered = min(calc.ADOPTION_LOOKBACK_ROWS, len(usage_rows))
    support_component = D('100.00') - D(account['support_risk_penalty'])
    delta = calc.r2(D(account['snapshot_health_score'])
                    - D(account['trended_health_score']))
    data = {
        'account_id': account['id'],
        'adoption_index': serialize._score(account['adoption_index']),
        'support_component': serialize._score(support_component),
        'exec_engagement_score': serialize._score(account['exec_engagement_score']),
        'outcome_attainment_index': serialize._score(
            account['outcome_attainment_index']),
        'snapshot_health_score': serialize._score(account['snapshot_health_score']),
        'trended_health_score': serialize._score(account['trended_health_score']),
        'variant_delta': serialize._score(delta),
        'health_tier': account['health_tier'],
        'usage_rows_considered': considered,
    }
    return resp.payload(data, 200)
