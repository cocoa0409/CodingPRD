"""Logical clock + daily ops sweep (PRD §2.4, §2.11)."""
from datetime import timedelta, date

from flask import Blueprint

from db import store, fmt_dt, clock_date, now_dt, touch
from errors import ApiError
from helpers import body, req_dt
from middleware import caller
from response import success
import services

bp = Blueprint("ops", __name__)


@bp.post("/dealership/_clock/set_current_utc")
def set_clock():
    caller(["DealershipAdmin"])
    data = body()
    target = req_dt(data, "to_iso8601")
    if target <= store.clock:
        raise ApiError("ERR_CLOCK_REGRESSION", 409,
                       "to_iso8601 must be strictly after the current clock")
    store.clock = target
    return success({"current_utc": fmt_dt(store.clock)})


@bp.post("/dealership/ops/run-daily-sweep")
def run_daily_sweep():
    caller(["DealershipAdmin"])
    now = now_dt()
    cdate = clock_date()

    interest_entries_posted = 0
    units_rebucketed = 0
    orders_expired = 0
    orders_started = 0
    orders_shipped = 0
    appraisals_expired = 0
    bookings_no_show = 0
    slot_pools_closed = 0

    # 1. Floor-plan interest accrual — units in stocking_date ASC, created_at ASC.
    units = sorted(
        store.units.values(),
        key=lambda u: (u["stocking_date"], u["_seq"]),
    )
    for u in units:
        if not u["floorplan_active"]:
            continue
        if u["status"] not in ("IN_STOCK", "RECONDITIONING", "READY"):
            continue
        if u["floorplan_balance_cents"] <= 0 or not u["last_accrual_date"]:
            continue
        days = (cdate - date.fromisoformat(u["last_accrual_date"])).days
        if days <= 0:
            continue
        interest = services.interest_amount(u["floorplan_balance_cents"],
                                            u["apr_bp"], days)
        services.post_fp_entry(u, "INTEREST_ACCRUAL", interest)
        u["last_accrual_date"] = cdate.isoformat()
        touch(u)
        interest_entries_posted += 1

    # 2. Aging buckets / curtailments recomputed; tally units whose bucket moved.
    for u in units:
        bucket = services.aging_bucket(services.days_in_stock(u))
        if u.get("_sweep_bucket") != bucket:
            u["_sweep_bucket"] = bucket
            units_rebucketed += 1

    # 3. Expire factory-order holds whose 14-day windows have lapsed.
    orders = sorted(store.factory_orders.values(), key=lambda o: o["_seq"])
    for o in orders:
        if o["status"] == "SLOT_HELD" and o["_hold_expires_dt"] <= now:
            o["status"] = "EXPIRED"
            slot = store.factory_build_slots.get(o["factory_build_slot_id"])
            if slot is not None:
                slot["held_count"] -= 1
                services.reeval_slot_posture(slot)
            touch(o)
            orders_expired += 1

    # 4. Build-cycle promotion — at most one promotion per order per run.
    for o in orders:
        slot = store.factory_build_slots.get(o["factory_build_slot_id"])
        if slot is None:
            continue
        first, _ = services.slot_month_bounds(slot)
        ship_day = first + timedelta(days=14)
        if o["status"] == "COMMITTED" and cdate >= first:
            o["status"] = "IN_PRODUCTION"
            touch(o)
            orders_started += 1
        elif o["status"] == "IN_PRODUCTION" and cdate >= ship_day:
            o["status"] = "SHIPPED"
            touch(o)
            orders_shipped += 1

    # 5. Expire appraisal offers past their 10-day windows.
    for a in sorted(store.trade_appraisals.values(), key=lambda x: x["_seq"]):
        if a["status"] == "OFFERED" and a["_offer_expires_dt"] <= now:
            a["status"] = "EXPIRED"
            touch(a)
            appraisals_expired += 1

    # 6. Booking no-shows (start passed by more than 60 minutes, never checked in).
    for b in sorted(store.service_bookings.values(), key=lambda x: x["_seq"]):
        if b["status"] == "BOOKED" and now > b["_start_dt"] + timedelta(
                minutes=services.NO_SHOW_GRACE_MINUTES):
            b["status"] = "NO_SHOW"
            touch(b)
            ro = store.repair_orders.get(b["repair_order_id"])
            if ro is not None:
                services.booking_demotion_check(ro)
            bookings_no_show += 1

    # 7. Close slot pools whose build month has passed; expire remaining holds.
    for s in sorted(store.factory_build_slots.values(), key=lambda x: x["_seq"]):
        if s["status"] == "CLOSED" or not services.month_is_closed(s):
            continue
        s["status"] = "CLOSED"
        touch(s)
        slot_pools_closed += 1
        for o in orders:
            if o["status"] == "SLOT_HELD" and o["factory_build_slot_id"] == s["id"]:
                o["status"] = "EXPIRED"
                s["held_count"] -= 1
                touch(o)
                orders_expired += 1

    # 8. SLA watch: IN_PROGRESS past promised_ready_at + 120-minute grace.
    for r in store.repair_orders.values():
        if (r["work_status"] == "IN_PROGRESS" and not r["sla_breached"]
                and now > r["_promised_dt"] + timedelta(
                    minutes=services.GRACE_MINUTES)):
            r["sla_breached"] = True
            touch(r)

    return success({
        "interest_entries_posted": interest_entries_posted,
        "units_rebucketed": units_rebucketed,
        "orders_expired": orders_expired,
        "orders_started": orders_started,
        "orders_shipped": orders_shipped,
        "appraisals_expired": appraisals_expired,
        "bookings_no_show": bookings_no_show,
        "slot_pools_closed": slot_pools_closed,
    })
