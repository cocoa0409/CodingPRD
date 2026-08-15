"""SamplingEvent + ChainOfCustody endpoints."""

import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_OUTFALL_NOT_FOUND,
    ERR_SAMPLE_NOT_FOUND,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_OUTFALL_INACTIVE,
    ERR_NO_ACTIVE_LIMIT,
    ERR_SAMPLE_NOT_SCHEDULED,
    ERR_COLLECTION_WINDOW_CLOSED,
    ERR_CUSTODY_OUT_OF_ORDER,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso, check_enum
from services.core import (
    base_entity,
    ledger_entity,
    touch,
    append_audit,
    serialize_sampling_event,
    serialize_custody_record,
    paginate,
    PARAMETER_CODES,
    CUSTODY_EVENT_TYPES,
)

bp = Blueprint("sampling", __name__)


@bp.route("/npdes/sampling-events", methods=["POST"])
def create_sampling_event():
    user_id, role = require_roles(["FieldSampler"])
    body = get_body()
    require_fields(body, ["outfall_id", "parameter_code", "scheduled_for"])
    outfall = db.outfalls.get(body["outfall_id"])
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")
    check_enum(body["parameter_code"], PARAMETER_CODES, "parameter_code")
    scheduled_for = parse_iso(body["scheduled_for"], "scheduled_for")

    window = body.get("collection_window_hours", 24)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1 or window > 168:
        raise err(ERR_INVALID_REQUEST, 400, "collection_window_hours must be an integer in 1..168")

    # Cross-entity gates in ladder order: permit ACTIVE, outfall ACTIVE, covering limit
    permit = db.permits.get(outfall["permit_id"])
    if permit is None or permit["status"] != "ACTIVE":
        raise err(ERR_PERMIT_NOT_ACTIVE, 409, "Permit is not ACTIVE")
    if outfall["status"] != "ACTIVE":
        raise err(ERR_OUTFALL_INACTIVE, 409, "Outfall is not ACTIVE")
    covering = any(
        l
        for l in db.effluent_limits.values()
        if l["outfall_id"] == outfall["id"]
        and l["status"] == "ACTIVE"
        and l["parameter_code"] == body["parameter_code"]
        and l["effective_from"] <= scheduled_for
        and (l["effective_to"] is None or scheduled_for < l["effective_to"])
    )
    if not covering:
        raise err(ERR_NO_ACTIVE_LIMIT, 409, "No ACTIVE effluent limit covers this parameter at scheduled_for")

    ev = base_entity("SamplingEvent")
    ev["id"] = str(uuid.uuid4())
    ev.update(
        {
            "outfall_id": outfall["id"],
            "parameter_code": body["parameter_code"],
            "scheduled_for": scheduled_for,
            "collection_window_hours": window,
            "schedule_status": "SCHEDULED",
            "custody_status": "NOT_SEALED",
            "collected_at": None,
            "collected_by_user_id": None,
        }
    )
    db.sampling_events[ev["id"]] = ev
    db.custody_seq[ev["id"]] = 1
    append_audit("SamplingEvent", ev["id"], "SAMPLE_SCHEDULED", user_id, role)
    return success(serialize_sampling_event(ev), 201)


@bp.route("/npdes/sampling-events", methods=["GET"])
def list_sampling_events():
    require_roles(["Any"])
    items = list(db.sampling_events.values())
    outfall_id = request.args.get("outfall_id")
    if outfall_id:
        items = [e for e in items if e["outfall_id"] == outfall_id]
    schedule_status = request.args.get("schedule_status")
    if schedule_status:
        items = [e for e in items if e["schedule_status"] == schedule_status]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_sampling_event(e) for e in page], total, limit, offset)


@bp.route("/npdes/sampling-events/<sid>", methods=["GET"])
def get_sampling_event(sid):
    require_roles(["Any"])
    ev = db.sampling_events.get(sid)
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    return success(serialize_sampling_event(ev), 200)


