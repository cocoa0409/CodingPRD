"""Renewal forecasts and the finance reconciliation axis: E43-E47."""
import re

from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from errors import ApiError
from services import calc, gates, serialize
from services.lookup import account as get_account
from services.lookup import renewal_forecast as get_forecast

bp = Blueprint('forecasts', __name__)

FISCAL_PERIOD_RE = re.compile(r'^20\d{2}Q[1-4]$')
CS_STATES = ('DRAFT', 'SUBMITTED', 'LOCKED')
FINANCE_STATES = ('PENDING', 'RECONCILED', 'VARIANCE_FLAGGED')
RECONCILE_ACTIONS = ('RECONCILE', 'LOCK')


def _bottom_up(account, likelihood_category):
    return calc.cs_bottom_up_amount(account['arr_cents'], likelihood_category)


@bp.route('/renewal-forecasts', methods=['POST'])
def create_forecast():
    mw.authenticate(('CsmUser',))
    data = mw.body()
    # rule 4: the body foreign key resolves before the schema is examined
    account_ref = mw.raw_id(data, 'account_id')
    if account_ref is not None:
        get_account(account_ref)

    account_id = mw.as_id(data, 'account_id')
    fiscal_period = mw.as_string(data, 'fiscal_period')
    if not FISCAL_PERIOD_RE.match(fiscal_period):
        raise mw.invalid('fiscal_period must match ^20[0-9]{2}Q[1-4]$.')
    cs_amount_cents = mw.as_int(data, 'cs_amount_cents', required=False, minimum=0)

    account = db.accounts[account_id]
    gates.require_not_frozen(account)

    for other in store.account_forecasts(account['id']):
        if other['fiscal_period'] == fiscal_period:
            raise ApiError('ERR_FORECAST_PERIOD_DUPLICATE',
                           'A forecast for %s already exists on this account.'
                           % fiscal_period)

    likelihood_category = account['renewal_likelihood']
    if cs_amount_cents is None:
        cs_amount_cents = _bottom_up(account, likelihood_category)

    row = base_row()
    row.update({
        'account_id': account['id'],
        'fiscal_period': fiscal_period,
        'cs_amount_cents': cs_amount_cents,
        'finance_amount_cents': None,
        'variance_cents': None,
        'likelihood_category': likelihood_category,
        'cs_state': 'DRAFT',
        'finance_state': 'PENDING',
        'submitted_at': None,
        'reconciled_at': None,
    })
    db.renewal_forecasts[row['id']] = row
    mark_fresh(row)
    return resp.entity(serialize.renewal_forecast, row, 201)


@bp.route('/renewal-forecasts/<forecast_id>', methods=['GET'])
def read_forecast(forecast_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'FinanceAnalyst'))
    forecast = get_forecast(forecast_id)
    return resp.entity(serialize.renewal_forecast, forecast, 200)


