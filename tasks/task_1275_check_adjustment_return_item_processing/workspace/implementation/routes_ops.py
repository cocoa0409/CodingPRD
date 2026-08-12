"""Daily operations sweep (PRD §3.9) and the logical-clock test driver."""
from db import store, clock, touch, fmt_ts
from domain import (ser_claim, aging_business_days, body)
from envelope import ok
from errors import ApiError
from flask import Blueprint
from security import auth_ctx, require_roles
from timeutil import business_days_elapsed, parse_dt

bp = Blueprint('ops', __name__)

CLAIM_ESCALATION_BUSINESS_DAYS = 10
RECREDIT_PROVISIONAL_BUSINESS_DAYS = 2


@bp.route('/bank/ops/run-daily', methods=['POST'])
def run_daily():
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    now = clock.now()

    # 1. Escalate stale adjustment claims (SUBMITTED / ACKNOWLEDGED, >= 10 biz days).
    claims_escalated = 0
    for c in store.claims.values():
        if c['status'] in ('SUBMITTED', 'ACKNOWLEDGED') \
                and aging_business_days(c) >= CLAIM_ESCALATION_BUSINESS_DAYS:
            c['status'] = 'ESCALATED'
            touch(c)
            claims_escalated += 1

    # 2. Escalate stale warranty claims (SUBMITTED, >= 10 biz days).
    warranties_escalated = 0
    for w in store.warranties.values():
        if w['status'] == 'SUBMITTED' \
                and aging_business_days(w) >= CLAIM_ESCALATION_BUSINESS_DAYS:
            w['status'] = 'ESCALATED'
            touch(w)
            warranties_escalated += 1

    # 3. Breach overdue notifications; escalate their linked cases.
    notifications_breached = 0
    for n in store.notifications.values():
        if n['status'] == 'PENDING' and now > n['due_at']:
            n['status'] = 'BREACHED'
            notifications_breached += 1
            case = store.cases.get(n['adjustment_case_id']) \
                if n['adjustment_case_id'] else None
            if case is not None and case['status'] in ('OPEN', 'ASSIGNED', 'REOPENED'):
                case['status'] = 'ESCALATED'
                case['escalated_at'] = now
                touch(case)

    # 4. Expire pending holds; auto-release UNDER_REVIEW items.
    holds_expired = 0
    for h in store.hold_decisions.values():
        if h['status'] == 'PENDING' and h['hold_until'] <= now:
            h['status'] = 'EXPIRED'
            touch(h)
            holds_expired += 1
            item = store.check_items.get(h['check_item_id'])
            if item is not None and item['status'] == 'UNDER_REVIEW':
                item['status'] = 'RECEIVED'
                touch(item)

    # 5. Flag late recredit requests (still SUBMITTED > 2 business days).
    recredits_flagged = 0
    for r in store.recredits.values():
        if r['status'] == 'SUBMITTED' and not r['breach_flagged']:
            if business_days_elapsed(r['submitted_at'].date(), now.date()) \
                    > RECREDIT_PROVISIONAL_BUSINESS_DAYS:
                r['breach_flagged'] = True
                touch(r)
                recredits_flagged += 1

    return ok({
        'claims_escalated': claims_escalated,
        'warranties_escalated': warranties_escalated,
        'notifications_breached': notifications_breached,
        'holds_expired': holds_expired,
        'recredits_flagged': recredits_flagged,
    })


@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    data = body()
    to_iso8601 = data.get('to_iso8601')
    if not isinstance(to_iso8601, str):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'to_iso8601 is required and must be an ISO 8601 timestamp')
    try:
        target = parse_dt(to_iso8601)
    except ValueError:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'to_iso8601 must be an ISO 8601 timestamp')
    clock.set(target)
    return ok({'current_utc': fmt_ts(clock.now())})
