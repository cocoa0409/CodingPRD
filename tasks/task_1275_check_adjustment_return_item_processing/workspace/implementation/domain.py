"""Shared business logic: balances, ledger, notifications, cases, fees, aging,
serializers, and input-validation helpers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store, clock, base_fields, touch, new_id, next_seq, fmt_ts, ts_or_none
from errors import ApiError
from timeutil import (business_days_elapsed, calendar_days_elapsed,
                      next_business_day_1700)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_required(collection, rid, error_id):
    obj = collection.get(rid)
    if obj is None:
        raise ApiError(error_id, 404, 'Resource %s not found' % rid)
    return obj


def item_account(item):
    return store.accounts.get(item['depositor_account_id'])


def case_item(case):
    return store.check_items.get(case['check_item_id'])


def case_account(case):
    item = case_item(case)
    return item_account(item) if item else None


# ---------------------------------------------------------------------------
# Balances and account freeze/thaw (PRD §2.7)
# ---------------------------------------------------------------------------

def available_balance(account_id):
    return sum(e['amount_cents'] for e in store.ledger.values()
               if e['depositor_account_id'] == account_id)


def settled_balance(account_id):
    return sum(e['amount_cents'] for e in store.ledger.values()
               if e['depositor_account_id'] == account_id and not e['provisional'])


def returned_item_count_30d(account_id):
    """CODED return events for this account with coded_at in (now-30d, now]."""
    now = clock.now()
    window_start = now - timedelta(days=30)
    count = 0
    for r in store.return_events.values():
        if r['status'] != 'CODED' or r['coded_at'] is None:
            continue
        item = store.check_items.get(r['check_item_id'])
        if item is None or item['depositor_account_id'] != account_id:
            continue
        if window_start < r['coded_at'] <= now:
            count += 1
    return count


def refresh_account(account_id):
    """Auto FROZEN/ACTIVE transition after any ledger write (cyclic)."""
    account = store.accounts.get(account_id)
    if account is None:
        return
    balance = available_balance(account_id)
    if balance < 0 and account['status'] == 'ACTIVE':
        account['status'] = 'FROZEN'
        touch(account)
    elif balance >= 0 and account['status'] == 'FROZEN':
        account['status'] = 'ACTIVE'
        touch(account)


def account_deposit_blocked(account):
    """FROZEN status or covered by an ACTIVE (closed-interval) freeze window."""
    if account['status'] == 'FROZEN':
        return True
    now = clock.now()
    for f in store.freezes.values():
        if f['depositor_account_id'] != account['id']:
            continue
        if f['start_at'] <= now <= f['end_at']:
            return True
    return False


# ---------------------------------------------------------------------------
# Ledger (append-only; PRD §2.6)
# ---------------------------------------------------------------------------

def post_ledger(account_id, entry_type, amount_cents, provisional, memo=None,
                check_item_id=None, adjustment_case_id=None,
                fee_assessment_id=None, recredit_request_id=None):
    entry = {
        'id': new_id(),
        'created_at': clock.now(),
        '_seq': next_seq(),
        'depositor_account_id': account_id,
        'entry_type': entry_type,
        'amount_cents': amount_cents,
        'provisional': provisional,
        'memo': memo,
        'check_item_id': check_item_id,
        'adjustment_case_id': adjustment_case_id,
        'fee_assessment_id': fee_assessment_id,
        'recredit_request_id': recredit_request_id,
    }
    store.ledger[entry['id']] = entry
    refresh_account(account_id)
    return entry


# ---------------------------------------------------------------------------
# Notifications (no updated_at / version; PRD §2.5, §3.7)
# ---------------------------------------------------------------------------

def create_notification(account_id, case_id, notification_type, message):
    now = clock.now()
    n = {
        'id': new_id(),
        'created_at': now,
        '_seq': next_seq(),
        'depositor_account_id': account_id,
        'adjustment_case_id': case_id,
        'notification_type': notification_type,
        'message': message,
        'due_at': next_business_day_1700(now),
        'status': 'PENDING',
        'delivered_at': None,
    }
    store.notifications[n['id']] = n
    return n


# ---------------------------------------------------------------------------
# Adjustment cases: closure gate + bubble-up (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------

CLAIM_TERMINAL = {'SETTLED', 'WRITTEN_OFF'}
WARRANTY_TERMINAL = {'HONORED', 'WRITTEN_OFF'}


def case_children_terminal(case):
    claims = [c for c in store.claims.values()
              if c['adjustment_case_id'] == case['id']]
    warranties = [w for w in store.warranties.values()
                  if w['adjustment_case_id'] == case['id']]
    return (all(c['status'] in CLAIM_TERMINAL for c in claims)
            and all(w['status'] in WARRANTY_TERMINAL for w in warranties))


def bubble_up_case_close(case):
    """Auto-close a RESOLVED case once no non-terminal claims/warranties remain."""
    if case['status'] != 'RESOLVED':
        return
    if not case_children_terminal(case):
        return
    case['status'] = 'CLOSED'
    case['closed_at'] = clock.now()
    touch(case)
    account = case_account(case)
    create_notification(account['id'] if account else None, case['id'],
                        'CASE_CLOSED',
                        'Adjustment case %s has been closed.' % case['id'])


def create_case(case_type, check_item_id, return_event_id=None):
    case = dict(base_fields())
    case.update({
        'case_type': case_type,
        'check_item_id': check_item_id,
        'return_event_id': return_event_id,
        'status': 'OPEN',
        'assigned_analyst_id': None,
        'disposition': None,
        'resolution_amount_cents': None,
        'reopen_count': 0,
        'escalated_at': None,
        'resolved_at': None,
        'closed_at': None,
    })
    store.cases[case['id']] = case
    return case


# ---------------------------------------------------------------------------
# Aging (PRD §3.6)
# ---------------------------------------------------------------------------

def aging_business_days(entity):
    return business_days_elapsed(entity['created_at'].date(), clock.now().date())


def aging_calendar_days(entity):
    return calendar_days_elapsed(entity['created_at'].date(), clock.now().date())


# ---------------------------------------------------------------------------
# Return-item fee (PRD §3.4 — component-first pinned rounding)
# ---------------------------------------------------------------------------

BASE_FEE_CENTS = {
    'NSF': 2500,
    'STOP_PAYMENT': 0,
    'CLOSED_ACCOUNT': 3000,
    'MISSING_ENDORSEMENT': 0,
    'ALTERED_OR_FICTITIOUS': 0,
    'IMAGE_NONCONFORMING': 0,
    'DUPLICATE_PRESENTMENT': 0,
    'REFER_TO_MAKER': 1500,
}

RISK_MULTIPLIER = {
    'STANDARD': Decimal('1.0'),
    'HIGH_RISK': Decimal('1.5'),
}

REASON_CODES = list(BASE_FEE_CENTS.keys())
RE_PRESENTMENT_ELIGIBLE_REASONS = {'NSF', 'MISSING_ENDORSEMENT',
                                   'IMAGE_NONCONFORMING', 'REFER_TO_MAKER'}


def compute_return_item_fee(account, return_event):
    """round_half_up(base * multiplier) first, then surcharge by prior returns."""
    prior_returns = returned_item_count_30d(account['id']) - 1
    base = BASE_FEE_CENTS[return_event['reason_code']]
    mult = RISK_MULTIPLIER[account['risk_tier']]
    component = int((Decimal(base) * mult).quantize(Decimal('1'),
                                                    rounding=ROUND_HALF_UP))
    if prior_returns <= 0:
        surcharge = 0
    elif prior_returns in (1, 2):
        surcharge = 500
    else:
        surcharge = 1500
    return component + surcharge


# ---------------------------------------------------------------------------
# Recredit provisional amount (PRD §3.8 — per-day rounding pinned)
# ---------------------------------------------------------------------------

RECREDIT_PROVISIONAL_CAP_CENTS = 250000
DAILY_INTEREST_RATE = Decimal('0.0002')


def compute_recredit_amounts(req, provisioned_at):
    principal = min(req['claimed_amount_cents'], RECREDIT_PROVISIONAL_CAP_CENTS)
    days = calendar_days_elapsed(req['submitted_at'].date(), provisioned_at.date())
    per_day = int((Decimal(principal) * DAILY_INTEREST_RATE).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP))
    interest = per_day * days
    return principal, interest, principal + interest


# ---------------------------------------------------------------------------
# Input validation helpers (priority-11 shape checks unless noted otherwise)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'Request body must be a JSON object')
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == '':
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s is required and must be a non-empty string' % field)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be a string' % field)
    return v


def req_int(data, field):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s is required and must be an integer' % field)
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_int(v):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be an integer' % field)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be a boolean' % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be a boolean' % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be one of %s' % (field, ', '.join(allowed)))
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if v not in allowed:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be one of %s' % (field, ', '.join(allowed)))
    return v


def req_datetime(data, field):
    from timeutil import parse_dt
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s is required and must be an ISO 8601 timestamp' % field)
    try:
        return parse_dt(v)
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be an ISO 8601 timestamp' % field)


def opt_datetime(data, field):
    from timeutil import parse_dt
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be an ISO 8601 timestamp' % field)
    try:
        return parse_dt(v)
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'Field %s must be an ISO 8601 timestamp' % field)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_bank(b):
    return {
        'id': b['id'],
        'name': b['name'],
        'routing_number': b['routing_number'],
        'claim_window_business_days': b['claim_window_business_days'],
        'warranty_window_days': b['warranty_window_days'],
        'daily_claim_capacity': b['daily_claim_capacity'],
        'status': b['status'],
        'created_at': fmt_ts(b['created_at']),
        'updated_at': fmt_ts(b['updated_at']),
        'version': b['version'],
    }


def ser_account(a):
    return {
        'id': a['id'],
        'customer_name': a['customer_name'],
        'account_number': a['account_number'],
        'status': a['status'],
        'risk_tier': a['risk_tier'],
        'reg_cc_eligible': a['reg_cc_eligible'],
        'opening_balance_cents': a['opening_balance_cents'],
        'available_balance_cents': available_balance(a['id']),
        'settled_balance_cents': settled_balance(a['id']),
        'returned_item_count_30d': returned_item_count_30d(a['id']),
        'created_at': fmt_ts(a['created_at']),
        'updated_at': fmt_ts(a['updated_at']),
        'version': a['version'],
    }


def ser_freeze(f):
    now = clock.now()
    status = 'ACTIVE' if f['start_at'] <= now <= f['end_at'] else 'EXPIRED'
    return {
        'id': f['id'],
        'depositor_account_id': f['depositor_account_id'],
        'start_at': fmt_ts(f['start_at']),
        'end_at': fmt_ts(f['end_at']),
        'reason': f['reason'],
        'status': status,
        'created_at': fmt_ts(f['created_at']),
        'updated_at': fmt_ts(f['updated_at']),
        'version': f['version'],
    }


def ser_item(i):
    return {
        'id': i['id'],
        'depositor_account_id': i['depositor_account_id'],
        'clearing_bank_id': i['clearing_bank_id'],
        'item_reference': i['item_reference'],
        'amount_cents': i['amount_cents'],
        'encoded_amount_cents': i['encoded_amount_cents'],
        'image_quality_score': i['image_quality_score'],
        'capture_channel': i['capture_channel'],
        'status': i['status'],
        'is_large_item': i['is_large_item'],
        'presentment_count': i['presentment_count'],
        'duplicate_of_item_id': i['duplicate_of_item_id'],
        'presented_at': ts_or_none(i['presented_at']),
        'paid_at': ts_or_none(i['paid_at']),
        'created_at': fmt_ts(i['created_at']),
        'updated_at': fmt_ts(i['updated_at']),
        'version': i['version'],
    }


def ser_hold(h):
    return {
        'id': h['id'],
        'check_item_id': h['check_item_id'],
        'source': h['source'],
        'window_start_at': fmt_ts(h['window_start_at']),
        'hold_until': fmt_ts(h['hold_until']),
        'decision': h['decision'],
        'decided_at': ts_or_none(h['decided_at']),
        'decided_by_user_id': h['decided_by_user_id'],
        'status': h['status'],
        'created_at': fmt_ts(h['created_at']),
        'updated_at': fmt_ts(h['updated_at']),
        'version': h['version'],
    }


def ser_return_event(r):
    return {
        'id': r['id'],
        'check_item_id': r['check_item_id'],
        'received_at': fmt_ts(r['received_at']),
        'reason_code': r['reason_code'],
        'coded_at': ts_or_none(r['coded_at']),
        're_presentment_eligible': r['re_presentment_eligible'],
        'status': r['status'],
        'created_at': fmt_ts(r['created_at']),
        'updated_at': fmt_ts(r['updated_at']),
        'version': r['version'],
    }


def ser_case(c):
    return {
        'id': c['id'],
        'case_type': c['case_type'],
        'check_item_id': c['check_item_id'],
        'return_event_id': c['return_event_id'],
        'status': c['status'],
        'assigned_analyst_id': c['assigned_analyst_id'],
        'disposition': c['disposition'],
        'resolution_amount_cents': c['resolution_amount_cents'],
        'reopen_count': c['reopen_count'],
        'escalated_at': ts_or_none(c['escalated_at']),
        'resolved_at': ts_or_none(c['resolved_at']),
        'closed_at': ts_or_none(c['closed_at']),
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def ser_claim(c):
    return {
        'id': c['id'],
        'adjustment_case_id': c['adjustment_case_id'],
        'clearing_bank_id': c['clearing_bank_id'],
        'claimed_amount_cents': c['claimed_amount_cents'],
        'created_by_user_id': c['created_by_user_id'],
        'status': c['status'],
        'submitted_at': ts_or_none(c['submitted_at']),
        'clearing_bank_ref': c['clearing_bank_ref'],
        'recovered_amount_cents': c['recovered_amount_cents'],
        'settled_at': ts_or_none(c['settled_at']),
        'aging_calendar_days': aging_calendar_days(c),
        'aging_business_days': aging_business_days(c),
        'write_off_reason': c['write_off_reason'],
        'written_off_at': ts_or_none(c['written_off_at']),
        'created_at': fmt_ts(c['created_at']),
        'updated_at': fmt_ts(c['updated_at']),
        'version': c['version'],
    }


def ser_warranty(w):
    return {
        'id': w['id'],
        'adjustment_case_id': w['adjustment_case_id'],
        'claimed_amount_cents': w['claimed_amount_cents'],
        'created_by_user_id': w['created_by_user_id'],
        'status': w['status'],
        'deadline_at': fmt_ts(w['deadline_at']),
        'submitted_at': ts_or_none(w['submitted_at']),
        'recovered_amount_cents': w['recovered_amount_cents'],
        'settled_at': ts_or_none(w['settled_at']),
        'aging_calendar_days': aging_calendar_days(w),
        'aging_business_days': aging_business_days(w),
        'write_off_reason': w['write_off_reason'],
        'written_off_at': ts_or_none(w['written_off_at']),
        'created_at': fmt_ts(w['created_at']),
        'updated_at': fmt_ts(w['updated_at']),
        'version': w['version'],
    }


def ser_notification(n):
    return {
        'id': n['id'],
        'depositor_account_id': n['depositor_account_id'],
        'adjustment_case_id': n['adjustment_case_id'],
        'notification_type': n['notification_type'],
        'message': n['message'],
        'due_at': fmt_ts(n['due_at']),
        'status': n['status'],
        'delivered_at': ts_or_none(n['delivered_at']),
        'created_at': fmt_ts(n['created_at']),
    }


def ser_fee(f):
    return {
        'id': f['id'],
        'depositor_account_id': f['depositor_account_id'],
        'adjustment_case_id': f['adjustment_case_id'],
        'return_event_id': f['return_event_id'],
        'fee_type': f['fee_type'],
        'amount_cents': f['amount_cents'],
        'status': f['status'],
        'waived_by_user_id': f['waived_by_user_id'],
        'waive_reason': f['waive_reason'],
        'waived_at': ts_or_none(f['waived_at']),
        'created_at': fmt_ts(f['created_at']),
        'updated_at': fmt_ts(f['updated_at']),
        'version': f['version'],
    }


def ser_recredit(r):
    return {
        'id': r['id'],
        'depositor_account_id': r['depositor_account_id'],
        'check_item_id': r['check_item_id'],
        'claimed_amount_cents': r['claimed_amount_cents'],
        'reason': r['reason'],
        'status': r['status'],
        'principal_amount_cents': r['principal_amount_cents'],
        'interest_cents': r['interest_cents'],
        'provisional_amount_cents': r['provisional_amount_cents'],
        'submitted_at': fmt_ts(r['submitted_at']),
        'provisioned_at': ts_or_none(r['provisioned_at']),
        'provisioned_late': r['provisioned_late'],
        'breach_flagged': r['breach_flagged'],
        'finalized_at': ts_or_none(r['finalized_at']),
        'created_at': fmt_ts(r['created_at']),
        'updated_at': fmt_ts(r['updated_at']),
        'version': r['version'],
    }


def ser_ledger(e):
    return {
        'id': e['id'],
        'depositor_account_id': e['depositor_account_id'],
        'entry_type': e['entry_type'],
        'amount_cents': e['amount_cents'],
        'provisional': e['provisional'],
        'memo': e['memo'],
        'check_item_id': e['check_item_id'],
        'adjustment_case_id': e['adjustment_case_id'],
        'fee_assessment_id': e['fee_assessment_id'],
        'recredit_request_id': e['recredit_request_id'],
        'created_at': fmt_ts(e['created_at']),
    }
