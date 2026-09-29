"""Cases, evidence items and retention determinations."""

from flask import Blueprint

import calc
import domain
import serializers as ser
import validate as v
from auth import ALL_ROLES, authorize
from envelope import created, listed, ok, paginate
from errors import ApiError
from store import db, mark, new_entity, now, sort_rows

bp = Blueprint("cases", __name__)

PRM = ["PropertyRoomManager"]
CASE_READERS = [
    "PropertyRoomManager",
    "EvidenceTechnician",
    "Investigator",
    "CourtClerk",
    "InternalAuditor",
]
DETERMINATION_READERS = [
    "PropertyRoomManager",
    "EvidenceTechnician",
    "CourtClerk",
    "InternalAuditor",
]

ITEM_CATEGORIES = ("GENERAL", "BIOLOGICAL", "CURRENCY", "FIREARM", "NARCOTICS", "OVERSIZED")
PACKAGING_TYPES = (
    "SEALED_ENVELOPE",
    "PAPER_BAG",
    "RIGID_BOX",
    "SHARPS_TUBE",
    "PALLET_WRAP",
    "CHAIN_TAG_ONLY",
)
RETENTION_BASES = ("PRELIMINARY", "FINAL")
CASE_NUMBER_PATTERN = r"^\d{2}-\d{5}$"


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------

@bp.post("/cases")
def create_case():
    authorize(["PropertyRoomManager", "EvidenceTechnician"])
    data = v.body()
    room_id = v.req_str(data, "property_room_id")
    case_number = v.req_str(data, "case_number", pattern=CASE_NUMBER_PATTERN)
    statute_id = v.req_str(data, "offense_statute_id")

    room = domain.find(db.rooms, room_id, "ERR_PROPERTY_ROOM_NOT_FOUND")
    statute = domain.find(db.statutes, statute_id, "ERR_OFFENSE_STATUTE_NOT_FOUND")
    domain.gate_locked_down(room)

    for existing in db.cases.values():
        if existing["property_room_id"] == room["id"] and existing["case_number"] == case_number:
            raise ApiError("ERR_DUPLICATE_CASE_NUMBER")

    case = new_entity(
        "Case",
        {
            "property_room_id": room["id"],
            "offense_statute_id": statute["id"],
            "case_number": case_number,
            "status": "OPEN",
            "charged_at": None,
            "adjudicated_at": None,
            "appeal_opened_at": None,
            "closed_at": None,
            "item_count": 0,
            "undisposed_item_count": 0,
        },
    )
    db.cases[case["id"]] = case
    return created(ser.case(case))


@bp.get("/cases/<case_id>")
def get_case(case_id):
    authorize(CASE_READERS)
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    return ok(ser.case(case))


