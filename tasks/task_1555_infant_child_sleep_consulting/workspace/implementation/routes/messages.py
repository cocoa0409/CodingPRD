from decimal import Decimal

from flask import Blueprint

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch, now
from domain import (ser_message, select_consumable_package, reeval_depleted,
                    round_half_up_cents, SLA_CREDIT_CENTS, SLA_CREDIT_CAP_PCT)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_str
from routes.cases import load_case

bp = Blueprint('messages', __name__)


@bp.post('/cases/<caseId>/messages')
def send_message(caseId):
    uid, role = user_context()
    require_role(role, 'Parent')
    data = body()
    text = req_str(data, 'body')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    pkg = select_consumable_package(case['id'])
    if pkg is None:
        raise ApiError('ERR_PACKAGE_NOT_ACTIVE', 409,
                       'No ACTIVE in-window package available for this case')
    if pkg['remaining_messages'] <= 0:
        raise ApiError('ERR_ENTITLEMENT_EXHAUSTED', 422,
                       'No remaining message entitlement on the selected package')
    msg = base_fields()
    msg.update({
        'case_id': case['id'],
        'package_id': pkg['id'],
        'body': text,
        'response_body': None,
        'first_responded_at': None,
        'sla_breached': None,
        'credit_granted_cents': None,
        'status': 'AWAITING_RESPONSE',
    })
    register(store.messages, msg)
    pkg['remaining_messages'] -= 1
    touch(pkg)
    reeval_depleted(pkg)
    return ok(ser_message(msg), status=201)


@bp.get('/cases/<caseId>/messages')
def list_case_messages(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [m for m in store.messages.values() if m['case_id'] == case['id']]
    return paginate(rows, ser_message)


@bp.post('/messages/<messageId>/respond')
def respond_message(messageId):
    uid, role = user_context()
    require_role(role, 'Consultant')
    data = body()
    response_body = req_str(data, 'response_body')
    msg = store.messages.get(messageId)
    if msg is None:
        raise ApiError('ERR_MESSAGE_NOT_FOUND', 404, 'Message not found')
    case = store.cases.get(msg['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if case['consultant_id'] != uid:
        forbidden('Only the assigned consultant may respond to messages')
    if msg['status'] != 'AWAITING_RESPONSE':
        raise ApiError('ERR_MESSAGE_ALREADY_RESPONDED', 409,
                       'Message has already been responded to')
    responded_at = now()
    msg['response_body'] = response_body
    msg['first_responded_at'] = responded_at
    msg['status'] = 'RESPONDED'
    pkg = store.packages.get(msg['package_id'])
    sla_hours = pkg['response_sla_hours'] if pkg is not None else 0
    elapsed_s = (responded_at - msg['created_at']).total_seconds()
    # Strictly greater than the SLA is a breach; exactly on the boundary is on time.
    breached = elapsed_s > sla_hours * 3600
    msg['sla_breached'] = breached
    credit = 0
    if breached and pkg is not None:
        cap = round_half_up_cents(Decimal(pkg['gross_price_cents']) * SLA_CREDIT_CAP_PCT)
        if pkg['sla_credit_total_cents'] + SLA_CREDIT_CENTS <= cap:
            credit = SLA_CREDIT_CENTS
    msg['credit_granted_cents'] = credit
    touch(msg)
    if credit:
        pkg['sla_credit_total_cents'] += credit
        family = store.families.get(case['family_id'])
        if family is not None:
            family['credit_balance_cents'] += credit
    if pkg is not None:
        # The message entitlement was consumed at send time; re-evaluate depletion.
        reeval_depleted(pkg)
    return ok(ser_message(msg))
