"""Check items: deposit, presentment (duplicate/encoding/image branches),
payment, return recording, reason coding, re-presentment (PRD §3.2–§3.4)."""
from flask import Blueprint, request

from db import store, clock, base_fields, touch
from domain import (get_required, post_ledger, create_notification, create_case,
                    account_deposit_blocked, compute_return_item_fee,
                    ser_item, ser_return_event, body, req_string, req_int,
                    opt_string, REASON_CODES, RE_PRESENTMENT_ELIGIBLE_REASONS,
                    item_account)
from envelope import ok, paginated_list
from errors import ApiError
from security import auth_ctx, require_roles, customer_owns, OPS_ROLES, ALL_ROLES
from timeutil import add_business_days

bp = Blueprint('items', __name__)

CAPTURE_CHANNELS = ['BRANCH', 'ATM', 'MOBILE', 'RDC']
LARGE_ITEM_THRESHOLD_CENTS = 500000
IMAGE_QUALITY_MIN_SCORE = 60
AUTO_HOLD_BUSINESS_DAYS = 2
ITEM_TERMINAL_STATES = {'PAID', 'DUPLICATE_REJECTED', 'DEPOSIT_REJECTED'}


def _touch_item(item):
    touch(item)


@bp.route('/bank/check-items', methods=['POST'])
def create_item():
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    data = body()

    # References needed for existence checks (priority 4).
    account_id = data.get('depositor_account_id')
    bank_id = data.get('clearing_bank_id')
    if not isinstance(account_id, str) or not account_id:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'depositor_account_id is required')
    if not isinstance(bank_id, str) or not bank_id:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'clearing_bank_id is required')
    account = get_required(store.accounts, account_id, 'ERR_ACCOUNT_NOT_FOUND')
    bank = get_required(store.clearing_banks, bank_id, 'ERR_CLEARING_BANK_NOT_FOUND')

    # State (priority 6): deposits rejected on FROZEN / freeze-windowed accounts.
    if account_deposit_blocked(account):
        raise ApiError('ERR_ACCOUNT_FROZEN', 409,
                       'Account is frozen or covered by an active freeze window')

    # Shape (priority 11).
    item_reference = req_string(data, 'item_reference')
    amount_cents = req_int(data, 'amount_cents')
    if amount_cents <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'amount_cents must be a positive integer')
    encoded_amount_cents = req_int(data, 'encoded_amount_cents')
    if encoded_amount_cents < 0:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'encoded_amount_cents must be a non-negative integer')
    image_quality_score = req_int(data, 'image_quality_score')
    if not (0 <= image_quality_score <= 100):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'image_quality_score must be between 0 and 100 inclusive')
    capture_channel = data.get('capture_channel')
    if capture_channel not in CAPTURE_CHANNELS:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'capture_channel must be one of BRANCH, ATM, MOBILE, RDC')

    is_large = amount_cents >= LARGE_ITEM_THRESHOLD_CENTS
    item = dict(base_fields())
    item.update({
        'depositor_account_id': account['id'],
        'clearing_bank_id': bank['id'],
        'item_reference': item_reference,
        'amount_cents': amount_cents,
        'encoded_amount_cents': encoded_amount_cents,
        'image_quality_score': image_quality_score,
        'capture_channel': capture_channel,
        'status': 'RECEIVED',
        'is_large_item': is_large,
        'presentment_count': 0,
        'duplicate_of_item_id': None,
        'presented_at': None,
        'paid_at': None,
    })
    store.check_items[item['id']] = item

    # Provisional deposit credit: funds visible at once, nothing settled.
    post_ledger(account['id'], 'DEPOSIT_CREDIT', amount_cents, True,
                memo='Deposit credit for item %s' % item_reference,
                check_item_id=item['id'])

    # Large-item review cascade: never rests in RECEIVED.
    if is_large:
        item['status'] = 'UNDER_REVIEW'
        touch(item)
        hold = dict(base_fields())
        hold.update({
            'check_item_id': item['id'],
            'source': 'AUTO_LARGE_ITEM',
            'window_start_at': item['created_at'],
            'hold_until': add_business_days(item['created_at'], AUTO_HOLD_BUSINESS_DAYS),
            'decision': None,
            'decided_at': None,
            'decided_by_user_id': None,
            'status': 'PENDING',
        })
        store.hold_decisions[hold['id']] = hold
        case = create_case('LARGE_ITEM_REVIEW', item['id'])
        create_notification(account['id'], case['id'], 'LARGE_ITEM_HOLD_NOTICE',
                            'Your deposit of %d cents is under large-item review.'
                            % amount_cents)

    return ok(ser_item(item), status=201)


