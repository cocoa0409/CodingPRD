"""All fee / payout / penalty / rating calculations."""

import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import db


# ---------- haversine ----------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------- surge multiplier ----------
def get_surge_multiplier(lat, lon):
    best = 1.0
    for sz in db.surge_zones.values():
        if sz["status"] != "ACTIVE":
            continue
        d = haversine_km(lat, lon, sz["center_latitude"], sz["center_longitude"])
        if d <= sz["radius_km"]:
            if sz["surge_multiplier"] > best:
                best = sz["surge_multiplier"]
    return best


# ---------- delivery fee ----------
def calc_delivery_fee_provisional(restaurant, delivery_lat, delivery_lon):
    """Provisional: no vehicle surcharge."""
    dist = haversine_km(restaurant["latitude"], restaurant["longitude"], delivery_lat, delivery_lon)
    distance_fee = math.ceil(dist) * 100
    raw = 299 + distance_fee
    surge = get_surge_multiplier(restaurant["latitude"], restaurant["longitude"])
    return int(math.floor(raw * surge)), dist


def calc_delivery_fee_final(restaurant, delivery_lat, delivery_lon, vehicle_type, dist_km):
    """After rider assignment: include vehicle surcharges."""
    distance_fee = math.ceil(dist_km) * 100
    raw = 299 + distance_fee
    surge = get_surge_multiplier(restaurant["latitude"], restaurant["longitude"])
    fee = int(math.floor(raw * surge))
    if vehicle_type == "BICYCLE" and dist_km > 5:
        fee += 200
    if vehicle_type == "CAR":
        fee += 150
    return fee


# ---------- service fee ----------
def calc_service_fee(subtotal_cents):
    if subtotal_cents < 2000:
        fee = math.ceil(subtotal_cents * 0.15)
    elif subtotal_cents < 5000:
        fee = math.ceil(subtotal_cents * 0.10)
    else:
        fee = math.ceil(subtotal_cents * 0.05)
    return max(fee, 99)


# ---------- small order fee ----------
def calc_small_order_fee(subtotal_cents):
    if subtotal_cents < 1500:
        return min(1500 - subtotal_cents, 500)
    return 0


# ---------- commission & payouts ----------
def calc_commission_and_payouts(subtotal_cents, commission_rate, delivery_fee_cents, tip_cents):
    commission = int(math.floor(subtotal_cents * commission_rate))
    restaurant_payout = subtotal_cents - commission
    rider_platform_fee = int(math.floor(delivery_fee_cents * 0.20))
    rider_payout = delivery_fee_cents - rider_platform_fee + tip_cents
    return commission, restaurant_payout, rider_payout


# ---------- estimated delivery time ----------
def calc_estimated_delivery_time(distance_km, vehicle_type, prep_time):
    rate_map = {"BICYCLE": 3.0, "MOTORCYCLE": 1.5, "CAR": 2.0}
    rate = rate_map.get(vehicle_type, 2.0)
    travel = math.ceil(distance_km * rate)
    return travel + prep_time


# ---------- rating average ----------
def recalculate_rating(entity_type, entity_id):
    """Recalculate rating_average and rating_count for a restaurant or rider."""
    scores = []
    for r in db.ratings.values():
        if r["status"] != "PUBLISHED":
            continue
        if entity_type == "restaurant":
            if r["rater_type"] == "CUSTOMER_TO_RESTAURANT" and r["ratee_id"] == entity_id:
                scores.append(r["score"])
        elif entity_type == "rider":
            if r["rater_type"] in ("CUSTOMER_TO_RIDER", "RESTAURANT_TO_RIDER") and r["ratee_id"] == entity_id:
                scores.append(r["score"])

    if entity_type == "restaurant":
        entity = db.restaurants.get(entity_id)
    else:
        entity = db.riders.get(entity_id)

    if not entity:
        return

    if len(scores) == 0:
        entity["rating_average"] = 0.0
        entity["rating_count"] = 0
    else:
        avg = Decimal(sum(scores)) / Decimal(len(scores))
        entity["rating_average"] = float(avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        entity["rating_count"] = len(scores)
    entity["updated_at"] = db.now_iso()
    entity["version"] += 1


# ---------- cancellation rate ----------
def recalculate_cancellation_rate(rider):
    total = rider["total_deliveries_completed"]
    cancellations = rider["cancellation_count"]
    denom = total + cancellations
    if denom == 0:
        rider["cancellation_rate"] = 0.0
    else:
        rate = Decimal(cancellations) / Decimal(denom)
        rider["cancellation_rate"] = float(rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------- penalty helpers ----------
def add_penalty(rider, points, reason, delivery_id=None, complaint_id=None):
    rider["penalty_points"] += points
    rider["updated_at"] = db.now_iso()
    rider["version"] += 1

    log_entry = {
        "id": db.new_id(),
        "rider_id": rider["id"],
        "reason": reason,
        "points": points,
        "delivery_id": delivery_id,
        "complaint_id": complaint_id,
        "created_at": db.now_iso(),
        "cumulative_points": rider["penalty_points"],
    }
    db.rider_penalty_logs[log_entry["id"]] = log_entry

    # auto-suspend if threshold reached
    if rider["penalty_points"] >= 100 and rider["status"] == "ACTIVE":
        _suspend_rider_cascade(rider)


def _suspend_rider_cascade(rider):
    """Suspend rider and cancel all ASSIGNED deliveries."""
    rider["status"] = "SUSPENDED"
    rider["is_online"] = False
    rider["updated_at"] = db.now_iso()
    rider["version"] += 1

    for d in list(db.deliveries.values()):
        if d["rider_id"] == rider["id"] and d["status"] == "ASSIGNED":
            d["status"] = "CANCELLED_BY_RIDER"
            d["updated_at"] = db.now_iso()
            d["version"] += 1
            rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
            rider["cancellation_count"] += 1

            # penalty for each cancelled delivery during suspension
            add_penalty(rider, 15, "CANCELLATION", delivery_id=d["id"])

            # revert order to READY_FOR_PICKUP
            order = db.orders.get(d["order_id"])
            if order and order["status"] in ("CONFIRMED", "PREPARING", "READY_FOR_PICKUP", "PICKED_UP"):
                order["status"] = "READY_FOR_PICKUP"
                order["updated_at"] = db.now_iso()
                order["version"] += 1

    recalculate_cancellation_rate(rider)


# ---------- wallet transaction ----------
def create_wallet_transaction(customer_id, txn_type, amount_cents, reference_id=None):
    customer = db.customers[customer_id]
    customer["wallet_balance_cents"] += amount_cents
    customer["updated_at"] = db.now_iso()
    customer["version"] += 1

    txn = {
        "id": db.new_id(),
        "customer_id": customer_id,
        "type": txn_type,
        "amount_cents": amount_cents,
        "reference_id": reference_id,
        "balance_after_cents": customer["wallet_balance_cents"],
        "created_at": db.now_iso(),
    }
    db.wallet_transactions[txn["id"]] = txn
    return txn
