from flask import Blueprint

from auth import user_context, require_role, check_parent_owns_case
from db import store, base_fields, register, touch
from domain import (ser_refund, select_refund_subject, refund_eligible,
                    refund_amount_cents, refund_paid_cascade)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_enum, opt_str, req_str
from routes.cases import load_case

bp = Blueprint('refunds', __name__)

REFUND_TYPES = ('COOLING_OFF', 'GUARANTEE', 'PRO_RATA')
REFUND_CASE_STATES = ('ACTIVE_SUPPORT', 'NEEDS_ATTENTION', 'COMPLETED')


@bp.post('/cases/<caseId>/refund-requests')
def request_refund(caseId):
    uid, role = user_context()
    require_role(role, 'Parent')
    data = body()
    refund_type = req_enum(data, 'refund_type', REFUND_TYPES)
    reason = opt_str(data, 'reason')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    if case['status'] not in REFUND_CASE_STATES:
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'Refunds require the case to be in ACTIVE_SUPPORT, '
                       'NEEDS_ATTENTION or COMPLETED')
    if any(r['case_id'] == case['id'] and r['status'] in ('REQUESTED', 'APPROVED')
           for r in store.refunds.values()):
        raise ApiError('ERR_REFUND_ALREADY_PENDING', 409,
                       'A refund in REQUESTED or APPROVED already exists for the case')
    # Server-selected subject: package in ACTIVE/DEPLETED/EXPIRED with the
    # latest starts_on (tie: later created_at).
    pkg = select_refund_subject(case['id'])
    if pkg is None:
        raise ApiError('ERR_REFUND_NOT_ELIGIBLE', 422,
                       'No package available as a refund subject')
    if not refund_eligible(case, pkg, refund_type):
        raise ApiError('ERR_REFUND_NOT_ELIGIBLE', 422,
                       'Eligibility predicate for {} is not met'.format(refund_type))
    r = base_fields()
    r.update({
        'case_id': case['id'],
        'package_id': pkg['id'],
        'refund_type': refund_type,
        'reason': reason,
        'amount_cents': None,
        'denial_reason': None,
        'status': 'REQUESTED',
    })
    register(store.refunds, r)
    return ok(ser_refund(r), status=201)


@bp.get('/cases/<caseId>/refund-requests')
def list_case_refunds(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [r for r in store.refunds.values() if r['case_id'] == case['id']]
    return paginate(rows, ser_refund)


def load_refund(refund_id):
    r = store.refunds.get(refund_id)
    if r is None:
        raise ApiError('ERR_REFUND_REQUEST_NOT_FOUND', 404, 'Refund request not found')
    return r


@bp.post('/refund-requests/<refundId>/approve')
def approve_refund(refundId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    r = load_refund(refundId)
    if r['status'] != 'REQUESTED':
        raise ApiError('ERR_REFUND_INVALID_STATE', 409,
                       'Approval requires the refund request to be REQUESTED')
    pkg = store.packages.get(r['package_id'])
    amount = refund_amount_cents(pkg, r['refund_type'])
    r['amount_cents'] = amount
    r['status'] = 'APPROVED'
    touch(r)
    case = store.cases.get(r['case_id'])
    family = store.families.get(case['family_id']) if case is not None else None
    if family is not None:
        family['credit_balance_cents'] += amount
    return ok(ser_refund(r))


@bp.post('/refund-requests/<refundId>/deny')
def deny_refund(refundId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    data = body()
    denial_reason = req_str(data, 'denial_reason')
    r = load_refund(refundId)
    if r['status'] != 'REQUESTED':
        raise ApiError('ERR_REFUND_INVALID_STATE', 409,
                       'Denial requires the refund request to be REQUESTED')
    r['denial_reason'] = denial_reason
    r['status'] = 'DENIED'
    touch(r)
    return ok(ser_refund(r))


@bp.post('/refund-requests/<refundId>/pay')
def pay_refund(refundId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    r = load_refund(refundId)
    if r['status'] != 'APPROVED':
        raise ApiError('ERR_REFUND_INVALID_STATE', 409,
                       'Payment requires the refund request to be APPROVED')
    r['status'] = 'PAID'
    touch(r)
    case = store.cases.get(r['case_id'])
    if case is not None:
        refund_paid_cascade(case)
    return ok(ser_refund(r))
