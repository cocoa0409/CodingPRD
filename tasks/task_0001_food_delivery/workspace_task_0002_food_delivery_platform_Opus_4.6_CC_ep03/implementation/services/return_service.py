from datetime import datetime, timezone
from models.database import db, Return, Order, Customer, Restaurant, Fine, WorkOrder
from utils.clock import clock


def open_return(order, data):
    now = clock.now()
    actual_dt = datetime.strptime(order.actual_delivery_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    actual_dt = actual_dt.replace(tzinfo=timezone.utc)
    hours_since = (now - actual_dt).total_seconds() / 3600
    if hours_since > 24:
        return None, 'ERR_RETURN_WINDOW_EXPIRED'

    requested = data.get('requested_refund_cents')
    if requested is None or not isinstance(requested, int):
        return None, 'ERR_REFUND_AMOUNT_INVALID'
    if requested < 1 or requested > order.subtotal_cents:
        return None, 'ERR_REFUND_AMOUNT_INVALID'

    existing = Return.query.filter_by(order_id=order.id).filter(
        Return.status.in_(['REQUESTED', 'APPROVED', 'ESCALATED'])
    ).first()
    if existing:
        return None, 'ERR_DUPLICATE_RETURN'

    reason = data.get('reason')
    valid_reasons = ('QUALITY_ISSUE', 'WRONG_ITEM', 'LATE', 'OTHER')
    if reason not in valid_reasons:
        return None, 'ERR_VALIDATION'

    ret = Return(
        order_id=order.id,
        reason=reason,
        requested_refund_cents=requested,
    )
    db.session.add(ret)
    db.session.flush()

    order.status = 'REFUND_REQUESTED'
    order.touch()

    return ret, None


def approve_return(ret, data, cs_user_id):
    order = Order.query.get(ret.order_id)
    approved = data.get('approved_refund_cents')
    if approved is None or not isinstance(approved, int):
        return 'ERR_REFUND_AMOUNT_INVALID'
    if approved < 1 or approved > order.subtotal_cents or approved > ret.requested_refund_cents:
        return 'ERR_REFUND_AMOUNT_INVALID'

    ret.status = 'APPROVED'
    ret.approved_refund_cents = approved
    ret.reviewer_cs_user_id = cs_user_id
    ret.touch()

    order.status = 'REFUNDED'
    if approved == order.subtotal_cents:
        order.payment_status = 'FULLY_REFUNDED'
    else:
        order.payment_status = 'PARTIALLY_REFUNDED'
    order.touch()

    customer = Customer.query.get(order.customer_id)
    customer.credit_balance_cents += approved
    customer.touch()

    restaurant = Restaurant.query.get(order.restaurant_id)
    restaurant.pending_settlement_cents -= approved
    restaurant.touch()

    if customer.trust_score < 0.5 and ret.reason == 'QUALITY_ISSUE':
        fine = Fine(
            subject_type='CUSTOMER',
            subject_id=customer.id,
            reason='ABUSIVE_RETURN',
            amount_cents=approved,
            order_id=order.id,
        )
        db.session.add(fine)

    return None


def reject_return(ret, cs_user_id):
    order = Order.query.get(ret.order_id)
    ret.status = 'REJECTED'
    ret.reviewer_cs_user_id = cs_user_id
    ret.touch()
    order.status = 'DELIVERED'
    order.touch()


def escalate_return(ret):
    ret.status = 'ESCALATED'
    ret.touch()

    wo = WorkOrder(
        opened_by_role='CUSTOMER_SERVICE',
        opened_by_id='system',
        category='OTHER',
        related_return_id=ret.id,
        related_order_id=ret.order_id,
    )
    db.session.add(wo)
    db.session.flush()
    return wo


def reopen_return(ret):
    ret.status = 'REQUESTED'
    ret.touch()

    wo = WorkOrder.query.filter_by(related_return_id=ret.id).filter(
        WorkOrder.status != 'CLOSED'
    ).first()
    if wo:
        wo.status = 'CLOSED'
        wo.touch()
