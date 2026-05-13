"""Reservation lifecycle: create, cancel, fare calc, waitlist, bill cascades."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db
from clock import iso, now
from errors import err
from services.audit import append_audit
from services.util import parse_dt, time_in_peak_windows, half_up_int


BASE_FARE_CENTS = 200
PEAK_FARE_MULTIPLIER = Decimal("1.5")
DAILY_RESERVATION_LIMIT = 3


def _fare_tier(segment_count: int) -> int:
    if 1 <= segment_count <= 2:
        return BASE_FARE_CENTS
    if 3 <= segment_count <= 5:
        return BASE_FARE_CENTS + 100
    if segment_count >= 6:
        return BASE_FARE_CENTS + 200
    # 0 segments shouldn't happen but treat as base
    return BASE_FARE_CENTS


def compute_fare_cents(segment_count: int, is_peak: bool) -> int:
    tier_cents = Decimal(_fare_tier(segment_count))
    raw = tier_cents * PEAK_FARE_MULTIPLIER if is_peak else tier_cents
    return half_up_int(raw)


def _route_version_for_run(rs: dict):
    route = db.routes.get(rs.get("route_id"))
    if not route:
        return None, None
    for rv in db.route_versions.values():
        if rv.get("route_code") == route.get("code") and \
                rv.get("version_number") == rs.get("route_version_number"):
            return route, rv
    return route, None


def create_reservation(rs: dict, body: dict, actor_role: str, actor_id: str) -> dict:
    # State eligibility
    if rs.get("status") not in ("PLANNED", "BOARDING"):
        # Reservations are typically created against PLANNED runs. BOARDING/IN_TRANSIT
        # is not a typical state for reservation creation. Default to PLANNED.
        raise err("ERR_INVALID_STATE",
                  f"Cannot create reservation against a {rs.get('status')} run")

    employee_id = body.get("employee_id")
    boarding_id = body.get("boarding_stop_id")
    alighting_id = body.get("alighting_stop_id")
    payer_mode = body.get("payer_mode")
    department_code = body.get("department_code")

    if not isinstance(employee_id, str) or not employee_id.strip():
        raise err("ERR_VALIDATION", "employee_id is required")
    if not isinstance(boarding_id, str) or not boarding_id:
        raise err("ERR_VALIDATION", "boarding_stop_id is required")
    if not isinstance(alighting_id, str) or not alighting_id:
        raise err("ERR_VALIDATION", "alighting_stop_id is required")
    if payer_mode not in ("SELF_PAY", "DEPARTMENT_PAID"):
        raise err("ERR_VALIDATION", "payer_mode must be SELF_PAY|DEPARTMENT_PAID")

    # FK existence
    if boarding_id not in db.stops:
        raise err("ERR_REFERENCE_NOT_FOUND",
                  f"boarding_stop_id {boarding_id} not found")
    if alighting_id not in db.stops:
        raise err("ERR_REFERENCE_NOT_FOUND",
                  f"alighting_stop_id {alighting_id} not found")

    # Stop-pair validity against route version snapshot
    _, rv = _route_version_for_run(rs)
    seq = (rv or {}).get("stop_sequence_snapshot") or []
    if boarding_id not in seq or alighting_id not in seq:
        raise err("ERR_INVALID_STOP_PAIR",
                  "Boarding/alighting stop not on the run's route snapshot")
    if seq.index(boarding_id) >= seq.index(alighting_id):
        raise err("ERR_INVALID_STOP_PAIR",
                  "Boarding stop must precede alighting stop in the snapshot")

    # Payer mode coherence
    if payer_mode == "DEPARTMENT_PAID":
        if not isinstance(department_code, str) or not department_code.strip():
            raise err("ERR_PAYER_MODE_MISMATCH",
                      "department_code required for DEPARTMENT_PAID")
    else:  # SELF_PAY
        if department_code is not None:
            raise err("ERR_PAYER_MODE_MISMATCH",
                      "department_code must not be set for SELF_PAY")

    # Daily limit: count non-CANCELLED reservations of same employee on same scheduled_date
    sched_date_dt = parse_dt(rs["scheduled_date"]).date()
    daily_count = 0
    for r in db.reservations.values():
        if r.get("employee_id") != employee_id:
            continue
        if r.get("status") == "CANCELLED":
            continue
        other_rs = db.run_sheets.get(r.get("run_sheet_id"))
        if not other_rs:
            continue
        if parse_dt(other_rs["scheduled_date"]).date() == sched_date_dt:
            daily_count += 1
    if daily_count >= DAILY_RESERVATION_LIMIT:
        raise err("ERR_DAILY_LIMIT_EXCEEDED",
                  f"Employee daily reservation limit of {DAILY_RESERVATION_LIMIT} reached")

    # Fare calc
    segment_count = seq.index(alighting_id) - seq.index(boarding_id)
    peak_windows = (rv or {}).get("peak_windows") or []
    is_peak = time_in_peak_windows(parse_dt(rs["scheduled_departure"]), peak_windows)
    fare = compute_fare_cents(segment_count, is_peak)

    # Capacity check / waitlist
    from services.run_sheets_svc import recompute_capacity_remaining
    recompute_capacity_remaining(rs)
    cap = rs.get("capacity_remaining", 0)

    if cap >= 1:
        status = "CONFIRMED"
        waitlist_position = None
    else:
        # Waitlist
        max_pos = 0
        for r in db.reservations.values():
            if r.get("run_sheet_id") == rs["id"] and r.get("status") == "WAITLISTED":
                if (r.get("waitlist_position") or 0) > max_pos:
                    max_pos = r.get("waitlist_position")
        status = "WAITLISTED"
        waitlist_position = max_pos + 1

    res = {
        "employee_id": employee_id,
        "run_sheet_id": rs["id"],
        "boarding_stop_id": boarding_id,
        "alighting_stop_id": alighting_id,
        "status": status,
        "waitlist_position": waitlist_position,
        "payer_mode": payer_mode,
        "department_code": department_code,
        "fare_cents": fare,
        "no_show_penalty_points": 0,
        "cancelled_at": None,
    }
    db.stamp_create(res)
    db.reservations[res["id"]] = res

    recompute_capacity_remaining(rs)
    db.stamp_update(rs)

    append_audit(
        event_type="RESERVATION_CREATED",
        subject_type="Reservation",
        subject_id=res["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={
            "run_sheet_id": rs["id"],
            "employee_id": employee_id,
            "status": status,
            "fare_cents": fare,
        },
    )
    return res


def cancel_reservation_cascade(res: dict, actor_role: str, actor_id: str,
                                cause: str | None = None,
                                is_cascade: bool = False) -> None:
    """Cancel a reservation (CONFIRMED or WAITLISTED). Handles waitlist promotion
    and finalized-bill refund line.
    """
    cur = res.get("status")
    if cur not in ("CONFIRMED", "WAITLISTED"):
        if cur == "CHECKED_IN":
            raise err("ERR_RESERVATION_ALREADY_CHECKED_IN",
                      "Reservation already checked in")
        raise err("ERR_INVALID_STATE",
                  f"Cannot cancel reservation in status {cur}")

    n = now()
    rs = db.run_sheets.get(res.get("run_sheet_id"))

    if cur == "CONFIRMED":
        res["status"] = "CANCELLED"
        res["cancelled_at"] = iso(n)
        db.stamp_update(res)
        # Free capacity
        if rs is not None:
            from services.run_sheets_svc import recompute_capacity_remaining
            recompute_capacity_remaining(rs)
            db.stamp_update(rs)

        # Promote next WAITLISTED if run still PLANNED
        if rs is not None and rs.get("status") == "PLANNED":
            wait = [r for r in db.reservations.values()
                    if r.get("run_sheet_id") == rs["id"]
                    and r.get("status") == "WAITLISTED"]
            if wait:
                wait.sort(key=lambda r: r.get("waitlist_position") or 0)
                # Recompute capacity to see if seat is available
                from services.run_sheets_svc import recompute_capacity_remaining
                recompute_capacity_remaining(rs)
                if rs.get("capacity_remaining", 0) >= 1:
                    nxt = wait[0]
                    nxt["status"] = "CONFIRMED"
                    nxt["waitlist_position"] = None
                    db.stamp_update(nxt)
                    recompute_capacity_remaining(rs)
                    db.stamp_update(rs)

        # Refund cascade on FINALIZED bill, if any
        from services.bills_svc import refund_for_cancelled_reservation
        refund_for_cancelled_reservation(res, actor_role=actor_role, actor_id=actor_id)

    elif cur == "WAITLISTED":
        cancelled_pos = res.get("waitlist_position") or 0
        res["status"] = "CANCELLED"
        res["cancelled_at"] = iso(n)
        res["waitlist_position"] = None
        db.stamp_update(res)
        # Renumber subsequent waitlist positions
        if rs is not None:
            for r in db.reservations.values():
                if r.get("run_sheet_id") == rs["id"] and r.get("status") == "WAITLISTED":
                    pos = r.get("waitlist_position") or 0
                    if pos > cancelled_pos:
                        r["waitlist_position"] = pos - 1
                        db.stamp_update(r)

    append_audit(
        event_type="RESERVATION_CANCELLED",
        subject_type="Reservation",
        subject_id=res["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"cause": cause, "cascade": is_cascade},
    )


def check_in_reservation(rs: dict, body: dict, actor_role: str, actor_id: str) -> dict:
    res_id = body.get("reservation_id")
    method = body.get("check_in_method")
    bsid = body.get("boarded_stop_id")
    if not isinstance(res_id, str) or not res_id:
        raise err("ERR_VALIDATION", "reservation_id is required")
    if method not in ("QR", "CARD", "FACE"):
        raise err("ERR_VALIDATION", "check_in_method must be QR|CARD|FACE")
    if not isinstance(bsid, str) or not bsid:
        raise err("ERR_VALIDATION", "boarded_stop_id is required")
    if bsid not in db.stops:
        raise err("ERR_REFERENCE_NOT_FOUND", "boarded_stop_id not found")
    res = db.reservations.get(res_id)
    if not res:
        raise err("ERR_REFERENCE_NOT_FOUND", "reservation_id not found")
    if res.get("run_sheet_id") != rs["id"]:
        raise err("ERR_REFERENCE_NOT_FOUND",
                  "Reservation does not belong to this run-sheet")

    if rs.get("status") not in ("BOARDING", "IN_TRANSIT", "DELAYED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot check in against run in status {rs.get('status')}")

    # Check-in time window: [-30min, arrival + 60min]
    sd = parse_dt(rs["scheduled_departure"])
    sa = parse_dt(rs["scheduled_arrival"])
    n = now()
    if not (sd - timedelta(minutes=30) <= n <= sa + timedelta(minutes=60)):
        raise err("ERR_CHECKIN_WINDOW_CLOSED",
                  "Outside check-in window")

    if res.get("status") != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  f"Reservation must be CONFIRMED to check in (current: {res.get('status')})")

    # Transition
    res["status"] = "CHECKED_IN"
    db.stamp_update(res)

    rr = {
        "reservation_id": res["id"],
        "run_sheet_id": rs["id"],
        "employee_id": res.get("employee_id"),
        "check_in_method": method,
        "boarded_stop_id": bsid,
        "alighted_stop_id": None,
        "boarded_at": iso(now()),
        "alighted_at": None,
    }
    db.stamp_create(rr, common_fields=False)
    db.ridership_records[rr["id"]] = rr

    append_audit(
        event_type="RESERVATION_CHECKED_IN",
        subject_type="Reservation",
        subject_id=res["id"],
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"run_sheet_id": rs["id"], "method": method,
                 "boarded_stop_id": bsid, "ridership_record_id": rr["id"]},
    )
    return rr
