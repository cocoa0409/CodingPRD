"""ScanSession, live scanning and the offline cache (PRD 3.7)."""

from flask import Blueprint, request

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_dt, f_enum, f_int, f_str, get_body, invalid, q
from response import ok
from services import calc
from services.domain import (
    find_ticket_by_seed,
    get_or_404,
    open_denied_entry_incident,
    scan_events_of_session,
    sessions_of_gate,
)
from routes._common import filter_eq, paginated
from util import iso_clock, parse_dt

bp = Blueprint("sessions", __name__)

SESSION_READERS = ("GateOperator", "SecurityInvestigator", "VenueAdmin")

# result -> (error_id, incident category or None for operational denials)
DENIAL_TABLE = {
    "DENIED_COUNTERFEIT": ("ERR_COUNTERFEIT_BARCODE", "COUNTERFEIT"),
    "DENIED_STALE_BARCODE": ("ERR_BARCODE_EPOCH_INVALID", "COUNTERFEIT"),
    "DENIED_DEVICE_MISMATCH": ("ERR_DEVICE_MISMATCH", "DEVICE_MISMATCH"),
    "DENIED_DUPLICATE": ("ERR_DUPLICATE_SCAN", "DUPLICATE"),
    "DENIED_ZONE": ("ERR_ZONE_NOT_ENTITLED", "ZONE_VIOLATION"),
    "DENIED_REENTRY_LOCKOUT": ("ERR_REENTRY_LOCKOUT", None),
    "DENIED_VOIDED": ("ERR_TICKET_VOIDED", None),
}


# ----------------------------------------------------------------------
# Sessions
# ----------------------------------------------------------------------

@bp.route("/scan-sessions", methods=["POST"])
def open_session():
    auth(("GateOperator",))
    body = get_body()
    gate_id = f_str(body, "gate_id", allow_empty=False)
    operator_device_id = f_str(body, "operator_device_id", allow_empty=False)
    mode = f_enum(body, "mode", ("ONLINE", "OFFLINE_CAPABLE"))
    expected_gate_version = f_int(body, "expected_gate_version")

    gate = get_or_404(db.gates, gate_id, "ERR_GATE_NOT_FOUND")
    if expected_gate_version != gate["version"]:
        raise ApiError("ERR_STALE_GATE_VERSION")

    event = db.events[gate["event_id"]]
    if event["status"] not in ("DOORS_OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")

    for other in sessions_of_gate(gate_id):
        upper = other["_closed_dt"]
        if other["_opened_dt"] <= db.clock and (upper is None or db.clock < upper):
            raise ApiError("ERR_GATE_SESSION_OVERLAP")

    rec = base_record()
    rec["gate_id"] = gate_id
    rec["operator_device_id"] = operator_device_id
    rec["mode"] = mode
    rec["status"] = "OPEN"
    rec["opened_at"] = iso_clock(db.clock)
    rec["closed_at"] = None
    rec["online_scan_count"] = 0
    rec["offline_uploaded_count"] = 0
    rec["duplicate_suppressed_count"] = 0
    rec["_opened_dt"] = db.clock
    rec["_closed_dt"] = None
    rec["_event_id"] = event["id"]
    rec["_dedupe_keys"] = set()
    db.sessions[rec["id"]] = rec

    gate["status"] = "SCANNING"
    touch(gate)
    return ok(public(rec), 201)


