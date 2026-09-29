"""Audit sessions, discrepancies and the chain of custody ledger."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
import serializers as ser
import validate as v
from auth import ALL_ROLES, authorize, require_self
from envelope import created, listed, ok, paginate
from errors import ApiError
from store import db, mark, new_entity, now, sort_rows

bp = Blueprint("audit", __name__)

PRM = ["PropertyRoomManager"]
AUDIT_READERS = ["PropertyRoomManager", "InternalAuditor", "EvidenceTechnician"]
RESOLUTIONS = ("FOUND", "WRITTEN_OFF")


# --------------------------------------------------------------------------
# audit sessions
# --------------------------------------------------------------------------

@bp.post("/audit-sessions")
def create_session():
    principal = authorize(["InternalAuditor"])
    data = v.body()
    require_self(principal, data, "auditor_id")

    location_id = v.req_str(data, "storage_location_id")
    auditor_id = v.req_str(data, "auditor_id")
    start_at = v.req_dt(data, "scheduled_start_at")
    end_at = v.req_dt(data, "scheduled_end_at")
    expected_version = v.req_int(data, "expected_storage_location_version")

    location = domain.find(db.locations, location_id, "ERR_STORAGE_LOCATION_NOT_FOUND")
    auditor = domain.find(db.custodians, auditor_id, "ERR_CUSTODIAN_NOT_FOUND")

    # audit scheduling stays available in a locked-down room (PRD 2.6)
    if location["version"] != expected_version:
        raise ApiError("ERR_STALE_STORAGE_LOCATION_VERSION")

    domain.gate_active(auditor)

    if end_at <= start_at:
        raise ApiError("ERR_INVALID_TRANSFER_WINDOW")

    buffer = calc.AUDIT_BUFFER_HOURS * 3600
    for existing in db.sessions.values():
        if existing["storage_location_id"] != location["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "IN_PROGRESS", "RECONCILED"):
            continue
        if start_at <= calc.add_seconds(existing["scheduled_end_at"], buffer) and existing[
            "scheduled_start_at"
        ] <= calc.add_seconds(end_at, buffer):
            raise ApiError("ERR_AUDIT_WINDOW_BUFFER")

    session = new_entity(
        "AuditSession",
        {
            "storage_location_id": location["id"],
            "auditor_id": auditor["id"],
            "scheduled_start_at": start_at,
            "scheduled_end_at": end_at,
            "status": "SCHEDULED",
            "started_at": None,
            "reconciled_at": None,
            "closed_at": None,
            "expected_evidence_item_ids": [],
            "expected_item_count": 0,
            "scanned_evidence_item_ids": [],
            "scanned_item_count": 0,
            "missing_count": 0,
            "misplaced_count": 0,
            "risk_index": Decimal("0.00"),
        },
    )
    db.sessions[session["id"]] = session
    mark(location)
    return created(ser.session(session))


@bp.get("/audit-sessions/<session_id>")
def get_session(session_id):
    authorize(AUDIT_READERS)
    session = domain.find(db.sessions, session_id, "ERR_AUDIT_SESSION_NOT_FOUND")
    return ok(ser.session(session))


@bp.get("/audit-sessions")
def list_sessions():
    authorize(AUDIT_READERS)
    rows = v.filter_rows(
        sort_rows(db.sessions.values()),
        {
            "storage_location_id": ("storage_location_id", "str"),
            "auditor_id": ("auditor_id", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.session(r) for r in page], limit, offset, total)


@bp.post("/audit-sessions/<session_id>/start")
def start_session(session_id):
    authorize(["InternalAuditor"])
    session = domain.find(db.sessions, session_id, "ERR_AUDIT_SESSION_NOT_FOUND")
    location = db.locations.get(session["storage_location_id"])
    room = domain.room_of_location(location)

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    if location["status"] != "OPEN":
        raise ApiError("ERR_LOCATION_SEALED")

    expected = [
        i["id"]
        for i in sort_rows(db.items.values())
        if i["storage_location_id"] == location["id"] and i["custody_state"] == "STORED"
    ]
    session["status"] = "IN_PROGRESS"
    session["started_at"] = now()
    session["expected_evidence_item_ids"] = expected
    session["expected_item_count"] = len(expected)
    mark(session)

    location["status"] = "SEALED_FOR_AUDIT"
    location["sealed_by_audit_session_id"] = session["id"]
    mark(location)

    domain.refresh_room(room)
    return ok(ser.session(session))


@bp.post("/audit-sessions/<session_id>/scan")
def scan_session(session_id):
    principal = authorize(["InternalAuditor"])
    session = domain.find(db.sessions, session_id, "ERR_AUDIT_SESSION_NOT_FOUND")
    data = v.body()
    barcode = v.req_str(data, "barcode", min_len=1)

    item = None
    for candidate in sort_rows(db.items.values()):
        if candidate["barcode"] == barcode:
            item = candidate
            break
    if item is None:
        raise ApiError("ERR_BARCODE_NOT_FOUND")

    location = db.locations.get(session["storage_location_id"])
    room = domain.room_of_location(location)

    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_AUDIT_STATE_INVALID")

    item_room = domain.room_of_item(item)
    if item_room is None or room is None or item_room["id"] != room["id"]:
        raise ApiError("ERR_BARCODE_FOREIGN_ROOM")

    session["scanned_evidence_item_ids"] = list(session["scanned_evidence_item_ids"]) + [
        item["id"]
    ]
    session["scanned_item_count"] = len(session["scanned_evidence_item_ids"])
    mark(session)

    domain.append_chain_event(
        item,
        "AUDIT_SCAN",
        principal.role,
        principal.custodian_id,
        None,
        "Barcode %s scanned during inventory audit." % barcode,
    )

    if item["storage_location_id"] != location["id"]:
        discrepancy = new_entity(
            "Discrepancy",
            {
                "evidence_item_id": item["id"],
                "audit_session_id": session["id"],
                "kind": "MISPLACED",
                "status": "OPEN",
                "weight_contribution": Decimal("0.00"),
                "resolution_note": None,
                "resolved_at": None,
            },
        )
        db.discrepancies[discrepancy["id"]] = discrepancy

    domain.refresh_session_risk(session)
    domain.refresh_room(room)
    return ok(ser.session(session))


@bp.post("/audit-sessions/<session_id>/reconcile")
def reconcile_session(session_id):
    authorize(["InternalAuditor"])
    session = domain.find(db.sessions, session_id, "ERR_AUDIT_SESSION_NOT_FOUND")
    location = db.locations.get(session["storage_location_id"])
    room = domain.room_of_location(location)

    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_AUDIT_STATE_INVALID")

    session["status"] = "RECONCILED"
    session["reconciled_at"] = now()
    mark(session)

    scanned = set(session["scanned_evidence_item_ids"])
    unscanned = [
        db.items[i]
        for i in session["expected_evidence_item_ids"]
        if i not in scanned and i in db.items
    ]
    for item in sort_rows(unscanned):
        if item["custody_state"] != "STORED":
            continue
        domain.raise_missing_discrepancy(item, session["id"], "SYSTEM", None)

    domain.refresh_session_risk(session)
    domain.refresh_room(room)
    return ok(ser.session(session))


@bp.post("/audit-sessions/<session_id>/close")
def close_session(session_id):
    authorize(["InternalAuditor", "PropertyRoomManager"])
    session = domain.find(db.sessions, session_id, "ERR_AUDIT_SESSION_NOT_FOUND")
    location = db.locations.get(session["storage_location_id"])
    room = domain.room_of_location(location)

    if session["status"] not in ("IN_PROGRESS", "RECONCILED"):
        raise ApiError("ERR_AUDIT_STATE_INVALID")
    for discrepancy in domain.discrepancies_of_session(session["id"]):
        if discrepancy["status"] in domain.OPEN_DISCREPANCY_STATUSES:
            raise ApiError("ERR_AUDIT_STATE_INVALID")

    session["status"] = "CLOSED"
    session["closed_at"] = now()
    mark(session)

    if location is not None and location["sealed_by_audit_session_id"] == session["id"]:
        location["status"] = "OPEN"
        location["sealed_by_audit_session_id"] = None
        mark(location)

    domain.refresh_room(room)
    return ok(ser.session(session))


# --------------------------------------------------------------------------
# discrepancies
# --------------------------------------------------------------------------

@bp.get("/discrepancies/<discrepancy_id>")
def get_discrepancy(discrepancy_id):
    authorize(AUDIT_READERS)
    row = domain.find(db.discrepancies, discrepancy_id, "ERR_DISCREPANCY_NOT_FOUND")
    return ok(ser.discrepancy(row))


@bp.get("/discrepancies")
def list_discrepancies():
    authorize(AUDIT_READERS)
    rows = v.filter_rows(
        sort_rows(db.discrepancies.values()),
        {
            "audit_session_id": ("audit_session_id", "str"),
            "evidence_item_id": ("evidence_item_id", "str"),
            "kind": ("kind", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.discrepancy(r) for r in page], limit, offset, total)


@bp.post("/discrepancies/<discrepancy_id>/investigate")
def investigate_discrepancy(discrepancy_id):
    authorize(PRM)
    discrepancy = domain.find(db.discrepancies, discrepancy_id, "ERR_DISCREPANCY_NOT_FOUND")
    if discrepancy["status"] != "OPEN":
        raise ApiError("ERR_DISCREPANCY_STATE_INVALID")
    discrepancy["status"] = "UNDER_INVESTIGATION"
    mark(discrepancy)
    return ok(ser.discrepancy(discrepancy))


@bp.post("/discrepancies/<discrepancy_id>/resolve")
def resolve_discrepancy(discrepancy_id):
    authorize(PRM)
    discrepancy = domain.find(db.discrepancies, discrepancy_id, "ERR_DISCREPANCY_NOT_FOUND")
    data = v.body()
    resolution = v.req_enum(data, "resolution", RESOLUTIONS)
    note = v.req_str(data, "resolution_note", min_len=1)

    item = db.items.get(discrepancy["evidence_item_id"])
    case = domain.case_of_item(item)
    room = domain.room_of_case(case)
    session = db.sessions.get(discrepancy["audit_session_id"]) if discrepancy[
        "audit_session_id"
    ] else None
    audited_location = db.locations.get(session["storage_location_id"]) if session else None
    current_location = domain.location_of_item(item)

    if discrepancy["status"] not in domain.OPEN_DISCREPANCY_STATUSES:
        raise ApiError("ERR_DISCREPANCY_STATE_INVALID")
    if discrepancy["kind"] == "MISSING" and item["custody_state"] != "MISSING":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")

    if resolution == "FOUND" and discrepancy["kind"] == "MISPLACED":
        if audited_location is None:
            raise ApiError("ERR_STORAGE_LOCATION_NOT_FOUND")
        if audited_location["category"] != item["required_storage_category"]:
            raise ApiError("ERR_STORAGE_CATEGORY_MISMATCH")

    if resolution == "WRITTEN_OFF" and discrepancy["kind"] != "MISSING":
        raise ApiError("ERR_DISCREPANCY_RESOLUTION_NOT_PERMITTED")

    if resolution == "FOUND":
        target = current_location if discrepancy["kind"] == "MISSING" else audited_location
        if target is not None and target["occupied_slots"] >= target["capacity_slots"]:
            raise ApiError("ERR_STORAGE_LOCATION_FULL")

    if resolution == "FOUND":
        discrepancy["status"] = "RESOLVED_FOUND"
        if discrepancy["kind"] == "MISSING":
            item["custody_state"] = "STORED"
            mark(item)
        else:
            previous = current_location
            item["storage_location_id"] = audited_location["id"]
            mark(item)
            domain.refresh_location(previous)
        domain.refresh_location(domain.location_of_item(item))
    else:
        discrepancy["status"] = "RESOLVED_WRITTEN_OFF"
        item["custody_state"] = "PURGED"
        item["disposition_state"] = "DISPOSED"
        mark(item)
        domain.refresh_location(current_location)
        domain.refresh_case(case)
        mark(case)

    discrepancy["resolution_note"] = note
    discrepancy["resolved_at"] = now()
    mark(discrepancy)

    domain.refresh_session_risk(session)
    domain.refresh_room(room)
    return ok(ser.discrepancy(discrepancy))


# --------------------------------------------------------------------------
# chain of custody
# --------------------------------------------------------------------------

@bp.get("/chain-events/<event_id>")
def get_chain_event(event_id):
    authorize(ALL_ROLES)
    event = domain.find(db.chain_events, event_id, "ERR_CHAIN_EVENT_NOT_FOUND")
    return ok(ser.chain_event(event))


@bp.get("/chain-events")
def list_chain_events():
    authorize(ALL_ROLES)
    rows = v.filter_rows(
        sort_rows(db.chain_events.values()),
        {
            "evidence_item_id": ("evidence_item_id", "str"),
            "actor_custodian_id": ("actor_custodian_id", "str"),
            "event_type": ("event_type", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.chain_event(r) for r in page], limit, offset, total)
