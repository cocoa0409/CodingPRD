"""Slot conflict checks, backlog projection, waitlist promotion, bath booking,
and zone receiving checks."""

import math
from decimal import Decimal

import db
from errors import (
    ApiError, ERR_SLOT_OVERLAP, ERR_CHANGEOVER_BUFFER_VIOLATION,
    ERR_MAINTENANCE_WINDOW_CONFLICT, ERR_BATH_TIME_CONFLICT,
    ERR_BATH_RINSE_GAP_VIOLATION, ERR_LINE_DAILY_CAPACITY_EXCEEDED,
    ERR_INVALID_REQUEST, ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED,
)
from .constants import (
    CHANGEOVER_HOURS, REPRESS_INFLATION, UNITS_PER_PALLET, ZONE_DAILY_PALLETS,
    TIER_WEIGHT,
)
from .pricing import round_half_up_2dp


def hourly_rate(line):
    return math.ceil(line["daily_unit_capacity"] / line["hours_per_day"])


def validate_production_hours(line, start_hour, end_hour):
    """PRODUCTION: 0 <= start < end <= hours_per_day."""
    if not isinstance(start_hour, int) or not isinstance(end_hour, int):
        raise ApiError(ERR_INVALID_REQUEST, "slot hours must be integers", 400)
    if start_hour < 0 or end_hour <= start_hour or end_hour > line["hours_per_day"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "PRODUCTION slot hours must satisfy 0 <= start < end <= hours_per_day",
            400,
        )


def validate_maintenance_hours(line, start_hour, end_hour):
    """MAINTENANCE: 0 <= start <= end < hours_per_day."""
    if not isinstance(start_hour, int) or not isinstance(end_hour, int):
        raise ApiError(ERR_INVALID_REQUEST, "slot hours must be integers", 400)
    if start_hour < 0 or end_hour < start_hour or end_hour >= line["hours_per_day"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "MAINTENANCE slot hours must satisfy 0 <= start <= end < hours_per_day",
            400,
        )


def check_slot_conflicts(line_id, date, new_slots):
    """Check interval occupation for candidate PRODUCTION slots on one
    line+date against existing unfreed slots AND against each other.

    new_slots: list of dicts with start_hour/end_hour/color_family.
    Existing slots include both PRODUCTION (half-open) and MAINTENANCE
    (closed) kinds.
    """
    existing = [
        s for s in db.press_slots.values()
        if s["press_line_id"] == line_id and s["date"] == date and not s.get("freed", False)
    ]
    pending = list(new_slots)

    def prod_vs_prod(a, b):
        # half-open [start, end)
        overlap = a["start_hour"] < b["end_hour"] and b["start_hour"] < a["end_hour"]
        if overlap:
            raise ApiError(ERR_SLOT_OVERLAP, "PRODUCTION slots overlap", 409)
        if a["color_family"] != b["color_family"]:
            # need CHANGEOVER_HOURS between earlier end and later start
            if a["end_hour"] <= b["start_hour"]:
                if b["start_hour"] < a["end_hour"] + CHANGEOVER_HOURS:
                    raise ApiError(
                        ERR_CHANGEOVER_BUFFER_VIOLATION,
                        "Adjacent slots of different color families require a changeover buffer",
                        409,
                    )
            elif b["end_hour"] <= a["start_hour"]:
                if a["start_hour"] < b["end_hour"] + CHANGEOVER_HOURS:
                    raise ApiError(
                        ERR_CHANGEOVER_BUFFER_VIOLATION,
                        "Adjacent slots of different color families require a changeover buffer",
                        409,
                    )

    def prod_vs_maint(p, m):
        # production half-open, maintenance closed [start, end]
        if p["start_hour"] <= m["end_hour"] and m["start_hour"] < p["end_hour"]:
            raise ApiError(
                ERR_MAINTENANCE_WINDOW_CONFLICT,
                "PRODUCTION slot conflicts with a MAINTENANCE window",
                409,
            )

    def check_against(slot, other):
        if other["slot_kind"] == "MAINTENANCE":
            prod_vs_maint(slot, other)
        else:
            prod_vs_prod(slot, other)

    for cand in pending:
        for ex in existing:
            check_against(cand, ex)
    # pairwise within candidates
    for i in range(len(pending)):
        for j in range(i + 1, len(pending)):
            prod_vs_prod(pending[i], pending[j])


