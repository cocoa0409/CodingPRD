"""Event endpoints (PRD 3.1) plus the computed occupancy read (PRD 2.9)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import ANY_ROLE, auth, f_dt, f_enum, f_int, f_str, get_body, q
from response import ok
from services import calc
from services.domain import (
    gates_of_event,
    get_or_404,
    scan_events_of_event,
    tickets_of_event,
    zones_of_event,
)
from routes._common import filter_eq, paginated

bp = Blueprint("events", __name__)

EVENT_STATUSES = ("DRAFT", "ON_SALE", "DOORS_OPEN", "IN_PROGRESS", "CLOSED", "RECONCILED")
SUCCESSOR = {
    "DRAFT": "ON_SALE",
    "ON_SALE": "DOORS_OPEN",
    "DOORS_OPEN": "IN_PROGRESS",
    "IN_PROGRESS": "CLOSED",
}


@bp.route("/events", methods=["POST"])
def create_event():
    auth(("VenueAdmin",))
    body = get_body()
    name = f_str(body, "name", allow_empty=False)
    venue_name = f_str(body, "venue_name", allow_empty=False)
    fire_code_capacity = f_int(body, "fire_code_capacity", minimum=1)
    anchor_raw, anchor_dt = f_dt(body, "barcode_anchor_at")
    doors_raw, _doors_dt = f_dt(body, "doors_open_at")
    start_raw, _start_dt = f_dt(body, "event_start_at")
    close_raw, close_dt = f_dt(body, "transfer_window_closes_at")
    price_cap_regime = f_enum(
        body, "price_cap_regime", ("STATUTORY", "VENUE_POLICY", "NONE"),
        required=False, default="VENUE_POLICY",
    )
    transfer_limit = f_int(body, "transfer_limit_per_ticket", required=False, default=2, minimum=0)

    rec = base_record()
    rec["name"] = name
    rec["venue_name"] = venue_name
    rec["fire_code_capacity"] = fire_code_capacity
    rec["barcode_anchor_at"] = anchor_raw
    rec["doors_open_at"] = doors_raw
    rec["event_start_at"] = start_raw
    rec["transfer_window_closes_at"] = close_raw
    rec["price_cap_regime"] = price_cap_regime
    rec["transfer_limit_per_ticket"] = transfer_limit
    rec["status"] = "DRAFT"
    rec["live_occupancy"] = 0
    rec["peak_live_occupancy"] = 0
    rec["entitlements_outstanding"] = 0
    rec["settlement_pool_cents"] = 0
    rec["_anchor_dt"] = anchor_dt
    rec["_transfer_close_dt"] = close_dt
    db.events[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/events/<event_id>", methods=["GET"])
def get_event(event_id):
    auth(ANY_ROLE)
    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    return ok(public(event))


@bp.route("/events", methods=["GET"])
def list_events():
    auth(ANY_ROLE)
    rows = sort_created_asc(list(db.events.values()))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)


@bp.route("/events/<event_id>/advance-status", methods=["POST"])
def advance_status(event_id):
    auth(("VenueAdmin",))
    body = get_body()
    target = f_enum(body, "target_status", EVENT_STATUSES)
    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")

    if SUCCESSOR.get(event["status"]) != target:
        raise ApiError("ERR_INVALID_STATE")

    if target == "ON_SALE":
        if not zones_of_event(event_id) or not gates_of_event(event_id):
            raise ApiError(
                "ERR_INVALID_STATE",
                "An event needs at least one access zone and one gate before going ON_SALE.",
            )
    if target == "CLOSED":
        gate_ids = {g["id"] for g in gates_of_event(event_id)}
        for session in db.sessions.values():
            if session["gate_id"] in gate_ids and session["status"] in ("OPEN", "SYNCING"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A scan session on this event is still OPEN or SYNCING.",
                )
        for gate in gates_of_event(event_id):
            gate["status"] = "IDLE"

    event["status"] = target
    touch(event)
    return ok(public(event))


@bp.route("/events/<event_id>/occupancy", methods=["GET"])
def occupancy(event_id):
    auth(("GateOperator", "SecurityInvestigator", "VenueAdmin"))
    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    zones = zones_of_event(event_id)
    gates = gates_of_event(event_id)
    tickets = tickets_of_event(event_id)
    data = {
        "event_id": event["id"],
        "live_occupancy": event["live_occupancy"],
        "peak_live_occupancy": event["peak_live_occupancy"],
        "reconciled_attendance": calc.reconciled_attendance(scan_events_of_event(event_id)),
        "fire_code_capacity": event["fire_code_capacity"],
        "headroom": event["fire_code_capacity"] - event["live_occupancy"],
        "projected_clearance_minutes": calc.gate_clearance_projection(gates, tickets),
        "zone_occupancy": [
            {
                "id": zone["id"],
                "zone_code": zone["zone_code"],
                "occupancy_count": zone["occupancy_count"],
                "fire_code_capacity": zone["fire_code_capacity"],
            }
            for zone in zones
        ],
    }
    return ok(data)


@bp.route("/events/<event_id>/audit-log-entries", methods=["GET"])
def audit_log(event_id):
    auth(("SecurityInvestigator", "VenueAdmin"))
    get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    rows = [e for e in db.audit_entries.values() if e["event_id"] == event_id]
    rows = filter_eq(rows, "subject_type", q("subject_type"))
    rows = filter_eq(rows, "subject_id", q("subject_id"))
    rows = filter_eq(rows, "action", q("action"))
    # Newest first: occurred_at DESC, created_at DESC.
    rows.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]), reverse=True)
    return paginated(rows)
