"""Safety score calculations."""

from decimal import Decimal

import db
from services.pricing import round_half_up_1dp


def compute_incident_impact(incident_type: str, severity: str) -> float:
    if severity == "MINOR":
        d = 2.0
    elif severity == "MODERATE":
        d = 5.0
    elif severity == "MAJOR":
        d = 12.0
    elif severity == "CRITICAL":
        d = 25.0
    else:
        d = 0.0

    if incident_type == "ACCIDENT":
        d = d * 1.5
    elif incident_type == "HOS_VIOLATION":
        d = d * 1.2
    return round_half_up_1dp(d)


def recalc_driver_safety_score(driver_id: str):
    driver = db.drivers.get(driver_id)
    if driver is None:
        return
    base = 100.0
    # Incidents on completed orders
    for incident in db.incidents.values():
        if incident.get("driver_id") != driver_id:
            continue
        order = db.orders.get(incident.get("order_id"))
        if order is None or order.get("status") != "COMPLETED":
            continue
        base -= compute_incident_impact(incident.get("incident_type"), incident.get("severity"))
    score = max(0.0, base)
    driver["safety_score"] = round_half_up_1dp(score)


def recalc_customer_safety_audit_score(customer_id: str):
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    completed_orders = [o for o in db.orders.values() if o.get("customer_id") == customer_id and o.get("status") == "COMPLETED"]
    if not completed_orders:
        customer["safety_audit_score"] = 100.0
        return

    total_weight = 0.0
    weighted_sum = 0.0
    now = db.now_utc()

    for order in completed_orders:
        order_score = 100.0
        for incident in db.incidents.values():
            if incident.get("order_id") != order["id"]:
                continue
            sev = incident.get("severity")
            if sev == "CRITICAL":
                order_score -= 30.0
            elif sev == "MAJOR":
                order_score -= 15.0
            elif sev == "MODERATE":
                order_score -= 7.0
            elif sev == "MINOR":
                order_score -= 3.0
        for bd in db.breakdowns.values():
            if bd.get("order_id") != order["id"]:
                continue
            if bd.get("status") not in ("REPLACED", "RESOLVED_IN_PLACE"):
                continue
            dm = bd.get("delay_minutes", 0) or 0
            if dm >= 240:
                order_score -= 10.0
            elif dm >= 60:
                order_score -= 5.0

        completed_at = order.get("completed_at")
        if completed_at:
            days_ago = (now - completed_at).total_seconds() / 86400.0
        else:
            days_ago = 0.0
        weight = max(0.1, 1.0 - (days_ago / 365.0))
        weighted_sum += order_score * weight
        total_weight += weight

    if total_weight > 0:
        customer["safety_audit_score"] = round_half_up_1dp(weighted_sum / total_weight)
    else:
        customer["safety_audit_score"] = 100.0
