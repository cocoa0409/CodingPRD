"""Hold decisions: manual hold placement, listing, and decide (PRD §3.2)."""
from flask import Blueprint

from db import store, clock, base_fields, touch
from domain import (get_required, post_ledger, create_notification, ser_hold,
                    body, req_string, req_datetime, opt_datetime)
from envelope import ok, paginated_list
from errors import ApiError
from security import auth_ctx, require_roles, OPS_ROLES

bp = Blueprint('holds', __name__)

ITEM_TERMINAL_STATES = {'PAID', 'DUPLICATE_REJECTED', 'DEPOSIT_REJECTED'}


@bp.route('/bank/check-items/<iid>/hold-decisions', methods=['POST'])
def create_hold(iid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')

    if item['status'] in ITEM_TERMINAL_STATES:
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Manual holds may only be placed on non-terminal items')

    data = body()
    hold_until = req_datetime(data, 'hold_until')
    reason = req_string(data, 'reason')

    # Half-open [now, hold_until) overlap: touching windows do NOT overlap.
    now = clock.now()
    for h in store.hold_decisions.values():
        if h['check_item_id'] != item['id']:
            continue
        if h['status'] == 'EXPIRED':
            continue
        if h['decision'] is not None and h['decision'] == 'RELEASE_FUNDS':
            continue
        if now < h['hold_until'] and h['window_start_at'] < hold_until:
            raise ApiError('ERR_HOLD_WINDOW_OVERLAP', 409,
                           'Hold window overlaps an existing active hold on this item')

    hold = dict(base_fields())
    hold.update({
        'check_item_id': item['id'],
        'source': 'MANUAL',
        'window_start_at': now,
        'hold_until': hold_until,
        'decision': None,
        'decided_at': None,
        'decided_by_user_id': None,
        'status': 'PENDING',
        'reason': reason,
    })
    store.hold_decisions[hold['id']] = hold
    return ok(ser_hold(hold), status=201)


@bp.route('/bank/check-items/<iid>/hold-decisions', methods=['GET'])
def list_holds(iid):
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    item = get_required(store.check_items, iid, 'ERR_ITEM_NOT_FOUND')
    items = [h for h in store.hold_decisions.values()
             if h['check_item_id'] == item['id']]
    page, pagination = paginated_list(items)
    return ok([ser_hold(h) for h in page], pagination=pagination)


@bp.route('/bank/hold-decisions/<hid>/decide', methods=['POST'])
def decide_hold(hid):
    ctx = auth_ctx()
    require_roles(ctx, ['AdjustmentAnalyst'])
    hold = get_required(store.hold_decisions, hid, 'ERR_HOLD_NOT_FOUND')

    if hold['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PENDING hold may be decided')

    data = body()
    decision = data.get('decision')
    if decision not in ('RELEASE_FUNDS', 'EXTEND_HOLD', 'RETURN_ITEM'):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'decision must be one of RELEASE_FUNDS, EXTEND_HOLD, RETURN_ITEM')

    item = store.check_items.get(hold['check_item_id'])

    if decision == 'EXTEND_HOLD':
        extend_until = req_datetime(data, 'extend_until')
        if extend_until <= hold['hold_until']:
            raise ApiError('ERR_INVALID_REQUEST', 400,
                           'extend_until must be strictly later than the current hold_until')

    if decision == 'RELEASE_FUNDS' and item is not None:
        pending = [h for h in store.hold_decisions.values()
                   if h['check_item_id'] == item['id'] and h['status'] == 'PENDING']
        pending.sort(key=lambda h: h['_seq'])
        if not pending or pending[-1]['id'] != hold['id']:
            raise ApiError('ERR_INVALID_STATE', 409,
                           'Only the item\'s latest PENDING hold may release funds')

    hold['decision'] = decision
    hold['decided_at'] = clock.now()
    hold['decided_by_user_id'] = ctx['user_id']
    hold['status'] = 'DECIDED'
    touch(hold)

    if item is not None:
        if decision == 'RELEASE_FUNDS':
            if item['status'] == 'UNDER_REVIEW':
                item['status'] = 'RECEIVED'
                touch(item)
        elif decision == 'EXTEND_HOLD':
            hold['hold_until'] = extend_until
            touch(hold)
        elif decision == 'RETURN_ITEM':
            if item['status'] == 'UNDER_REVIEW':
                item['status'] = 'DEPOSIT_REJECTED'
                touch(item)
                account = store.accounts.get(item['depositor_account_id'])
                post_ledger(account['id'], 'PROVISIONAL_REVERSAL',
                            -item['amount_cents'], True,
                            memo='Deposit rejected for item %s'
                                 % item['item_reference'],
                            check_item_id=item['id'])
                # Linked LARGE_ITEM_REVIEW case auto-resolves with NO_ACTION.
                linked = next((c for c in store.cases.values()
                               if c['check_item_id'] == item['id']
                               and c['case_type'] == 'LARGE_ITEM_REVIEW'), None)
                if linked is not None and linked['status'] == 'OPEN':
                    linked['status'] = 'RESOLVED'
                    linked['disposition'] = 'NO_ACTION'
                    linked['resolved_at'] = clock.now()
                    touch(linked)
                create_notification(account['id'],
                                    linked['id'] if linked else None,
                                    'DEPOSIT_REJECTED_NOTICE',
                                    'Your deposit of item %s was rejected.'
                                    % item['item_reference'])

    return ok(ser_hold(hold))
