"""Clock, property rooms, offense statutes, storage locations and custodians."""

from decimal import Decimal

from flask import Blueprint

import domain
import serializers as ser
import validate as v
from auth import ALL_ROLES, authorize
from envelope import created, fmt_dt, listed, ok, paginate
from errors import ApiError
from store import db, mark, new_entity, now, set_clock, sort_rows

bp = Blueprint("core", __name__)

PRM = ["PropertyRoomManager"]

LOCATION_CATEGORIES = ("GENERAL", "REFRIGERATED", "HIGH_VALUE_VAULT", "OVERSIZED_YARD")
PRESERVATION_CLASSES = (
    "STANDARD",
    "DRUG_SCHEDULE",
    "BIOLOGICAL_INDEFINITE",
    "HOMICIDE_PERMANENT",
)
CUSTODIAN_ROLE_TYPES = ("EVIDENCE_TECH", "INVESTIGATOR", "LAB_ANALYST", "AUDITOR")

REFRIGERATION_MIN_C = Decimal("-30.0")
REFRIGERATION_MAX_C = Decimal("30.0")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(PRM)
    data = v.body()
    instant = v.req_dt(data, "current_utc")
    previous = set_clock(instant)
    return ok({"current_utc": fmt_dt(instant), "previous_utc": fmt_dt(previous)})


# --------------------------------------------------------------------------
# property rooms
# --------------------------------------------------------------------------

@bp.post("/property-rooms")
def create_room():
    authorize(PRM)
    data = v.body()
    name = v.req_str(data, "name", min_len=1, max_len=120)
    agency_code = v.req_str(data, "agency_code", min_len=3, max_len=5, pattern=r"^[A-Z0-9]{3,5}$")
    for existing in db.rooms.values():
        if existing["agency_code"] == agency_code:
            raise ApiError("ERR_DUPLICATE_AGENCY_CODE")
    room = new_entity(
        "PropertyRoom",
        {
            "name": name,
            "agency_code": agency_code,
            "posture": "OPEN",
            "open_discrepancy_count": 0,
            "missing_high_risk_count": 0,
            "sealed_location_count": 0,
            "disposal_eligible_count": 0,
            "escrow_balance_cents": 0,
            "last_sweep_at": None,
        },
    )
    db.rooms[room["id"]] = room
    return created(ser.room(room))


@bp.get("/property-rooms/<room_id>")
def get_room(room_id):
    authorize(ALL_ROLES)
    room = domain.find(db.rooms, room_id, "ERR_PROPERTY_ROOM_NOT_FOUND")
    return ok(ser.room(room))


@bp.post("/property-rooms/<room_id>/daily-sweep")
def daily_sweep(room_id):
    authorize(PRM)
    room = domain.find(db.rooms, room_id, "ERR_PROPERTY_ROOM_NOT_FOUND")
    instant = now()

    # step 1 — overdue escorts
    for transfer in domain.transfers_of_room(room["id"]):
        if transfer["status"] == "RELEASED" and transfer["due_back_at"] <= instant:
            transfer["status"] = "OVERDUE"
            mark(transfer)

    items = domain.items_of_room(room["id"])
    item_ids = set(i["id"] for i in items)

    # step 2 — expire owner notices
    claims = sort_rows([c for c in db.claims.values() if c["evidence_item_id"] in item_ids])
    for claim in claims:
        if claim["status"] != "NOTICE_SENT" or claim["claim_deadline_at"] > instant:
            continue
        claim["status"] = "EXPIRED"
        mark(claim)
        item = db.items.get(claim["evidence_item_id"])
        if item is not None and item["disposition_state"] == "RETAINED":
            item["disposition_state"] = "UNCLAIMED_ELIGIBLE"
            mark(item)

    # step 3 — mature retention
    for item in items:
        domain.mature_if_due(item)

    # step 4 — re-derive every dependent figure
    domain.refresh_all_locations(room["id"])
    domain.refresh_room(room)
    room["last_sweep_at"] = instant
    mark(room)
    return ok(ser.room(room))


# --------------------------------------------------------------------------
# offense statutes
# --------------------------------------------------------------------------

@bp.post("/offense-statutes")
def create_statute():
    authorize(PRM)
    data = v.body()
    offense_code = v.req_str(data, "offense_code", min_len=1, max_len=16)
    description = v.req_str(data, "description")
    preservation_class = v.req_enum(data, "preservation_class", PRESERVATION_CLASSES)
    retention_days = v.req_int(data, "statutory_retention_days", minimum=0, maximum=36500)
    appeal_days = v.req_int(data, "appeal_window_days", minimum=0, maximum=3650)
    requires_order = v.req_bool(data, "destruction_requires_court_order")
    for existing in db.statutes.values():
        if existing["offense_code"] == offense_code:
            raise ApiError("ERR_DUPLICATE_OFFENSE_CODE")
    statute = new_entity(
        "OffenseStatute",
        {
            "offense_code": offense_code,
            "description": description,
            "preservation_class": preservation_class,
            "statutory_retention_days": retention_days,
            "appeal_window_days": appeal_days,
            "destruction_requires_court_order": requires_order,
        },
    )
    db.statutes[statute["id"]] = statute
    return created(ser.statute(statute))