@bp.route("/scan-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    auth(SESSION_READERS)
    session = get_or_404(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return ok(public(session))


@bp.route("/scan-sessions", methods=["GET"])
def list_sessions():
    auth(SESSION_READERS)
    rows = sort_created_asc(list(db.sessions.values()))
    rows = filter_eq(rows, "gate_id", q("gate_id"))
    rows = filter_eq(rows, "status", q("status"))
    rows = filter_eq(rows, "mode", q("mode"))
    return paginated(rows)


@bp.route("/scan-sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    auth(("GateOperator",))
    session = get_or_404(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] not in ("OPEN", "SYNCING"):
        raise ApiError("ERR_INVALID_STATE", "The session is already CLOSED.")

    closed_at = iso_clock(db.clock)
    session["status"] = "CLOSED"
    session["closed_at"] = closed_at
    session["_closed_dt"] = db.clock
    touch(session)

    gate = db.gates[session["gate_id"]]
    gate["status"] = "IDLE"
    gate["last_session_closed_at"] = closed_at
    touch(gate)
    return ok(public(session))


# ----------------------------------------------------------------------
# Scan adjudication
# ----------------------------------------------------------------------

def _persist_scan(session, event, gate, ticket, presented, fingerprint, direction,
                  dedupe_key, scanned_raw, scanned_dt, source, result, denied_reason_code):
    scan = base_record(versioned=False)
    scan["scan_session_id"] = session["id"]
    scan["ticket_id"] = ticket["id"] if ticket is not None else None
    scan["presented_barcode"] = presented
    scan["device_fingerprint"] = fingerprint
    scan["direction"] = direction
    scan["scanned_at"] = scanned_raw
    scan["recorded_at"] = iso_clock(db.clock)
    scan["source"] = source
    scan["result"] = result
    scan["dedupe_key"] = dedupe_key
    scan["denied_reason_code"] = denied_reason_code
    scan["_event_id"] = event["id"]
    scan["_gate_id"] = gate["id"]
    scan["_scanned_dt"] = scanned_dt
    db.scan_events[scan["id"]] = scan

    session["_dedupe_keys"].add(dedupe_key)
    if source == "ONLINE":
        session["online_scan_count"] += 1
    else:
        session["offline_uploaded_count"] += 1
    if result == "DENIED_DUPLICATE":
        session["duplicate_suppressed_count"] += 1
    return scan


def _apply_effects(scan, session, event, gate, zone, ticket, result, live):
    """Counter and status movements for one adjudicated scan."""
    if result == "ADMITTED":
        ticket["admission_status"] = "INSIDE"
        ticket["last_admitted_at"] = scan["recorded_at"]
        ticket["_last_admitted_dt"] = db.clock
        ticket["admitted_scan_count"] += 1
        touch(ticket)
        gate["admitted_scan_count"] += 1
        if live:
            zone["occupancy_count"] += 1
            touch(zone)
            event["live_occupancy"] += 1
            if event["live_occupancy"] > event["peak_live_occupancy"]:
                event["peak_live_occupancy"] = event["live_occupancy"]
            touch(event)
        return

    if result == "EXIT_RECORDED":
        ticket["admission_status"] = "EXITED"
        ticket["last_exited_at"] = scan["recorded_at"]
        ticket["_last_exited_dt"] = db.clock
        touch(ticket)
        if live:
            zone["occupancy_count"] = max(zone["occupancy_count"] - 1, 0)
            touch(zone)
            event["live_occupancy"] = max(event["live_occupancy"] - 1, 0)
            touch(event)
        return

    # Denials: only the declared presence transitions move admission_status.
    if ticket is None:
        return
    if result == "DENIED_DUPLICATE" and ticket["admission_status"] == "INSIDE":
        ticket["admission_status"] = "DENIED_FLAGGED"
        touch(ticket)
    elif result in ("DENIED_DEVICE_MISMATCH", "DENIED_ZONE", "DENIED_STALE_BARCODE") \
            and ticket["admission_status"] == "NOT_ADMITTED":
        ticket["admission_status"] = "DENIED_FLAGGED"
        touch(ticket)


def _adjudicate(event, gate, zone, ticket, same_event, epoch_part, epoch_reference,
                fingerprint, direction, live):
    """Returns the adjudicated result string. Rules 20-27 of PRD 2.12."""
    epoch_value = calc.parse_epoch_part(epoch_part)
    if not same_event or epoch_value is None:
        return "DENIED_COUNTERFEIT"
    if not live and ticket["lifecycle_status"] == "VOIDED":
        # DENIED_VOIDED is a result only the offline path can produce.
        return "DENIED_VOIDED"
    now_epoch = calc.epoch_index(event["_anchor_dt"], epoch_reference)
    if not calc.epoch_accepted(epoch_value, now_epoch):
        return "DENIED_STALE_BARCODE"
    if ticket["device_binding_status"] != "BOUND" \
            or ticket["bound_device_fingerprint"] != fingerprint:
        return "DENIED_DEVICE_MISMATCH"
    if direction == "IN" and ticket["admission_status"] == "INSIDE":
        return "DENIED_DUPLICATE"
    if live and direction == "IN" and calc.reentry_locked_out(ticket["_last_exited_dt"], db.clock):
        return "DENIED_REENTRY_LOCKOUT"
    if gate["access_zone_id"] != ticket["access_zone_id"]:
        return "DENIED_ZONE"
    if zone["required_entitlement_level"] == "BACK_OF_HOUSE" \
            and ticket["ticket_type"] != "CREDENTIAL":
        return "DENIED_ZONE"
    if live and direction == "IN":
        if zone["occupancy_count"] + 1 > zone["fire_code_capacity"]:
            return "DENIED_CAPACITY_ZONE"
        if event["live_occupancy"] + 1 > event["fire_code_capacity"]:
            return "DENIED_CAPACITY_EVENT"
    if direction == "OUT":
        if ticket["admission_status"] != "INSIDE":
            return "NOT_INSIDE"
        return "EXIT_RECORDED"
    return "ADMITTED"


@bp.route("/scan-sessions/<session_id>/scan-events", methods=["POST"])
def record_scan(session_id):
    user_id, role = auth(("GateOperator",))
    body = get_body()
    presented = f_str(body, "presented_barcode", allow_empty=False)
    fingerprint = f_str(body, "device_fingerprint", allow_empty=False)
    direction = f_enum(body, "direction", ("IN", "OUT"))
    dedupe_key = f_str(body, "dedupe_key", allow_empty=False)
    scanned_raw, scanned_dt = f_dt(body, "scanned_at", required=False)

    session = get_or_404(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    gate = db.gates[session["gate_id"]]
    event = db.events[gate["event_id"]]
    zone = db.zones[gate["access_zone_id"]]

    seed_part, epoch_part = calc.split_barcode(presented)
    resolved = find_ticket_by_seed(seed_part)
    same_event = resolved is not None and resolved["event_id"] == event["id"]
    ticket = resolved if same_event else None

    # Rule 10: a live scan of a VOIDED ticket persists nothing at all.
    if same_event and resolved["lifecycle_status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED")
    # Rule 11 sits above rule 15 on purpose.
    if gate["status"] != "SCANNING":
        raise ApiError("ERR_GATE_NOT_SCANNING")
    # Rule 13.
    if event["status"] not in ("DOORS_OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    # Rule 15.
    if session["status"] != "OPEN":
        raise ApiError("ERR_SESSION_NOT_OPEN")
    # Rule 19.
    if dedupe_key in session["_dedupe_keys"]:
        raise ApiError("ERR_DUPLICATE_DEDUPE_KEY")

    result = _adjudicate(
        event, gate, zone, ticket, same_event, epoch_part, db.clock,
        fingerprint, direction, live=True,
    )
    if result == "NOT_INSIDE":
        raise ApiError("ERR_INVALID_STATE", "An exit scan requires the ticket to be INSIDE.")

    error_id = None
    category = None
    if result == "DENIED_CAPACITY_ZONE":
        result, error_id = "DENIED_CAPACITY", "ERR_ZONE_CAPACITY_FULL"
    elif result == "DENIED_CAPACITY_EVENT":
        result, error_id = "DENIED_CAPACITY", "ERR_EVENT_FIRE_CODE_FULL"
    elif result in DENIAL_TABLE:
        error_id, category = DENIAL_TABLE[result]

    scan = _persist_scan(
        session, event, gate, ticket, presented, fingerprint, direction, dedupe_key,
        scanned_raw if scanned_raw is not None else iso_clock(db.clock),
        scanned_dt if scanned_dt is not None else db.clock,
        "ONLINE", result, error_id,
    )
    _apply_effects(scan, session, event, gate, zone, ticket, result, live=True)

    if category is not None:
        open_denied_entry_incident(scan["id"], ticket, category, event["id"], role, user_id)
    if error_id is not None:
        raise ApiError(error_id)
    return ok(public(scan), 201)


@bp.route("/scan-sessions/<session_id>/offline-batch", methods=["POST"])
def offline_batch(session_id):
    user_id, role = auth(("GateOperator",))
    body = get_body()
    scans = body.get("scans")
    if not isinstance(scans, list) or not scans:
        invalid("'scans' must be a non-empty array of scan objects.")
    items = []
    for index, raw in enumerate(scans):
        if not isinstance(raw, dict):
            invalid("Each element of 'scans' must be an object.")
        item = {
            "presented_barcode": f_str(raw, "presented_barcode", allow_empty=False),
            "device_fingerprint": f_str(raw, "device_fingerprint", allow_empty=False),
            "direction": f_enum(raw, "direction", ("IN", "OUT")),
            "dedupe_key": f_str(raw, "dedupe_key", allow_empty=False),
            "index": index,
        }
        scanned_raw, scanned_dt = f_dt(raw, "scanned_at")
        item["scanned_raw"] = scanned_raw
        item["scanned_dt"] = scanned_dt
        items.append(item)

    session = get_or_404(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    gate = db.gates[session["gate_id"]]
    event = db.events[gate["event_id"]]
    zone = db.zones[gate["access_zone_id"]]

    # Rule 9: OPEN -> SYNCING is the only declared upload transition.
    if session["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN session may take an offline upload.")
    if gate["status"] != "SCANNING":
        raise ApiError("ERR_GATE_NOT_SCANNING")
    if session["mode"] != "OFFLINE_CAPABLE":
        raise ApiError("ERR_SESSION_NOT_OFFLINE_CAPABLE")
    if event["status"] not in ("DOORS_OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")

    items.sort(key=lambda i: (i["scanned_dt"], i["index"]))

    accepted_count = 0
    duplicate_count = 0
    denied_count = 0
    scan_event_ids = []

    for item in items:
        seed_part, epoch_part = calc.split_barcode(item["presented_barcode"])
        resolved = find_ticket_by_seed(seed_part)
        same_event = resolved is not None and resolved["event_id"] == event["id"]
        ticket = resolved if same_event else None

        result = _adjudicate(
            event, gate, zone, ticket, same_event, epoch_part, item["scanned_dt"],
            item["device_fingerprint"], item["direction"], live=False,
        )
        if result == "NOT_INSIDE":
            # Best-effort: a cached exit is recorded even without a live entry.
            result = "EXIT_RECORDED"

        error_id, category = DENIAL_TABLE.get(result, (None, None))
        scan = _persist_scan(
            session, event, gate, ticket, item["presented_barcode"], item["device_fingerprint"],
            item["direction"], item["dedupe_key"], item["scanned_raw"], item["scanned_dt"],
            "OFFLINE_BATCH", result, error_id,
        )
        _apply_effects(scan, session, event, gate, zone, ticket, result, live=False)
        if category is not None:
            open_denied_entry_incident(scan["id"], ticket, category, event["id"], role, user_id)

        scan_event_ids.append(scan["id"])
        if result in ("ADMITTED", "EXIT_RECORDED"):
            accepted_count += 1
        else:
            denied_count += 1
            if result == "DENIED_DUPLICATE":
                duplicate_count += 1

    session["status"] = "SYNCING"
    touch(session)

    return ok({
        "accepted_count": accepted_count,
        "duplicate_suppressed_count": duplicate_count,
        "denied_count": denied_count,
        "scan_event_ids": scan_event_ids,
    })


# ----------------------------------------------------------------------
# ScanEvent reads
# ----------------------------------------------------------------------

@bp.route("/scan-events/<scan_event_id>", methods=["GET"])
def get_scan_event(scan_event_id):
    auth(SESSION_READERS)
    scan = get_or_404(db.scan_events, scan_event_id, "ERR_SCAN_EVENT_NOT_FOUND")
    return ok(public(scan))


@bp.route("/scan-events", methods=["GET"])
def list_scan_events():
    auth(SESSION_READERS)
    rows = list(db.scan_events.values())
    rows = filter_eq(rows, "scan_session_id", q("scan_session_id"))
    rows = filter_eq(rows, "ticket_id", q("ticket_id"))
    rows = filter_eq(rows, "result", q("result"))
    rows = filter_eq(rows, "source", q("source"))
    rows = filter_eq(rows, "direction", q("direction"))
    # recorded_at ASC, tie-break created_at ASC.
    rows.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))
    return paginated(rows)