@bp.route('/accounts/<account_id>/renewal-forecasts', methods=['GET'])
def list_forecasts(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'FinanceAnalyst'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    cs_state = mw.query_enum('cs_state', CS_STATES)
    finance_state = mw.query_enum('finance_state', FINANCE_STATES)
    rows = store.account_forecasts(account['id'])
    if cs_state is not None:
        rows = [r for r in rows if r['cs_state'] == cs_state]
    if finance_state is not None:
        rows = [r for r in rows if r['finance_state'] == finance_state]
    return resp.collection(serialize.renewal_forecast, rows, limit, offset)


@bp.route('/renewal-forecasts/<forecast_id>/submit', methods=['POST'])
def submit_forecast(forecast_id):
    mw.authenticate(('CsmUser',))
    forecast = get_forecast(forecast_id)
    mw.body()
    account = db.accounts.get(forecast['account_id'])
    cs_state = forecast['cs_state']

    # rule 12: a LOCKED forecast accepts neither submit nor reconcile, and the
    # only edge out of SUBMITTED on the cs axis is the revision edge, which
    # exists only while the finance axis is VARIANCE_FLAGGED.
    if cs_state == 'LOCKED':
        raise gates.invalid_transition('A LOCKED forecast is immutable.')
    if cs_state == 'SUBMITTED' and forecast['finance_state'] != 'VARIANCE_FLAGGED':
        raise gates.invalid_transition(
            'A SUBMITTED forecast may only be revised while its finance_state is '
            'VARIANCE_FLAGGED.')

    if account is not None:
        gates.require_not_frozen(account)

    if cs_state == 'SUBMITTED':
        # The revision edge: back to DRAFT with a freshly computed bottom-up
        # amount from the account's CURRENT likelihood, and the finance axis
        # reset.  likelihood_category is a creation snapshot and is not rewritten.
        touch(forecast)
        forecast['cs_state'] = 'DRAFT'
        if account is not None:
            forecast['cs_amount_cents'] = _bottom_up(
                account, account['renewal_likelihood'])
        forecast['finance_state'] = 'PENDING'
        forecast['finance_amount_cents'] = None
        forecast['variance_cents'] = None
        return resp.entity(serialize.renewal_forecast, forecast, 200)

    # DRAFT -> SUBMITTED
    staffed = account is not None and any(
        a['state'] == 'COMMITTED' for a in store.account_assignments(account['id']))
    if not staffed:
        raise gates.invalid_transition(
            'An unstaffed account may not submit a forecast; at least one '
            'coverage assignment must be COMMITTED.')
    if forecast['cs_amount_cents'] is None:
        raise gates.invalid_transition(
            'cs_amount_cents must not be null to submit a forecast.')
    touch(forecast)
    forecast['cs_state'] = 'SUBMITTED'
    forecast['submitted_at'] = db.clock_stamp()
    return resp.entity(serialize.renewal_forecast, forecast, 200)


@bp.route('/renewal-forecasts/<forecast_id>/reconcile', methods=['POST'])
def reconcile_forecast(forecast_id):
    mw.authenticate(('FinanceAnalyst',))
    forecast = get_forecast(forecast_id)
    data = mw.body()
    action = mw.as_enum(data, 'action', RECONCILE_ACTIONS)
    finance_amount_cents = mw.as_int(data, 'finance_amount_cents', required=False,
                                     minimum=0)

    account = db.accounts.get(forecast['account_id'])

    # rule 12 for this endpoint is exactly the locked row
    if forecast['cs_state'] == 'LOCKED':
        raise gates.invalid_transition('A LOCKED forecast is immutable.')
    # rule 16
    if forecast['cs_state'] != 'SUBMITTED':
        raise ApiError('ERR_FORECAST_NOT_SUBMITTED',
                       'The forecast must be SUBMITTED to be reconciled; its '
                       'cs_state is %s.' % forecast['cs_state'])

    if action == 'RECONCILE':
        if forecast['finance_state'] != 'PENDING':
            raise gates.invalid_transition(
                'The finance axis must be PENDING to reconcile; it is %s.'
                % forecast['finance_state'])
        if finance_amount_cents is None:
            if account is None:
                raise gates.invalid_transition(
                    'finance_amount_cents cannot be derived without the account.')
            finance_amount_cents = calc.finance_top_down_amount(
                account['arr_cents'], account['segment_band'])
        touch(forecast)
        forecast['finance_amount_cents'] = finance_amount_cents
        forecast['variance_cents'] = (finance_amount_cents
                                     - forecast['cs_amount_cents'])
        forecast['reconciled_at'] = db.clock_stamp()
        forecast['finance_state'] = calc.variance_state(
            forecast['variance_cents'], forecast['cs_amount_cents'])
        return resp.entity(serialize.renewal_forecast, forecast, 200)

    # LOCK
    if forecast['finance_state'] != 'RECONCILED':
        raise gates.invalid_transition(
            'A forecast may only be locked while its finance_state is RECONCILED; '
            'it is %s.' % forecast['finance_state'])
    touch(forecast)
    forecast['cs_state'] = 'LOCKED'
    return resp.entity(serialize.renewal_forecast, forecast, 200)
