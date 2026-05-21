"""Rolling 30-day redelivery aggregation per PRD §3.5/§3.7."""
from datetime import timedelta

from .. import store
from ..clock import clock, parse_iso8601


def recompute_customer_rolling(customer: dict):
    """Recompute redelivery_attempts_used_30d on the supplied customer record."""
    now = clock.now()
    lower = now - timedelta(days=30)
    customer_id = customer["id"]
    count = 0
    for parcel in store.parcels.values():
        if parcel.get("customer_id") != customer_id:
            continue
        parcel_id = parcel["id"]
        for attempt in store.delivery_attempts.values():
            if attempt.get("parcel_id") != parcel_id:
                continue
            outcome = attempt.get("outcome")
            if outcome not in ("NO_ONE_HOME", "REFUSED"):
                continue
            attempted_at_str = attempt.get("attempted_at")
            if not attempted_at_str:
                continue
            try:
                at = parse_iso8601(attempted_at_str)
            except Exception:
                continue
            if at >= lower and at <= now:
                count += 1
    customer["redelivery_attempts_used_30d"] = count
    return count
