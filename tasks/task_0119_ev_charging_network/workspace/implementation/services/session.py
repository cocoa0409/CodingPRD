"""ChargingSession lifecycle: the parallel charging_status x billing_status
state machine, time accounting, and the cascades it drives (PRD §3.6, §3.8).

Time accounting: charging_minutes = whole minutes spent in CHARGING (start->stop,
excluding SUSPENDED); idle_minutes = whole minutes spent in SUSPENDED before stop.
We accumulate elapsed seconds in each dimension across transitions using the
server clock and floor to whole minutes when computing the reported counts.
"""
from decimal import Decimal

import db
import errors
from clock import current_utc, parse_iso
import services.site as site_svc
import services.pricing as pricing


def _flush_charging(session):
    """Move elapsed CHARGING time into the accumulator and clear the marker."""
    started = session.get("_charging_started_at")
    if started is not None:
        elapsed = (current_utc() - started).total_seconds()
        if elapsed > 0:
            session["_charging_seconds"] += elapsed
        session["_charging_started_at"] = None


def _flush_idle(session):
    """Move elapsed SUSPENDED time into the accumulator and clear the marker."""
    started = session.get("_suspend_started_at")
    if started is not None:
        elapsed = (current_utc() - started).total_seconds()
        if elapsed > 0:
            session["_idle_seconds"] += elapsed
        session["_suspend_started_at"] = None


def _whole_minutes(seconds):
    return int(seconds // 60)


def recompute_energy(session):
    """energy_delivered_kwh = latest meter_kwh - start meter_kwh for this session."""
    events = [m for m in db.meter_events.values() if m["session_id"] == session["id"]]
    if not events:
        session["energy_delivered_kwh"] = Decimal("0")
        return
    events.sort(key=lambda m: m["_seq"])
    start = Decimal(str(events[0]["meter_kwh"]))
    latest = Decimal(str(events[-1]["meter_kwh"]))
    delivered = latest - start
    if delivered < 0:
        delivered = Decimal("0")
    session["energy_delivered_kwh"] = delivered


def begin_charging(session):
    """PREPARING->CHARGING or SUSPENDED->CHARGING (StationController)."""
    status = session["charging_status"]
    stall = db.stalls[session["stall_id"]]

    if status == "PREPARING":
        # preconditions: stall OCCUPIED + a TRANSACTION_BEGIN meter event exists
        if stall["ocpp_status"] != "OCCUPIED":
            raise errors.err(errors.ERR_INVALID_STATE, "stall is not OCCUPIED")
        if not _has_context(session, "TRANSACTION_BEGIN"):
            raise errors.err(errors.ERR_INVALID_STATE,
                             "a TRANSACTION_BEGIN meter event is required")
        session["charging_status"] = "CHARGING"
        session["_charging_started_at"] = current_utc()
    elif status == "SUSPENDED":
        # resume: stall OCCUPIED required; freeze idle minutes at elapsed
        if stall["ocpp_status"] != "OCCUPIED":
            raise errors.err(errors.ERR_INVALID_STATE, "stall is not OCCUPIED")
        _flush_idle(session)
        session["idle_minutes"] = _whole_minutes(session["_idle_seconds"])
        session["charging_status"] = "CHARGING"
        session["_charging_started_at"] = current_utc()
    else:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "begin-charging not defined from %s" % status)

    site = db.sites[stall["site_id"]]
    site_svc.run_allocation(site, "SESSION_START")
    db.touch(site)
    site_svc.recompute_site_aggregates(site)
    db.touch(session)


def suspend(session):
    """CHARGING->SUSPENDED (StationController)."""
    if session["charging_status"] != "CHARGING":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "suspend not defined from %s" % session["charging_status"])
    _flush_charging(session)
    session["charging_status"] = "SUSPENDED"
    session["allocated_power_kw"] = Decimal("0")
    session["_suspend_started_at"] = current_utc()

    stall = db.stalls[session["stall_id"]]
    site = db.sites[stall["site_id"]]
    site_svc.run_allocation(site, "SESSION_SUSPEND")
    db.touch(site)
    site_svc.recompute_site_aggregates(site)
    db.touch(session)


