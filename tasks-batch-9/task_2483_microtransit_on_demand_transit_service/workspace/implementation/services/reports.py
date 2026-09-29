"""Subsidy-per-trip aggregation (PRD Section 3.9)."""
import calculations as calc
import clock
import db

PROVISIONAL_BLOCK_STATES = ("SCHEDULED", "OPEN", "CLOSED")
PROVISIONAL_TRIP_STATUSES = ("ASSIGNED", "PICKED_UP", "COMPLETED")
FINAL_BLOCK_STATES = ("CLOSED",)
FINAL_TRIP_STATUSES = ("COMPLETED",)


def _in_period(date_string, start_date, end_date):
    return start_date <= date_string <= end_date


def block_scope(report):
    if report["variant"] == "PROVISIONAL":
        states = PROVISIONAL_BLOCK_STATES
        hours_field = "scheduled_revenue_hours"
    else:
        states = FINAL_BLOCK_STATES
        hours_field = "actual_revenue_hours"
    scope = []
    for block in db.vehicle_blocks.values():
        if block["zone_id"] != report["zone_id"]:
            continue
        if block["state"] not in states:
            continue
        start_date = clock.date_string_of_raw(block["start_utc"])
        if not _in_period(start_date, report["period_start_date"],
                          report["period_end_date"]):
            continue
        scope.append(block)
    scope.sort(key=lambda b: (clock.parse_dt(b["start_utc"]), b["created_at"],
                              b["_seq"]))
    return scope, hours_field


def trip_scope(report):
    statuses = (PROVISIONAL_TRIP_STATUSES if report["variant"] == "PROVISIONAL"
                else FINAL_TRIP_STATUSES)
    scope = []
    for trip in db.trip_requests.values():
        if trip["zone_id"] != report["zone_id"]:
            continue
        if trip["status"] not in statuses:
            continue
        if not _in_period(trip["created_at"][:10], report["period_start_date"],
                          report["period_end_date"]):
            continue
        scope.append(trip)
    return db.by_created_at(scope)


def recompute_totals(report):
    scope, hours_field = block_scope(report)
    # the per-block cost is rounded FIRST, then the rounded figures are summed
    total_operating_cost_cents = sum(
        calc.block_operating_cost_cents(block[hours_field]) for block in scope)

    trips = trip_scope(report)
    trip_ids = {trip["id"] for trip in trips}
    total_fare_revenue_cents = sum(
        row["amount_cents"] for row in db.fare_transactions.values()
        if row["trip_request_id"] in trip_ids)
    total_trips = len(trips)

    report["total_operating_cost_cents"] = total_operating_cost_cents
    report["total_fare_revenue_cents"] = total_fare_revenue_cents
    report["total_trips"] = total_trips
    report["subsidy_per_trip_cents"] = calc.subsidy_per_trip_cents(
        total_operating_cost_cents, total_fare_revenue_cents, total_trips)


def period_overlaps(zone_id, variant, start_date, end_date, exclude_id=None):
    live = ("DRAFT", "SUBMITTED", "CERTIFIED", "AMENDED")
    for report in db.subsidy_reports.values():
        if report["id"] == exclude_id:
            continue
        if report["zone_id"] != zone_id or report["variant"] != variant:
            continue
        if report["state"] not in live:
            continue
        if report["period_start_date"] <= end_date and \
                start_date <= report["period_end_date"]:
            return True
    return False


def blocks_not_finalized(report):
    for block in db.vehicle_blocks.values():
        if block["zone_id"] != report["zone_id"]:
            continue
        start_date = clock.date_string_of_raw(block["start_utc"])
        if not _in_period(start_date, report["period_start_date"],
                          report["period_end_date"]):
            continue
        if block["state"] not in ("CLOSED", "CANCELLED"):
            return True
    return False
