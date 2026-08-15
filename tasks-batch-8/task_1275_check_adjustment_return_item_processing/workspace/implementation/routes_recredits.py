"""Regulation CC expedited recredit requests (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, clock, base_fields, touch
from domain import (get_required, post_ledger, ser_recredit, body, req_string,
                    compute_recredit_amounts)
from envelope import ok, paginated_list
from errors import ApiError
from security import (auth_ctx, require_roles, customer_owns,
                      customer_list_scope, ALL_ROLES)
from timeutil import business_days_elapsed

bp = Blueprint('recredits', __name__)

RECREDIT_CLAIM_WINDOW_DAYS = 40
RECREDIT_FINALIZE_WINDOW_DAYS = 45
RECREDIT_PROVISIONAL_BUSINESS_DAYS = 2


@bp.route('/bank/recredit-requests', methods=['POST'])
def create_recredit():
    ctx = auth_ctx()
    require_roles(ctx, ['Customer', 'CustomerService'])
    data = body()

    account_id = data.get('depositor_account_id')
    check_item_id = data.get('check_item_id')

    # Ownership (priority 3): Customer files only against their own account.
    if ctx['role'] == 'Customer':
        if not isinstance(account_id, str):
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'depositor_account_id is required')
        customer_owns(ctx, account_id)

    # Existence (priority 4), left-to-right: account before item.
    if not isinstance(account_id, str) or not account_id:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'depositor_account_id is required')
    if not isinstance(check_item_id, str) or not check_item_id:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'check_item_id is required')
    account = get_required(store.accounts, account_id, 'ERR_ACCOUNT_NOT_FOUND')
    item = get_required(store.check_items, check_item_id, 'ERR_ITEM_NOT_FOUND')

    # State (priority 6): item must be PAID.
    if item['status'] != 'PAID':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Recredit may only be requested for a PAID item')

    # Temporal (priority 8): within 40 calendar days of paid_at.
    if item['paid_at'] is None or clock.now() > item['paid_at'] + timedelta(days=RECREDIT_CLAIM_WINDOW_DAYS):
        raise ApiError('ERR_RECREDIT_WINDOW_EXPIRED', 422,
                       'Recredit request window (40 days from payment) has expired')

    # Structural (priority 9): Reg CC eligibility, then one-open-per-item.
    if not account['reg_cc_eligible']:
        raise ApiError('ERR_RECREDIT_NOT_ELIGIBLE', 422,
                       'Account is not eligible for Regulation CC recredit')
    for r in store.recredits.values():
        if (r['check_item_id'] == item['id']
                and r['status'] in ('SUBMITTED', 'PROVISIONALLY_CREDITED')):
            raise ApiError('ERR_RECREDIT_ALREADY_OPEN', 409,
                           'Another recredit request for this item is still open')

    # Cross-reference (priority 10): item must belong to the named account.
    if item['depositor_account_id'] != account['id']:
        raise ApiError('ERR_RECREDIT_ITEM_MISMATCH', 422,
                       'check_item_id does not belong to depositor_account_id')

    # Amount sanity (priority 11).
    claimed = data.get('claimed_amount_cents')
    if not isinstance(claimed, int) or isinstance(claimed, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'claimed_amount_cents is required and must be an integer')
    if claimed <= 0 or claimed > item['amount_cents']:
        raise ApiError('ERR_INVALID_AMOUNT', 422,
                       'claimed_amount_cents must be > 0 and no more than the item amount')
    reason = req_string(data, 'reason')

    recredit = dict(base_fields())
    recredit.update({
        'depositor_account_id': account['id'],
        'check_item_id': item['id'],
        'claimed_amount_cents': claimed,
        'reason': reason,
        'status': 'SUBMITTED',
        'principal_amount_cents': None,
        'interest_cents': None,
        'provisional_amount_cents': None,
        'submitted_at': clock.now(),
        'provisioned_at': None,
        'provisioned_late': None,
        'breach_flagged': False,
        'finalized_at': None,
    })
    store.recredits[recredit['id']] = recredit
    return ok(ser_recredit(recredit), status=201)


@bp.route('/bank/recredit-requests/<rid>', methods=['GET'])
def get_recredit(rid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    r = get_required(store.recredits, rid, 'ERR_RECREDIT_NOT_FOUND')
    customer_owns(ctx, r['depositor_account_id'])
    return ok(ser_recredit(r))


@bp.route('/bank/recredit-requests', methods=['GET'])
def list_recredits():
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    account_id = customer_list_scope(ctx, request.args.get('depositor_account_id'))
    check_item_id = request.args.get('check_item_id')
    status = request.args.get('status')
    items = [r for r in store.recredits.values()
             if (account_id is None or r['depositor_account_id'] == account_id)
             and (check_item_id is None or r['check_item_id'] == check_item_id)
             and (status is None or r['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_recredit(r) for r in page], pagination=pagination)


@bp.route('/bank/recredit-requests/<rid>/provisional-credit', methods=['POST'])
def provisional_credit(rid):
    ctx = auth_ctx()
    require_roles(ctx, ['CustomerService'])
    r = get_required(store.recredits, rid, 'ERR_RECREDIT_NOT_FOUND')
    if r['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a SUBMITTED recredit request may receive provisional credit')

    now = clock.now()
    principal, interest, provisional = compute_recredit_amounts(r, now)
    r['principal_amount_cents'] = principal
    r['interest_cents'] = interest
    r['provisional_amount_cents'] = provisional
    r['provisioned_at'] = now
    r['provisioned_late'] = (business_days_elapsed(r['submitted_at'].date(),
                                                   now.date())
                             > RECREDIT_PROVISIONAL_BUSINESS_DAYS)
    r['status'] = 'PROVISIONALLY_CREDITED'
    touch(r)

    post_ledger(r['depositor_account_id'], 'RECREDIT_PROVISIONAL_CREDIT',
                provisional, True,
                memo='Reg CC provisional credit',
                recredit_request_id=r['id'])
    return ok(ser_recredit(r))


@bp.route('/bank/recredit-requests/<rid>/finalize', methods=['POST'])
def finalize_recredit(rid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    r = get_required(store.recredits, rid, 'ERR_RECREDIT_NOT_FOUND')
    if r['status'] != 'PROVISIONALLY_CREDITED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PROVISIONALLY_CREDITED recredit request may be finalized')

    data = body()
    outcome = data.get('outcome')
    if outcome not in ('CONFIRMED', 'REVOKED'):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'outcome must be one of CONFIRMED, REVOKED')

    if outcome == 'REVOKED':
        if clock.now() > r['submitted_at'] + timedelta(days=RECREDIT_FINALIZE_WINDOW_DAYS):
            raise ApiError('ERR_FINALIZE_WINDOW_EXPIRED', 422,
                           'Revocation window (45 days from submission) has expired')
        post_ledger(r['depositor_account_id'], 'RECREDIT_CLAWBACK_DEBIT',
                    -r['provisional_amount_cents'], True,
                    memo='Reg CC provisional credit clawback',
                    recredit_request_id=r['id'])

    r['status'] = outcome
    r['finalized_at'] = clock.now()
    touch(r)
    return ok(ser_recredit(r))
