from datetime import datetime, timezone
from models.database import db, Assignment, Order, Rider, Restaurant, Fine, RouteGroup
from services.rider_service import (
    recompute_bonus_tier, recompute_acceptance_rate, recompute_on_time_rate,
)
from services.dispatch_service import dispatch_order, get_rejected_rider_ids, try_merge_route
from utils.clock import clock
from utils.calculations import (
    compute_delivery_fee, compute_tiered_commission, compute_flat_commission,
    compute_late_fine,
)
import math


def create_fine(subject_type, subject_id, reason, amount_cents, order_id=None):
    fine = Fine(
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason,
        amount_cents=amount_cents,
        order_id=order_id,
    )
    db.session.add(fine)
    db.session.flush()
    return fine


def accept_assignment(assignment, rider):
    order = Order.query.get(assignment.order_id)

    active = Assignment.query.filter_by(order_id=assignment.order_id).filter(
        Assignment.status.in_(['ACCEPTED', 'PICKED_UP'])
    ).first()
    if active:
        return None, 'ERR_ORDER_ALREADY_ASSIGNED'

    assignment.status = 'ACCEPTED'
    assignment.accepted_at = clock.format(clock.now())

    if rider.status == 'AVAILABLE':
        rider.status = 'ON_DELIVERY'
    rider.touch()

    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)

    try_merge_route(assignment, rider, order)

    return assignment, None


def reject_assignment(assignment, rider):
    assignment.status = 'REJECTED'

    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)
    rider.touch()

    order = Order.query.get(assignment.order_id)
    exclude_ids = get_rejected_rider_ids(order.id)
    dispatch_order(order, exclude_rider_ids=exclude_ids)

    return assignment


def pickup_assignment(assignment):
    order = Order.query.get(assignment.order_id)
    assignment.status = 'PICKED_UP'
    assignment.picked_up_at = clock.format(clock.now())
    order.status = 'PICKED_UP'
    order.touch()
    return assignment


def deliver_assignment(assignment):
    order = Order.query.get(assignment.order_id)
    rider = Rider.query.get(assignment.rider_id)
    restaurant = Restaurant.query.get(order.restaurant_id)
    now = clock.now()

    assignment.status = 'DELIVERED'
    assignment.delivered_at = clock.format(now)

    order.status = 'DELIVERED'
    order.actual_delivery_time = clock.format(now)

    promised_dt = datetime.strptime(order.promised_delivery_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    promised_dt = promised_dt.replace(tzinfo=timezone.utc)
    diff_seconds = (now - promised_dt).total_seconds()
    order.minutes_late = max(0, int(math.floor(diff_seconds / 60))) if diff_seconds > 0 else 0

    solo_fee = compute_delivery_fee(order.distance_km, order.is_peak)
    if assignment.route_group_id:
        group = RouteGroup.query.get(assignment.route_group_id)
        if group and len(group.assignment_ids) >= 2:
            discount = int(math.floor(solo_fee * 0.25))
            final_fee = solo_fee - discount
        else:
            final_fee = solo_fee
    else:
        final_fee = solo_fee

    order.final_delivery_fee_cents = final_fee
    assignment.final_delivery_fee_cents = final_fee

    if restaurant.commission_rate_override is not None:
        order.final_commission_cents = compute_flat_commission(
            order.subtotal_cents, restaurant.commission_rate_override
        )
    else:
        order.final_commission_cents = compute_tiered_commission(order.subtotal_cents)

    order.payment_status = 'CAPTURED'
    order.touch()

    if order.minutes_late > 0:
        fine_amount = compute_late_fine(order.minutes_late, final_fee)
        fine = create_fine('RIDER', rider.id, 'LATE_DELIVERY', fine_amount, order.id)
        rider.wallet_balance_cents -= fine_amount
        recompute_on_time_rate(rider)
        recompute_bonus_tier(rider)

    restaurant.pending_settlement_cents += (order.subtotal_cents - order.final_commission_cents)
    restaurant.touch()

    rider.wallet_balance_cents += final_fee
    recompute_on_time_rate(rider)
    recompute_bonus_tier(rider)
    rider.touch()

    if assignment.route_group_id:
        group = RouteGroup.query.get(assignment.route_group_id)
        if group:
            all_delivered = True
            for aid in group.assignment_ids:
                peer = Assignment.query.get(aid)
                if peer and peer.status != 'DELIVERED':
                    all_delivered = False
                    break
            if all_delivered:
                group.status = 'COMPLETED'

    has_active = Assignment.query.filter_by(rider_id=rider.id).filter(
        Assignment.status.in_(['OFFERED', 'ACCEPTED', 'PICKED_UP'])
    ).first()
    if not has_active:
        rider.status = 'AVAILABLE'
        rider.touch()

    return assignment


def cancel_assignment(assignment):
    rider = Rider.query.get(assignment.rider_id)
    order = Order.query.get(assignment.order_id)
    assignment.status = 'CANCELLED'

    fine = create_fine('RIDER', rider.id, 'RIDER_NO_SHOW', 500, order.id)
    rider.wallet_balance_cents -= 500
    recompute_bonus_tier(rider)
    rider.touch()

    if assignment.route_group_id:
        group = RouteGroup.query.get(assignment.route_group_id)
        if group:
            ids = list(group.assignment_ids)
            if assignment.id in ids:
                ids.remove(assignment.id)
                group.assignment_ids = ids
            if not ids:
                group.status = 'ABANDONED'

    exclude_ids = get_rejected_rider_ids(order.id)
    exclude_ids.append(rider.id)
    dispatch_order(order, exclude_rider_ids=exclude_ids)

    has_active = Assignment.query.filter_by(rider_id=rider.id).filter(
        Assignment.status.in_(['OFFERED', 'ACCEPTED', 'PICKED_UP'])
    ).first()
    if not has_active and rider.status == 'ON_DELIVERY':
        rider.status = 'AVAILABLE'
        rider.touch()

    return assignment
