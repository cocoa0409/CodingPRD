from store import store
from services.computations import recompute_bonus_tier


def recompute_acceptance_rate(rider):
    rider_id = rider["id"]
    relevant = []
    for a in store.assignments.values():
        if a["rider_id"] == rider_id and a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED", "REJECTED"):
            relevant.append(a)
    relevant.sort(key=lambda a: a["created_at"], reverse=True)
    last_30 = relevant[:30]
    if len(last_30) == 0:
        rider["acceptance_rate"] = 1.0
        return
    accepted_count = sum(1 for a in last_30 if a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED"))
    rider["acceptance_rate"] = round(accepted_count / len(last_30), 10)


def recompute_on_time_rate(rider):
    rider_id = rider["id"]
    delivered = []
    for a in store.assignments.values():
        if a["rider_id"] == rider_id and a["status"] == "DELIVERED":
            delivered.append(a)
    delivered.sort(key=lambda a: a["created_at"], reverse=True)
    last_30 = delivered[:30]
    if len(last_30) < 10:
        rider["on_time_rate"] = 1.0
        return
    on_time_count = 0
    for a in last_30:
        order = store.orders.get(a["order_id"])
        if order and (order.get("minutes_late") or 0) == 0:
            on_time_count += 1
    rider["on_time_rate"] = round(on_time_count / len(last_30), 10)
