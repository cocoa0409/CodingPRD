"""Trip operations: assign/unassign, depart, weather holds, rest/resume,
arrive, weight tickets, deliver, cancel (PRD 3.5-3.6)."""
from datetime import timedelta

from flask import Blueprint, g

import db
import hos
import services as svc
from errors import (
    raise_err, ERR_LOAD_NOT_FOUND, ERR_DRIVER_NOT_FOUND, ERR_HOLD_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH, ERR_LOAD_NOT_PAPERWORK_VERIFIED,
    ERR_LOAD_NOT_ASSIGNED, ERR_LOAD_NOT_IN_TRANSIT, ERR_LOAD_NOT_REST_UNLOAD,
    ERR_LOAD_NOT_ARRIVED, ERR_LOAD_NOT_HOLDABLE, ERR_LOAD_NOT_CANCELLABLE,
    ERR_HOLD_NOT_ACTIVE, ERR_STALE_VERSION, ERR_DRIVER_SUSPENDED,
    ERR_DRIVER_NOT_HOS_ELIGIBLE, ERR_TRAILER_WINDOW_OVERLAP,
    ERR_TRAILER_NOT_CLEAN, ERR_WEATHER_HOLD_REQUIRED, ERR_PAPER_EXPIRED,
    ERR_BRAND_INSPECTION_STALE, ERR_CONFINEMENT_LIMIT_EXCEEDED,
    ERR_INSUFFICIENT_REST_UNLOAD, ERR_TICKET_STATE_FORBIDDEN,
    ERR_INVALID_TICKET_WEIGHT, ERR_EVENT_IN_FUTURE, ERR_NO_DELIVERY_TICKET,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_int, v_enum, v_dt, paginate, minutes_between

bp = Blueprint("ops", __name__)

HOLD_TYPES = {"HEAT", "COLD"}
TICKET_TYPES = {"ORIGIN", "DELIVERY"}
BRAND_FRESH_HOURS = 96
DISPUTE_WINDOW_HOURS = 48
ORIGIN_TICKET_STATES = {"DRAFT", "PLANNED", "PAPERWORK_VERIFIED", "ASSIGNED", "IN_TRANSIT"}
WINDOW_ACTIVE = {"ASSIGNED", "IN_TRANSIT", "WEATHER_HOLD", "REST_UNLOAD", "ARRIVED"}


def load_or_404(load_id):
    ld = db.store["loads"].get(load_id)
    if ld is None:
        raise_err(ERR_LOAD_NOT_FOUND)
    return ld


def check_driver_ownership(ld):
    if g.user_role == "Driver" and ld["driver_id"] != g.user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "load belongs to another driver")


# ---------------------------------------------------------------- assignment
@bp.post("/haul/loads/<lid>/assign-driver")
def assign_driver(lid):
    require_role("Dispatcher")
    body = get_body()
    driver_id = v_str(body, "driver_id")
    expected_version = v_int(body, "expected_driver_version")
    ld = load_or_404(lid)
    driver = db.store["drivers"].get(driver_id)
    if driver is None:
        raise_err(ERR_DRIVER_NOT_FOUND)
    if ld["status"] != "PAPERWORK_VERIFIED":
        raise_err(ERR_LOAD_NOT_PAPERWORK_VERIFIED, "assign-driver requires PAPERWORK_VERIFIED")
    if expected_version != driver["version"]:
        raise_err(ERR_STALE_VERSION, "expected_driver_version does not match driver version")
    if driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_SUSPENDED, "driver is SUSPENDED")
    now = db.now()
    f = hos.hos_snapshot(driver_id, now)
    if f["hos_status"] != "ELIGIBLE":
        raise_err(ERR_DRIVER_NOT_HOS_ELIGIBLE, "driver is not HOS-eligible")
    # planned-window conflict: closed intervals, touching endpoints conflict
    w0 = ld["planned_departure_at"]
    w1 = w0 + timedelta(hours=ld["planned_duration_hours"])
    for other in db.store["loads"].values():
        if other["id"] == lid or other["status"] not in WINDOW_ACTIVE:
            continue
        if other["driver_id"] != driver_id and other["trailer_id"] != ld["trailer_id"]:
            continue
        o0 = other["planned_departure_at"]
        o1 = o0 + timedelta(hours=other["planned_duration_hours"])
        if o0 <= w1 and w0 <= o1:
            raise_err(ERR_TRAILER_WINDOW_OVERLAP,
                      "planned window touches or overlaps another active load")
    ld["driver_id"] = driver_id
    ld["status"] = "ASSIGNED"
    svc.touch(ld)
    svc.touch(driver)
    return success(svc.load_json(ld))


