from decimal import Decimal, ROUND_HALF_UP
from storage import db


def recompute_acceptance_rate(rider):
    offers = []
    for a in db.assignments.values():
        if a.rider_id == rider.id and a.status in ("ACCEPTED", "PICKED_UP", "DELIVERED", "REJECTED", "CANCELLED"):
            offers.append(a)
    offers.sort(key=lambda a: a.created_at, reverse=True)
    last_30 = offers[:30]
    if not last_30:
        rider.acceptance_rate = 1.0
        return
    accepted = sum(1 for a in last_30 if a.status in ("ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"))
    rider.acceptance_rate = round(accepted / len(last_30), 10)


def recompute_on_time_rate(rider):
    delivered = []
    for a in db.assignments.values():
        if a.rider_id == rider.id and a.status == "DELIVERED":
            delivered.append(a)
    delivered.sort(key=lambda a: a.delivered_at, reverse=True)
    last_30 = delivered[:30]
    if len(last_30) < 10:
        rider.on_time_rate = 1.0
        return
    on_time = 0
    for a in last_30:
        order = db.orders.get(a.order_id)
        if order and a.delivered_at <= order.promised_delivery_time:
            on_time += 1
    rider.on_time_rate = round(on_time / len(last_30), 10)


def recompute_bonus_tier(rider):
    score = Decimal("0.6") * Decimal(str(rider.on_time_rate)) + \
            Decimal("0.3") * Decimal(str(rider.acceptance_rate)) + \
            Decimal("0.1") * (Decimal(str(rider.rating)) / Decimal("5"))
    score = score.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    score_f = float(score)
    if score_f >= 0.90:
        rider.bonus_tier = "PLATINUM"
    elif score_f >= 0.80:
        rider.bonus_tier = "GOLD"
    elif score_f >= 0.70:
        rider.bonus_tier = "SILVER"
    else:
        rider.bonus_tier = "BRONZE"


def recompute_rating(rider):
    delivered = []
    for a in db.assignments.values():
        if a.rider_id == rider.id and a.status == "DELIVERED":
            delivered.append(a)
    delivered.sort(key=lambda a: a.delivered_at, reverse=True)
    last_30 = delivered[:30]
    if not last_30:
        rider.rating = 5.0
        return
    ratings = []
    for a in last_30:
        order = db.orders.get(a.order_id)
        if order and hasattr(order, "rider_rating") and order.rider_rating is not None:
            ratings.append(order.rider_rating)
    if not ratings:
        rider.rating = 5.0
    else:
        rider.rating = round(sum(ratings) / len(ratings), 10)
