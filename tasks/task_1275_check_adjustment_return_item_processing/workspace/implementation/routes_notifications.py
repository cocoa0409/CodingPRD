"""Customer notifications: read, list, deliver (PRD §3.7)."""
from flask import Blueprint, request

from db import store, clock
from domain import get_required, ser_notification
from envelope import ok, paginated_list
from errors import ApiError
from security import (auth_ctx, require_roles, customer_owns,
                      customer_list_scope, ALL_ROLES)

bp = Blueprint('notifications', __name__)


@bp.route('/bank/notifications/<nid>', methods=['GET'])
def get_notification(nid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    n = get_required(store.notifications, nid, 'ERR_NOTIFICATION_NOT_FOUND')
    customer_owns(ctx, n['depositor_account_id'])
    return ok(ser_notification(n))


@bp.route('/bank/notifications', methods=['GET'])
def list_notifications():
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    account_id = customer_list_scope(ctx, request.args.get('depositor_account_id'))
    case_id = request.args.get('adjustment_case_id')
    status = request.args.get('status')
    items = [n for n in store.notifications.values()
             if (account_id is None or n['depositor_account_id'] == account_id)
             and (case_id is None or n['adjustment_case_id'] == case_id)
             and (status is None or n['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_notification(n) for n in page], pagination=pagination)


@bp.route('/bank/notifications/<nid>/deliver', methods=['POST'])
def deliver_notification(nid):
    ctx = auth_ctx()
    require_roles(ctx, ['CustomerService'])
    n = get_required(store.notifications, nid, 'ERR_NOTIFICATION_NOT_FOUND')
    if n['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'Only a PENDING notification may be delivered')
    n['status'] = 'DELIVERED'
    n['delivered_at'] = clock.now()
    return ok(ser_notification(n))
