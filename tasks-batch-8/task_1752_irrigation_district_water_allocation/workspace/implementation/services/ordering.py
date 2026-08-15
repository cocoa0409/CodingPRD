"""Turnout-order interval gates: turnaround gap, maintenance conflicts, capacity.

All intervals are half-open [start, end) compared to the second.
"""
import db
from db import store, D
from errors import ApiError

TURNAROUND_MIN_GAP_SECONDS = 6 * 3600  # TURNAROUND_MIN_GAP_HOURS = 6
NON_TERMINAL_ORDER_STATES = ("REQUESTED", "SCHEDULED", "FLOWING")


def intervals_overlap(s1, e1, s2, e2):
    """Half-open overlap: adjacency (e1 == s2 or e2 == s1) is NOT overlap."""
    return s1 < e2 and s2 < e1


def linked_work_order(order):
    for wo in store.rider_work_orders.values():
        if wo["turnout_order_id"] == order["id"]:
            return wo
    return None


def check_turnaround(account_id, start, end, exclude_order_id=None):
    """ERR_ORDER_TURNAROUND_CONFLICT when the candidate window overlaps another
    non-terminal order of the same account, or the gap to an adjacent one is
    strictly under 6 hours (a gap of exactly 6 hours is allowed)."""
    for o in store.turnout_orders.values():
        if o["water_account_id"] != account_id or o["id"] == exclude_order_id:
            continue
        if o["status"] not in NON_TERMINAL_ORDER_STATES:
            continue
        os_, oe = o["_start_dt"], o["_end_dt"]
        if intervals_overlap(start, end, os_, oe):
            raise ApiError("ERR_ORDER_TURNAROUND_CONFLICT", 422,
                           "Order window overlaps another non-terminal order of this account")
        gap_seconds = None
        if oe <= start:
            gap_seconds = (start - oe).total_seconds()
        elif end <= os_:
            gap_seconds = (os_ - end).total_seconds()
        if gap_seconds is not None and gap_seconds < TURNAROUND_MIN_GAP_SECONDS:
            raise ApiError("ERR_ORDER_TURNAROUND_CONFLICT", 422,
                           "Order window sits within the 6-hour turnaround gap of another order")


def check_window_time_conflict(reach_id, start, end):
    """ERR_WINDOW_TIME_CONFLICT when a PLANNED/ACTIVE maintenance window on the
    reach overlaps the order's half-open window."""
    for w in store.maintenance_windows.values():
        if w["canal_reach_id"] != reach_id or w["status"] not in ("PLANNED", "ACTIVE"):
            continue
        if intervals_overlap(start, end, w["_start_dt"], w["_end_dt"]):
            raise ApiError("ERR_WINDOW_TIME_CONFLICT", 422,
                           "Order window overlaps a maintenance window on the reach")


def check_reach_capacity(reach, start, end, this_cfs):
    """ERR_REACH_CAPACITY_EXCEEDED when at any instant of the window the summed
    requested_cfs of the reach's other SCHEDULED/FLOWING orders plus this
    order's requested_cfs would exceed max_capacity_cfs."""
    capacity = D(reach["max_capacity_cfs"])
    mine = D(this_cfs)
    others = [o for o in store.turnout_orders.values()
              if o["canal_reach_id"] == reach["id"]
              and o["status"] in ("SCHEDULED", "FLOWING")
              and intervals_overlap(start, end, o["_start_dt"], o["_end_dt"])]
    if not others:
        if mine > capacity:
            raise ApiError("ERR_REACH_CAPACITY_EXCEEDED", 422,
                           "Requested flow exceeds the reach's maximum capacity")
        return
    points = {start, end}
    for o in others:
        points.add(max(start, o["_start_dt"]))
        points.add(min(end, o["_end_dt"]))
    pts = sorted(points)
    for i in range(len(pts) - 1):
        instant = pts[i]
        total = sum(D(o["requested_cfs"]) for o in others
                    if o["_start_dt"] <= instant < o["_end_dt"])
        if total + mine > capacity:
            raise ApiError("ERR_REACH_CAPACITY_EXCEEDED", 422,
                           "Scheduling would exceed the reach's instantaneous capacity")


def cascade_cancel_order(order):
    """CANCELLED + linked non-terminal work order CANCELLED (caller refreshes
    the allocation ledger)."""
    order["status"] = "CANCELLED"
    db.touch(order)
    wo = linked_work_order(order)
    if wo is not None and wo["status"] in ("ASSIGNED", "IN_PROGRESS"):
        wo["status"] = "CANCELLED"
        db.touch(wo)