@bp.post("/haul/loads/<lid>/unassign-driver")
def unassign_driver(lid):
    require_role("Dispatcher")
    ld = load_or_404(lid)
    if ld["status"] != "ASSIGNED":
        raise_err(ERR_LOAD_NOT_ASSIGNED, "unassign-driver requires ASSIGNED")
    driver = db.store["drivers"].get(ld["driver_id"])
    ld["driver_id"] = None
    ld["status"] = "PAPERWORK_VERIFIED"
    svc.touch(ld)
    if driver is not None:
        svc.touch(driver)
    return success(svc.load_json(ld))


# ---------------------------------------------------------------- depart
@bp.post("/haul/loads/<lid>/depart")
def depart(lid):
    require_role("Driver")
    ld = load_or_404(lid)
    check_driver_ownership(ld)
    body = get_body()
    temp = v_int(body, "origin_temperature_f")
    if ld["status"] != "ASSIGNED":
        raise_err(ERR_LOAD_NOT_ASSIGNED, "depart requires ASSIGNED")
    driver = db.store["drivers"].get(ld["driver_id"])
    if driver is None or driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_SUSPENDED, "driver is SUSPENDED")
    now = db.now()
    f = hos.hos_snapshot(driver["id"], now)
    if f["hos_status"] != "ELIGIBLE":
        raise_err(ERR_DRIVER_NOT_HOS_ELIGIBLE, "driver is not HOS-eligible")
    trailer = db.store["trailers"].get(ld["trailer_id"])
    if svc.washout_status(trailer, now) != "CLEAN":
        raise_err(ERR_TRAILER_NOT_CLEAN, "trailer washout_status is not CLEAN")
    species = ld["species"]
    if (temp >= svc.HEAT_THRESHOLD[species] or temp <= svc.COLD_THRESHOLD[species]):
        raise_err(ERR_WEATHER_HOLD_REQUIRED,
                  "origin temperature violates the species threshold")
    has_paper = any(
        p["load_id"] == lid and p["status"] == "VERIFIED" and p["expires_at"] > now
        for p in db.store["health_papers"].values())
    if not has_paper:
        raise_err(ERR_PAPER_EXPIRED, "no VERIFIED health paper valid at departure")
    has_brand = any(
        b["load_id"] == lid and b["status"] == "VERIFIED"
        and b["inspected_at"] <= now
        and now - b["inspected_at"] <= timedelta(hours=BRAND_FRESH_HOURS)
        for b in db.store["brand_inspections"].values())
    if not has_brand:
        raise_err(ERR_BRAND_INSPECTION_STALE,
                  "no VERIFIED brand inspection within 96h of departure")
    ld["departed_at"] = now
    ld["confinement_anchor_at"] = now
    ld["status"] = "IN_TRANSIT"
    svc.append_system_event(driver["id"], "DUTY_ON", now, lid)
    svc.append_system_event(driver["id"], "DRIVING_ON", now, lid)
    # settlement: PRELIMINARY, provisional assumes on-weight delivery
    base = svc.compute_base_amount(ld)
    st = svc.new_common()
    st.update({
        "load_id": lid, "status": "PRELIMINARY",
        "base_amount_cents": base, "provisional_amount_cents": base,
        "shrink_allowance_lb": None, "delivered_weight_lb": None,
        "effective_delivered_weight_lb": None, "shrink_lb": None,
        "excess_shrink_lb": None, "shrink_penalty_cents": 0,
        "welfare_deduction_cents": 0, "dispute_adjustment_cents": 0,
        "final_amount_cents": base, "dispute_deadline_at": None,
        "disputed_weight_lb": None, "counter_weight_lb": None, "paid_at": None,
    })
    db.store["settlements"][st["id"]] = st
    svc.touch(ld)
    return success(svc.load_json(ld))


# ---------------------------------------------------------------- weather holds
@bp.post("/haul/loads/<lid>/weather-holds")
def place_weather_hold(lid):
    require_role("Driver", "Dispatcher")
    ld = load_or_404(lid)
    check_driver_ownership(ld)
    body = get_body()
    hold_type = v_enum(body, "hold_type", HOLD_TYPES)
    temp = v_int(body, "temperature_f")
    reason = v_str(body, "reason", required=False)
    if ld["status"] not in ("ASSIGNED", "IN_TRANSIT"):
        raise_err(ERR_LOAD_NOT_HOLDABLE, "weather hold requires ASSIGNED or IN_TRANSIT")
    now = db.now()
    if ld["status"] == "IN_TRANSIT" and ld["driver_id"] is not None:
        svc.append_system_event(ld["driver_id"], "DRIVING_OFF", now, lid)
    rec = svc.new_common()
    rec.update({"load_id": lid, "hold_type": hold_type, "temperature_f": temp,
                "reason": reason, "released_at": None})
    db.store["holds"][rec["id"]] = rec
    ld["status"] = "WEATHER_HOLD"
    svc.touch(ld)
    return success(svc.hold_json(rec), status=201)


