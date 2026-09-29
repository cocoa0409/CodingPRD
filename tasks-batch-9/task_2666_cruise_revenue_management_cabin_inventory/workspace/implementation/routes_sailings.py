"""Sailing endpoints: create, read, list, and the five lifecycle transitions."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import ALL_ROLES, actor
from envelope import created, list_response, object_response
from errors import ApiError
from ops import run_sweep

bp = Blueprint("sailings", __name__)


def new_sailing_row():
    row = store.stamp_new({})
    row.update({
        "ship_code": None,
        "voyage_code": None,
        "embark_date": None,
        "nights": 0,
        "total_lower_berths": 0,
        "final_payment_days_before": 75,
        "deposit_due_days_after_booking": 7,
        "status": "PLANNED",
        "suspension_count": 0,
        "suspension_reason": None,
        "inventory_posture": "OPEN",
        "lower_berths_sold": 0,
        "third_berths_sold": 0,
        "fourth_berths_sold": 0,
        "occupancy_pct": 0.0,
        "gross_ticket_revenue_cents": 0,
        "projected_onboard_revenue_cents": 0,
        "compensation_liability_cents": 0,
        "available_lower_berth_days_gross": 0,
        "available_lower_berth_days_net": 0,
        "ralbd_gross_cents": 0,
        "ralbd_net_cents": 0,
        "revenue_alert": False,
        "confirmed_bookings_count": 0,
        "paid_in_full_bookings_count": 0,
        "final_payment_risk_flag": False,
    })
    return row


@bp.post("/sailings")
def create_sailing():
    actor("RevenueManager")
    data = shape.body()

    ship_code = shape.req_str(data, "ship_code", max_len=32)
    voyage_code = shape.req_str(data, "voyage_code", max_len=32)
    embark_date = shape.req_dt(data, "embark_date")
    nights = shape.req_int(data, "nights", minimum=1)
    total_lower_berths = shape.req_int(data, "total_lower_berths", minimum=2)
    final_payment_days_before = shape.opt_int(
        data, "final_payment_days_before", 75, minimum=1)
    deposit_due_days_after_booking = shape.opt_int(
        data, "deposit_due_days_after_booking", 7, minimum=1)

    for other in store.sailings.values():
        if other["voyage_code"] == voyage_code:
            raise ApiError("ERR_DUPLICATE_VOYAGE_CODE")

    row = new_sailing_row()
    row.update({
        "ship_code": ship_code,
        "voyage_code": voyage_code,
        "embark_date": store.iso(embark_date),
        "nights": nights,
        "total_lower_berths": total_lower_berths,
        "final_payment_days_before": final_payment_days_before,
        "deposit_due_days_after_booking": deposit_due_days_after_booking,
    })
    store.sailings[row["id"]] = row
    cascade.recompute_sailing(row, bump=False)
    return created(row)


@bp.get("/sailings/<sailing_id>")
def read_sailing(sailing_id):
    actor(*ALL_ROLES)
    return object_response(cascade.sailing_or_404(sailing_id))


@bp.get("/sailings")
def list_sailings():
    actor("RevenueManager", "ReservationAgent", "GroupSalesAgent", "PortOpsCoordinator")
    limit, offset = shape.pagination()
    ship_code = shape.filter_str("ship_code")
    voyage_code = shape.filter_str("voyage_code")
    status = shape.filter_str("status")
    posture = shape.filter_str("inventory_posture")
    alert = shape.filter_bool("revenue_alert")

    rows = []
    for row in store.sailings.values():
        if ship_code is not None and row["ship_code"] != ship_code:
            continue
        if voyage_code is not None and row["voyage_code"] != voyage_code:
            continue
        if status is not None and row["status"] != status:
            continue
        if posture is not None and row["inventory_posture"] != posture:
            continue
        if alert is not None and row["revenue_alert"] != alert:
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/sailings/<sailing_id>/open-for-sale")
def open_for_sale(sailing_id):
    actor("RevenueManager")
    shape.body()
    sailing = cascade.sailing_or_404(sailing_id)

    # Tier 10: own-state precondition.
    if sailing["status"] != "PLANNED":
        raise ApiError("ERR_SAILING_NOT_PLANNED")
    # Tier 19: the voyage must be sellable in substance.
    has_allotment = bool(cascade.inventories_of(sailing_id))
    has_fare_rule = any(r["sailing_id"] == sailing_id for r in store.fare_rules.values())
    if not has_allotment or not has_fare_rule:
        raise ApiError("ERR_SAILING_NOT_SELLABLE")

    sailing["status"] = "OPEN_FOR_SALE"
    cascade.recompute_sailing(sailing, bump=False)
    store.touch(sailing)
    return object_response(sailing)


@bp.post("/sailings/<sailing_id>/suspend-sales")
def suspend_sales(sailing_id):
    actor("RevenueManager")
    data = shape.body()
    reason = shape.req_str(data, "reason")
    sailing = cascade.sailing_or_404(sailing_id)

    if sailing["status"] != "OPEN_FOR_SALE":
        raise ApiError("ERR_SAILING_NOT_OPEN")
    if sailing["suspension_count"] >= calcs.MAX_SALES_SUSPENSIONS:
        raise ApiError("ERR_SUSPENSION_LIMIT_REACHED")

    sailing["status"] = "SALES_SUSPENDED"
    sailing["suspension_count"] = sailing["suspension_count"] + 1
    sailing["suspension_reason"] = reason
    store.touch(sailing)
    return object_response(sailing)


@bp.post("/sailings/<sailing_id>/resume-sales")
def resume_sales(sailing_id):
    actor("RevenueManager")
    shape.body()
    sailing = cascade.sailing_or_404(sailing_id)

    if sailing["status"] != "SALES_SUSPENDED":
        raise ApiError("ERR_SAILING_NOT_SUSPENDED")

    sailing["status"] = "OPEN_FOR_SALE"
    sailing["suspension_reason"] = None
    store.touch(sailing)
    return object_response(sailing)


@bp.post("/sailings/<sailing_id>/close-inventory")
def close_inventory(sailing_id):
    actor("RevenueManager")
    shape.body()
    sailing = cascade.sailing_or_404(sailing_id)

    if sailing["status"] not in ("OPEN_FOR_SALE", "SALES_SUSPENDED"):
        raise ApiError("ERR_SAILING_NOT_OPEN")

    sailing["status"] = "INVENTORY_CLOSED"
    # Every WAITLISTED booking is cancelled owing nothing; payment_status is untouched.
    for booking in cascade.bookings_of_sailing(sailing_id):
        if booking["booking_status"] == "WAITLISTED":
            cascade.cancel_booking(
                booking, sailing, "INVENTORY_CLOSED",
                provisional_cents=0, final_cents=0, assess_payment=False)
    cascade.recompute_inventories_of(sailing_id, bump=True)
    cascade.recompute_sailing(sailing, bump=False)
    store.touch(sailing)
    return object_response(sailing)


@bp.post("/sailings/<sailing_id>/ops-run")
def ops_run(sailing_id):
    actor("RevenueManager")
    shape.body()
    sailing = cascade.sailing_or_404(sailing_id)
    run_sweep(sailing)
    return object_response(sailing)


@bp.get("/sailings/<sailing_id>/revenue-summary")
def revenue_summary(sailing_id):
    actor("RevenueManager")
    sailing = cascade.sailing_or_404(sailing_id)
    # A computed read-through: it refreshes the derived block but never bumps version.
    cascade.recompute_inventories_of(sailing_id, bump=False)
    cascade.recompute_sailing(sailing, bump=False)
    return object_response(sailing)
