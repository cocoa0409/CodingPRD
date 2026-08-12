"""Technicians, route days and the life of a stop (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    CERT_LEVELS, CLOCK, DB, FULFILLMENT_STATUSES, LOCK, ROUTE_DAY_STATUSES,
    SCHEDULING_STATUSES, SERVICE_TYPES, TECH_STATUSES, ZONES, Ctx, by_created,
    fail, make_row, need_instrument, need_location, need_order, need_other,
    not_terminal, ok, page, parse_date, parse_iso, touch,
)

bp = Blueprint("scheduling", __name__)

ROUTE_DAY_TERMINAL = ("DISPATCHED",)
SCHEDULING_TERMINAL = ("CANCELLED",)
FULFILLMENT_TERMINAL = ("COMPLETED", "NO_SHOW", "ABORTED")


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/technicians")
def create_technician():
    with LOCK:
        ctx = Ctx(["PlatformAdmin"])
        body = ctx.read_body(["display_name", "certification_level", "zone_codes"])
        ctx.enum("certification_level", CERT_LEVELS)
        ctx.enum_list("zone_codes", ZONES)
        ctx.number("daily_capacity_minutes", lo=60, hi=960, integer=True)
        row = make_row(
            display_name=body["display_name"],
            certification_level=body["certification_level"],
            move_certified=bool(body.get("move_certified") or False),
            zone_codes=list(body["zone_codes"]),
            daily_capacity_minutes=(
                body["daily_capacity_minutes"]
                if body.get("daily_capacity_minutes") is not None
                else calc.ROUTE_DAY_DEFAULT_CAPACITY_MINUTES),
            status="ACTIVE",
        )
        DB.technicians[row["id"]] = row
        payload, status = ok(serialize.technician(row), 201)
        return jsonify(payload), status


@bp.get("/technicians")
def list_technicians():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        level = ctx.enum_q("certification_level", CERT_LEVELS)
        status_f = ctx.enum_q("status", TECH_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("technicians"))
        if level:
            rows = [r for r in rows if r["certification_level"] == level]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        payload, http = page(rows, limit, offset, serialize.technician)
        return jsonify(payload), http


@bp.patch("/technicians/<tid>")
def update_technician(tid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin"])
        body = ctx.read_body([])
        ctx.enum("certification_level", CERT_LEVELS)
        ctx.enum("status", TECH_STATUSES)
        ctx.enum_list("zone_codes", ZONES)
        ctx.number("daily_capacity_minutes", lo=60, hi=960, integer=True)
        row = need_other("technicians", tid)
        for field in ("certification_level", "move_certified", "zone_codes",
                      "daily_capacity_minutes", "status"):
            if field in body and body[field] is not None:
                row[field] = body[field]
        touch(row)
        payload, status = ok(serialize.technician(row))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Route days
# ---------------------------------------------------------------------------

@bp.post("/route-days")
def create_route_day():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["technician_id", "service_date"])
        ctx.number("capacity_minutes", lo=60, hi=960, integer=True)
        tech = need_other("technicians", body["technician_id"])
        if parse_date(body["service_date"]) is None:
            fail("ERR_VALIDATION", "service_date must be an ISO date.")
        if tech["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The technician is not ACTIVE.")
        capacity = body.get("capacity_minutes")
        row = make_row(
            technician_id=tech["id"],
            service_date=body["service_date"],
            capacity_minutes=(capacity if capacity is not None
                              else tech["daily_capacity_minutes"]),
            committed_minutes=0,
            stop_count=0,
            status="OPEN",
        )
        DB.route_days[row["id"]] = row
        payload, status = ok(serialize.route_day(row), 201)
        return jsonify(payload), status


@bp.get("/route-days")
def list_route_days():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician"])
        tech_filter = request.args.get("technician_id")
        if tech_filter:
            ctx.scope_tech(tech_filter)
        status_f = ctx.enum_q("status", ROUTE_DAY_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("route_days"))
        if tech_filter:
            rows = [r for r in rows if r["technician_id"] == tech_filter]
        service_date = request.args.get("service_date")
        if service_date:
            rows = [r for r in rows if r["service_date"] == service_date]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        payload, http = page(rows, limit, offset, serialize.route_day)
        return jsonify(payload), http


@bp.get("/route-days/<rid>")
def read_route_day(rid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician"])
        existing = DB.route_days.get(rid)
        if existing is not None:
            ctx.scope_tech(existing["technician_id"])
        row = need_other("route_days", rid)
        payload, status = ok(serialize.route_day(row))
        return jsonify(payload), status


@bp.post("/route-days/<rid>/status-transitions")
def route_day_transition(rid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        ctx.read_body(["to_status"])
        target = ctx.enum("to_status", ROUTE_DAY_STATUSES)
        day = need_other("route_days", rid)
        current = day["status"]
        not_terminal(current, ROUTE_DAY_TERMINAL)
        if (current, target) not in (("OPEN", "LOCKED"), ("LOCKED", "OPEN"),
                                     ("LOCKED", "DISPATCHED")):
            fail("ERR_INVALID_STATE",
                 "No route-day edge from %s to %s." % (current, target))

        if target == "LOCKED":
            service_date = parse_date(day["service_date"])
            midnight = parse_iso(service_date.isoformat() + "T00:00:00Z")
            earliest = midnight - timedelta(hours=calc.ROUTE_DAY_LOCK_LEAD_HOURS)
            if CLOCK.dt < earliest:
                fail("ERR_ROUTE_DAY_LOCK_LEAD",
                     "A route day may only be locked within 12 hours of its date.")

        if target == "DISPATCHED":
            if day["stop_count"] < 1:
                fail("ERR_INVALID_STATE", "A dispatched day needs at least one stop.")
            tech = DB.technicians.get(day["technician_id"])
            stops = [a for a in DB.appointments.values()
                     if a["route_day_id"] == day["id"]
                     and a["scheduling_status"] in ("SCHEDULED", "CONFIRMED")
                     and a["fulfillment_status"] == "PENDING"]
            # rung 52 -- MUTATE-THEN-REJECT: earlier flips are not rolled back.
            for stop in by_created(stops):
                if tech is not None and not calc.cert_ok(
                        tech["certification_level"], stop["service_type"]):
                    fail("ERR_TECH_CERT_INSUFFICIENT",
                         "The technician may not perform %s." % stop["service_type"])
                stop["fulfillment_status"] = "EN_ROUTE"
                touch(stop)

        day["status"] = target
        touch(day)
        payload, status = ok(serialize.route_day(day))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Appointment helpers
# ---------------------------------------------------------------------------

def _same_address_chained(route_day_id, address_key, created_at, exclude_id):
    for other in DB.appointments.values():
        if other["id"] == exclude_id:
            continue
        if other["route_day_id"] != route_day_id:
            continue
        if other["scheduling_status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if created_at is not None and not (other["created_at"] < created_at):
            continue
        other_loc = DB.locations.get(other["location_id"])
        if other_loc is not None and other_loc["address_key"] == address_key:
            return True
    return False


def _overlap(route_day_id, start_dt, block_minutes, exclude_id):
    end_dt = start_dt + timedelta(minutes=block_minutes)
    for other in DB.appointments.values():
        if other["id"] == exclude_id or other["route_day_id"] != route_day_id:
            continue
        if other["scheduling_status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        o_start = parse_iso(other["scheduled_start_utc"])
        if o_start is None:
            continue
        o_end = o_start + timedelta(minutes=other["total_block_minutes"])
        if start_dt < o_end and o_start < end_dt:  # half-open intersection
            return True
    return False


def _double_booked(instrument_id, service_date, exclude_id):
    for other in DB.appointments.values():
        if other["id"] == exclude_id or other["instrument_id"] != instrument_id:
            continue
        if other["scheduling_status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        day = DB.route_days.get(other["route_day_id"])
        if day is not None and day["service_date"] == service_date:
            return True
    return False


def _appointment_owner(appt):
    instrument = DB.instruments.get(appt["instrument_id"])
    return instrument["client_id"] if instrument else None


def _route_day_tech(appt):
    day = DB.route_days.get(appt["route_day_id"])
    return day["technician_id"] if day else None


def _fee_settlement(appt, fee):
    """PRD 3.7: the linked order's deposit absorbs the fee first; only the
    residual reaches the ledger."""
    client_id = _appointment_owner(appt)
    residual = fee
    order = DB.service_orders.get(appt["service_order_id"]) \
        if appt.get("service_order_id") else None
    if order is not None and fee > 0:
        unspoken = (order["deposit_held_cents"] - order["deposit_applied_cents"]
                    - order["deposit_refunded_cents"])
        forfeit = min(fee, max(0, unspoken))
        if forfeit > 0:
            order["deposit_forfeited_cents"] += forfeit
            touch(order)
        residual = fee - forfeit
    if residual > 0:
        services.post_ledger(client_id, "CANCELLATION_FEE", -residual,
                             service_order_id=appt.get("service_order_id"))
    if fee > 0:
        services.recompute_balance_for(client_id)


# ---------------------------------------------------------------------------
# Booking a stop
# ---------------------------------------------------------------------------

@bp.post("/appointments")
def create_appointment():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        peek = ctx.peek_body()
        pre_instrument = DB.instruments.get(peek.get("instrument_id")) \
            if isinstance(peek.get("instrument_id"), str) else None
        if pre_instrument is not None:
            ctx.scope_client(pre_instrument["client_id"])

        body = ctx.read_body(["instrument_id", "route_day_id", "location_id",
                              "scheduled_start_utc", "service_type",
                              "expected_route_day_version"])
        service_type = ctx.enum("service_type", SERVICE_TYPES)
        start_dt = parse_iso(body["scheduled_start_utc"])
        if start_dt is None:
            fail("ERR_VALIDATION", "scheduled_start_utc must be an ISO instant.")

        location = need_location(body["location_id"])
        instrument = need_instrument(body["instrument_id"])
        order = None
        if body.get("service_order_id") is not None:
            order = need_order(body["service_order_id"])
        day = need_other("route_days", body["route_day_id"])
        recall = None
        if body.get("tuning_recall_id") is not None:
            recall = need_other("tuning_recalls", body["tuning_recall_id"])

        # rung 17 -- address ownership
        if location["client_id"] != instrument["client_id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "The location is owned by a different client.")
        if instrument["current_location_id"] != location["id"]:
            fail("ERR_OWNERSHIP_MISMATCH",
                 "The stop must sit at the instrument's current location.")

        client = DB.clients.get(instrument["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        tech = DB.technicians.get(day["technician_id"])
        if tech is not None and tech["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The technician is not ACTIVE.")
        if day["status"] != "OPEN":
            fail("ERR_INVALID_STATE", "The route day no longer accepts bookings.")

        if body["expected_route_day_version"] != day["version"]:
            fail("ERR_STALE_ROUTE_DAY_VERSION",
                 "expected_route_day_version does not match.")
        if tech is not None and not calc.cert_ok(tech["certification_level"],
                                                 service_type):
            fail("ERR_TECH_CERT_INSUFFICIENT",
                 "The technician may not perform %s." % service_type)

        _check_lead_and_date(start_dt, day)
        _check_zone(location, client, tech)

        effective = instrument["pitch_raise_tier"]
        chained = _same_address_chained(day["id"], location["address_key"],
                                        None, None)
        service_minutes = calc.appointment_service_minutes(
            service_type, instrument["instrument_class"], effective)
        buffer_minutes = calc.appointment_travel_buffer(
            chained, location["zone_code"], tech["zone_codes"] if tech else [])
        block = service_minutes + buffer_minutes
        price = calc.appointment_estimated_price(
            service_type, instrument["instrument_class"], effective, chained)

        if _overlap(day["id"], start_dt, block, None):
            fail("ERR_APPOINTMENT_OVERLAP", "The stop overlaps another stop.")
        if _double_booked(instrument["id"], day["service_date"], None):
            fail("ERR_INSTRUMENT_DOUBLE_BOOKED",
                 "The instrument already has a stop on that date.")
        if day["committed_minutes"] + block > day["capacity_minutes"]:
            fail("ERR_ROUTE_CAPACITY_EXCEEDED", "The route day has no room left.")

        row = make_row(
            instrument_id=instrument["id"],
            route_day_id=day["id"],
            location_id=location["id"],
            service_order_id=order["id"] if order else None,
            tuning_recall_id=recall["id"] if recall else None,
            service_type=service_type,
            scheduled_start_utc=body["scheduled_start_utc"],
            service_minutes=service_minutes,
            travel_buffer_minutes=buffer_minutes,
            total_block_minutes=block,
            same_address_chained=chained,
            estimated_price_cents=price,
            cancellation_fee_cents=0,
            reschedule_count=0,
            scheduling_status="SCHEDULED",
            fulfillment_status="PENDING",
        )
        DB.appointments[row["id"]] = row
        services.recompute_route_day(day)
        if recall is not None and recall["status"] == "NOTIFIED":
            recall["status"] = "SCHEDULED"
            touch(recall)
        payload, status = ok(serialize.appointment(row), 201)
        return jsonify(payload), status


def _check_lead_and_date(start_dt, day):
    earliest = CLOCK.dt + timedelta(minutes=calc.APPOINTMENT_MIN_LEAD_MINUTES)
    if start_dt < earliest:
        fail("ERR_APPOINTMENT_LEAD_TIME",
             "A stop must start at least 120 minutes from now.")
    if start_dt.date().isoformat() != day["service_date"]:
        fail("ERR_APPOINTMENT_DATE_MISMATCH",
             "scheduled_start_utc must fall on the route day's service_date.")


def _check_zone(location, client, tech):
    zones = tech["zone_codes"] if tech else []
    home = client["home_zone_code"] if client else None
    if location["zone_code"] not in zones and home not in zones:
        fail("ERR_TECHNICIAN_ZONE_MISMATCH",
             "The technician does not serve this zone.")


@bp.get("/appointments")
def list_appointments():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        sched = ctx.enum_q("scheduling_status", SCHEDULING_STATUSES)
        fulfil = ctx.enum_q("fulfillment_status", FULFILLMENT_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("appointments"))
        for key in ("instrument_id", "route_day_id", "location_id",
                    "service_order_id", "tuning_recall_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if sched:
            rows = [r for r in rows if r["scheduling_status"] == sched]
        if fulfil:
            rows = [r for r in rows if r["fulfillment_status"] == fulfil]
        if ctx.is_client:
            rows = [r for r in rows if _appointment_owner(r) == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.appointment)
        return jsonify(payload), http


@bp.get("/appointments/<aid>")
def read_appointment(aid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_client(_appointment_owner(existing))
            ctx.scope_tech(_route_day_tech(existing))
        row = need_other("appointments", aid)
        payload, status = ok(serialize.appointment(row))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/confirm")
def confirm_appointment(aid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_client(_appointment_owner(existing))
        ctx.read_body([])
        appt = need_other("appointments", aid)
        not_terminal(appt["scheduling_status"], SCHEDULING_TERMINAL)
        if appt["scheduling_status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE",
                 "No scheduling edge from %s to CONFIRMED."
                 % appt["scheduling_status"])
        if appt["fulfillment_status"] != "PENDING":
            fail("ERR_INVALID_STATE", "The stop is already under way.")
        day = DB.route_days.get(appt["route_day_id"])
        if day is not None and day["status"] not in ("OPEN", "LOCKED"):
            fail("ERR_INVALID_STATE",
                 "A dispatched day no longer accepts confirmations.")
        appt["scheduling_status"] = "CONFIRMED"
        touch(appt)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/reschedule")
def reschedule_appointment(aid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_client(_appointment_owner(existing))
        body = ctx.read_body(["route_day_id", "scheduled_start_utc",
                              "expected_route_day_version"])
        start_dt = parse_iso(body["scheduled_start_utc"])
        if start_dt is None:
            fail("ERR_VALIDATION", "scheduled_start_utc must be an ISO instant.")
        appt = need_other("appointments", aid)
        day = need_other("route_days", body["route_day_id"])
        instrument = DB.instruments.get(appt["instrument_id"])
        location = DB.locations.get(appt["location_id"])

        if location is not None and instrument is not None:
            if location["client_id"] != instrument["client_id"]:
                fail("ERR_OWNERSHIP_MISMATCH",
                     "The location is owned by a different client.")
            if instrument["current_location_id"] != location["id"]:
                fail("ERR_OWNERSHIP_MISMATCH",
                     "The stop must sit at the instrument's current location.")

        not_terminal(appt["scheduling_status"], SCHEDULING_TERMINAL)
        not_terminal(appt["fulfillment_status"], FULFILLMENT_TERMINAL)
        if appt["scheduling_status"] not in ("SCHEDULED", "CONFIRMED"):
            fail("ERR_INVALID_STATE",
                 "No scheduling edge from %s to RESCHEDULED."
                 % appt["scheduling_status"])
        if appt["fulfillment_status"] != "PENDING":
            fail("ERR_INVALID_STATE", "The stop is already under way.")
        if day["status"] != "OPEN":
            fail("ERR_INVALID_STATE", "The target route day is not OPEN.")
        if body["expected_route_day_version"] != day["version"]:
            fail("ERR_STALE_ROUTE_DAY_VERSION",
                 "expected_route_day_version does not match.")

        _check_lead_and_date(start_dt, day)
        client = DB.clients.get(instrument["client_id"]) if instrument else None
        tech = DB.technicians.get(day["technician_id"])
        _check_zone(location, client, tech)

        effective = instrument["pitch_raise_tier"] if instrument else None
        chained = _same_address_chained(day["id"], location["address_key"],
                                        appt["created_at"], appt["id"])
        service_minutes = calc.appointment_service_minutes(
            appt["service_type"], instrument["instrument_class"], effective)
        buffer_minutes = calc.appointment_travel_buffer(
            chained, location["zone_code"], tech["zone_codes"] if tech else [])
        block = service_minutes + buffer_minutes
        price = calc.appointment_estimated_price(
            appt["service_type"], instrument["instrument_class"], effective,
            chained)

        if _overlap(day["id"], start_dt, block, appt["id"]):
            fail("ERR_APPOINTMENT_OVERLAP", "The stop overlaps another stop.")
        if _double_booked(appt["instrument_id"], day["service_date"], appt["id"]):
            fail("ERR_INSTRUMENT_DOUBLE_BOOKED",
                 "The instrument already has a stop on that date.")
        if appt["reschedule_count"] >= calc.RESCHEDULE_LIMIT:
            fail("ERR_ATTEMPT_LIMIT_EXCEEDED", "The reschedule cap is reached.")
        room = day["committed_minutes"] + block
        if day["id"] == appt["route_day_id"]:
            room -= appt["total_block_minutes"]
        if room > day["capacity_minutes"]:
            fail("ERR_ROUTE_CAPACITY_EXCEEDED", "The route day has no room left.")

        old_start = parse_iso(appt["scheduled_start_utc"])
        lead_hours = services.lead_hours_from_clock(old_start) \
            if old_start else services.lead_hours_from_clock(CLOCK.dt)
        fee = calc.reschedule_fee(appt["fulfillment_status"], lead_hours)

        previous_day = DB.route_days.get(appt["route_day_id"])
        appt["route_day_id"] = day["id"]
        appt["scheduled_start_utc"] = body["scheduled_start_utc"]
        appt["service_minutes"] = service_minutes
        appt["travel_buffer_minutes"] = buffer_minutes
        appt["total_block_minutes"] = block
        appt["same_address_chained"] = chained
        appt["estimated_price_cents"] = price
        appt["reschedule_count"] += 1
        appt["scheduling_status"] = "SCHEDULED"
        touch(appt)

        if previous_day is not None and previous_day["id"] != day["id"]:
            services.recompute_route_day(previous_day)
        services.recompute_route_day(day)

        if fee > 0:
            client_id = _appointment_owner(appt)
            services.post_ledger(client_id, "CANCELLATION_FEE", -fee,
                                 service_order_id=appt.get("service_order_id"))
            services.recompute_balance_for(client_id)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/cancel")
def cancel_appointment(aid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Client"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_client(_appointment_owner(existing))
        ctx.read_body([])
        appt = need_other("appointments", aid)
        not_terminal(appt["scheduling_status"], SCHEDULING_TERMINAL)
        if appt["scheduling_status"] not in ("SCHEDULED", "CONFIRMED"):
            fail("ERR_INVALID_STATE",
                 "No scheduling edge from %s to CANCELLED."
                 % appt["scheduling_status"])
        if appt["fulfillment_status"] not in ("PENDING", "EN_ROUTE", "IN_PROGRESS"):
            fail("ERR_INVALID_STATE", "The stop can no longer be cancelled.")

        start_dt = parse_iso(appt["scheduled_start_utc"])
        lead_hours = services.lead_hours_from_clock(start_dt) if start_dt \
            else services.lead_hours_from_clock(CLOCK.dt)
        fee, _variant = calc.cancellation_fee(appt["estimated_price_cents"],
                                              appt["fulfillment_status"],
                                              lead_hours)
        appt["cancellation_fee_cents"] = fee
        appt["scheduling_status"] = "CANCELLED"
        appt["fulfillment_status"] = "ABORTED"
        touch(appt)
        services.recompute_route_day(DB.route_days.get(appt["route_day_id"]))
        _fee_settlement(appt, fee)
        recall = DB.tuning_recalls.get(appt["tuning_recall_id"]) \
            if appt.get("tuning_recall_id") else None
        if recall is not None and recall["status"] == "SCHEDULED":
            recall["status"] = "NOTIFIED"
            touch(recall)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/start")
def start_appointment(aid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_tech(_route_day_tech(existing))
        ctx.read_body([])
        appt = need_other("appointments", aid)
        not_terminal(appt["fulfillment_status"], FULFILLMENT_TERMINAL)
        if appt["fulfillment_status"] != "EN_ROUTE":
            fail("ERR_INVALID_STATE",
                 "No fulfillment edge from %s to IN_PROGRESS."
                 % appt["fulfillment_status"])
        appt["fulfillment_status"] = "IN_PROGRESS"
        touch(appt)
        order = DB.service_orders.get(appt["service_order_id"]) \
            if appt.get("service_order_id") else None
        if order is not None and order["status"] == "PENDING":
            order["status"] = "IN_PROGRESS"
            order["started_at"] = CLOCK.stamp()
            touch(order)
            stones = [m for m in DB.milestones.values()
                      if m["service_order_id"] == order["id"]
                      and m["status"] == "PENDING"]
            for stone in sorted(stones, key=lambda m: m["sequence_index"]):
                stone["status"] = "READY"
                touch(stone)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/complete")
def complete_appointment(aid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_tech(_route_day_tech(existing))
        ctx.read_body([])
        appt = need_other("appointments", aid)
        not_terminal(appt["fulfillment_status"], FULFILLMENT_TERMINAL)
        if appt["fulfillment_status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE",
                 "No fulfillment edge from %s to COMPLETED."
                 % appt["fulfillment_status"])
        appt["fulfillment_status"] = "COMPLETED"
        touch(appt)
        recall = DB.tuning_recalls.get(appt["tuning_recall_id"]) \
            if appt.get("tuning_recall_id") else None
        if recall is not None and recall["status"] == "SCHEDULED":
            recall["status"] = "FULFILLED"
            touch(recall)
            instrument = DB.instruments.get(appt["instrument_id"])
            if instrument is not None:
                instrument["last_tuning_date"] = CLOCK.date.isoformat()
                touch(instrument)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status


@bp.post("/appointments/<aid>/no-show")
def no_show_appointment(aid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.appointments.get(aid)
        if existing is not None:
            ctx.scope_tech(_route_day_tech(existing))
        ctx.read_body([])
        appt = need_other("appointments", aid)
        not_terminal(appt["fulfillment_status"], FULFILLMENT_TERMINAL)
        if appt["fulfillment_status"] != "EN_ROUTE":
            fail("ERR_INVALID_STATE",
                 "No fulfillment edge from %s to NO_SHOW."
                 % appt["fulfillment_status"])
        fee, _variant = calc.cancellation_fee(appt["estimated_price_cents"],
                                              "EN_ROUTE", None)
        appt["fulfillment_status"] = "NO_SHOW"
        appt["scheduling_status"] = "CANCELLED"
        appt["cancellation_fee_cents"] = fee
        touch(appt)
        services.recompute_route_day(DB.route_days.get(appt["route_day_id"]))
        _fee_settlement(appt, fee)
        order = DB.service_orders.get(appt["service_order_id"]) \
            if appt.get("service_order_id") else None
        if order is not None and order["status"] == "IN_PROGRESS":
            order["status"] = "ON_HOLD"
            touch(order)
        payload, status = ok(serialize.appointment(appt))
        return jsonify(payload), status