@bp.get("/haul/loads/<lid>/weather-holds")
def list_weather_holds(lid):
    load_or_404(lid)
    items = sorted(
        (h for h in db.store["holds"].values() if h["load_id"] == lid),
        key=lambda h: h["seq"])
    page, meta = paginate([svc.hold_json(h) for h in items])
    return success(page, response_type="array", pagination=meta)


@bp.post("/haul/weather-holds/<hid>/release")
def release_weather_hold(hid):
    require_role("Dispatcher", "Driver")
    hold = db.store["holds"].get(hid)
    if hold is None:
        raise_err(ERR_HOLD_NOT_FOUND)
    ld = db.store["loads"].get(hold["load_id"])
    check_driver_ownership(ld)
    if hold["released_at"] is not None:
        raise_err(ERR_HOLD_NOT_ACTIVE, "hold is not ACTIVE")
    now = db.now()
    hold["released_at"] = now
    svc.touch(hold)
    if ld["departed_at"] is None:
        ld["status"] = "ASSIGNED"
    else:
        if ld["driver_id"] is not None:
            svc.append_system_event(ld["driver_id"], "DRIVING_ON", now, ld["id"])
        ld["status"] = "IN_TRANSIT"
    svc.touch(ld)
    return success(svc.hold_json(hold))


# ---------------------------------------------------------------- rest / resume / arrive
@bp.post("/haul/loads/<lid>/rest-unload")
def rest_unload(lid):
    require_role("Driver")
    ld = load_or_404(lid)
    check_driver_ownership(ld)
    if ld["status"] != "IN_TRANSIT":
        raise_err(ERR_LOAD_NOT_IN_TRANSIT, "rest-unload requires IN_TRANSIT")
    now = db.now()
    svc.append_system_event(ld["driver_id"], "DRIVING_OFF", now, lid)
    ld["rest_unload_started_at"] = now
    ld["status"] = "REST_UNLOAD"
    svc.touch(ld)
    return success(svc.load_json(ld))


@bp.post("/haul/loads/<lid>/resume-transit")
def resume_transit(lid):
    require_role("Driver")
    ld = load_or_404(lid)
    check_driver_ownership(ld)
    if ld["status"] != "REST_UNLOAD":
        raise_err(ERR_LOAD_NOT_REST_UNLOAD, "resume-transit requires REST_UNLOAD")
    now = db.now()
    if minutes_between(ld["rest_unload_started_at"], now) < svc.REST_UNLOAD_MIN:
        raise_err(ERR_INSUFFICIENT_REST_UNLOAD,
                  "at least 300 minutes of rest/unload are required")
    svc.append_system_event(ld["driver_id"], "DRIVING_ON", now, lid)
    ld["confinement_anchor_at"] = now
    ld["rest_unload_started_at"] = None
    ld["status"] = "IN_TRANSIT"
    svc.touch(ld)
    return success(svc.load_json(ld))


@bp.post("/haul/loads/<lid>/arrive")
def arrive(lid):
    require_role("Driver")
    ld = load_or_404(lid)
    check_driver_ownership(ld)
    if ld["status"] != "IN_TRANSIT":
        raise_err(ERR_LOAD_NOT_IN_TRANSIT, "arrive requires IN_TRANSIT")
    now = db.now()
    if minutes_between(ld["confinement_anchor_at"], now) > svc.MAX_CONFINEMENT_MIN:
        raise_err(ERR_CONFINEMENT_LIMIT_EXCEEDED,
                  "arrival would exceed 1680 minutes of confinement")
    svc.append_system_event(ld["driver_id"], "DRIVING_OFF", now, lid)
    ld["arrived_at"] = now
    ld["status"] = "ARRIVED"
    svc.touch(ld)
    return success(svc.load_json(ld))