def check_daily_capacity(line, date, additional_by_date):
    """Sum of planned_units per line+date <= daily_unit_capacity.
    additional_by_date: {date: units} being committed on this line."""
    for d, add in additional_by_date.items():
        existing = sum(
            s["planned_units"]
            for s in db.press_slots.values()
            if s["press_line_id"] == line["id"] and s["date"] == d
            and s["slot_kind"] == "PRODUCTION" and not s.get("freed", False)
        )
        if existing + add > line["daily_unit_capacity"]:
            raise ApiError(
                ERR_LINE_DAILY_CAPACITY_EXCEEDED,
                "Sum of planned_units exceeds the line's daily capacity",
                409,
            )


def check_maintenance_conflicts(line, date, start_hour, end_hour):
    """New MAINTENANCE window vs existing unfreed slots on the same
    line+date."""
    for s in db.press_slots.values():
        if s["press_line_id"] != line["id"] or s["date"] != date or s.get("freed", False):
            continue
        if s["slot_kind"] == "PRODUCTION":
            # p.start <= m.end AND m.start < p.end
            if s["start_hour"] <= end_hour and start_hour < s["end_hour"]:
                raise ApiError(
                    ERR_MAINTENANCE_WINDOW_CONFLICT,
                    "MAINTENANCE window conflicts with a PRODUCTION slot",
                    409,
                )
        else:
            # maintenance vs maintenance: closed/closed overlap
            if start_hour <= s["end_hour"] and s["start_hour"] <= end_hour:
                raise ApiError(
                    ERR_MAINTENANCE_WINDOW_CONFLICT,
                    "MAINTENANCE window conflicts with another MAINTENANCE window",
                    409,
                )


def compute_backlog(line):
    """backlog_projection: booked hours, optimistic and conservative days."""
    today = db.today_logical().isoformat()
    slots = [
        s for s in db.press_slots.values()
        if s["press_line_id"] == line["id"]
        and s["slot_kind"] == "PRODUCTION"
        and not s.get("freed", False)
        and s["date"] >= today
    ]
    booked_hours = sum(s["end_hour"] - s["start_hour"] for s in slots)

    # changeover: adjacent different-family pairs on the same date
    by_date = {}
    for s in slots:
        by_date.setdefault(s["date"], []).append(s)
    for d, day_slots in by_date.items():
        day_slots.sort(key=lambda s: s["start_hour"])
        for i in range(len(day_slots) - 1):
            if day_slots[i]["color_family"] != day_slots[i + 1]["color_family"]:
                booked_hours += CHANGEOVER_HOURS

    hpd = line["hours_per_day"]
    optimistic = round_half_up_2dp(Decimal(booked_hours) / Decimal(hpd))

    rate = hourly_rate(line)
    repress_queue_hours = 0
    line_order_ids = {s["press_order_id"] for s in slots if s.get("press_order_id")}
    # orders of this line currently QUEUED with repress_round >= 1: orders
    # that were repressed and sit back in the queue waiting to be rescheduled.
    # They have no slots yet (freed/none), so find them via the order's
    # most-recent line association. The scaffold pins: orders of this line
    # currently in QUEUED with repress_round >= 1. An order in QUEUED has no
    # active slots; association to a line comes from prior (freed or consumed)
    # slots. We attribute an order to a line if its most recent slot was on
    # this line.
    for order in db.press_orders.values():
        if order["production_status"] != "QUEUED" or order.get("repress_round", 0) < 1:
            continue
        order_slots = [
            s for s in db.press_slots.values()
            if s.get("press_order_id") == order["id"] and s["slot_kind"] == "PRODUCTION"
        ]
        if order_slots:
            last = max(order_slots, key=lambda s: (s["date"], s["start_hour"]))
            if last["press_line_id"] != line["id"]:
                continue
        else:
            continue
        repress_queue_hours += math.ceil(order["quantity_ordered"] / rate)

    conservative = round_half_up_2dp(
        (Decimal(booked_hours) * (Decimal("1") + REPRESS_INFLATION)
         + Decimal(repress_queue_hours)) / Decimal(hpd)
    )

    return {
        "press_line_id": line["id"],
        "booked_hours": booked_hours,
        "optimistic_backlog_days": float(optimistic),
        "conservative_backlog_days": float(conservative),
    }


