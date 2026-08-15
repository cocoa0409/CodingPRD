"""VisitSession endpoints (PRD §3.4, §3.7)."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_DAY_NOT_OPEN,
    ERR_FIELD_DEPLETED,
    ERR_FIELD_NOT_OPEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NO_ACTIVE_POLICY,
    ERR_PARKING_FULL,
    ERR_SEASON_NOT_ACTIVE,
    ERR_UNPAID_BALANCE,
    ERR_UNRESOLVED_LINES,
    ERR_WINDOW_CAPACITY_FULL,
    ERR_WINDOW_NOT_OPEN,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_int,
    req_str,
    require,
)

bp = Blueprint("sessions", __name__)

GATE = ("GateStaff", "FarmManager")
FIELD = ("FieldStaff", "FarmManager")
READERS = ("FarmManager", "GateStaff", "FieldStaff", "KioskDevice")
LIST_READERS = ("FarmManager", "GateStaff", "FieldStaff")


def _active_policy(season_id):
    return next(
        (
            p
            for p in db.pricing_policies.values()
            if p["season_id"] == season_id and p["status"] == "ACTIVE"
        ),
        None,
    )


def make_session(
    window,
    waiver_id,
    policy_id,
    party_size,
    container_count,
    parking_spaces,
    origin,
    offline_ref,
    device_id,
    visit_status,
    sync_outcome,
    admission_charge_cents,
):
    session = domain.new_entity()
    session.update(
        {
            "window_id": window["id"],
            "waiver_id": waiver_id,
            "pricing_policy_id": policy_id,
            "party_size": party_size,
            "container_count": container_count,
            "parking_spaces": parking_spaces,
            "origin": origin,
            "offline_ref": offline_ref,
            "device_id": device_id,
            "visit_status": visit_status,
            "admission_charge_cents": admission_charge_cents,
            "final_total_cents": None,
            "bundle_discount_cents": 0,
            "checkout_mode": None,
            "sync_outcome": sync_outcome,
        }
    )
    db.visit_sessions[session["id"]] = session
    return session


@bp.post("/farm/visit-sessions")
def create_session():
    require(GATE)
    body = get_body()
    check_no_undeclared(
        body,
        {"window_id", "waiver_id", "party_size", "container_count", "parking_spaces", "origin"},
    )
    window_id = req_str(body, "window_id")
    waiver_id = req_str(body, "waiver_id")
    party_size = req_int(body, "party_size", min_value=1)
    container_count = req_int(body, "container_count", min_value=0)
    parking_spaces = req_int(body, "parking_spaces", min_value=0)
    origin = req_str(body, "origin")
    if origin != "ONLINE":
        raise_err(ERR_INVALID_REQUEST, "origin must be ONLINE at the gate")
    # Body foreign keys (tier 5), declared order: window_id, waiver_id.
    window = db.windows.get(window_id)
    if window is None:
        raise_err(ERR_NOT_FOUND, "window_id does not resolve")
    waiver = db.waivers.get(waiver_id)
    if waiver is None:
        raise_err(ERR_NOT_FOUND, "waiver_id does not resolve")
    field = domain.field_of_window(window)
    season = domain.season_of_window(window)
    # Tier 8: season active.
    if season is None or season["status"] != "ACTIVE":
        raise_err(ERR_SEASON_NOT_ACTIVE, "Season is not ACTIVE")
    # Tier 9: waiver trio.
    domain.check_waiver_trio(waiver, season, party_size)
    # Tier 10: an ACTIVE pricing policy must exist to pin.
    policy = _active_policy(season["id"])
    if policy is None:
        raise_err(ERR_NO_ACTIVE_POLICY, "Season has no ACTIVE PricingPolicy")
    # Tier 11: window slot capacity (equality fills the window and succeeds).
    if domain.window_booked_slots(window) + party_size > window["picking_capacity_slots"]:
        raise_err(ERR_WINDOW_CAPACITY_FULL, "Window capacity exceeded")
    # Tier 11: parking capacity.
    day = domain.sales_day_for(season["id"], window["date"])
    if day is not None and domain.day_booked_parking(day) + parking_spaces > day["parking_capacity"]:
        raise_err(ERR_PARKING_FULL, "Parking capacity exceeded")
    # Tier 11: field depletion gate (forward-looking basis).
    if domain.field_projected_remaining_oz(field) <= 0:
        raise_err(ERR_FIELD_DEPLETED, "Field is projected picked out")
    # Tier 12: cross-resource state.
    if window["status"] != "OPEN":
        raise_err(ERR_WINDOW_NOT_OPEN, "Window is not OPEN")
    if day is None or day["status"] != "OPEN":
        raise_err(ERR_DAY_NOT_OPEN, "SalesDay is not OPEN")
    admission = domain.compute_admission_charge(policy, day, party_size, container_count)
    session = make_session(
        window=window,
        waiver_id=waiver_id,
        policy_id=policy["id"],
        party_size=party_size,
        container_count=container_count,
        parking_spaces=parking_spaces,
        origin="ONLINE",
        offline_ref=None,
        device_id=None,
        visit_status="CHECKED_IN",
        sync_outcome=None,
        admission_charge_cents=admission,
    )
    return ok_object(domain.serialize_session(session), 201)


@bp.get("/farm/visit-sessions/<sid>")
def get_session(sid):
    require(READERS)
    session = db.visit_sessions.get(sid)
    if session is None:
        raise_err(ERR_NOT_FOUND, "VisitSession not found")
    return ok_object(domain.serialize_session(session))


@bp.get("/farm/visit-sessions")
def list_sessions():
    require(LIST_READERS)
    items = list(db.visit_sessions.values())
    window_id = request.args.get("window_id")
    if window_id is not None:
        items = [s for s in items if s["window_id"] == window_id]
    waiver_id = request.args.get("waiver_id")
    if waiver_id is not None:
        items = [s for s in items if s["waiver_id"] == waiver_id]
    policy_id = request.args.get("pricing_policy_id")
    if policy_id is not None:
        items = [s for s in items if s["pricing_policy_id"] == policy_id]
    visit_status = request.args.get("visit_status")
    if visit_status is not None:
        items = [s for s in items if s["visit_status"] == visit_status]
    return paginate(items, domain.serialize_session)


@bp.post("/farm/visit-sessions/<sid>/enter-field")
def enter_field(sid):
    require(FIELD)
    session = db.visit_sessions.get(sid)
    if session is None:
        raise_err(ERR_NOT_FOUND, "VisitSession not found")
    if session["visit_status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "Only a CHECKED_IN session can enter the field")
    # Tier 9: waiver trio runs again.
    waiver = db.waivers.get(session["waiver_id"])
    season = domain.season_of_session(session)
    if waiver is not None and season is not None:
        domain.check_waiver_trio(waiver, season, session["party_size"])
    # Tier 12: cross-resource state.
    window = domain.window_of_session(session)
    if window is None or window["status"] != "OPEN":
        raise_err(ERR_WINDOW_NOT_OPEN, "Window is not OPEN")
    field = domain.field_of_session(session)
    if field is None or field["status"] != "OPEN":
        raise_err(ERR_FIELD_NOT_OPEN, "Field is not OPEN")
    # Tier 14: admission balance gate.
    net_paid = domain.session_total_paid(session) - domain.session_total_refunded(session)
    if net_paid < session["admission_charge_cents"]:
        raise_err(ERR_UNPAID_BALANCE, "Net paid is below the admission charge")
    session["visit_status"] = "FIELD_ACTIVE"
    domain.touch(session)
    return ok_object(domain.serialize_session(session))


@bp.post("/farm/visit-sessions/<sid>/checkout")
def checkout(sid):
    require(FIELD)
    session = db.visit_sessions.get(sid)
    if session is None:
        raise_err(ERR_NOT_FOUND, "VisitSession not found")
    if session["visit_status"] not in ("CHECKED_IN", "FIELD_ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Session cannot be checked out from its current state")
    # Tier 11: no PROVISIONAL harvest lines.
    if any(l["status"] == "PROVISIONAL" for l in domain.session_lines(session)):
        raise_err(ERR_UNRESOLVED_LINES, "Session has unresolved PROVISIONAL harvest lines")
    final_total, bundle_discount = domain.checkout_settlement(session)
    # Tier 14: balance gate against the computed final total.
    net_paid = domain.session_total_paid(session) - domain.session_total_refunded(session)
    if net_paid < final_total:
        raise_err(ERR_UNPAID_BALANCE, "Net paid is below the final total")
    session["final_total_cents"] = final_total
    session["bundle_discount_cents"] = bundle_discount
    session["visit_status"] = "CHECKED_OUT"
    session["checkout_mode"] = "NORMAL"
    # Unredeemed bookings release at checkout WITHOUT refund (never charged).
    for b in domain.session_bookings(session):
        if b["status"] == "BOOKED":
            domain.release_booking(b, refund=False)
    # Overpayment auto-refund, oldest payments first.
    if net_paid > final_total:
        domain.apply_refund(session, net_paid - final_total)
    domain.touch(session)
    return ok_object(domain.serialize_session(session))


@bp.post("/farm/visit-sessions/<sid>/cancel")
def cancel(sid):
    require(GATE)
    session = db.visit_sessions.get(sid)
    if session is None:
        raise_err(ERR_NOT_FOUND, "VisitSession not found")
    if session["visit_status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "Only a CHECKED_IN session can be cancelled")
    session["visit_status"] = "CANCELLED"
    # Cancel-time release; the full net-paid auto-refund below subsumes any
    # booking value the guest actually paid.
    for b in domain.session_bookings(session):
        if b["status"] == "BOOKED":
            domain.release_booking(b, refund=False)
    net_paid = domain.session_total_paid(session) - domain.session_total_refunded(session)
    if net_paid > 0:
        domain.apply_refund(session, net_paid)
    domain.touch(session)
    return ok_object(domain.serialize_session(session))
