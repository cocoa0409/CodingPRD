"""Cascade side effects shared across routes. Every cascade-touched entity is
touched() so its version advances exactly once per request and updated_at refreshes."""
from db import store, touch
from services.calculations import (
    MINOR_INCIDENT_DAILY_THRESHOLD,
    FAIR_WIND_CLOSURE_MPH,
)


def void_queued_redemptions(ride_id, day_id):
    """QUEUED redemptions for (ride, day) -> VOIDED (no credit movement; QUEUED holds no credit)."""
    for red in store["redemptions"].values():
        if (
            red["ride_id"] == ride_id
            and red["operating_day_id"] == day_id
            and red["status"] == "QUEUED"
        ):
            red["status"] = "VOIDED"
            touch(red)


def suspend_license_cascade(ride, day_id):
    """license LICENSED -> SUSPENDED; daily OPEN|WEATHER_HOLD -> CLOSED; queue voided.
    Used by the cycle-threshold cascade."""
    if ride["license_status"] != "LICENSED":
        return
    ride["license_status"] = "SUSPENDED"
    if ride["daily_status"] in ("OPEN", "WEATHER_HOLD"):
        ride["daily_status"] = "CLOSED"
    void_queued_redemptions(ride["id"], day_id)
    touch(ride)


def revoke_license_cascade(ride, day_id, from_statuses):
    """license -> REVOKED when currently in from_statuses; daily -> CLOSED from
    OPEN/WEATHER_HOLD/INCIDENT_HOLD; today's QUEUED redemptions -> VOIDED."""
    if ride["license_status"] in from_statuses:
        ride["license_status"] = "REVOKED"
    if ride["daily_status"] in ("OPEN", "WEATHER_HOLD", "INCIDENT_HOLD"):
        ride["daily_status"] = "CLOSED"
    void_queued_redemptions(ride["id"], day_id)
    touch(ride)


def serious_incident_cascade(ride):
    """SERIOUS filing: license LICENSED -> SUSPENDED; daily OPEN|WEATHER_HOLD -> INCIDENT_HOLD.
    Queued redemptions preserved."""
    if ride["license_status"] == "LICENSED":
        ride["license_status"] = "SUSPENDED"
    if ride["daily_status"] in ("OPEN", "WEATHER_HOLD"):
        ride["daily_status"] = "INCIDENT_HOLD"
    touch(ride)


def minor_incident_cascade(ride):
    """MINOR filing: counter += 1; at the inclusive threshold an OPEN/WEATHER_HOLD
    ride moves to INCIDENT_HOLD (license untouched)."""
    ride["minor_incidents_today"] += 1
    if (
        ride["minor_incidents_today"] >= MINOR_INCIDENT_DAILY_THRESHOLD
        and ride["daily_status"] in ("OPEN", "WEATHER_HOLD")
    ):
        ride["daily_status"] = "INCIDENT_HOLD"
    touch(ride)


def wind_sweep(day, wind_speed_mph):
    """Ride hold rule + fair closure rule for a new weather observation."""
    fair_id = day["fair_id"]
    fair_rides = [r for r in store["rides"].values() if r["fair_id"] == fair_id]
    if wind_speed_mph >= FAIR_WIND_CLOSURE_MPH and day["posture"] == "OPEN":
        day["posture"] = "WEATHER_HOLD"
        touch(day)
        for ride in fair_rides:
            if ride["daily_status"] == "OPEN":
                ride["daily_status"] = "WEATHER_HOLD"
                touch(ride)
        return
    for ride in fair_rides:
        if ride["daily_status"] == "OPEN" and wind_speed_mph >= ride["wind_limit_mph"]:
            ride["daily_status"] = "WEATHER_HOLD"
            touch(ride)


def close_gates_cascade(day):
    """Nightly cascade: rides -> CLOSED, QUEUED -> EXPIRED, ACTIVE credit sales forfeit."""
    fair_id = day["fair_id"]
    for ride in store["rides"].values():
        if ride["fair_id"] == fair_id and ride["daily_status"] in (
            "OPEN",
            "WEATHER_HOLD",
            "INCIDENT_HOLD",
        ):
            ride["daily_status"] = "CLOSED"
            touch(ride)
    for red in store["redemptions"].values():
        if red["operating_day_id"] == day["id"] and red["status"] == "QUEUED":
            red["status"] = "EXPIRED"
            touch(red)
    for sale in store["sales"].values():
        if (
            sale["operating_day_id"] == day["id"]
            and sale["status"] == "ACTIVE"
            and not sale["is_unlimited"]
        ):
            sale["credits_forfeited"] += sale["credits_remaining"]
            sale["credits_remaining"] = 0
            sale["status"] = "EXPIRED"
            touch(sale)


def refund_boarded_credit(sale):
    """Compensating refund for one boarded guest on a credit-bearing instrument."""
    if sale is not None and not sale["is_unlimited"]:
        sale["credits_redeemed"] -= 1
        sale["credits_remaining"] += 1
        touch(sale)


def staff_release_cascade(staff):
    """Cancel the worker's future-dated SCHEDULED/CONFIRMED shifts; past-dated untouched."""
    today = db_today()
    for shift in store["shifts"].values():
        if (
            shift["staff_id"] == staff["id"]
            and shift["status"] in ("SCHEDULED", "CONFIRMED")
            and shift["work_date"] >= today
        ):
            shift["status"] = "CANCELLED"
            touch(shift)


def db_today():
    import db

    return db.today_str()


def license_verified_rides(fair_id):
    """Permit approval cascade: every SETUP_VERIFIED ride's license PENDING -> LICENSED."""
    for ride in store["rides"].values():
        if (
            ride["fair_id"] == fair_id
            and ride["setup_status"] == "SETUP_VERIFIED"
            and ride["license_status"] == "PENDING"
        ):
            ride["license_status"] = "LICENSED"
            touch(ride)