def check_bath_booking(bath, start_hour, end_hour, exclude_job_id=None):
    """bath_booking_check against jobs currently in PLATING on this bath."""
    for job in db.tooling_jobs.values():
        if job.get("plating_bath_id") != bath["id"]:
            continue
        if job["status"] != "PLATING":
            continue
        if exclude_job_id and job["id"] == exclude_job_id:
            continue
        e_start, e_end = job["plating_start"], job["plating_end"]
        # closed-interval overlap
        if start_hour <= e_end and e_start <= end_hour:
            raise ApiError(
                ERR_BATH_TIME_CONFLICT,
                "Bath booking overlaps another booking on the same bath",
                409,
            )
        # rinse gap (in hour units in this model)
        gap = bath["rinse_gap_minutes"]
        if not (start_hour >= e_end + gap or e_start >= end_hour + gap):
            raise ApiError(
                ERR_BATH_RINSE_GAP_VIOLATION,
                "Bath bookings lack the mandatory rinse gap between them",
                409,
            )


def waitlist_promotion(freed_slots, cancelled_order_id):
    """waitlist_promotion waterfall over freed PRODUCTION windows."""
    from . import risk as risk_service

    # remaining windows: mutable list of dicts (line, date, start, end)
    windows = []
    for s in freed_slots:
        windows.append({
            "press_line_id": s["press_line_id"],
            "date": s["date"],
            "start_hour": s["start_hour"],
            "end_hour": s["end_hour"],
        })

    candidates = [
        o for o in db.press_orders.values()
        if o["production_status"] == "QUEUED" and o["id"] != cancelled_order_id
    ]

    def rank_key(o):
        customer = db.customers.get(
            db.releases[o["release_id"]]["customer_id"]
        )
        weight = TIER_WEIGHT.get(customer["discount_tier"], 10) if customer else 10
        # tier weight DESC, created_at ASC, intake_seq ASC
        return (-weight, o["created_at"], o["intake_seq"])

    candidates.sort(key=rank_key)

    promoted = []
    for cand in candidates:
        fitted = False
        for w in windows:
            line = db.press_lines[w["press_line_id"]]
            rate = hourly_rate(line)
            required = math.ceil(
                (cand["quantity_ordered"] - cand["accepted_units"]) / rate
            )
            if required <= 0:
                required = 1
            window_hours = w["end_hour"] - w["start_hour"]
            if required <= window_hours:
                # promote: new slot covers exactly `required` hours from start
                slot = {
                    "id": db.new_id(),
                    "created_at": db.timestamp_now(),
                    "updated_at": db.timestamp_now(),
                    "version": 1,
                    "press_line_id": w["press_line_id"],
                    "press_order_id": cand["id"],
                    "slot_kind": "PRODUCTION",
                    "date": w["date"],
                    "start_hour": w["start_hour"],
                    "end_hour": w["start_hour"] + required,
                    "planned_units": cand["quantity_ordered"] - cand["accepted_units"],
                    "color_family": cand["color_family"],
                    "freed": False,
                }
                db.press_slots[slot["id"]] = slot
                # shrink the freed remainder
                w["start_hour"] = w["start_hour"] + required
                cand["production_status"] = "SCHEDULED"
                cand["updated_at"] = db.timestamp_now()
                cand["version"] += 1
                release = db.releases[cand["release_id"]]
                risk_service.recompute_release_risk(release, "SCHEDULE", cand["id"])
                promoted.append(cand["id"])
                fitted = True
                break
        # continue scanning regardless of fit
    return promoted


def zone_receiving_check(release, zone, quantity, event_date):
    """zone_receiving_check: daily pallet budget per zone."""
    upp = UNITS_PER_PALLET[release["format"]]
    pallets = math.ceil(quantity / upp)
    used = 0
    for other in db.inventory_lots.values():
        if other["zone"] != zone:
            continue
        for ev_date, ev_pallets in other.get("_receive_events", []):
            if ev_date == event_date:
                used += ev_pallets
    if used + pallets > ZONE_DAILY_PALLETS[zone]:
        raise ApiError(
            ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED,
            "Zone daily receiving pallet capacity exceeded",
            409,
        )
    return pallets
