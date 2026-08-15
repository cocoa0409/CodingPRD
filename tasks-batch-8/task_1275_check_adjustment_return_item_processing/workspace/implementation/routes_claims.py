"""Adjustment claim lifecycle: submit, acknowledge, settle, write-off (PRD §3.6)."""
from flask import Blueprint

from db import store, clock, touch
from domain import (get_required, ser_claim, body, opt_string, req_string,
                    aging_business_days, bubble_up_case_close)
from envelope import ok
from errors import ApiError
from security import auth_ctx, require_roles

bp = Blueprint('claims', __name__)


@bp.route('/bank/adjustment-claims/<cid>/submit', methods=['POST'])
def submit_claim(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    claim = get_required(store.claims, cid, 'ERR_CLAIM_NOT_FOUND')

    # PRD §3.6 pinned evaluation order: DRAFT -> case ASSIGNED -> window ->
    # capacity -> bank ACTIVE -> amount.
    if claim['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a DRAFT claim may be submitted')
    case = store.cases.get(claim['adjustment_case_id'])
    if case is None or case['status'] != 'ASSIGNED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'The linked case must be ASSIGNED before claim submission')
    bank = store.clearing_banks.get(claim['clearing_bank_id'])
    if bank is not None and aging_business_days(claim) > bank['claim_window_business_days']:
        raise ApiError('ERR_CLAIM_WINDOW_EXPIRED', 422,
                       'Claim submission window has expired')
    if bank is not None:
        today = clock.now().date()
        submitted_today = sum(
            1 for c in store.claims.values()
            if c['clearing_bank_id'] == bank['id']
            and c['submitted_at'] is not None
            and c['submitted_at'].date() == today)
        if submitted_today >= bank['daily_claim_capacity']:
            raise ApiError('ERR_CLEARING_BANK_CAPACITY_EXCEEDED', 409,
                           'Clearing bank daily claim capacity exceeded')
    if bank is None or bank['status'] != 'ACTIVE':
        raise ApiError('ERR_CLEARING_BANK_SUSPENDED', 409,
                       'Clearing bank is suspended')
    if claim['claimed_amount_cents'] <= 0:
        raise ApiError('ERR_INVALID_AMOUNT', 422,
                       'claimed_amount_cents must be greater than zero')

    claim['status'] = 'SUBMITTED'
    claim['submitted_at'] = clock.now()
    touch(claim)
    return ok(ser_claim(claim))


@bp.route('/bank/adjustment-claims/<cid>/acknowledge', methods=['POST'])
def acknowledge_claim(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    claim = get_required(store.claims, cid, 'ERR_CLAIM_NOT_FOUND')
    if claim['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a SUBMITTED claim may be acknowledged')
    data = body()
    ref = opt_string(data, 'clearing_bank_ref')
    claim['clearing_bank_ref'] = ref
    claim['status'] = 'ACKNOWLEDGED'
    touch(claim)
    return ok(ser_claim(claim))


@bp.route('/bank/adjustment-claims/<cid>/settle', methods=['POST'])
def settle_claim(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    claim = get_required(store.claims, cid, 'ERR_CLAIM_NOT_FOUND')

    if claim['status'] not in ('ACKNOWLEDGED', 'ESCALATED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only an ACKNOWLEDGED or ESCALATED claim may be settled')

    # Segregation of duties (priority 7): creator may not settle own claim.
    if ctx['user_id'] == claim['created_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'The claim creator may not settle their own claim')

    data = body()
    outcome = data.get('outcome')
    if outcome not in ('SETTLED', 'DENIED'):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'outcome must be one of SETTLED, DENIED')
    if outcome == 'SETTLED':
        recovered = data.get('recovered_amount_cents')
        if not isinstance(recovered, int) or isinstance(recovered, bool) or recovered < 0:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'recovered_amount_cents is required and must be >= 0 when outcome is SETTLED')
        claim['recovered_amount_cents'] = recovered
    claim['status'] = outcome
    claim['settled_at'] = clock.now()
    touch(claim)

    case = store.cases.get(claim['adjustment_case_id'])
    if case is not None:
        bubble_up_case_close(case)
    return ok(ser_claim(claim))


@bp.route('/bank/adjustment-claims/<cid>/write-off', methods=['POST'])
def write_off_claim(cid):
    ctx = auth_ctx()
    require_roles(ctx, ['ComplianceOfficer'])
    claim = get_required(store.claims, cid, 'ERR_CLAIM_NOT_FOUND')

    if claim['status'] not in ('DENIED', 'ESCALATED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a DENIED or ESCALATED claim may be written off')
    if ctx['user_id'] == claim['created_by_user_id']:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'The claim creator may not write off their own claim')
    if aging_business_days(claim) < 30:
        raise ApiError('ERR_CLAIM_NOT_AGED_ENOUGH', 422,
                       'Claim must be aged at least 30 business days before write-off')

    data = body()
    claim['write_off_reason'] = req_string(data, 'write_off_reason')
    claim['written_off_at'] = clock.now()
    claim['status'] = 'WRITTEN_OFF'
    touch(claim)

    case = store.cases.get(claim['adjustment_case_id'])
    if case is not None:
        bubble_up_case_close(case)
    return ok(ser_claim(claim))
