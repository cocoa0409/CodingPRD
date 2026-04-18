from models.database import db, Rider, Assignment
from utils.calculations import compute_bonus_score, score_to_tier


def create_rider(data):
    r = Rider(name=data['name'], phone=data['phone'])
    db.session.add(r)
    db.session.flush()
    return r


def recompute_bonus_tier(rider):
    score = compute_bonus_score(rider.on_time_rate, rider.acceptance_rate, rider.rating)
    rider.bonus_tier = score_to_tier(score)


def recompute_acceptance_rate(rider):
    recent = (
        Assignment.query
        .filter_by(rider_id=rider.id)
        .filter(Assignment.status.in_(['ACCEPTED', 'PICKED_UP', 'DELIVERED', 'REJECTED', 'CANCELLED']))
        .order_by(Assignment.created_at.desc())
        .limit(30)
        .all()
    )
    if not recent:
        rider.acceptance_rate = 1.0
        return
    accepted = sum(1 for a in recent if a.status in ('ACCEPTED', 'PICKED_UP', 'DELIVERED', 'CANCELLED'))
    rider.acceptance_rate = round(accepted / len(recent), 10)


def recompute_on_time_rate(rider):
    from models.database import Order
    delivered = (
        Assignment.query
        .filter_by(rider_id=rider.id, status='DELIVERED')
        .order_by(Assignment.delivered_at.desc())
        .limit(30)
        .all()
    )
    if len(delivered) < 10:
        rider.on_time_rate = 1.0
        return
    on_time = 0
    for a in delivered:
        order = Order.query.get(a.order_id)
        if order and (order.minutes_late is None or order.minutes_late == 0):
            on_time += 1
    rider.on_time_rate = round(on_time / len(delivered), 10)


def has_active_assignments(rider_id):
    return Assignment.query.filter_by(rider_id=rider_id).filter(
        Assignment.status.in_(['OFFERED', 'ACCEPTED', 'PICKED_UP'])
    ).first() is not None
