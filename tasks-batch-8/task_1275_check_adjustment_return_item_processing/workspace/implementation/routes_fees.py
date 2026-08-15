"""Fee assessments: read, list, waive (PRD §3.7)."""
from flask import Blueprint, request

from db import store, clock, touch
from domain import get_required, post_ledger, ser_fee, body, req_string
from envelope import ok, paginated_list
from errors import ApiError
from security import (auth_ctx, require_roles, customer_owns,
                      customer_list_scope, ALL_ROLES)

bp = Blueprint('fees', __name__)

CUSTOMER_SERVICE_WAIVE_CAP_CENTS = 2500


@bp.route('/bank/fees/<fid>', methods=['GET'])
def get_fee(fid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    fee = get_required(store.fees, fid, 'ERR_FEE_NOT_FOUND')
    customer_owns(ctx, fee['depositor_account_id'])
    return ok(ser_fee(fee))


@bp.route('/bank/fees', methods=['GET'])
def list_fees():
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    account_id = customer_list_scope(ctx, request.args.get('depositor_account_id'))
    case_id = request.args.get('adjustment_case_id')
    return_event_id = request.args.get('return_event_id')
    status = request.args.get('status')
    items = [f for f in store.fees.values()
             if (account_id is None or f['depositor_account_id'] == account_id)
             and (case_id is None or f['adjustment_case_id'] == case_id)
             and (return_event_id is None or f['return_event_id'] == return_event_id)
             and (status is None or f['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_fee(f) for f in page], pagination=pagination)


@bp.route('/bank/fees/<fid>/waive', methods=['POST'])
def waive_fee(fid):
    ctx = auth_ctx()
    require_roles(ctx, ['CustomerService', 'ComplianceOfficer'])
    fee = get_required(store.fees, fid, 'ERR_FEE_NOT_FOUND')

    if fee['status'] != 'POSTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a POSTED fee may be waived')

    # Authority (priority 7): CustomerService capped at 2500; ComplianceOfficer uncapped.
    if (ctx['role'] == 'CustomerService'
            and fee['amount_cents'] > CUSTOMER_SERVICE_WAIVE_CAP_CENTS):
        raise ApiError('ERR_FEE_WAIVE_LIMIT_EXCEEDED', 403,
                       'CustomerService may only waive fees of at most 2500 cents')

    data = body()
    reason = req_string(data, 'waive_reason')

    fee['status'] = 'WAIVED'
    fee['waived_by_user_id'] = ctx['user_id']
    fee['waive_reason'] = reason
    fee['waived_at'] = clock.now()
    touch(fee)

    post_ledger(fee['depositor_account_id'], 'FEE_WAIVER_CREDIT',
                fee['amount_cents'], False,
                memo='Fee waiver credit', fee_assessment_id=fee['id'])
    return ok(ser_fee(fee))
