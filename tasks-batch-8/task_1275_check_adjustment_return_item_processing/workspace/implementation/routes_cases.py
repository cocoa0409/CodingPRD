"""Adjustment cases: list/read, assign, resolve, reopen, close, and the
per-case claim / warranty-claim creation and listing endpoints (PRD §3.5, §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, clock, base_fields, touch
from domain import (get_required, post_ledger, create_notification, ser_case,
                    ser_claim, ser_warranty, body, req_string, req_int,
                    opt_string, case_children_terminal, case_account, case_item)
from envelope import ok, paginated_list
from errors import ApiError
from security import auth_ctx, require_roles, customer_owns, OPS_ROLES, ALL_ROLES

bp = Blueprint('cases', __name__)

ASSIGNABLE_STATES = {'OPEN', 'ASSIGNED', 'REOPENED', 'ESCALATED'}
DISPOSITIONS = ['CREDIT_CUSTOMER', 'DEBIT_CUSTOMER', 'NO_ACTION']


def _case_account_id(case):
    account = case_account(case)
    return account['id'] if account else None


@bp.route('/bank/check-items/<iid>/adjustment-cases', methods=['GET'])
def list_item_cases(iid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    customer_owns(ctx, item['depositor_account_id'])
    case_type = request.args.get('case_type')
    status = request.args.get('status')
    items = [c for c in store.cases.values()
             if c['check_item_id'] == item['id']
             and (case_type is None or c['case_type'] == case_type)
             and (status is None or c['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_case(c) for c in page], pagination=pagination)


@bp.route('/bank/adjustment-cases/<cid>', methods=['GET'])
def get_case(cid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    customer_owns(ctx, _case_account_id(case))
    return ok(ser_case(case))


@bp.route('/bank/adjustment-cases', methods=['GET'])
def list_cases():
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    check_item_id = request.args.get('check_item_id')
    return_event_id = request.args.get('return_event_id')
    case_type = request.args.get('case_type')
    status = request.args.get('status')
    items = [c for c in store.cases.values()
             if (check_item_id is None or c['check_item_id'] == check_item_id)
             and (return_event_id is None or c['return_event_id'] == return_event_id)
             and (case_type is None or c['case_type'] == case_type)
             and (status is None or c['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_case(c) for c in page], pagination=pagination)


@bp.route('/bank/adjustment-cases/<cid>/assign', methods=['POST'])
def assign_case(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    data = body()

    # OCC (priority 5): expected_adjustment_case_version is non-optional.
    expected = data.get('expected_adjustment_case_version')
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'expected_adjustment_case_version is required and must be an integer')
    if expected != case['version']:
        raise ApiError('ERR_STALE_VERSION', 412,
                       'Case version has advanced; refresh and retry')

    if case['status'] not in ASSIGNABLE_STATES:
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Case in status %s cannot be assigned' % case['status'])

    assigned_analyst_id = req_string(data, 'assigned_analyst_id')
    case['assigned_analyst_id'] = assigned_analyst_id
    case['status'] = 'ASSIGNED'
    touch(case)
    return ok(ser_case(case))


@bp.route('/bank/adjustment-cases/<cid>/resolve', methods=['POST'])
def resolve_case(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')

    if case['status'] != 'ASSIGNED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only an ASSIGNED case may be resolved')

    # Authority (priority 7): resolution belongs to the assignee alone.
    if ctx['user_id'] != case['assigned_analyst_id']:
        raise ApiError('ERR_NOT_ASSIGNED_ANALYST', 403,
                       'Only the assigned analyst may resolve this case')

    data = body()
    disposition = data.get('disposition')
    if disposition not in DISPOSITIONS:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'disposition must be one of CREDIT_CUSTOMER, DEBIT_CUSTOMER, NO_ACTION')
    amount = None
    if disposition != 'NO_ACTION':
        amount = data.get('amount_cents')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'amount_cents is required and must be > 0 unless disposition is NO_ACTION')

    case['disposition'] = disposition
    case['resolution_amount_cents'] = amount
    case['resolved_at'] = clock.now()
    case['status'] = 'RESOLVED'
    touch(case)

    account = case_account(case)
    if disposition == 'CREDIT_CUSTOMER':
        post_ledger(account['id'], 'ADJUSTMENT_CREDIT', amount, False,
                    memo='Adjustment credit for case %s' % case['id'],
                    adjustment_case_id=case['id'])
    elif disposition == 'DEBIT_CUSTOMER':
        post_ledger(account['id'], 'ADJUSTMENT_DEBIT', -amount, False,
                    memo='Adjustment debit for case %s' % case['id'],
                    adjustment_case_id=case['id'])
    return ok(ser_case(case))


@bp.route('/bank/adjustment-cases/<cid>/reopen', methods=['POST'])
def reopen_case(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['ComplianceOfficer'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    if case['status'] != 'RESOLVED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a RESOLVED case may be reopened')
    data = body()
    req_string(data, 'reopen_reason')

    case['status'] = 'REOPENED'
    case['reopen_count'] += 1
    case['disposition'] = None
    case['resolution_amount_cents'] = None
    case['resolved_at'] = None
    touch(case)
    return ok(ser_case(case))


@bp.route('/bank/adjustment-cases/<cid>/close', methods=['POST'])
def close_case(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst', 'ComplianceOfficer'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    if case['status'] != 'RESOLVED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a RESOLVED case may be closed')
    if not case_children_terminal(case):
        raise ApiError('ERR_CASE_HAS_OPEN_CLAIMS', 409,
                       'Case has non-terminal claims or warranties')

    case['status'] = 'CLOSED'
    case['closed_at'] = clock.now()
    touch(case)
    create_notification(_case_account_id(case), case['id'], 'CASE_CLOSED',
                        'Adjustment case %s has been closed.' % case['id'])
    return ok(ser_case(case))


@bp.route('/bank/adjustment-cases/<cid>/claims', methods=['POST'])
def create_claim(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    data = body()

    claimed = data.get('claimed_amount_cents')
    if not isinstance(claimed, int) or isinstance(claimed, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'claimed_amount_cents is required and must be an integer')
    if claimed <= 0:
        raise ApiError('ERR_INVALID_AMOUNT', 422,
                       'claimed_amount_cents must be greater than zero')
    opt_string(data, 'description')

    item = case_item(case)
    claim = dict(base_fields())
    claim.update({
        'adjustment_case_id': case['id'],
        'clearing_bank_id': item['clearing_bank_id'] if item else None,
        'claimed_amount_cents': claimed,
        'created_by_user_id': ctx['user_id'],
        'status': 'DRAFT',
        'submitted_at': None,
        'clearing_bank_ref': None,
        'recovered_amount_cents': None,
        'settled_at': None,
        'write_off_reason': None,
        'written_off_at': None,
    })
    store.claims[claim['id']] = claim
    return ok(ser_claim(claim), status=201)


@bp.route('/bank/adjustment-cases/<cid>/claims', methods=['GET'])
def list_case_claims(cid):
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    status = request.args.get('status')
    items = [c for c in store.claims.values()
             if c['adjustment_case_id'] == case['id']
             and (status is None or c['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_claim(c) for c in page], pagination=pagination)


@bp.route('/bank/adjustment-cases/<cid>/warranty-claims', methods=['POST'])
def create_warranty(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')

    if case['case_type'] != 'IMAGE_WARRANTY':
        raise ApiError('ERR_CASE_TYPE_MISMATCH', 422,
                       'Warranty claims may only be created on IMAGE_WARRANTY cases')

    data = body()
    claimed = data.get('claimed_amount_cents')
    if not isinstance(claimed, int) or isinstance(claimed, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'claimed_amount_cents is required and must be an integer')
    if claimed <= 0:
        raise ApiError('ERR_INVALID_AMOUNT', 422,
                       'claimed_amount_cents must be greater than zero')

    item = case_item(case)
    bank = store.clearing_banks.get(item['clearing_bank_id']) if item else None
    deadline_at = item['presented_at'] + timedelta(days=bank['warranty_window_days'])

    warranty = dict(base_fields())
    warranty.update({
        'adjustment_case_id': case['id'],
        'claimed_amount_cents': claimed,
        'created_by_user_id': ctx['user_id'],
        'status': 'DRAFT',
        'deadline_at': deadline_at,
        'submitted_at': None,
        'recovered_amount_cents': None,
        'settled_at': None,
        'write_off_reason': None,
        'written_off_at': None,
    })
    store.warranties[warranty['id']] = warranty
    return ok(ser_warranty(warranty), status=201)


@bp.route('/bank/adjustment-cases/<cid>/warranty-claims', methods=['GET'])
def list_case_warranties(cid):
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    case = get_required(store.cases, cid, 'ERR_CASE_NOT_FOUND')
    status = request.args.get('status')
    items = [w for w in store.warranties.values()
             if w['adjustment_case_id'] == case['id']
             and (status is None or w['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_warranty(w) for w in page], pagination=pagination)
