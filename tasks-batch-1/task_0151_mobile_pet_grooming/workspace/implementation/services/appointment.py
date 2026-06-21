"""Appointment lifecycle business logic (PRD §3.3–§3.5)."""
from datetime import timedelta

import db
import models
import clock
from errors import (
    err, ERR_INVALID_STATE, ERR_ROUTE_LOCKED, ERR_VACCINATION_REQUIRED,
    ERR_NO_QUALIFIED_GROOMER, ERR_ZIP_NOT_COVERED, ERR_SLOT_OVERLAP,
    ERR_VAN_STOPS_FULL, ERR_ACCOUNT_SUSPENDED, ERR_ROUTE_CAPACITY_EXCEEDED,
    ERR_STALE_ROUTE_VERSION, ERR_SHOW_CUT_UNSUPPORTED,
)
from services import calc, reconcile

COUNTED_STOP_STATUSES = {"RESERVED", "SERVICED", "NO_SHOW"}


# ---------------------------------------------------------------------------
# Helpers reading related entities
# ---------------------------------------------------------------------------
def _appt_addons(appt):
    return [l for l in db.appointment_add_ons.values()
            if l["appointment_id"] == appt["id"]]


def _addon_duration_list(appt):
    out = []
    for link in _appt_addons(appt):
        ao = db.add_ons.get(link["add_on_id"])
        if ao is not None:
            out.append(ao["duration_minutes"])
    return out


def _addon_snapshot_total(appt, skipped_ids=None):
    skipped = set(skipped_ids or [])
    total = 0
    for link in _appt_addons(appt):
        if link["add_on_id"] in skipped:
            continue
        total += link["price_cents_snapshot"]
    return total


# ---------------------------------------------------------------------------
# Quote (REQUESTED->QUOTED and QUOTED->QUOTED)
# ---------------------------------------------------------------------------
def issue_quote(appt):
    if appt["status"] not in ("REQUESTED", "QUOTED"):
        raise err(ERR_INVALID_STATE, "Quote requires REQUESTED or QUOTED status")
    if appt["status"] == "QUOTED" and appt["route_stop_id"] is not None:
        raise err(ERR_INVALID_STATE, "Already-scheduled appointment cannot be re-quoted")

    pet = db.pets[appt["pet_id"]]
    # vaccination must be VALID at current clock
    if reconcile.recompute_vaccination_status(pet) != "VALID":
        raise err(ERR_VACCINATION_REQUIRED, "Pet has no valid RABIES vaccination")

    breed = db.breeds[pet["breed_id"]]
    tier = db.service_tiers[appt["service_tier_id"]]

    appt["estimated_minutes"] = calc.duration_estimate(
        breed["base_service_minutes"], tier["duration_multiplier"],
        pet["weight_lbs"], pet["coat_condition"], _addon_duration_list(appt),
    )
    discount_pct = None
    if appt.get("recurring_plan_id"):
        plan = db.recurring_plans.get(appt["recurring_plan_id"])
        if plan is not None:
            discount_pct = plan["discount_pct"]
    appt["quoted_price_cents"] = calc.quote_price(
        tier["base_price_cents"], pet["coat_condition"], pet["weight_lbs"],
        _addon_snapshot_total(appt), discount_pct,
    )
    appt["quote_round"] += 1
    appt["status"] = "QUOTED"
    models.touch(appt)
    return appt


# ---------------------------------------------------------------------------
# Schedule (QUOTED->SCHEDULED) — priority-ordered checks (PRD §3.4)
# ---------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap test."""
    return a_start < b_end and b_start < a_end


def _select_groomer(appt, route_day, pet, tier, slot_start, slot_end):
    """Groomer selection per PRD §3.4. Returns selected groomer or None."""
    candidates = []
    for g in db.groomers.values():
        if g["status"] != "AVAILABLE":
            continue
        if pet["muzzle_required"] and not g["handles_aggressive"]:
            continue
        if tier["code"] == "SHOW_CUT" and g["skill_level"] != "SENIOR":
            continue
        # free at requested time: raw [slot_start, slot_end) intervals, no buffer,
        # over the groomer's own non-VOIDED stops (across all route days)
        busy = False
        for other_appt in db.appointments.values():
            if other_appt.get("groomer_id") != g["id"]:
                continue
            stop = db.route_stops.get(other_appt.get("route_stop_id"))
            if stop is None or stop["status"] == "VOIDED":
                continue
            if _intervals_overlap(slot_start, slot_end, stop["slot_start"], stop["slot_end"]):
                busy = True
                break
        if busy:
            continue
        candidates.append(g)

    if not candidates:
        return None

    def reserved_count(g):
        n = 0
        for other_appt in db.appointments.values():
            if other_appt.get("groomer_id") != g["id"]:
                continue
            stop = db.route_stops.get(other_appt.get("route_stop_id"))
            if stop is None:
                continue
            if stop["route_day_id"] == route_day["id"] and stop["status"] == "RESERVED":
                n += 1
        return n

    # rank: SENIOR first, then fewer reserved stops on this day, then created_at ASC
    def rank_key(g):
        skill_rank = 0 if g["skill_level"] == "SENIOR" else 1
        return (skill_rank, reserved_count(g), g["created_at"], g["id"])

    candidates.sort(key=rank_key)
    return candidates[0]


