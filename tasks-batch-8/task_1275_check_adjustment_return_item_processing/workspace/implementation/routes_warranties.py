"""Warranty claim lifecycle: submit, settle, write-off (PRD §3.6)."""
from flask import Blueprint

from db import store, clock, touch
from domain import (get_required, ser_warranty, body, req_string,
                    aging_business_days, bubble_up_case_close)
from envelope import ok
from errors import ApiError
from security import auth_ctx, require_roles

bp = Blueprint('warranties', __name__)


@bp.route('/bank/warranty-claims/<wid>/submit', methods=['POST'])
def submit_warranty(wid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    warranty = get_required(store.warranties, wid, 'ERR_WARRANTY_NOT_FOUND')

    if warranty['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a DRAFT warranty claim may be submitted')
    if clock.now() > warranty['deadline_at']:
        raise ApiError('ERR_WARRANTY_WINDOW_EXPIRED', 422,
                       'Warranty submission deadline has passed')

    warranty['status'] = 'SUBMITTED'
    warranty['submitted_at'] = clock.now()
    touch(warranty)
    return ok(ser_warranty(warranty))


@bp.route('/bank/warranty-claims/<wid>/settle', methods=['POST'])
def settle_warranty(wid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    warranty = get_required(store.warranties, wid, 'ERR_WARRANTY_NOT_FOUND')

    if warranty['status'] not in ('SUBMITTED', 'ESCALATED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a SUBMITTED or ESCALATED warranty claim may be settled')
    if ctx['user_id'] == warranty['created_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'The warranty creator may not settle their own claim')

    data = body()
    outcome = data.get('outcome')
    if outcome not in ('HONORED', 'REJECTED'):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'outcome must be one of HONORED, REJECTED')
    if outcome == 'HONORED':
        recovered = data.get('recovered_amount_cents')
        if not isinstance(recovered, int) or isinstance(recovered, bool) or recovered < 0:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'recovered_amount_cents is required and must be >= 0 when outcome is HONORED')
        warranty['recovered_amount_cents'] = recovered
    warranty['status'] = outcome
    warranty['settled_at'] = clock.now()
    touch(warranty)

    case = store.cases.get(warranty['adjustment_case_id'])
    if case is not None:
        bubble_up_case_close(case)
    return ok(ser_warranty(warranty))


@bp.route('/bank/warranty-claims/<wid>/write-off', methods=['POST'])
def write_off_warranty(wid):
    ctx = auth_ctx()
    require_roles(ctx, ['ComplianceOfficer'])
    warranty = get_required(store.warranties, wid, 'ERR_WARRANTY_NOT_FOUND')

    if warranty['status'] not in ('REJECTED', 'ESCALATED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a REJECTED or ESCALATED warranty claim may be written off')
    if ctx['user_id'] == warranty['created_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'The warranty creator may not write off their own claim')
    if aging_business_days(warranty) < 30:
        raise ApiError('ERR_CLAIM_NOT_AGED_ENOUGH', 422,
                       'Warranty claim must be aged at least 30 business days before write-off')

    data = body()
    warranty['write_off_reason'] = req_string(data, 'write_off_reason')
    warranty['written_off_at'] = clock.now()
    warranty['status'] = 'WRITTEN_OFF'
    touch(warranty)

    case = store.cases.get(warranty['adjustment_case_id'])
    if case is not None:
        bubble_up_case_close(case)
    return ok(ser_warranty(warranty))
