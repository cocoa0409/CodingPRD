"""Fare quoting, settlement, the append-only ledger and fare capping."""
import calculations as calc
import clock
import db


def connection_of(trip):
    if trip.get("connection_id"):
        return db.transit_connections.get(trip["connection_id"])
    return None


def effective_counters(rider):
    """The rider's cap counters period-scoped to the logical clock (PRD 3.7)."""
    today = clock.date_of(clock.now())
    week_start = clock.week_start_of(clock.now())
    daily = rider["daily_fare_paid_cents"] if rider["fare_counter_date"] == today else 0
    weekly = (rider["weekly_fare_paid_cents"]
              if rider["fare_counter_week_start"] == week_start else 0)
    return daily, weekly


def recompute_rider_counters(rider):
    rows = [r for r in db.fare_transactions.values() if r["rider_id"] == rider["id"]]
    service_date = rider["fare_counter_date"]
    week_start = rider["fare_counter_week_start"]
    daily = 0
    weekly = 0
    for row in rows:
        if service_date is not None and row["service_date"] == service_date:
            daily += row["amount_cents"]
        if week_start is not None and \
                clock.week_start_of_date_string(row["service_date"]) == week_start:
            weekly += row["amount_cents"]
    changed = (rider["daily_fare_paid_cents"] != daily
               or rider["weekly_fare_paid_cents"] != weekly)
    rider["daily_fare_paid_cents"] = daily
    rider["weekly_fare_paid_cents"] = weekly
    if changed:
        db.touch(rider)


def _append_row(trip, rider, kind, amount_cents, applied_cap):
    row = db.base_record(versioned=False)
    row.update({
        "trip_request_id": trip["id"],
        "rider_id": rider["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "service_date": clock.date_of(clock.now()),
        "applied_cap": applied_cap,
    })
    return db.fare_transactions.add(row)


# --------------------------------------------------------------------------
# PROVISIONAL_QUOTE
# --------------------------------------------------------------------------

def quote(trip, zone, rider, baseline_minutes):
    """Runs at offer creation; returns the cents written to quoted_fare_cents."""
    daily, weekly = effective_counters(rider)
    result = calc.trip_fare(
        zone, rider, connection_of(trip),
        baseline_minutes,
        clock.parse_dt(trip["requested_pickup_utc"]),
        daily, weekly,
    )
    return result["charge_cents"]


# --------------------------------------------------------------------------
# SETTLED_CHARGE
# --------------------------------------------------------------------------

def settle(trip, zone, rider):
    """Runs at drop-off; writes the ledger and moves the rider's counters."""
    daily, weekly = effective_counters(rider)
    result = calc.trip_fare(
        zone, rider, connection_of(trip),
        trip["ride_minutes"],
        clock.parse_dt(trip["actual_pickup_utc"]),
        daily, weekly,
    )

    trip["charged_fare_cents"] = result["charge_cents"]
    trip["applied_cap"] = result["applied_cap"]
    trip["fare_status"] = "CHARGED"

    # the stored counters are re-anchored to the clock's period before the new
    # ledger rows are appended
    rider["fare_counter_date"] = clock.date_of(clock.now())
    rider["fare_counter_week_start"] = clock.week_start_of(clock.now())

    applied_cap = result["applied_cap"]
    _append_row(trip, rider, "CHARGE", result["category_cents"], applied_cap)
    if result["transfer_credit_cents"] > 0:
        _append_row(trip, rider, "TRANSFER_CREDIT",
                    -result["transfer_credit_cents"], applied_cap)
    if result["cap_rebate_cents"] > 0:
        _append_row(trip, rider, "CAP_REBATE",
                    -result["cap_rebate_cents"], applied_cap)

    recompute_rider_counters(rider)
    _propagate_daily_cap(trip, zone, rider)
    return result


def _propagate_daily_cap(settling_trip, zone, rider):
    """Third hop of completion: the rider's other quotes visibly become free."""
    if rider["daily_fare_paid_cents"] < zone["fare_cap_cents_daily"]:
        return
    others = [t for t in db.trip_requests.values()
              if t["rider_id"] == rider["id"]
              and t["id"] != settling_trip["id"]
              and t["fare_status"] == "QUOTED"]
    for trip in db.by_created_at(others):
        trip["quoted_fare_cents"] = 0
        trip["fare_status"] = "CAPPED"
        db.touch(trip)


# --------------------------------------------------------------------------
# refund
# --------------------------------------------------------------------------

def refund(trip, rider):
    net_settled = trip["charged_fare_cents"] or 0
    _append_row(trip, rider, "REFUND", -net_settled, trip["applied_cap"])
    trip["charged_fare_cents"] = 0
    trip["fare_status"] = "REFUNDED"
    recompute_rider_counters(rider)


# --------------------------------------------------------------------------
# voiding a quote when the offer behind it goes away
# --------------------------------------------------------------------------

def void_quote(trip):
    if trip["fare_status"] in ("QUOTED", "CAPPED"):
        trip["fare_status"] = "UNPRICED"
        trip["quoted_fare_cents"] = None
