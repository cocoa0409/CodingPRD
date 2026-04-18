from models.database import db, Assignment, Rider, RouteGroup, Order, Restaurant
from utils.clock import clock
from utils.calculations import haversine_raw


def find_best_rider(exclude_ids=None):
    query = Rider.query.filter(Rider.status.in_(['AVAILABLE', 'ON_DELIVERY']))
    if exclude_ids:
        query = query.filter(~Rider.id.in_(exclude_ids))
    riders = query.order_by(Rider.created_at.asc()).all()
    if not riders:
        return None
    available = [r for r in riders if r.status == 'AVAILABLE']
    if available:
        return available[0]
    return riders[0]


def dispatch_order(order, exclude_rider_ids=None):
    rider = find_best_rider(exclude_ids=exclude_rider_ids)
    if not rider:
        return None
    now = clock.now()
    a = Assignment(
        order_id=order.id,
        rider_id=rider.id,
        status='OFFERED',
        offered_at=clock.format(now),
    )
    db.session.add(a)
    db.session.flush()
    return a


def get_rejected_rider_ids(order_id):
    rejected = Assignment.query.filter_by(
        order_id=order_id, status='REJECTED'
    ).all()
    cancelled = Assignment.query.filter_by(
        order_id=order_id, status='CANCELLED'
    ).all()
    return [a.rider_id for a in rejected] + [a.rider_id for a in cancelled]


def try_merge_route(assignment, rider, order):
    active_group = RouteGroup.query.filter_by(
        rider_id=rider.id, status='ACTIVE'
    ).first()

    restaurant = Restaurant.query.get(order.restaurant_id)
    if not restaurant:
        return

    rider_assignments = Assignment.query.filter_by(rider_id=rider.id).filter(
        Assignment.status.in_(['ACCEPTED', 'PICKED_UP'])
    ).filter(Assignment.id != assignment.id).all()

    if not rider_assignments:
        return

    for ra in rider_assignments:
        if ra.status != 'ACCEPTED':
            continue
        peer_order = Order.query.get(ra.order_id)
        if not peer_order:
            continue
        peer_restaurant = Restaurant.query.get(peer_order.restaurant_id)
        if not peer_restaurant:
            continue
        dist = haversine_raw(restaurant.lat, restaurant.lng, peer_restaurant.lat, peer_restaurant.lng)
        if dist <= 0.5:
            if active_group:
                assignment.route_group_id = active_group.id
                ids = list(active_group.assignment_ids or [])
                ids.append(assignment.id)
                active_group.assignment_ids = ids
            else:
                now_str = clock.format(clock.now())
                group = RouteGroup(
                    rider_id=rider.id,
                    assignment_ids=[ra.id, assignment.id],
                    merged_at=now_str,
                    status='ACTIVE',
                )
                db.session.add(group)
                db.session.flush()
                ra.route_group_id = group.id
                assignment.route_group_id = group.id
                active_group = group
            return