@bp.get("/offense-statutes/<statute_id>")
def get_statute(statute_id):
    authorize(
        [
            "PropertyRoomManager",
            "EvidenceTechnician",
            "Investigator",
            "CourtClerk",
            "InternalAuditor",
        ]
    )
    statute = domain.find(db.statutes, statute_id, "ERR_OFFENSE_STATUTE_NOT_FOUND")
    return ok(ser.statute(statute))


# --------------------------------------------------------------------------
# storage locations
# --------------------------------------------------------------------------

LOCATION_READERS = ["PropertyRoomManager", "EvidenceTechnician", "InternalAuditor"]


@bp.post("/storage-locations")
def create_location():
    authorize(PRM)
    data = v.body()
    room_id = v.req_str(data, "property_room_id")
    code = v.req_str(data, "code", min_len=1, max_len=16)
    category = v.req_enum(data, "category", LOCATION_CATEGORIES)
    capacity = v.req_int(data, "capacity_slots", minimum=1, maximum=1000)
    if category == "REFRIGERATED":
        raw = v.req_number(data, "temperature_c")
        temperature = Decimal(str(raw))
        if temperature < REFRIGERATION_MIN_C or temperature > REFRIGERATION_MAX_C:
            v.bad("temperature_c must be between -30.0 and 30.0.")
    else:
        v.must_be_absent(data, "temperature_c", "unless category is REFRIGERATED")
        temperature = None
    dual = v.opt_bool(data, "requires_dual_signature", False)

    room = domain.find(db.rooms, room_id, "ERR_PROPERTY_ROOM_NOT_FOUND")
    domain.gate_locked_down(room)

    for existing in db.locations.values():
        if existing["property_room_id"] == room["id"] and existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_LOCATION_CODE")

    location = new_entity(
        "StorageLocation",
        {
            "property_room_id": room["id"],
            "code": code,
            "category": category,
            "capacity_slots": capacity,
            "occupied_slots": 0,
            "temperature_c": temperature,
            "requires_dual_signature": dual,
            "status": "OPEN",
            "sealed_by_audit_session_id": None,
        },
    )
    db.locations[location["id"]] = location
    return created(ser.location(location))


@bp.get("/storage-locations/<location_id>")
def get_location(location_id):
    authorize(LOCATION_READERS)
    location = domain.find(db.locations, location_id, "ERR_STORAGE_LOCATION_NOT_FOUND")
    return ok(ser.location(location))


@bp.get("/storage-locations")
def list_locations():
    authorize(LOCATION_READERS)
    rows = v.filter_rows(
        sort_rows(db.locations.values()),
        {
            "property_room_id": ("property_room_id", "str"),
            "category": ("category", "str"),
            "status": ("status", "str"),
            "sealed_by_audit_session_id": ("sealed_by_audit_session_id", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.location(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# custodians
# --------------------------------------------------------------------------

CUSTODIAN_READERS = [
    "PropertyRoomManager",
    "EvidenceTechnician",
    "Investigator",
    "LabAnalyst",
    "InternalAuditor",
]


@bp.post("/custodians")
def create_custodian():
    authorize(PRM)
    data = v.body()
    room_id = v.req_str(data, "property_room_id")
    badge = v.req_str(data, "badge_number", min_len=1, max_len=16)
    full_name = v.req_str(data, "full_name", min_len=1)
    role_type = v.req_enum(data, "role_type", CUSTODIAN_ROLE_TYPES)
    expires_at = v.req_dt(data, "certification_expires_at")

    room = domain.find(db.rooms, room_id, "ERR_PROPERTY_ROOM_NOT_FOUND")
    domain.gate_locked_down(room)

    for existing in db.custodians.values():
        if existing["property_room_id"] == room["id"] and existing["badge_number"] == badge:
            raise ApiError("ERR_DUPLICATE_BADGE_NUMBER")

    custodian = new_entity(
        "Custodian",
        {
            "property_room_id": room["id"],
            "badge_number": badge,
            "full_name": full_name,
            "role_type": role_type,
            "certification_expires_at": expires_at,
            "status": "ACTIVE",
            "suspension_reason": None,
            "open_escort_count": 0,
        },
    )
    db.custodians[custodian["id"]] = custodian
    return created(ser.custodian(custodian))


@bp.get("/custodians/<custodian_id>")
def get_custodian(custodian_id):
    authorize(CUSTODIAN_READERS)
    custodian = domain.find(db.custodians, custodian_id, "ERR_CUSTODIAN_NOT_FOUND")
    return ok(ser.custodian(custodian))


@bp.get("/custodians")
def list_custodians():
    authorize(CUSTODIAN_READERS)
    rows = v.filter_rows(
        sort_rows(db.custodians.values()),
        {
            "property_room_id": ("property_room_id", "str"),
            "role_type": ("role_type", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.custodian(r) for r in page], limit, offset, total)


@bp.post("/custodians/<custodian_id>/suspend")
def suspend_custodian(custodian_id):
    authorize(PRM)
    custodian = domain.find(db.custodians, custodian_id, "ERR_CUSTODIAN_NOT_FOUND")
    data = v.body()
    reason = v.req_str(data, "reason", min_len=1)
    # suspension stays available in a locked-down room (PRD 2.6, 2.11)
    if custodian["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTODIAN_SUSPENDED")
    custodian["status"] = "SUSPENDED"
    custodian["suspension_reason"] = reason
    mark(custodian)
    return ok(ser.custodian(custodian))
