"""Capacity bookkeeping: bay minutes, mobile buffered overlap, calibration rig."""

from datetime import timedelta
from decimal import Decimal

from db import store, parse_dt
from errors import ApiError, ERR_BAY_CAPACITY_EXCEEDED, ERR_MOBILE_BUFFER_VIOLATION, ERR_CALIBRATION_SLOT_CONFLICT

MOBILE_BUFFER_MINUTES = 45


def wo_interval_seconds(work_order):
    start = parse_dt(work_order["scheduled_start"])
    end = parse_dt(work_order["scheduled_end"])
    return (end - start).total_seconds()


def bay_seconds_booked(shop_id, date_str, exclude_id=None):
    """Seconds booked on the shop's SCHEDULED IN_SHOP work orders whose
    scheduled_start calendar date (UTC) equals date_str."""
    total = 0.0
    for wo in store.work_orders.values():
        if wo["id"] == exclude_id:
            continue
        if wo["shop_id"] != shop_id:
            continue
        if wo["status"] != "SCHEDULED" or wo.get("service_mode") != "IN_SHOP":
            continue
        start = parse_dt(wo["scheduled_start"])
        if start.date().isoformat() != date_str:
            continue
        total += wo_interval_seconds(wo)
    return total


def bay_minutes_booked(shop_id, date_str):
    seconds = bay_seconds_booked(shop_id, date_str)
    minutes = Decimal(str(seconds)) / Decimal(60)
    return int(minutes) if minutes == int(minutes) else float(minutes)


def check_bay_capacity(shop, work_order, new_start, new_end):
    """IN_SHOP temporal rule: booked minutes on the calendar date of the new
    scheduled_start plus the new duration must not exceed bay_count *
    operating_minutes_per_day. The rescheduled work order's own prior booking
    is excluded (its capacity is released first)."""
    date_str = new_start.date().isoformat()
    booked = bay_seconds_booked(shop["id"], date_str, exclude_id=work_order["id"])
    new_seconds = (new_end - new_start).total_seconds()
    budget = shop["bay_count"] * shop["operating_minutes_per_day"] * 60
    if booked + new_seconds > budget:
        raise ApiError(ERR_BAY_CAPACITY_EXCEEDED, 409, "In-shop daily bay-minutes budget would be exceeded")


def _buffered(start, end):
    return start, end + timedelta(minutes=MOBILE_BUFFER_MINUTES)


def _overlaps(a_start, a_end, b_start, b_end):
    """Strict half-open interval overlap: touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


def check_mobile_buffer(shop, work_order, new_start, new_end):
    """MOBILE temporal rule: the new buffered interval [start, end+45min) must
    overlap fewer of the shop's other SCHEDULED MOBILE buffered intervals than
    mobile_unit_count."""
    n_start, n_end = _buffered(new_start, new_end)
    count = 0
    for wo in store.work_orders.values():
        if wo["id"] == work_order["id"]:
            continue
        if wo["shop_id"] != shop["id"]:
            continue
        if wo["status"] != "SCHEDULED" or wo.get("service_mode") != "MOBILE":
            continue
        o_start, o_end = _buffered(parse_dt(wo["scheduled_start"]), parse_dt(wo["scheduled_end"]))
        if _overlaps(n_start, n_end, o_start, o_end):
            count += 1
    if count >= shop["mobile_unit_count"]:
        raise ApiError(ERR_MOBILE_BUFFER_VIOLATION, 409, "Mobile buffered-interval overlap limit reached")


def check_calibration_slot(shop_id, new_start, new_end):
    """The shop runs a single calibration rig: strict half-open overlap with
    any other SCHEDULED calibration event of the same shop is rejected."""
    for ev in store.calibrations.values():
        if ev["status"] != "SCHEDULED":
            continue
        wo = store.work_orders.get(ev["work_order_id"])
        if wo is None or wo["shop_id"] != shop_id:
            continue
        o_start = parse_dt(ev["scheduled_start"])
        o_end = parse_dt(ev["scheduled_end"])
        if _overlaps(new_start, new_end, o_start, o_end):
            raise ApiError(
                ERR_CALIBRATION_SLOT_CONFLICT,
                409,
                "Calibration rig window overlaps another SCHEDULED calibration event",
            )