@bp.route("/npdes/sampling-events/<sid>/collect", methods=["POST"])
def collect_sampling_event(sid):
    user_id, role = require_roles(["FieldSampler"])
    ev = db.sampling_events.get(sid)
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    if ev["schedule_status"] != "SCHEDULED":
        raise err(ERR_SAMPLE_NOT_SCHEDULED, 409, "Sampling event is not SCHEDULED")

    now = db.clock.now()
    window = timedelta(hours=ev["collection_window_hours"])
    if not (ev["scheduled_for"] - window <= now <= ev["scheduled_for"] + window):
        raise err(ERR_COLLECTION_WINDOW_CLOSED, 422, "Clock is outside the collection window")

    outfall = db.outfalls.get(ev["outfall_id"])
    if outfall is None or outfall["status"] != "ACTIVE":
        raise err(ERR_OUTFALL_INACTIVE, 409, "Outfall is not ACTIVE")

    ev["collected_at"] = now
    ev["collected_by_user_id"] = user_id
    ev["schedule_status"] = "COLLECTED"
    ev["custody_status"] = "SEALED"
    touch(ev)

    # Auto-append the SEAL chain-of-custody record (sequence_index 1)
    rec = ledger_entity()
    rec["id"] = str(uuid.uuid4())
    rec.update(
        {
            "sampling_event_id": ev["id"],
            "event_type": "SEAL",
            "event_at": now,
            "from_party": None,
            "to_party": None,
            "note": None,
            "sequence_index": db.custody_seq[ev["id"]],
            "recorded_by_user_id": user_id,
        }
    )
    db.custody_records[rec["id"]] = rec
    db.custody_seq[ev["id"]] += 1

    append_audit("SamplingEvent", ev["id"], "SAMPLE_COLLECTED", user_id, role)
    return success(serialize_sampling_event(ev), 200)


@bp.route("/npdes/sampling-events/<sid>/cancel", methods=["POST"])
def cancel_sampling_event(sid):
    user_id, role = require_roles(["FieldSampler"])
    ev = db.sampling_events.get(sid)
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    if ev["schedule_status"] != "SCHEDULED":
        raise err(ERR_SAMPLE_NOT_SCHEDULED, 409, "Sampling event is not SCHEDULED")
    ev["schedule_status"] = "CANCELLED"
    touch(ev)
    append_audit("SamplingEvent", ev["id"], "SAMPLE_CANCELLED", user_id, role)
    return success(serialize_sampling_event(ev), 200)


_CUSTODY_NEXT = {
    "TRANSFER": ("SEALED", "IN_TRANSIT"),
    "RECEIVE_LAB": ("IN_TRANSIT", "LAB_RECEIVED"),
    "ANALYSIS_START": ("LAB_RECEIVED", "ANALYZED"),
}


@bp.route("/npdes/sampling-events/<sid>/custody-events", methods=["POST"])
def append_custody_event(sid):
    user_id, role = require_roles(["FieldSampler", "LabAnalyst"])
    ev = db.sampling_events.get(sid)
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    body = get_body()
    require_fields(body, ["event_type", "event_at"])
    check_enum(body["event_type"], CUSTODY_EVENT_TYPES, "event_type")
    event_type = body["event_type"]
    event_at = parse_iso(body["event_at"], "event_at")

    from_party = body.get("from_party")
    to_party = body.get("to_party")
    if event_type in ("TRANSFER", "RECEIVE_LAB"):
        if from_party is None or to_party is None:
            raise err(ERR_INVALID_REQUEST, 400, f"from_party and to_party are required for {event_type}")

    # Custody machine: only one event type accepted per position.
    # SEAL as an explicit event type is never accepted from any current state
    # (the SEAL record is auto-appended at collect).
    expected = _CUSTODY_NEXT.get(event_type)
    if expected is None or ev["custody_status"] != expected[0]:
        raise err(
            ERR_CUSTODY_OUT_OF_ORDER,
            409,
            f"Cannot append {event_type} while custody_status is {ev['custody_status']}",
        )

    rec = ledger_entity()
    rec["id"] = str(uuid.uuid4())
    rec.update(
        {
            "sampling_event_id": ev["id"],
            "event_type": event_type,
            "event_at": event_at,
            "from_party": from_party,
            "to_party": to_party,
            "note": body.get("note"),
            "sequence_index": db.custody_seq[ev["id"]],
            "recorded_by_user_id": user_id,
        }
    )
    db.custody_records[rec["id"]] = rec
    db.custody_seq[ev["id"]] += 1

    ev["custody_status"] = expected[1]
    touch(ev)
    append_audit("SamplingEvent", ev["id"], "CUSTODY_APPENDED", user_id, role)
    return success(serialize_custody_record(rec), 201)


@bp.route("/npdes/sampling-events/<sid>/custody-events", methods=["GET"])
def list_custody_events(sid):
    require_roles(["Any"])
    ev = db.sampling_events.get(sid)
    if ev is None:
        raise err(ERR_SAMPLE_NOT_FOUND, 404, "SamplingEvent not found")
    items = [r for r in db.custody_records.values() if r["sampling_event_id"] == sid]
    items.sort(key=lambda r: r["sequence_index"])
    # Custody chain is ordered by sequence_index; still envelope-paginated
    from errors import ERR_INVALID_REQUEST as _EIR  # noqa
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else 10
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw not in (None, "") else 0
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    return list_success([serialize_custody_record(r) for r in page], total, limit, offset)