def schedule(appt, route_day_id, slot_start, expected_route_day_version):
    # state
    if appt["status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Schedule requires QUOTED status")
    route_day = db.route_days[route_day_id]  # existence checked by caller

    # route lock
    if route_day["status"] in ("LOCKED", "CLOSED"):
        raise err(ERR_ROUTE_LOCKED, "Route day is not accepting stops")

    pet = db.pets[appt["pet_id"]]
    tier = db.service_tiers[appt["service_tier_id"]]

    # vaccination
    if reconcile.recompute_vaccination_status(pet) != "VALID":
        raise err(ERR_VACCINATION_REQUIRED, "Pet has no valid RABIES vaccination")

    est = appt["estimated_minutes"]
    slot_end = slot_start + timedelta(minutes=est)

    # qualified groomer existence (before zip/overlap per PRD ordering)
    selected = _select_groomer(appt, route_day, pet, tier, slot_start, slot_end)
    if selected is None:
        raise err(ERR_NO_QUALIFIED_GROOMER, "No qualified groomer available")

    # zip coverage
    customer = db.customers[pet["customer_id"]]
    if route_day["coverage_zip"] != customer["service_zip"]:
        raise err(ERR_ZIP_NOT_COVERED, "Route coverage ZIP does not match customer service ZIP")

    # slot fit + overlap (buffered van geometry)
    if not (slot_start >= route_day["window_start"] and slot_end <= route_day["window_end"]):
        raise err(ERR_SLOT_OVERLAP, "Requested slot does not fit within the route window")
    buffer = timedelta(minutes=calc.TRAVEL_BUFFER_MIN)
    for stop in db.route_stops.values():
        if stop["route_day_id"] != route_day["id"]:
            continue
        if stop["status"] not in COUNTED_STOP_STATUSES:
            continue
        b_start = stop["slot_start"] - buffer
        b_end = stop["slot_end"] + buffer
        if _intervals_overlap(slot_start, slot_end, b_start, b_end):
            raise err(ERR_SLOT_OVERLAP, "Requested slot overlaps an existing buffered stop")

    # van stop count
    van = db.vans[route_day["van_id"]]
    stop_count = sum(1 for s in db.route_stops.values()
                     if s["route_day_id"] == route_day["id"])
    if stop_count + 1 > van["max_stops"]:
        raise err(ERR_VAN_STOPS_FULL, "Van max stops reached")

    # account suspension
    reconcile.recompute_customer_strikes(customer)
    if customer["account_status"] != "ACTIVE":
        raise err(ERR_ACCOUNT_SUSPENDED, "Customer account is suspended")

    # route capacity
    window_minutes = int((route_day["window_end"] - route_day["window_start"]).total_seconds() // 60)
    existing_load = route_day["booked_minutes"]
    new_load = est + calc.TRAVEL_BUFFER_MIN
    if existing_load + new_load > window_minutes:
        raise err(ERR_ROUTE_CAPACITY_EXCEEDED, "Route load exceeds window capacity")

    # OCC stale version
    if expected_route_day_version != route_day["version"]:
        raise err(ERR_STALE_ROUTE_VERSION, "Stale route day version")

    # show-cut support
    if tier["code"] == "SHOW_CUT":
        senior_available = any(
            g["status"] == "AVAILABLE" and g["skill_level"] == "SENIOR"
            for g in db.groomers.values()
        )
        if not van["has_show_equipment"] or not senior_available:
            raise err(ERR_SHOW_CUT_UNSUPPORTED, "SHOW_CUT not supported on this van/pool")

    # ---- all checks passed: commit ----
    stop = models.base_versioned()
    stop.update({
        "route_day_id": route_day["id"], "slot_start": slot_start,
        "scheduled_minutes": est, "slot_end": slot_end, "status": "RESERVED",
    })
    db.route_stops[stop["id"]] = stop

    appt["route_stop_id"] = stop["id"]
    appt["groomer_id"] = selected["id"]
    appt["status"] = "SCHEDULED"

    reconcile.recompute_booked_minutes(route_day)
    models.touch(route_day)
    models.touch(appt)
    return appt


# ---------------------------------------------------------------------------
# Complete (SCHEDULED->COMPLETED)
# ---------------------------------------------------------------------------
def complete(appt, skipped_add_on_ids):
    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Complete requires SCHEDULED status")
    pet = db.pets[appt["pet_id"]]
    tier = db.service_tiers[appt["service_tier_id"]]
    discount_pct = None
    if appt.get("recurring_plan_id"):
        plan = db.recurring_plans.get(appt["recurring_plan_id"])
        if plan is not None:
            discount_pct = plan["discount_pct"]
    delivered_total = _addon_snapshot_total(appt, skipped_add_on_ids)
    appt["final_price_cents"] = calc.final_price(
        tier["base_price_cents"], pet["coat_condition"], pet["weight_lbs"],
        delivered_total, discount_pct,
    )
    appt["status"] = "COMPLETED"

    stop = db.route_stops.get(appt["route_stop_id"])
    if stop is not None:
        stop["status"] = "SERVICED"
        models.touch(stop)
        _maybe_close_route_day(stop["route_day_id"])
    models.touch(appt)
    return appt


def _maybe_close_route_day(route_day_id):
    rd = db.route_days.get(route_day_id)
    if rd is None or rd["status"] != "LOCKED":
        return
    stops = [s for s in db.route_stops.values() if s["route_day_id"] == rd["id"]]
    if not stops:
        return
    if all(s["status"] in ("SERVICED", "NO_SHOW", "VOIDED") for s in stops):
        rd["status"] = "CLOSED"
        models.touch(rd)


# ---------------------------------------------------------------------------
# No-show (SCHEDULED->NO_SHOW)
# ---------------------------------------------------------------------------
def no_show(appt):
    if appt["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "No-show requires SCHEDULED status")
    stop = db.route_stops.get(appt["route_stop_id"])
    now = clock.now()
    if stop is None or now < stop["slot_start"]:
        raise err(ERR_INVALID_STATE, "Cannot record no-show before slot_start")

    pet = db.pets[appt["pet_id"]]
    customer = db.customers[pet["customer_id"]]

    # fee uses strike count BEFORE this event is registered; recompute the
    # rolling window now (no NO_SHOW fee for this appointment exists yet).
    strikes_before = reconcile.recompute_customer_strikes(customer)
    amount = calc.no_show_fee(appt["quoted_price_cents"], strikes_before)

    fee = models.base_versioned()
    fee.update({
        "customer_id": customer["id"], "appointment_id": appt["id"],
        "fee_type": "NO_SHOW", "amount_cents": amount, "settlement_status": "PENDING",
    })
    db.fee_charges[fee["id"]] = fee

    appt["status"] = "NO_SHOW"
    stop["status"] = "NO_SHOW"
    models.touch(stop)

    reconcile.recompute_outstanding_fees(customer)
    reconcile.recompute_customer_strikes(customer)
    models.touch(customer)

    rd = db.route_days.get(stop["route_day_id"])
    if rd is not None:
        reconcile.recompute_booked_minutes(rd)
        models.touch(rd)
        _maybe_close_route_day(rd["id"])

    models.touch(appt)
    return appt


# ---------------------------------------------------------------------------
# Cancel (REQUESTED/QUOTED/SCHEDULED -> CANCELLED)
# ---------------------------------------------------------------------------
def cancel(appt):
    status = appt["status"]
    if status not in ("REQUESTED", "QUOTED", "SCHEDULED"):
        raise err(ERR_INVALID_STATE, "Cancel not allowed from %s" % status)

    if status in ("REQUESTED", "QUOTED"):
        appt["status"] = "CANCELLED"
        models.touch(appt)
        return appt

    # SCHEDULED cancel
    stop = db.route_stops.get(appt["route_stop_id"])
    pet = db.pets[appt["pet_id"]]
    customer = db.customers[pet["customer_id"]]
    now = clock.now()

    late = stop is not None and calc.is_late_cancel(stop["slot_start"], now)

    appt["status"] = "CANCELLED"
    if stop is not None:
        stop["status"] = "VOIDED"
        models.touch(stop)

    if late:
        fee = models.base_versioned()
        fee.update({
            "customer_id": customer["id"], "appointment_id": appt["id"],
            "fee_type": "LATE_CANCEL", "amount_cents": calc.late_cancel_fee(),
            "settlement_status": "PENDING",
        })
        db.fee_charges[fee["id"]] = fee
        reconcile.recompute_outstanding_fees(customer)
        reconcile.recompute_customer_strikes(customer)
        models.touch(customer)

    rd = db.route_days.get(stop["route_day_id"]) if stop else None
    if rd is not None:
        reconcile.recompute_booked_minutes(rd)
        models.touch(rd)
        _maybe_close_route_day(rd["id"])

    models.touch(appt)
    return appt
