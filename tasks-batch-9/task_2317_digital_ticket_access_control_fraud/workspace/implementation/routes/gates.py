"""Gate endpoints (PRD 3.1)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc
from errors import ApiError
from middleware import auth, f_int, f_str, get_body, q
from response import ok
from services.domain import gates_of_event, get_or_404
from routes._common import filter_eq, paginated

bp = Blueprint("gates", __name__)

GATE_READERS = ("GateOperator", "SecurityInvestigator", "VenueAdmin")


@bp.route("/events/<event_id>/gates", methods=["POST"])
def create_gate(event_id):
    auth(("VenueAdmin",))
    body = get_body()
    gate_code = f_str(body, "gate_code", allow_empty=False)
    access_zone_id = f_str(body, "access_zone_id", allow_empty=False)
    throughput = f_int(body, "throughput_per_minute", minimum=1)
    lanes_open = f_int(body, "lanes_open", required=False, default=1, minimum=1)

    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    zone = get_or_404(db.zones, access_zone_id, "ERR_ZONE_NOT_FOUND")
    if zone["event_id"] != event_id:
        raise ApiError("ERR_CROSS_EVENT_REFERENCE")
    if event["status"] != "DRAFT":
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    for gate in gates_of_event(event_id):
        if gate["gate_code"] == gate_code:
            raise ApiError("ERR_DUPLICATE_CODE", "gate_code is already used in this event.")

    rec = base_record()
    rec["event_id"] = event_id
    rec["access_zone_id"] = access_zone_id
    rec["gate_code"] = gate_code
    rec["throughput_per_minute"] = throughput
    rec["lanes_open"] = lanes_open
    rec["status"] = "IDLE"
    rec["last_session_closed_at"] = None
    rec["admitted_scan_count"] = 0
    db.gates[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/gates/<gate_id>", methods=["GET"])
def get_gate(gate_id):
    auth(GATE_READERS)
    gate = get_or_404(db.gates, gate_id, "ERR_GATE_NOT_FOUND")
    return ok(public(gate))


@bp.route("/gates", methods=["GET"])
def list_gates():
    auth(GATE_READERS)
    rows = sort_created_asc(list(db.gates.values()))
    rows = filter_eq(rows, "event_id", q("event_id"))
    rows = filter_eq(rows, "access_zone_id", q("access_zone_id"))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)