@bp.route('/bank/check-items/<iid>', methods=['GET'])
def get_item(iid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    customer_owns(ctx, item['depositor_account_id'])
    return ok(ser_item(item))


@bp.route('/bank/check-items', methods=['GET'])
def list_items():
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    account_id = request.args.get('depositor_account_id')
    bank_id = request.args.get('clearing_bank_id')
    dup_of = request.args.get('duplicate_of_item_id')
    status = request.args.get('status')
    items = [i for i in store.check_items.values()
             if (account_id is None or i['depositor_account_id'] == account_id)
             and (bank_id is None or i['clearing_bank_id'] == bank_id)
             and (dup_of is None or i['duplicate_of_item_id'] == dup_of)
             and (status is None or i['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_item(i) for i in page], pagination=pagination)


@bp.route('/bank/check-items/<iid>/present', methods=['POST'])
def present_item(iid):
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')

    if item['status'] != 'RECEIVED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a RECEIVED item may be presented')
    bank = store.clearing_banks.get(item['clearing_bank_id'])
    if bank is None or bank['status'] != 'ACTIVE':
        raise ApiError('ERR_CLEARING_BANK_SUSPENDED', 409,
                       'Clearing bank is suspended')

    # Duplicate detection: another item with the same reference already
    # PRESENTED or PAID (earliest created_at is the match).
    matches = [i for i in store.check_items.values()
               if i['id'] != item['id']
               and i['item_reference'] == item['item_reference']
               and i['status'] in ('PRESENTED', 'PAID')]
    account = item_account(item)
    if matches:
        matches.sort(key=lambda i: i['_seq'])
        item['status'] = 'DUPLICATE_REJECTED'
        item['duplicate_of_item_id'] = matches[0]['id']
        touch(item)
        post_ledger(account['id'], 'DUPLICATE_REVERSAL_CREDIT',
                    -item['amount_cents'], True,
                    memo='Duplicate presentment reversal for item %s'
                         % item['item_reference'],
                    check_item_id=item['id'])
        case = create_case('DUPLICATE_PRESENTMENT', item['id'])
        create_notification(account['id'], case['id'], 'DUPLICATE_NOTICE',
                            'A duplicate presentment of item %s was rejected.'
                            % item['item_reference'])
        return ok(ser_item(item))

    item['status'] = 'PRESENTED'
    item['presented_at'] = clock.now()
    item['presentment_count'] += 1
    touch(item)

    # Defect detectors at presentment.
    if item['encoded_amount_cents'] != item['amount_cents']:
        case = create_case('ENCODING_ERROR', item['id'])
        claim = dict(base_fields())
        claim.update({
            'adjustment_case_id': case['id'],
            'clearing_bank_id': item['clearing_bank_id'],
            'claimed_amount_cents': abs(item['encoded_amount_cents']
                                        - item['amount_cents']),
            'created_by_user_id': 'system',
            'status': 'DRAFT',
            'submitted_at': None,
            'clearing_bank_ref': None,
            'recovered_amount_cents': None,
            'settled_at': None,
            'write_off_reason': None,
            'written_off_at': None,
        })
        store.claims[claim['id']] = claim
    if item['image_quality_score'] < IMAGE_QUALITY_MIN_SCORE:
        create_case('IMAGE_WARRANTY', item['id'])

    return ok(ser_item(item))


@bp.route('/bank/check-items/<iid>/pay', methods=['POST'])
def pay_item(iid):
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    if item['status'] != 'PRESENTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PRESENTED item may be paid')
    item['status'] = 'PAID'
    item['paid_at'] = clock.now()
    touch(item)
    account = item_account(item)
    post_ledger(account['id'], 'PROVISIONAL_REVERSAL', -item['amount_cents'], True,
                memo='Provisional reversal on payment of item %s'
                     % item['item_reference'],
                check_item_id=item['id'])
    post_ledger(account['id'], 'SETTLEMENT_CREDIT', item['amount_cents'], False,
                memo='Settlement credit for item %s' % item['item_reference'],
                check_item_id=item['id'])
    return ok(ser_item(item))


@bp.route('/bank/check-items/<iid>/return-events', methods=['POST'])
def create_return_event(iid):
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    if item['status'] != 'PRESENTED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PRESENTED item may be returned')
    item['status'] = 'RETURNED'
    touch(item)

    event = dict(base_fields())
    event.update({
        'check_item_id': item['id'],
        'received_at': clock.now(),
        'reason_code': None,
        'coded_at': None,
        're_presentment_eligible': None,
        'status': 'PENDING_CODING',
    })
    store.return_events[event['id']] = event

    account = item_account(item)
    post_ledger(account['id'], 'ITEM_RETURN_DEBIT', -item['amount_cents'], True,
                memo='Return debit for item %s' % item['item_reference'],
                check_item_id=item['id'])
    create_case('RETURN_ITEM', item['id'], return_event_id=event['id'])
    return ok(ser_return_event(event), status=201)


@bp.route('/bank/check-items/<iid>/return-events', methods=['GET'])
def list_return_events(iid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    customer_owns(ctx, item['depositor_account_id'])
    items = [r for r in store.return_events.values()
             if r['check_item_id'] == item['id']]
    page, pagination = paginated_list(items)
    return ok([ser_return_event(r) for r in page], pagination=pagination)


@bp.route('/bank/return-events/<rid>/code', methods=['POST'])
def code_return_event(rid):
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    event = get_required(store.return_events, rid, 'ERR_RETURN_EVENT_NOT_FOUND')
    if event['status'] != 'PENDING_CODING':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PENDING_CODING return event may be coded')

    data = body()
    reason_code = data.get('reason_code')
    if reason_code not in REASON_CODES:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'reason_code must be one of %s' % ', '.join(REASON_CODES))

    event['reason_code'] = reason_code
    event['coded_at'] = clock.now()
    event['re_presentment_eligible'] = reason_code in RE_PRESENTMENT_ELIGIBLE_REASONS
    event['status'] = 'CODED'
    touch(event)

    item = store.check_items.get(event['check_item_id'])
    account = item_account(item)
    case = next((c for c in store.cases.values()
                 if c.get('return_event_id') == event['id']), None)

    # Return-item fee: assessed and posted immediately at coding.
    fee_amount = compute_return_item_fee(account, event)
    fee = dict(base_fields())
    fee.update({
        'depositor_account_id': account['id'],
        'adjustment_case_id': case['id'] if case else None,
        'return_event_id': event['id'],
        'fee_type': 'RETURN_ITEM_FEE',
        'amount_cents': fee_amount,
        'status': 'POSTED',
        'waived_by_user_id': None,
        'waive_reason': None,
        'waived_at': None,
    })
    store.fees[fee['id']] = fee
    post_ledger(account['id'], 'FEE_DEBIT', -fee_amount, False,
                memo='Return-item fee (%s)' % reason_code,
                fee_assessment_id=fee['id'])

    create_notification(account['id'], case['id'] if case else None,
                        'RETURN_NOTICE',
                        'Your deposited item %s was returned: %s.'
                        % (item['item_reference'], reason_code))
    return ok(ser_return_event(event))


@bp.route('/bank/check-items/<iid>/represent', methods=['POST'])
def represent_item(iid):
    ctx = auth_ctx()
    require_roles(ctx, ['ItemProcessor'])
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')

    if item['status'] != 'RETURNED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a RETURNED item may be re-presented')
    events = [r for r in store.return_events.values()
              if r['check_item_id'] == item['id']]
    events.sort(key=lambda r: r['_seq'])
    latest = events[-1] if events else None
    if latest is None or latest['status'] != 'CODED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Latest return event must be coded before re-presentment')
    if not latest['re_presentment_eligible']:
        raise ApiError('ERR_RE_PRESENTMENT_NOT_ELIGIBLE', 409,
                       'Latest coded return is not eligible for re-presentment')
    if item['presentment_count'] >= 2:
        raise ApiError('ERR_MAX_PRESENTMENTS_EXCEEDED', 409,
                       'Item has reached the maximum of 2 presentments')

    item['status'] = 'PRESENTED'
    item['presentment_count'] += 1
    item['presented_at'] = clock.now()
    touch(item)
    return ok(ser_item(item))
