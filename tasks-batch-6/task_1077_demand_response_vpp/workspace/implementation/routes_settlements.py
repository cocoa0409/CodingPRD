"""Settlements, payments, and the logical-clock setter (PRD §3.7, §2.10)."""
from flask import Blueprint, request

from errors import err
from common import (require, ALL_ROLES, get_body, ok, ok_object, list_response,
                    require_str)
from models import (get, get_or_404, insert, touch, recompute_paid_balance)
from store import db, parse_iso
from calc import dispatch_line_payout, settlement_totals, event_duration_hours

bp_settlements = Blueprint("settlements", __name__)


def _event_of(settlement):
    return get("dispatch_events", settlement["dispatch_event_id"])


def _completed_dispatches(event_id):
    return [d for d in db.data["dispatches"].values()
            if d["dispatch_event_id"] == event_id and d["status"] == "COMPLETED"]


def _aggregator_of_dispatch(d):
    enr = get("enrollments", d["enrollment_id"])
    dev = get("devices", enr["device_id"]) if enr else None
    return dev["aggregator_id"] if dev else None


def _recompute_settlement(settlement, event):
    """Recompute per-dispatch net_payment_cents and settlement totals."""
    program = get("programs", event["program_id"])
    duration = event_duration_hours(event)
    eligible = _completed_dispatches(event["id"])
    for d in eligible:
        d["net_payment_cents"] = dispatch_line_payout(d, program, duration)
    total_delivered, net = settlement_totals(settlement, event, program, eligible)
    settlement["total_delivered_kwh"] = total_delivered
    settlement["net_payment_cents"] = net


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------
@bp_settlements.route("/dr/settlements", methods=["POST"])
def create_settlement():
    require(["ProgramOperator"])
    body = get_body()
    if body.get("dispatch_event_id") is not None:
        get_or_404("dispatch_events", body["dispatch_event_id"])
    dispatch_event_id = require_str(body, "dispatch_event_id")
    event = get("dispatch_events", dispatch_event_id)
    program = get("programs", event["program_id"])
    rec = insert("settlements", {
        "dispatch_event_id": dispatch_event_id,
        "method_snapshot": program["settlement_method"],
        "total_delivered_kwh": 0,
        "net_payment_cents": 0,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    return ok_object(rec, status=201)


@bp_settlements.route("/dr/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    require(ALL_ROLES)
    return ok_object(get_or_404("settlements", sid))


@bp_settlements.route("/dr/settlements/<sid>/submit", methods=["POST"])
def submit_settlement(sid):
    require(["ProgramOperator"])
    s = get_or_404("settlements", sid)
    if s["status"] not in ("DRAFT", "REVISED"):
        raise err("ERR_INVALID_STATE", "Settlement is not DRAFT or REVISED.")
    event = _event_of(s)
    if s["status"] == "DRAFT" and (event is None or event["status"] != "COMPLETED"):
        raise err("ERR_INVALID_STATE", "Event is not COMPLETED.")
    _recompute_settlement(s, event)
    s["status"] = "PENDING_APPROVAL"
    touch(s)
    return ok_object(s)


@bp_settlements.route("/dr/settlements/<sid>/approve", methods=["POST"])
def approve_settlement(sid):
    uid, _ = require(["ProgramOperator"])
    s = get_or_404("settlements", sid)
    if s["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE", "Settlement is not PENDING_APPROVAL.")
    event = _event_of(s)
    if uid == event["dispatched_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The operator who dispatched the event may not approve its settlement.")
    s["approved_by_user_id"] = uid
    s["status"] = "APPROVED"
    touch(s)
    # Cascade: one Payment per distinct aggregator among COMPLETED dispatches.
    eligible = _completed_dispatches(event["id"])
    by_agg = {}  # preserve encounter order
    for d in eligible:
        agg_id = _aggregator_of_dispatch(d)
        by_agg.setdefault(agg_id, 0)
        by_agg[agg_id] += d["net_payment_cents"] or 0
    for agg_id, amount in by_agg.items():
        insert("payments", {
            "settlement_id": s["id"],
            "aggregator_id": agg_id,
            "amount_cents": amount,
            "status": "ISSUED",
        })
    recompute_paid_balance(list(by_agg.keys()))
    event["status"] = "SETTLED"
    touch(event)
    return ok_object(s)


@bp_settlements.route("/dr/settlements/<sid>/dispute", methods=["POST"])
def dispute_settlement(sid):
    uid, _ = require(["Aggregator"])
    s = get_or_404("settlements", sid)
    event = _event_of(s)
    # ownership: acting aggregator holds at least one dispatch in the event
    owns = any(_aggregator_of_dispatch(d) == uid
               for d in db.data["dispatches"].values()
               if d["dispatch_event_id"] == event["id"])
    if not owns:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator has no dispatch in this event.")
    if s["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Settlement cannot be disputed from its current state.")
    was_approved = s["status"] == "APPROVED"
    s["status"] = "DISPUTED"
    touch(s)
    if was_approved:
        affected = set()
        for p in db.data["payments"].values():
            if p["settlement_id"] == sid and p["status"] == "ISSUED":
                p["status"] = "REVERSED"
                touch(p)
                affected.add(p["aggregator_id"])
        recompute_paid_balance(affected)
    return ok_object(s)


@bp_settlements.route("/dr/settlements/<sid>/revise", methods=["POST"])
def revise_settlement(sid):
    require(["ProgramOperator"])
    s = get_or_404("settlements", sid)
    if s["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Settlement is not DISPUTED.")
    event = _event_of(s)
    _recompute_settlement(s, event)
    s["status"] = "REVISED"
    touch(s)
    return ok_object(s)


@bp_settlements.route("/dr/settlements/<sid>/mark-paid", methods=["POST"])
def mark_paid(sid):
    require(["ProgramOperator"])
    s = get_or_404("settlements", sid)
    if s["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Settlement is not APPROVED.")
    s["status"] = "PAID"
    touch(s)
    for p in db.data["payments"].values():
        if p["settlement_id"] == sid and p["status"] == "ISSUED":
            p["status"] = "CLEARED"
            touch(p)
    return ok_object(s)


@bp_settlements.route("/dr/settlements/<sid>/payments", methods=["GET"])
def list_settlement_payments(sid):
    require(ALL_ROLES)
    get_or_404("settlements", sid)
    status = request.args.get("status")
    records = [p for p in db.data["payments"].values()
               if p["settlement_id"] == sid
               and (status is None or p["status"] == status)]
    return list_response(records)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@bp_settlements.route("/dr/payments/<pid>", methods=["GET"])
def get_payment(pid):
    require(ALL_ROLES)
    return ok_object(get_or_404("payments", pid))


@bp_settlements.route("/dr/payments", methods=["GET"])
def list_payments():
    require(ALL_ROLES)
    aggregator_id = request.args.get("aggregator_id")
    settlement_id = request.args.get("settlement_id")
    status = request.args.get("status")
    records = []
    for p in db.data["payments"].values():
        if aggregator_id is not None and p["aggregator_id"] != aggregator_id:
            continue
        if settlement_id is not None and p["settlement_id"] != settlement_id:
            continue
        if status is not None and p["status"] != status:
            continue
        records.append(p)
    return list_response(records)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10)
# ---------------------------------------------------------------------------
@bp_settlements.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["ProgramOperator"])
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        db.current_utc = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime.")
    return ok({}, status=200, response_type="object")
