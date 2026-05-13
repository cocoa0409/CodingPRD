"""Charging session endpoints."""

from flask import Blueprint, g, request

import db
from clock import now, now_iso, parse_iso
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from services import audit, pricing as pricing_svc, queue_service, settlement
from validators import (
    check_version,
    get_pagination,
    paginate_list,
    parse_json_body,
    require_enum,
    require_int,
    require_number,
    require_str,
)


bp = Blueprint("sessions", __name__)

VALID_AUTH_METHODS = {"APP", "RFID", "PLUG_AND_CHARGE"}
VALID_ABNORMAL = {"OVER_TEMPERATURE", "COMMUNICATION_LOSS"}
VALID_WINDOW_TAGS = {"PEAK", "FLAT", "VALLEY"}
MIN_AUTH_HOLD_CENTS = 1000


@bp.post("/sessions")
@require_roles({"EVDriver"})
def create_session():
    body = parse_json_body()
    pile_id = require_str(body, "pile_id")
    member_id = require_str(body, "member_id")
    auth_method = require_enum(body, "auth_method", VALID_AUTH_METHODS)
    reservation_id = body.get("reservation_id")

    if pile_id not in db.piles:
        raise_error("ERR_NOT_FOUND", "pile not found")
    if member_id not in db.members:
        raise_error("ERR_NOT_FOUND", "member not found")
    if reservation_id is not None and reservation_id not in db.reservations:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    if member_id != g.user_id:
        raise_error("ERR_FORBIDDEN", "may only create session for self")

    # Reservation referential integrity (priority 9) — applies on create
    if reservation_id:
        res = db.reservations[reservation_id]
        if res["member_id"] != member_id or res["pile_id"] != pile_id:
            raise_error("ERR_RESERVATION_MISMATCH", "reservation/member/pile mismatch")

    record = {
        "pile_id": pile_id,
        "member_id": member_id,
        "reservation_id": reservation_id,
        "pricing_version_id": None,
        "promo_activity_id": None,
        "auth_method": auth_method,
        "status": "PENDING_AUTH",
        "started_at": None,
        "ended_at": None,
        "peak_kwh_milli": 0,
        "flat_kwh_milli": 0,
        "valley_kwh_milli": 0,
        "abnormal_events": [],
        "electricity_fee_cents": 0,
        "service_fee_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
    }
    db.with_common_fields(record)
    db.sessions[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/sessions/<session_id>/start")
@require_roles({"EVDriver"})
def start_session(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    body = parse_json_body()
    check_version(body, session)

    if session["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your session")
    if session["status"] != "PENDING_AUTH":
        raise_error("ERR_INVALID_STATE", "session not in PENDING_AUTH state")

    pile = db.piles.get(session["pile_id"])
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile vanished")
    member = db.members.get(session["member_id"])
    if member is None:
        raise_error("ERR_AUTH_INVALID", "member missing")

    # Priority 8: pile must be ON_SHELF & IDLE (safety > reservation hold)
    if pile["lifecycle_state"] != "ON_SHELF" or pile["operational_state"] != "IDLE":
        raise_error("ERR_PILE_UNAVAILABLE", "pile not available")

    # Priority 9: reservation/member/pile must agree.
    res = None
    if session.get("reservation_id"):
        res = db.reservations.get(session["reservation_id"])
        if res is None:
            raise_error("ERR_NOT_FOUND", "reservation not found")
        if res["member_id"] != session["member_id"] or res["pile_id"] != session["pile_id"]:
            raise_error("ERR_RESERVATION_MISMATCH", "reservation mismatch")
        # Reservation must still be HELD.
        if res["status"] != "HELD":
            raise_error("ERR_RESERVATION_EXPIRED", "reservation not HELD")
        # Priority 10: hold not expired.
        if now() >= parse_iso(res["hold_expires_at"]):
            raise_error("ERR_RESERVATION_EXPIRED", "reservation hold expired")
    else:
        # Priority 11: queue front check.
        station_id = pile["station_id"]
        waiting = queue_service.waiting_entries_at_station(station_id)
        if waiting:
            # Driver must be holder of the position-1 entry.
            front = waiting[0]
            if front["member_id"] != session["member_id"]:
                raise_error("ERR_QUEUE_NOT_AT_FRONT", "not at front of queue")

    # Priority 17: wallet balance.
    if int(member["wallet_balance_cents"]) < MIN_AUTH_HOLD_CENTS:
        raise_error("ERR_INSUFFICIENT_BALANCE", "wallet below minimum auth hold")

    # Pin pricing version + promo.
    station = db.stations[pile["station_id"]]
    pv = pricing_svc.find_active_pricing(station["operator_id"], now_iso())
    if pv is None:
        raise_error("ERR_INVALID_STATE", "no active pricing version for operator")
    session["pricing_version_id"] = pv["id"]
    promo = pricing_svc.find_active_promo(station["operator_id"], member["tier"], now_iso())
    session["promo_activity_id"] = promo["id"] if promo else None
    session["status"] = "CHARGING"
    session["started_at"] = now_iso()
    db.bump(session)

    # Pile transitions IDLE -> IN_USE
    pile["operational_state"] = "IN_USE"
    db.bump(pile)

    # Reservation -> ACTIVATED if applicable.
    if res is not None:
        res["status"] = "ACTIVATED"
        db.bump(res)

    # Queue entry promotion if started from queue.
    station_id = pile["station_id"]
    waiting = queue_service.waiting_entries_at_station(station_id)
    if waiting and waiting[0]["member_id"] == session["member_id"] and res is None:
        front = waiting[0]
        old_position = front["position"]
        front["status"] = "PROMOTED"
        db.bump(front)
        queue_service.decrement_positions_after(station_id, old_position)

    return success(db.public(session))


@bp.post("/sessions/<session_id>/curve-points")
@require_roles({"PlatformOperator", "FieldTechnician"})
def append_curve_point(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    body = parse_json_body()
    sampled_at = require_str(body, "sampled_at")
    instant_power_kw = require_number(
        body, "instant_power_kw", min_value=0.0, max_frac_digits=2
    )
    cumulative_energy_milli = require_int(body, "cumulative_energy_milli", 0)
    window_tag = require_enum(body, "window_tag", VALID_WINDOW_TAGS)

    try:
        sampled_dt = parse_iso(sampled_at)
    except Exception:
        raise_error("ERR_VALIDATION", "sampled_at must be ISO 8601")

    # Monotonic check.
    existing = [p for p in db.curve_points.values() if p["session_id"] == session_id]
    existing.sort(key=lambda p: (p["sampled_at"], p["_seq"]))
    if existing:
        last = existing[-1]
        last_dt = parse_iso(last["sampled_at"])
        if sampled_dt <= last_dt:
            raise_error("ERR_CURVE_NON_MONOTONIC", "sampled_at must be strictly increasing")
        if cumulative_energy_milli < int(last["cumulative_energy_milli"]):
            raise_error("ERR_CURVE_NON_MONOTONIC", "cumulative_energy_milli must be non-decreasing")

    record = {
        "session_id": session_id,
        "sampled_at": sampled_at,
        "instant_power_kw": instant_power_kw,
        "cumulative_energy_milli": cumulative_energy_milli,
        "window_tag": window_tag,
    }
    db.append_only_record(record)
    db.curve_points[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/sessions/<session_id>/mark-abnormal")
@require_roles({"PlatformOperator", "FieldTechnician"})
def mark_abnormal(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    body = parse_json_body()
    event_type = require_enum(body, "event_type", VALID_ABNORMAL)
    events = list(session.get("abnormal_events") or [])
    events.append({"type": event_type, "at": now_iso()})
    session["abnormal_events"] = events
    db.bump(session)
    return success(db.public(session))


@bp.post("/sessions/<session_id>/stop")
@require_roles({"EVDriver", "PlatformOperator"})
def stop_session(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    body = parse_json_body()
    check_version(body, session)

    if g.role == "EVDriver" and session["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your session")

    if session["status"] != "CHARGING":
        # If session is already terminal we surface session-state error.
        if session["status"] in {"SETTLED", "ABORTED", "SETTLING"}:
            raise_error("ERR_INVALID_SESSION_STATE", "session not in CHARGING state")
        raise_error("ERR_INVALID_STATE", "session not in CHARGING state")

    session["status"] = "SETTLING"
    session["ended_at"] = now_iso()
    db.bump(session)

    # Settlement requires at least one curve point.
    points = [p for p in db.curve_points.values() if p["session_id"] == session_id]
    if not points:
        # No metering: emit zero settlement directly.
        session["peak_kwh_milli"] = 0
        session["flat_kwh_milli"] = 0
        session["valley_kwh_milli"] = 0
        session["electricity_fee_cents"] = 0
        session["service_fee_cents"] = 0
        session["tax_cents"] = 0
        session["total_cents"] = 0
        session["status"] = "SETTLED"
        db.bump(session)
    else:
        settlement.settle_session(session)

    # Pile -> IDLE; queue promotion check.
    pile = db.piles.get(session["pile_id"])
    if pile is not None and pile["lifecycle_state"] == "ON_SHELF":
        pile["operational_state"] = "IDLE"
        db.bump(pile)
        queue_service.promote_if_possible(pile["station_id"])

    return success(db.public(session))


@bp.post("/sessions/<session_id>/abort")
@require_roles({"CustomerService"})
def abort_session(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    body = parse_json_body()
    check_version(body, session)

    if session["status"] not in {"CHARGING", "PENDING_AUTH"}:
        raise_error("ERR_INVALID_SESSION_STATE", "session cannot be aborted in this state")

    session["status"] = "ABORTED"
    session["ended_at"] = now_iso()
    session["electricity_fee_cents"] = 0
    session["service_fee_cents"] = 0
    session["tax_cents"] = 0
    session["total_cents"] = 0
    db.bump(session)

    audit.write(
        actor_role=g.role,
        actor_id=g.user_id,
        entity_kind="ChargingSession",
        entity_id=session["id"],
        event_kind="FAULT_EVENT",
        payload={"reason": "customer_service_abort"},
    )

    pile = db.piles.get(session["pile_id"])
    if pile is not None and pile["lifecycle_state"] == "ON_SHELF" and pile["operational_state"] == "IN_USE":
        pile["operational_state"] = "IDLE"
        db.bump(pile)
        queue_service.promote_if_possible(pile["station_id"])

    return success(db.public(session))


@bp.get("/sessions/<session_id>")
@require_roles({"EVDriver", "PlatformOperator", "CustomerService", "StationOwner"})
def get_session(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    if g.role == "EVDriver" and session["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your session")
    if g.role == "StationOwner":
        pile = db.piles.get(session["pile_id"])
        station = db.stations.get(pile["station_id"]) if pile else None
        if station is None or station["station_owner_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "not your station's session")
    return success(db.public(session))


@bp.get("/sessions/<session_id>/estimate")
@require_roles({"EVDriver", "PlatformOperator", "CustomerService"})
def session_estimate(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    if g.role == "EVDriver" and session["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your session")
    fees = settlement.compute_session_fees(session)
    return success({
        "electricity_fee_cents": fees["electricity_fee_cents"],
        "service_fee_cents": fees["service_fee_cents"],
        "tax_cents": fees["tax_cents"],
        "total_cents": fees["total_cents"],
    })


@bp.get("/sessions/<session_id>/curve-points")
@require_roles({"EVDriver", "PlatformOperator", "FieldTechnician", "CustomerService"})
def list_curve_points(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    if g.role == "EVDriver" and session["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your session")
    limit, offset = get_pagination()
    items = [p for p in db.curve_points.values() if p["session_id"] == session_id]
    items.sort(key=lambda p: (p["sampled_at"], p["_seq"]))
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)


@bp.get("/sessions/<session_id>/ledger-entries")
@require_roles({"PlatformOperator", "StationOwner", "CustomerService"})
def list_session_ledger(session_id: str):
    session = db.sessions.get(session_id)
    if session is None:
        raise_error("ERR_NOT_FOUND", "session not found")
    if g.role == "StationOwner":
        pile = db.piles.get(session["pile_id"])
        station = db.stations.get(pile["station_id"]) if pile else None
        if station is None or station["station_owner_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "not your station's session")
    limit, offset = get_pagination()
    items = [le for le in db.ledger_entries.values() if le["session_id"] == session_id]
    items.sort(key=lambda r: r["_seq"])
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)
