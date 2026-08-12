"""Depositor accounts and freeze windows (PRD §3.1)."""
from flask import Blueprint, request

from db import store, base_fields, touch
from domain import (get_required, post_ledger, ser_account, ser_freeze, body,
                    req_string, opt_enum, opt_bool, opt_int, req_datetime,
                    req_int)
from envelope import ok, paginated_list
from errors import ApiError
from security import auth_ctx, require_roles, customer_owns, OPS_ROLES, ALL_ROLES

bp = Blueprint('accounts', __name__)


@bp.route('/bank/accounts', methods=['POST'])
def create_account():
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    data = body()

    customer_name = req_string(data, 'customer_name')
    account_number = req_string(data, 'account_number')

    # Structural (priority 9): unique account_number
    for a in store.accounts.values():
        if a['account_number'] == account_number:
            raise ApiError('ERR_DUPLICATE_ACCOUNT_NUMBER', 409,
                           'account_number already exists')

    risk_tier = opt_enum(data, 'risk_tier', ['STANDARD', 'HIGH_RISK'], 'STANDARD')
    reg_cc_eligible = opt_bool(data, 'reg_cc_eligible', True)
    opening = opt_int(data, 'opening_balance_cents', 0)

    account = dict(base_fields())
    account.update({
        'customer_name': customer_name,
        'account_number': account_number,
        'status': 'ACTIVE',
        'risk_tier': risk_tier,
        'reg_cc_eligible': reg_cc_eligible,
        'opening_balance_cents': opening,
    })
    store.accounts[account['id']] = account
    if opening > 0:
        post_ledger(account['id'], 'OPENING_CREDIT', opening, False,
                    memo='Opening credit')
    return ok(ser_account(account), status=201)


@bp.route('/bank/accounts/<aid>', methods=['GET'])
def get_account(aid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    # Customer: X-User-ID IS the account id — ownership check needs no lookup.
    customer_owns(ctx, aid)
    account = get_required(store.accounts, aid, 'ERR_ACCOUNT_NOT_FOUND')
    return ok(ser_account(account))


@bp.route('/bank/accounts', methods=['GET'])
def list_accounts():
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    status = request.args.get('status')
    items = [a for a in store.accounts.values()
             if status is None or a['status'] == status]
    page, pagination = paginated_list(items)
    return ok([ser_account(a) for a in page], pagination=pagination)


@bp.route('/bank/accounts/<aid>', methods=['PATCH'])
def update_account(aid):
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    account = get_required(store.accounts, aid, 'ERR_ACCOUNT_NOT_FOUND')
    data = body()

    # OCC (priority 5): expected_depositor_account_version is non-optional.
    expected = data.get('expected_depositor_account_version')
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'expected_depositor_account_version is required and must be an integer')
    if expected != account['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'Account version has advanced; refresh and retry')

    risk_tier = opt_enum(data, 'risk_tier', ['STANDARD', 'HIGH_RISK'], None)
    reg_cc_eligible = opt_bool(data, 'reg_cc_eligible', None)
    if risk_tier is not None:
        account['risk_tier'] = risk_tier
    if reg_cc_eligible is not None:
        account['reg_cc_eligible'] = reg_cc_eligible
    touch(account)
    return ok(ser_account(account))


@bp.route('/bank/accounts/<aid>/freezes', methods=['POST'])
def create_freeze(aid):
    ctx = auth_ctx()
    require_roles(ctx, ['ComplianceOfficer'])
    account = get_required(store.accounts, aid, 'ERR_ACCOUNT_NOT_FOUND')
    data = body()

    start_at = req_datetime(data, 'start_at')
    end_at = req_datetime(data, 'end_at')
    reason = req_string(data, 'reason')
    if end_at < start_at:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'end_at must not precede start_at')

    # Closed-interval overlap: touching windows DO overlap.
    for f in store.freezes.values():
        if f['depositor_account_id'] != account['id']:
            continue
        if start_at <= f['end_at'] and f['start_at'] <= end_at:
            raise ApiError('ERR_FREEZE_WINDOW_OVERLAP', 409,
                           'Freeze window overlaps an existing freeze on this account')

    freeze = dict(base_fields())
    freeze.update({
        'depositor_account_id': account['id'],
        'start_at': start_at,
        'end_at': end_at,
        'reason': reason,
    })
    store.freezes[freeze['id']] = freeze
    return ok(ser_freeze(freeze), status=201)


@bp.route('/bank/accounts/<aid>/freezes', methods=['GET'])
def list_freezes(aid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    customer_owns(ctx, aid)
    account = get_required(store.accounts, aid, 'ERR_ACCOUNT_NOT_FOUND')
    items = [f for f in store.freezes.values()
             if f['depositor_account_id'] == account['id']]
    page, pagination = paginated_list(items)
    return ok([ser_freeze(f) for f in page], pagination=pagination)