# ---------------------------------------------------------------- weight tickets
@bp.post("/haul/loads/<lid>/weight-tickets")
def record_weight_ticket(lid):
    require_role("ConsigneeAgent", "Driver")
    body = get_body()
    ticket_type = v_enum(body, "ticket_type", TICKET_TYPES)
    gross = v_int(body, "gross_lb")
    tare = v_int(body, "tare_lb", min_value=0)
    weighed_at = v_dt(body, "weighed_at")
    ld = load_or_404(lid)
    if ticket_type == "ORIGIN":
        ok = ld["status"] in ORIGIN_TICKET_STATES
    else:
        ok = ld["status"] == "ARRIVED" or (
            ld["status"] == "DELIVERED"
            and (st := svc.get_settlement_for_load(lid)) is not None
            and st["status"] == "PENDING")
    if not ok:
        raise_err(ERR_TICKET_STATE_FORBIDDEN,
                  "ticket type not allowed in the load's current state")
    if gross <= tare:
        raise_err(ERR_INVALID_TICKET_WEIGHT, "gross_lb must be strictly > tare_lb")
    if weighed_at > db.now():
        raise_err(ERR_EVENT_IN_FUTURE, "weighed_at is after the current time")
    rec = svc.new_immutable()
    rec.update({"load_id": lid, "ticket_type": ticket_type, "gross_lb": gross,
                "tare_lb": tare, "net_weight_lb": gross - tare,
                "weighed_at": weighed_at})
    db.store["weight_tickets"][rec["id"]] = rec
    # DELIVERY reweigh while PENDING: refresh weight basis and recompute final
    if ticket_type == "DELIVERY" and ld["status"] == "DELIVERED":
        st = svc.get_settlement_for_load(lid)
        if st is not None and st["status"] == "PENDING":
            latest = svc.latest_delivery_ticket(lid)
            before = (st["delivered_weight_lb"], st["effective_delivered_weight_lb"],
                      st["shrink_penalty_cents"], st["final_amount_cents"])
            st["delivered_weight_lb"] = latest["net_weight_lb"]
            st["effective_delivered_weight_lb"] = latest["net_weight_lb"]
            svc.apply_weight_basis(st, ld, latest["net_weight_lb"])
            after = (st["delivered_weight_lb"], st["effective_delivered_weight_lb"],
                     st["shrink_penalty_cents"], st["final_amount_cents"])
            if before != after:
                svc.touch(st)
    return success(svc.ticket_json(rec), status=201)


@bp.get("/haul/loads/<lid>/weight-tickets")
def list_weight_tickets(lid):
    load_or_404(lid)
    items = sorted(
        (t for t in db.store["weight_tickets"].values() if t["load_id"] == lid),
        key=lambda t: t["seq"])
    page, meta = paginate([svc.ticket_json(t) for t in items])
    return success(page, response_type="array", pagination=meta)


# ---------------------------------------------------------------- deliver
@bp.post("/haul/loads/<lid>/deliver")
def deliver(lid):
    require_role("ConsigneeAgent")
    ld = load_or_404(lid)
    if ld["status"] != "ARRIVED":
        raise_err(ERR_LOAD_NOT_ARRIVED, "deliver requires ARRIVED")
    latest = svc.latest_delivery_ticket(lid)
    if latest is None:
        raise_err(ERR_NO_DELIVERY_TICKET, "at least one DELIVERY ticket is required")
    now = db.now()
    ld["delivered_at"] = now
    ld["status"] = "DELIVERED"
    driver = db.store["drivers"].get(ld["driver_id"]) if ld["driver_id"] else None
    if driver is not None:
        svc.append_system_event(driver["id"], "DUTY_OFF", now, lid)
    # chain link 1: release allocations (DELIVERED)
    svc.release_allocations(ld, "DELIVERED")
    # chain link 2: dirty the trailer
    trailer = db.store["trailers"].get(ld["trailer_id"]) if ld["trailer_id"] else None
    if trailer is not None:
        trailer["dirtied_at"] = now
        svc.touch(trailer)
    # settlement finalize: PRELIMINARY -> PENDING
    st = svc.get_settlement_for_load(lid)
    if st is not None:
        st["delivered_weight_lb"] = latest["net_weight_lb"]
        st["effective_delivered_weight_lb"] = latest["net_weight_lb"]
        svc.apply_weight_basis(st, ld, latest["net_weight_lb"])
        st["status"] = "PENDING"
        st["dispute_deadline_at"] = now + timedelta(hours=DISPUTE_WINDOW_HOURS)
        svc.touch(st)
    svc.touch(ld)
    # chain link 3: cycle exhaustion force-unassigns the driver's other loads
    if driver is not None:
        f = hos.hos_snapshot(driver["id"], now)
        if f["cycle_on_duty_minutes_8d"] >= hos.CYCLE_ON_DUTY_LIMIT_MIN:
            svc.force_unassign_driver_loads(driver["id"])
    return success(svc.load_json(ld))


# ---------------------------------------------------------------- cancel
@bp.post("/haul/loads/<lid>/cancel")
def cancel(lid):
    require_role("Dispatcher")
    ld = load_or_404(lid)
    if ld["status"] not in ("DRAFT", "PLANNED", "PAPERWORK_VERIFIED", "ASSIGNED"):
        raise_err(ERR_LOAD_NOT_CANCELLABLE,
                  "cancel requires DRAFT/PLANNED/PAPERWORK_VERIFIED/ASSIGNED")
    svc.release_allocations(ld, "CANCELLED")
    if ld["status"] == "ASSIGNED" and ld["driver_id"] is not None:
        driver = db.store["drivers"].get(ld["driver_id"])
        ld["driver_id"] = None
        if driver is not None:
            svc.touch(driver)
    ld["trailer_id"] = None
    ld["status"] = "CANCELLED"
    svc.touch(ld)
    return success(svc.load_json(ld))