@bp.get("/cases")
def list_cases():
    authorize(CASE_READERS)
    rows = v.filter_rows(
        sort_rows(db.cases.values()),
        {
            "property_room_id": ("property_room_id", "str"),
            "offense_statute_id": ("offense_statute_id", "str"),
            "status": ("status", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.case(r) for r in page], limit, offset, total)


@bp.post("/cases/<case_id>/charge")
def charge_case(case_id):
    authorize(["Investigator", "PropertyRoomManager"])
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    domain.gate_locked_down(domain.room_of_case(case))
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_STATE_INVALID")
    case["status"] = "CHARGED"
    case["charged_at"] = now()
    mark(case)
    return ok(ser.case(case))


@bp.post("/cases/<case_id>/adjudicate")
def adjudicate_case(case_id):
    authorize(["CourtClerk", "PropertyRoomManager"])
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    room = domain.room_of_case(case)
    domain.gate_locked_down(room)
    if case["status"] != "CHARGED":
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "ADJUDICATED"
    case["adjudicated_at"] = now()
    mark(case)

    for item in domain.items_of_case(case["id"]):
        domain.create_determination(item, "FINAL", "SYSTEM", None)
        domain.mature_if_due(item)

    domain.refresh_room(room)
    return ok(ser.case(case))


@bp.post("/cases/<case_id>/appeal")
def appeal_case(case_id):
    authorize(["CourtClerk"])
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    room = domain.room_of_case(case)
    domain.gate_locked_down(room)
    if case["status"] != "ADJUDICATED":
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "APPEAL_PENDING"
    case["appeal_opened_at"] = now()
    mark(case)

    for item in domain.items_of_case(case["id"]):
        if item["disposition_state"] == "DISPOSED":
            continue
        item["disposition_state"] = "COURT_HOLD"
        mark(item)
        domain.create_determination(item, "FINAL", "SYSTEM", None)

    domain.refresh_room(room)
    return ok(ser.case(case))


@bp.post("/cases/<case_id>/resolve-appeal")
def resolve_appeal(case_id):
    authorize(["CourtClerk"])
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    room = domain.room_of_case(case)
    domain.gate_locked_down(room)
    if case["status"] != "APPEAL_PENDING":
        raise ApiError("ERR_CASE_STATE_INVALID")

    case["status"] = "ADJUDICATED"
    case["adjudicated_at"] = now()
    case["appeal_opened_at"] = None
    mark(case)

    for item in domain.items_of_case(case["id"]):
        if item["disposition_state"] == "DISPOSED":
            continue
        item["disposition_state"] = "RETAINED"
        mark(item)
        domain.create_determination(item, "FINAL", "SYSTEM", None)
        domain.mature_if_due(item)

    domain.refresh_room(room)
    return ok(ser.case(case))


@bp.post("/cases/<case_id>/close")
def close_case(case_id):
    authorize(PRM)
    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    domain.gate_locked_down(domain.room_of_case(case))
    if case["status"] != "ADJUDICATED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    if case["undisposed_item_count"] != 0:
        raise ApiError("ERR_CASE_HAS_UNDISPOSED_ITEMS")
    case["status"] = "CLOSED"
    case["closed_at"] = now()
    mark(case)
    return ok(ser.case(case))


# --------------------------------------------------------------------------
# evidence items
# --------------------------------------------------------------------------

@bp.post("/evidence-items")
def create_item():
    principal = authorize(["EvidenceTechnician"])
    data = v.body()
    case_id = v.req_str(data, "case_id")
    description = v.req_str(data, "item_description", min_len=1)
    category = v.req_enum(data, "category", ITEM_CATEGORIES)
    packaging = v.req_enum(data, "packaging_type", PACKAGING_TYPES)
    value_cents = v.req_int(data, "appraised_value_cents", minimum=0, maximum=100000000)
    seized_at = v.req_dt(data, "seized_at")
    is_found = v.opt_bool(data, "is_found_property", False)

    case = domain.find(db.cases, case_id, "ERR_CASE_NOT_FOUND")
    room = domain.room_of_case(case)
    domain.gate_locked_down(room)

    if not calc.packaging_permitted(category, packaging):
        raise ApiError("ERR_PACKAGING_NOT_PERMITTED")

    sequence = len([i for i in db.items.values() if i["case_id"] == case["id"]]) + 1
    barcode = calc.barcode(room["agency_code"], case["case_number"], sequence)

    item = new_entity(
        "EvidenceItem",
        {
            "case_id": case["id"],
            "item_description": description,
            "category": category,
            "packaging_type": packaging,
            "appraised_value_cents": value_cents,
            "is_found_property": is_found,
            "seized_at": seized_at,
            "item_sequence": sequence,
            "barcode": barcode,
            "intake_at": now(),
            "required_storage_category": calc.required_storage_category(category, value_cents),
            "storage_location_id": None,
            "custody_state": "LOGGED",
            "disposition_state": "RETAINED",
            "current_holder_id": None,
            "retention_release_at": None,
            "retention_basis": None,
            "open_transfer_count": 0,
        },
    )
    db.items[item["id"]] = item

    # the preliminary determination writes retention onto the item; the single
    # chain entry produced by intake is the INTAKE line itself (PRD 3.2)
    domain.create_determination(
        item, "PRELIMINARY", principal.role, principal.custodian_id, append_event=False
    )
    domain.append_chain_event(
        item,
        "INTAKE",
        principal.role,
        principal.custodian_id,
        None,
        "Item logged into the property room as %s." % barcode,
    )
    domain.refresh_case(case)
    mark(case)
    return created(ser.item(item))


@bp.get("/evidence-items/<item_id>")
def get_item(item_id):
    authorize(ALL_ROLES)
    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    return ok(ser.item(item))


@bp.get("/evidence-items")
def list_items():
    authorize(ALL_ROLES)
    rows = v.filter_rows(
        sort_rows(db.items.values()),
        {
            "case_id": ("case_id", "str"),
            "storage_location_id": ("storage_location_id", "str"),
            "current_holder_id": ("current_holder_id", "str"),
            "custody_state": ("custody_state", "str"),
            "disposition_state": ("disposition_state", "str"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.item(r) for r in page], limit, offset, total)


@bp.post("/evidence-items/<item_id>/storage-assignment")
def assign_storage(item_id):
    principal = authorize(["EvidenceTechnician"])
    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    data = v.body()
    named_id = v.opt_str(data, "storage_location_id")

    named = None
    if named_id is not None:
        named = domain.find(db.locations, named_id, "ERR_STORAGE_LOCATION_NOT_FOUND")

    room = domain.room_of_item(item)
    domain.gate_locked_down(room)

    if item["custody_state"] != "LOGGED":
        raise ApiError("ERR_ITEM_CUSTODY_STATE_INVALID")

    if named is not None:
        if named["status"] != "OPEN":
            raise ApiError("ERR_LOCATION_SEALED")
        if named["category"] != item["required_storage_category"]:
            raise ApiError("ERR_STORAGE_CATEGORY_MISMATCH")
        if named["category"] == "REFRIGERATED" and (
            named["temperature_c"] is None or named["temperature_c"] > calc.REFRIGERATION_MAX_OK_C
        ):
            raise ApiError("ERR_REFRIGERATION_OUT_OF_RANGE")
        if named["occupied_slots"] >= named["capacity_slots"]:
            raise ApiError("ERR_STORAGE_LOCATION_FULL")
        location = named
    else:
        location = _autoselect(item, room)

    item["storage_location_id"] = location["id"]
    item["custody_state"] = "STORED"
    mark(item)
    domain.refresh_location(location)
    domain.append_chain_event(
        item,
        "STORAGE_ASSIGN",
        principal.role,
        principal.custodian_id,
        None,
        "Item assigned to storage location %s." % location["code"],
    )
    domain.refresh_room(room)
    return ok(ser.item(item))


def _autoselect(item, room):
    """calculations.storage_location_autoselect — tightest fitting bin."""
    pool = []
    for location in db.locations.values():
        if room is None or location["property_room_id"] != room["id"]:
            continue
        if location["status"] != "OPEN":
            continue
        if location["category"] != item["required_storage_category"]:
            continue
        if location["occupied_slots"] >= location["capacity_slots"]:
            continue
        if location["category"] == "REFRIGERATED" and (
            location["temperature_c"] is None
            or location["temperature_c"] > calc.REFRIGERATION_MAX_OK_C
        ):
            continue
        pool.append(location)
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_STORAGE")
    pool.sort(
        key=lambda l: (
            l["capacity_slots"] - l["occupied_slots"],
            l["capacity_slots"],
            l["created_at"],
            l["_seq"],
        )
    )
    return pool[0]


# --------------------------------------------------------------------------
# retention determinations
# --------------------------------------------------------------------------

@bp.post("/retention-determinations")
def create_determination():
    principal = authorize(["EvidenceTechnician", "PropertyRoomManager"])
    data = v.body()
    item_id = v.req_str(data, "evidence_item_id")
    basis = v.req_enum(data, "basis", RETENTION_BASES)
    expected_version = v.req_int(data, "expected_evidence_item_version")

    item = domain.find(db.items, item_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")
    room = domain.room_of_item(item)
    domain.gate_locked_down(room)

    if item["version"] != expected_version:
        raise ApiError("ERR_STALE_EVIDENCE_ITEM_VERSION")

    case = domain.case_of_item(item)
    statute = domain.statute_of_case(case)
    override = (
        item["disposition_state"] == "COURT_HOLD"
        or case["status"] == "APPEAL_PENDING"
        or statute["preservation_class"] in ("BIOLOGICAL_INDEFINITE", "HOMICIDE_PERMANENT")
    )
    if basis == "FINAL" and not override and case["status"] != "ADJUDICATED":
        raise ApiError("ERR_CASE_STATE_INVALID")

    determination = domain.create_determination(
        item, basis, principal.role, principal.custodian_id
    )
    return created(ser.determination(determination))


@bp.get("/retention-determinations/<determination_id>")
def get_determination(determination_id):
    authorize(DETERMINATION_READERS)
    row = domain.find(
        db.determinations, determination_id, "ERR_RETENTION_DETERMINATION_NOT_FOUND"
    )
    return ok(ser.determination(row))


@bp.get("/retention-determinations")
def list_determinations():
    authorize(DETERMINATION_READERS)
    rows = v.filter_rows(
        sort_rows(db.determinations.values()),
        {
            "evidence_item_id": ("evidence_item_id", "str"),
            "basis": ("basis", "str"),
            "superseded": ("superseded", "bool"),
        },
    )
    page, limit, offset, total = paginate(rows)
    return listed([ser.determination(r) for r in page], limit, offset, total)
