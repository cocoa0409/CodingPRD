import math
from models.assignment import Assignment
from models.route_group import RouteGroup
from storage import db
from models.base import now_ts


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def find_best_available_rider(exclude_rider_ids=None):
    if exclude_rider_ids is None:
        exclude_rider_ids = set()
    candidates = []
    for rider in db.riders.values():
        if rider.id in exclude_rider_ids:
            continue
        if rider.status in ("AVAILABLE", "ON_DELIVERY"):
            candidates.append(rider)
    if not candidates:
        return None
    tier_order = {"PLATINUM": 0, "GOLD": 1, "SILVER": 2, "BRONZE": 3}
    candidates.sort(key=lambda r: (tier_order.get(r.bonus_tier, 4), -r.acceptance_rate, r.created_at))
    return candidates[0]


def dispatch_order(order_id, exclude_rider_ids=None):
    rider = find_best_available_rider(exclude_rider_ids)
    if rider is None:
        return None
    assignment = Assignment(order_id, rider.id)
    db.assignments[assignment.id] = assignment
    return assignment


def try_merge_route(assignment, rider):
    rider_active_assignments = [
        a for a in db.assignments.values()
        if a.rider_id == rider.id
        and a.id != assignment.id
        and a.status in ("ACCEPTED", "PICKED_UP")
    ]
    if not rider_active_assignments:
        return

    new_order = db.orders.get(assignment.order_id)
    if not new_order:
        return
    new_restaurant = db.restaurants.get(new_order.restaurant_id)
    if not new_restaurant:
        return

    for existing_a in rider_active_assignments:
        if existing_a.status != "ACCEPTED":
            continue
        existing_order = db.orders.get(existing_a.order_id)
        if not existing_order:
            continue
        existing_restaurant = db.restaurants.get(existing_order.restaurant_id)
        if not existing_restaurant:
            continue

        dist_m = haversine_km(
            new_restaurant.lat, new_restaurant.lng,
            existing_restaurant.lat, existing_restaurant.lng
        ) * 1000

        if dist_m <= 500:
            if existing_a.route_group_id:
                rg = db.route_groups.get(existing_a.route_group_id)
                if rg and rg.status == "ACTIVE":
                    rg.assignment_ids.append(assignment.id)
                    assignment.route_group_id = rg.id
                    return
            else:
                rg = RouteGroup(rider.id, [existing_a.id, assignment.id])
                db.route_groups[rg.id] = rg
                existing_a.route_group_id = rg.id
                assignment.route_group_id = rg.id
                return


def sweep_expired_offers(current_time):
    expired = []
    for a in list(db.assignments.values()):
        if a.status == "OFFERED":
            elapsed = (current_time - a.offered_at).total_seconds()
            if elapsed >= 60:
                expired.append(a)

    for a in expired:
        a.status = "REJECTED"
        rider = db.riders.get(a.rider_id)
        if rider:
            from services.rider_metrics import recompute_acceptance_rate, recompute_bonus_tier
            recompute_acceptance_rate(rider)
            recompute_bonus_tier(rider)
            rider.touch()
        active_for_order = [
            x for x in db.assignments.values()
            if x.order_id == a.order_id and x.status in ("OFFERED", "ACCEPTED", "PICKED_UP")
        ]
        if not active_for_order:
            order = db.orders.get(a.order_id)
            if order and order.status not in ("CANCELLED", "DELIVERED", "REFUNDED"):
                tried = {x.rider_id for x in db.assignments.values() if x.order_id == a.order_id}
                dispatch_order(a.order_id, exclude_rider_ids=tried)