def stop(session):
    """CHARGING/SUSPENDED -> FINISHING -> COMPLETED, then billing UNBILLED->RATED."""
    status = session["charging_status"]
    if status not in ("CHARGING", "SUSPENDED"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "stop not defined from %s" % status)
    if not _has_context(session, "TRANSACTION_END"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "a TRANSACTION_END meter event is required")

    # Flush whichever dimension is currently running.
    _flush_charging(session)
    _flush_idle(session)

    # Compute measured quantities.
    recompute_energy(session)
    session["charging_minutes"] = _whole_minutes(session["_charging_seconds"])
    session["idle_minutes"] = _whole_minutes(session["_idle_seconds"])
    session["allocated_power_kw"] = Decimal("0")

    stall = db.stalls[session["stall_id"]]
    site = db.sites[stall["site_id"]]

    # charging_status -> FINISHING (then auto -> COMPLETED below)
    session["charging_status"] = "FINISHING"

    # Re-run load balancing over remaining CHARGING sessions.
    site_svc.run_allocation(site, "SESSION_STOP")
    db.touch(site)

    # ---- Rating (billing UNBILLED -> RATED) is computed first so a wallet
    #      shortfall can reject the whole stop before any mutation lands. ----
    tariff = db.tariffs[session["tariff_id"]]
    total_cost, idle_fee = pricing.session_cost(session, tariff)

    driver = db.drivers[session["driver_id"]]
    if not session["is_roaming"]:
        if driver["wallet_balance_cents"] - total_cost < 0:
            raise errors.err(errors.ERR_INSUFFICIENT_WALLET,
                             "rating would drive wallet below zero")

    # Commit: auto-advance to COMPLETED and rate.
    session["charging_status"] = "COMPLETED"
    session["total_cost_cents"] = total_cost
    session["idle_fee_cents"] = idle_fee
    session["billing_status"] = "RATED"

    if not session["is_roaming"]:
        driver["wallet_balance_cents"] -= total_cost
        db.touch(driver)

    # Reservation consume cascade.
    if session["reservation_id"]:
        res = db.reservations.get(session["reservation_id"])
        if res is not None and res["status"] == "CHECKED_IN":
            res["status"] = "CONSUMED"
            # refund deposit (branch A — fulfilled)
            driver["wallet_balance_cents"] += res["hold_fee_cents"]
            db.touch(driver)
            db.touch(res)

    # Return the stall to AVAILABLE (OCCUPIED -> AVAILABLE cascade).
    if stall["ocpp_status"] == "OCCUPIED":
        stall["ocpp_status"] = "AVAILABLE"
        db.touch(stall)

    site_svc.recompute_site_aggregates(site)
    db.touch(session)


def abort(session):
    """PREPARING->ABORTED (Driver/StationController). Releases stall, no cost."""
    if session["charging_status"] != "PREPARING":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "abort not defined from %s" % session["charging_status"])
    session["charging_status"] = "ABORTED"

    stall = db.stalls[session["stall_id"]]
    if stall["ocpp_status"] == "OCCUPIED":
        stall["ocpp_status"] = "AVAILABLE"
        db.touch(stall)

    site = db.sites[stall["site_id"]]
    site_svc.recompute_site_aggregates(site)
    db.touch(session)


def cost_preview(session):
    """Preview (total_cost_cents, idle_fee_cents) for current meter state.

    Uses the current accumulated charging/idle minutes plus any in-progress
    elapsed time, without mutating the session.
    """
    tariff = db.tariffs[session["tariff_id"]]

    # Compute provisional minutes including any currently-running dimension.
    charging_seconds = session["_charging_seconds"]
    if session.get("_charging_started_at") is not None:
        charging_seconds += (current_utc() - session["_charging_started_at"]).total_seconds()
    idle_seconds = session["_idle_seconds"]
    if session.get("_suspend_started_at") is not None:
        idle_seconds += (current_utc() - session["_suspend_started_at"]).total_seconds()

    recompute_energy(session)
    provisional = dict(session)
    provisional["charging_minutes"] = _whole_minutes(charging_seconds)
    provisional["idle_minutes"] = _whole_minutes(idle_seconds)
    total_cost, idle_fee = pricing.session_cost(provisional, tariff)
    return total_cost, idle_fee


def force_suspend_from_fault(session):
    """Stall FAULTED cascade: force an active session to SUSPENDED and free power.

    Applies to sessions in PREPARING/CHARGING/SUSPENDED.
    """
    status = session["charging_status"]
    if status == "CHARGING":
        _flush_charging(session)
    if status in ("PREPARING", "CHARGING"):
        session["_suspend_started_at"] = current_utc()
    session["charging_status"] = "SUSPENDED"
    session["allocated_power_kw"] = Decimal("0")
    db.touch(session)


def _has_context(session, context):
    for m in db.meter_events.values():
        if m["session_id"] == session["id"] and m["reading_context"] == context:
            return True
    return False
