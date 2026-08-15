"""Routes: spots (booking with OCC, preemption, make-goods) and barter
avails."""
from flask import Blueprint, request

import store
from helpers import (DAYPARTS, DAYPART_HOURS, err, get_body, opt_bool,
                     opt_int, opt_str, paginate, req_enum, req_int, req_str,
                     require_role, success_object, weekday_of)
from logic import (append_ledger, auto_resolve_linked_discrepancy,
                   compute_unit_rate, find, find_rate_card,
                   post_trade_reversal, select_preemption_victims,
                   ser_barter_avail, ser_spot, spot_fits, stamp_new, touch,
                   trade_totals, trade_value_of)

bp = Blueprint("spots", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")

SPOT_DURATIONS = {15, 30, 60}


def _daypart_target_units(order, daypart):
    for t in order["daypart_targets"]:
        if t["daypart"] == daypart:
            return t["units"]
    return 0


def _scheduled_count_for_daypart(order, daypart):
    return sum(1 for s in store.spots.values()
               if s["order_id"] == order["id"] and s["daypart"] == daypart
               and s["status"] in ("SCHEDULED", "AIRED")
               and s["makeup_of_spot_id"] is None)


@bp.post("/spots")
def book_spot():
    body = get_body()
    order_id = req_str(body, "order_id")
    log_id = req_str(body, "log_id")
    daypart = req_enum(body, "daypart", set(DAYPARTS))
    hour = req_int(body, "hour", minimum=0, maximum=23)
    duration_sec = req_int(body, "duration_sec")
    if duration_sec not in SPOT_DURATIONS:
        err("ERR_BAD_REQUEST", "duration_sec must be one of 15, 30, 60")
    expected_order_version = req_int(body, "expected_order_version")
    override = opt_int(body, "unit_rate_override_cents")
    if override is not None and override < 1:
        err("ERR_BAD_REQUEST", "unit_rate_override_cents must be positive")
    allow_below_floor = opt_bool(body, "allow_below_floor", False)
    allow_preemption = opt_bool(body, "allow_preemption", False)
    event_id = opt_str(body, "event_id")

    # POST /spots: SalesRep or TrafficDirector; SalesManager is additionally
    # admitted because the below-floor rate override is a SalesManager-only
    # capability on this endpoint (RBAC matrix).
    user_id, role = require_role("SalesRep", "TrafficDirector",
                                 "SalesManager")

    # Existence, left-to-right: order_id, log_id, event_id.
    order = find(store.orders, order_id)
    log = find(store.logs, log_id)
    if event_id is not None:
        find(store.remote_events, event_id)

    # OCC before any from-state rule.
    if expected_order_version != order["version"]:
        err("ERR_STALE_VERSION",
            "expected_order_version does not match the order's current "
            "version")
    # Log posture gate, then order-active gate.
    if log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Spot booking requires log posture DRAFT or LOCKED")
    if order["status"] != "ACTIVE":
        err("ERR_ORDER_NOT_ACTIVE",
            "Spot booking requires an ACTIVE order")
    # Compliance: TRADE agreement must be ACTIVE.
    agreement = None
    if order["order_kind"] == "TRADE":
        agreement = store.trade_agreements.get(order["trade_agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            err("ERR_TRADE_AGREEMENT_INACTIVE",
                "Referenced TradeAgreement is not ACTIVE")
    # Temporal: hour belongs to daypart, then air_date within flight.
    if hour not in DAYPART_HOURS[daypart]:
        err("ERR_DAYPART_HOUR_MISMATCH",
            "Spot hour not in the daypart's hour set")
    air_date = log["log_date"]
    if not (order["flight_start"] <= air_date <= order["flight_end"]):
        err("ERR_SPOT_OUTSIDE_FLIGHT",
            "Spot air_date outside the order's flight")
    # Quota: per-(order, daypart) scheduled units must remain below target.
    if _scheduled_count_for_daypart(order, daypart) >= \
            _daypart_target_units(order, daypart):
        err("ERR_DAYPART_UNITS_EXHAUSTED",
            "Booking would exceed the order's daypart_targets units")
    # Capacity / preemption-permission tier.
    if allow_preemption and order["rate_tier"] != "FIXED":
        err("ERR_PREEMPTION_NOT_ALLOWED",
            "allow_preemption requires order rate_tier FIXED")
    victims = []
    if not spot_fits(log, hour, duration_sec):
        if not allow_preemption:
            err("ERR_HOUR_CAPACITY_EXCEEDED",
                "Hour pool cannot fit the new unit")
        victims = select_preemption_victims(log, hour, duration_sec)
        if victims is None:
            err("ERR_HOUR_CAPACITY_EXCEEDED",
                "Hour pool cannot fit the new unit even after preempting "
                "the full victim pool")
    # Fiscal: rate card, then floor, then trade credit headroom.
    rate_card = find_rate_card(order["station_id"], daypart, air_date)
    if rate_card is None:
        err("ERR_NO_RATE_CARD",
            "No ACTIVE RateCardEntry matches (station, daypart, weekday, "
            "air_date)")
    station = store.stations[order["station_id"]]
    if override is not None:
        unit_rate = override
        if (unit_rate < rate_card["min_rate_cents"]
                and not (role == "SalesManager" and allow_below_floor)):
            err("ERR_RATE_FLOOR_VIOLATION",
                "unit_rate_override_cents below min_rate_cents without "
                "SalesManager allow_below_floor")
    else:
        unit_rate, _ = compute_unit_rate(station, log, daypart, air_date,
                                         rate_card=rate_card)
    trade_value = None
    if agreement is not None:
        trade_value = trade_value_of(unit_rate, agreement["trade_ratio"])
        _, _, available = trade_totals(agreement)
        if trade_value > available:
            err("ERR_TRADE_CREDIT_EXCEEDED",
                "Projected DEBIT exceeds the agreement's available_cents")

    # Commit: preemption cascade first (victims -> MAKE_GOOD_PENDING with
    # reason PREEMPTED; TRADE victims post REVERSALs).
    victim_orders = set()
    for victim in victims:
        victim["status"] = "MAKE_GOOD_PENDING"
        victim["make_good_reason"] = "PREEMPTED"
        touch(victim)
        post_trade_reversal(victim)
        victim_orders.add(victim["order_id"])
    for oid in victim_orders:
        vorder = store.orders.get(oid)
        if vorder is not None:
            touch(vorder)

    rec = {"id": store.new_id(), "station_id": order["station_id"],
           "order_id": order["id"], "log_id": log["id"],
           "event_id": event_id, "air_date": air_date, "daypart": daypart,
           "hour": hour, "duration_sec": duration_sec,
           "unit_rate_cents": unit_rate,
           "billed_rate_cents": (unit_rate if order["reprice_policy"]
                                 == "LOCKED_AT_BOOKING" else None),
           "cash_equivalent_cents": (unit_rate if order["order_kind"]
                                     == "TRADE" else None),
           "makeup_of_spot_id": None, "make_good_reason": None,
           "status": "SCHEDULED"}
    stamp_new(rec)
    store.spots[rec["id"]] = rec
    if agreement is not None:
        append_ledger(agreement, "DEBIT", trade_value, spot_id=rec["id"])
    # Order counters recomputed; one OCC version bump.
    touch(order)
    return success_object(ser_spot(rec), 201)


@bp.get("/spots/<sid>")
def get_spot(sid):
    require_role(*ALL)
    return success_object(ser_spot(find(store.spots, sid)), 200)


@bp.get("/spots")
def list_spots():
    require_role(*ALL)
    recs = list(store.spots.values())
    station_id = request.args.get("station_id")
    order_id = request.args.get("order_id")
    log_id = request.args.get("log_id")
    event_id = request.args.get("event_id")
    status = request.args.get("status")
    daypart = request.args.get("daypart")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if order_id is not None:
        recs = [r for r in recs if r["order_id"] == order_id]
    if log_id is not None:
        recs = [r for r in recs if r["log_id"] == log_id]
    if event_id is not None:
        recs = [r for r in recs if r["event_id"] == event_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if daypart is not None:
        recs = [r for r in recs if r["daypart"] == daypart]
    return paginate(recs, ser_spot)


@bp.post("/spots/<sid>/cancel")
def cancel_spot(sid):
    require_role("TrafficDirector")
    spot = find(store.spots, sid)
    if spot["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Spot cancel requires status SCHEDULED")
    log = store.logs[spot["log_id"]]
    if log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Spot cancel requires log posture DRAFT or LOCKED")
    spot["status"] = "CANCELLED"
    touch(spot)
    post_trade_reversal(spot)
    order = store.orders.get(spot["order_id"])
    if order is not None:
        touch(order)  # units_scheduled recomputed
    return success_object(ser_spot(spot), 200)


@bp.post("/spots/<sid>/reschedule")
def reschedule_spot(sid):
    body = get_body()
    target_log_id = req_str(body, "target_log_id")
    target_daypart = req_enum(body, "target_daypart", set(DAYPARTS))
    target_hour = req_int(body, "target_hour", minimum=0, maximum=23)
    duration_sec = req_int(body, "duration_sec")
    if duration_sec not in SPOT_DURATIONS:
        err("ERR_BAD_REQUEST", "duration_sec must be one of 15, 30, 60")
    require_role("TrafficDirector")
    spot = find(store.spots, sid)
    target_log = find(store.logs, target_log_id)
    if spot["status"] != "MAKE_GOOD_PENDING":
        err("ERR_INVALID_STATE",
            "Reschedule requires status MAKE_GOOD_PENDING")
    if target_log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Reschedule target log must be DRAFT or LOCKED")
    order = store.orders[spot["order_id"]]
    # Temporal: target hour in daypart, then target date within flight.
    if target_hour not in DAYPART_HOURS[target_daypart]:
        err("ERR_DAYPART_HOUR_MISMATCH",
            "Target hour not in the target daypart's hour set")
    air_date = target_log["log_date"]
    if not (order["flight_start"] <= air_date <= order["flight_end"]):
        err("ERR_SPOT_OUTSIDE_FLIGHT",
            "Target air_date outside the order's flight")
    # Capacity: make-goods never preempt.
    if not spot_fits(target_log, target_hour, duration_sec):
        err("ERR_HOUR_CAPACITY_EXCEEDED",
            "Target hour pool cannot fit the make-good unit")
    # Fiscal: fresh rate via spot_unit_rate; then trade credit headroom.
    station = store.stations[order["station_id"]]
    unit_rate, _ = compute_unit_rate(station, target_log, target_daypart,
                                     air_date)
    agreement = None
    trade_value = None
    if order["order_kind"] == "TRADE":
        agreement = store.trade_agreements.get(order["trade_agreement_id"])
        trade_value = trade_value_of(unit_rate, agreement["trade_ratio"])
        _, _, available = trade_totals(agreement)
        if trade_value > available:
            err("ERR_TRADE_CREDIT_EXCEEDED",
                "Projected DEBIT exceeds the agreement's available_cents")

    # Commit: original -> RESOLVED (reason persists for conservation);
    # successor created SCHEDULED and does NOT count against daypart_targets.
    spot["status"] = "RESOLVED"
    touch(spot)
    successor = {"id": store.new_id(), "station_id": order["station_id"],
                 "order_id": order["id"], "log_id": target_log["id"],
                 "event_id": spot["event_id"], "air_date": air_date,
                 "daypart": target_daypart, "hour": target_hour,
                 "duration_sec": duration_sec, "unit_rate_cents": unit_rate,
                 "billed_rate_cents": (unit_rate if order["reprice_policy"]
                                       == "LOCKED_AT_BOOKING" else None),
                 "cash_equivalent_cents": (unit_rate if order["order_kind"]
                                           == "TRADE" else None),
                 "makeup_of_spot_id": spot["id"], "make_good_reason": None,
                 "status": "SCHEDULED"}
    stamp_new(successor)
    store.spots[successor["id"]] = successor
    if agreement is not None:
        append_ledger(agreement, "DEBIT", trade_value,
                      spot_id=successor["id"])
    auto_resolve_linked_discrepancy("MISSED_SPOT", "spot_id", spot["id"])
    return success_object(ser_spot(successor), 201)


@bp.post("/spots/<sid>/issue-credit")
def issue_spot_credit(sid):
    body = get_body()
    note = body.get("note")
    if note is None:
        note = body.get("resolution_note")
    if note is not None and not isinstance(note, str):
        err("ERR_BAD_REQUEST", "note must be a string")
    require_role("BillingAdmin")
    spot = find(store.spots, sid)
    if spot["status"] != "MAKE_GOOD_PENDING":
        err("ERR_INVALID_STATE",
            "Issue credit requires status MAKE_GOOD_PENDING")
    # Closes the obligation with no successor; any TRADE reversal already
    # posted when the spot entered MAKE_GOOD_PENDING.
    spot["status"] = "RESOLVED"
    touch(spot)
    linked = auto_resolve_linked_discrepancy("MISSED_SPOT", "spot_id",
                                             spot["id"])
    if linked is not None and note is not None:
        linked["resolution_note"] = note
    return success_object(ser_spot(spot), 200)


# ---------------------------------------------------------------------------
# Barter avails
# ---------------------------------------------------------------------------
@bp.post("/barter-avails")
def schedule_barter_avail():
    body = get_body()
    clearance_id = req_str(body, "clearance_id")
    log_id = req_str(body, "log_id")
    hour = req_int(body, "hour", minimum=0, maximum=23)
    duration_sec = req_int(body, "duration_sec")
    if duration_sec not in SPOT_DURATIONS:
        err("ERR_BAD_REQUEST", "duration_sec must be one of 15, 30, 60")
    expected_clearance_version = req_int(body, "expected_clearance_version")
    require_role("TrafficDirector")
    clearance = find(store.clearances, clearance_id)
    log = find(store.logs, log_id)
    # OCC before from-state rules.
    if expected_clearance_version != clearance["version"]:
        err("ERR_STALE_VERSION",
            "expected_clearance_version does not match the clearance's "
            "current version")
    if log["posture"] not in ("DRAFT", "LOCKED"):
        err("ERR_LOG_POSTURE_BLOCKED",
            "Barter avail scheduling requires log posture DRAFT or LOCKED")
    # Compliance: clearance must be CLEARED.
    if clearance["status"] != "CLEARED":
        err("ERR_CLEARANCE_NOT_CLEARED",
            "Clearance is not in CLEARED status")
    # Temporal: clearance weekday set, half-open hour window, effective range.
    air_date = log["log_date"]
    from routes_logs import store_log_date
    wd = weekday_of(store_log_date(log))
    if (wd not in clearance["weekday_set"]
            or not (clearance["start_hour"] <= hour
                    < clearance["start_hour"] + clearance["duration_hours"])
            or not (clearance["effective_from"] <= air_date
                    <= clearance["effective_to"])):
        err("ERR_CLEARANCE_WINDOW_VIOLATION",
            "Barter avail outside clearance weekday set, hour window, or "
            "effective range")
    # Capacity: consumes the hour's SPOT_BREAK pool.
    if not spot_fits(log, hour, duration_sec):
        err("ERR_HOUR_CAPACITY_EXCEEDED",
            "Hour SPOT_BREAK pool cannot fit the avail")
    rec = {"id": store.new_id(), "station_id": clearance["station_id"],
           "clearance_id": clearance["id"], "log_id": log["id"],
           "air_date": air_date, "hour": hour, "duration_sec": duration_sec,
           "status": "SCHEDULED"}
    stamp_new(rec)
    store.barter_avails[rec["id"]] = rec
    touch(clearance)  # OCC write: scheduling bumps the clearance version
    return success_object(ser_barter_avail(rec), 201)


@bp.get("/barter-avails/<aid>")
def get_barter_avail(aid):
    require_role(*ALL)
    return success_object(ser_barter_avail(find(store.barter_avails, aid)),
                          200)


@bp.get("/barter-avails")
def list_barter_avails():
    require_role(*ALL)
    recs = list(store.barter_avails.values())
    station_id = request.args.get("station_id")
    clearance_id = request.args.get("clearance_id")
    log_id = request.args.get("log_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if clearance_id is not None:
        recs = [r for r in recs if r["clearance_id"] == clearance_id]
    if log_id is not None:
        recs = [r for r in recs if r["log_id"] == log_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_barter_avail)
