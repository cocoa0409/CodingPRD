"""Rotation box routes: read, item add, ship, initiate-return, shipments,
inspect, close, box fees."""
from datetime import timedelta

from flask import Blueprint

from domain import (
    GRADE_ORDER,
    age_gate_passes,
    base_fields,
    by_seq,
    create_fee,
    inspection_components,
    member_of_box,
    release_reserved_copy,
    sanitization_valid,
    touch,
)
from envelope import ok_list, ok_object
from errors import domain as derr, invalid_state, not_found, stale_version, validation
from serializers import (
    serialize_box,
    serialize_box_item,
    serialize_fee,
    serialize_shipment,
)
from store import DB, clock
from timestamps import parse_datetime
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
    require_ownership,
)

bp = Blueprint("boxes", __name__)


def _get_box(bid):
    b = DB.boxes.get(bid)
    if b is None:
        raise not_found("ERR_BOX_NOT_FOUND", "RotationBox id does not exist.")
    return b


def _get_copy(cid):
    c = DB.copies.get(cid)
    if c is None:
        raise not_found("ERR_COPY_NOT_FOUND", "ToyCopy id does not exist.")
    return c


def _slotted_count(box_id):
    return sum(
        1 for it in DB.box_items.values()
        if it["rotation_box_id"] == box_id and it["loan_status"] == "PENDING_RETURN"
    )


@bp.get("/toy-rental/rotation-boxes/<bid>")
def get_box(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    b = _get_box(bid)
    require_ownership(role, uid, member_of_box(b))
    return ok_object(serialize_box(b))


@bp.post("/toy-rental/rotation-boxes/<bid>/items")
def add_box_item(bid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = _get_box(bid)
    data = body()
    shape = parse_fields(data, [
        F("toy_copy_id", True, "str"),
        F("expected_rotation_box_version", True, "int"),
    ])
    copy_id = shape.values.get("toy_copy_id")
    copy = DB.copies.get(copy_id) if isinstance(copy_id, str) else None
    if isinstance(copy_id, str) and copy is None:
        raise not_found("ERR_COPY_NOT_FOUND", "ToyCopy id does not exist.")
    owner = member_of_box(b)
    require_ownership(role, uid, owner)
    m = DB.members.get(owner)
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    if b["status"] != "PLANNED":
        raise invalid_state("Rotation box is not PLANNED.")
    expected = shape.values.get("expected_rotation_box_version")
    if isinstance(expected, int) and expected != b["version"]:
        raise stale_version()
    if copy is not None:
        available = copy["status"] == "AVAILABLE"
        self_reserved = (
            copy["status"] == "RESERVED" and copy["reserved_member_id"] == owner
        )
        if not (available or self_reserved):
            raise derr("ERR_COPY_NOT_AVAILABLE", 409,
                       "Copy is not AVAILABLE or RESERVED to this member.")
        cat = DB.catalog_items.get(copy["catalog_item_id"])
        if cat is not None and not age_gate_passes(owner, cat):
            raise derr("ERR_AGE_INCOMPATIBLE", 422,
                       "No child of the member passes the age gate for this toy.")
        if not sanitization_valid(copy):
            raise derr("ERR_NEEDS_RESANITIZATION", 422,
                       "Copy sanitization is stale.")
    if _slotted_count(b["id"]) >= b["plan_snapshot"]["toys_per_box"]:
        raise derr("ERR_SLOT_CAPACITY_EXCEEDED", 422,
                   "The box already holds its maximum number of items.")
    finalize_shape(shape)
    it = base_fields()
    it.update({
        "rotation_box_id": b["id"],
        "toy_copy_id": copy_id,
        "swapped_from_item_id": None,
        "loan_status": "PENDING_RETURN",
        "resolution_status": "NONE",
        "condition_returned": None,
        "damage_severity": None,
        "missing_piece_count": 0,
        "buyout_price_cents": None,
        "wallet_applied_cents": None,
        "net_charge_cents": None,
    })
    DB.box_items[it["id"]] = it
    if copy["status"] != "RESERVED" or copy["reserved_member_id"] != owner:
        copy["status"] = "RESERVED"
        copy["reserved_member_id"] = owner
    touch(copy)
    touch(b)
    return ok_object(serialize_box_item(it), status=201)


@bp.get("/toy-rental/rotation-boxes/<bid>/items")
def list_box_items(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    b = _get_box(bid)
    require_ownership(role, uid, member_of_box(b))
    items = by_seq([it for it in DB.box_items.values() if it["rotation_box_id"] == bid])
    page, meta = paginate(items)
    return ok_list([serialize_box_item(it) for it in page], meta)


@bp.post("/toy-rental/rotation-boxes/<bid>/ship")
def ship_box(bid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = _get_box(bid)
    if b["status"] != "PLANNED":
        raise invalid_state("Rotation box is not PLANNED.")
    data = body()
    shape = parse_fields(data, [
        F("carrier", True, "str"),
        F("tracking_number", True, "str"),
    ])
    if _slotted_count(b["id"]) < 1:
        raise derr("ERR_BOX_EMPTY", 422, "The box holds no slotted items.")
    finalize_shape(shape)
    sh = base_fields()
    sh.update({
        "rotation_box_id": b["id"],
        "direction": "OUTBOUND",
        "carrier": shape.values["carrier"],
        "tracking_number": shape.values["tracking_number"],
        "status": "LABEL_CREATED",
        "events": [],
    })
    DB.shipments[sh["id"]] = sh
    b["status"] = "SHIPPED"
    touch(b)
    for it in DB.box_items.values():
        if it["rotation_box_id"] == b["id"] and it["loan_status"] == "PENDING_RETURN":
            copy = DB.copies.get(it["toy_copy_id"])
            if copy is not None and copy["status"] == "RESERVED":
                copy["status"] = "OUT_ON_LOAN"
                copy["reserved_member_id"] = None
                touch(copy)
    return ok_object(serialize_shipment(sh), status=201)


@bp.post("/toy-rental/rotation-boxes/<bid>/initiate-return")
def initiate_return(bid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    b = _get_box(bid)
    require_ownership(role, uid, member_of_box(b))
    if b["status"] != "DELIVERED":
        raise invalid_state("Rotation box is not DELIVERED.")
    data = body()
    shape = parse_fields(data, [
        F("carrier", True, "str"),
        F("tracking_number", True, "str"),
    ])
    finalize_shape(shape)
    sh = base_fields()
    sh.update({
        "rotation_box_id": b["id"],
        "direction": "RETURN",
        "carrier": shape.values["carrier"],
        "tracking_number": shape.values["tracking_number"],
        "status": "LABEL_CREATED",
        "events": [],
    })
    DB.shipments[sh["id"]] = sh
    b["status"] = "RETURNING"
    touch(b)
    return ok_object(serialize_shipment(sh), status=201)


@bp.get("/toy-rental/rotation-boxes/<bid>/shipments")
def list_box_shipments(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    b = _get_box(bid)
    require_ownership(role, uid, member_of_box(b))
    shipments = by_seq([s for s in DB.shipments.values() if s["rotation_box_id"] == bid])
    page, meta = paginate(shipments)
    return ok_list([serialize_shipment(s) for s in page], meta)


INSPECT_CONDITIONS = {"GOOD", "FAIR", "WORN"}
INSPECT_SEVERITIES = {"NONE", "MINOR", "MODERATE", "SEVERE"}
INSPECT_DISPOSITIONS = {"RESTOCK", "QUARANTINE"}


@bp.post("/toy-rental/rotation-boxes/<bid>/inspect")
def inspect_box(bid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = _get_box(bid)
    if b["status"] not in ("RECEIVED", "INSPECTED"):
        raise invalid_state("Rotation box is not RECEIVED or INSPECTED.")
    data = body()
    records = data.get("items")
    if set(data.keys()) - {"items"}:
        raise validation("Unknown request field.")
    if not isinstance(records, list):
        raise validation("items must be an array.")
    parsed = []
    for rec in records:
        if not isinstance(rec, dict):
            raise validation("Each items entry must be an object.")
        if set(rec.keys()) - {
            "box_item_id", "condition_returned", "damage_severity",
            "missing_piece_count", "disposition",
        }:
            raise validation("Unknown inspection field.")
        item_id = rec.get("box_item_id")
        cond = rec.get("condition_returned")
        sev = rec.get("damage_severity")
        missing = rec.get("missing_piece_count")
        disp = rec.get("disposition")
        if not isinstance(item_id, str):
            raise validation("box_item_id is required.")
        item = DB.box_items.get(item_id)
        if item is None:
            raise not_found("ERR_BOX_ITEM_NOT_FOUND", "BoxItem id does not exist.")
        if item["rotation_box_id"] != b["id"]:
            raise validation("box_item_id does not belong to this box.")
        if cond not in INSPECT_CONDITIONS:
            raise validation("condition_returned out of range.")
        if sev not in INSPECT_SEVERITIES:
            raise validation("damage_severity out of range.")
        if not isinstance(missing, int) or isinstance(missing, bool) or missing < 0:
            raise validation("missing_piece_count must be a non-negative integer.")
        if disp not in INSPECT_DISPOSITIONS:
            raise validation("disposition out of range.")
        if item["loan_status"] != "PENDING_RETURN":
            raise invalid_state("Box item has already been inspected or resolved.")
        parsed.append((item, cond, sev, missing, disp))

    sub = DB.subscriptions.get(b["subscription_id"])
    for item, cond, sev, missing, disp in parsed:
        copy = DB.copies.get(item["toy_copy_id"])
        cat = DB.catalog_items.get(copy["catalog_item_id"]) if copy else None
        item["loan_status"] = "RETURNED"
        item["condition_returned"] = cond
        item["damage_severity"] = sev
        item["missing_piece_count"] = missing
        fees_created = 0
        if cat is not None:
            damage_c, missing_c = inspection_components(cat, sev, missing)
            if damage_c > 0:
                create_fee(sub["id"], item["id"], b["id"], "DAMAGE", damage_c)
                fees_created += 1
            if missing_c > 0:
                create_fee(sub["id"], item["id"], b["id"], "MISSING_PIECES", missing_c)
                fees_created += 1
        item["resolution_status"] = "FEE_ASSESSED" if fees_created else "RESOLVED"
        touch(item)
        if copy is not None:
            if disp == "RESTOCK":
                copy["status"] = "SANITIZING"
                copy["sanitization_started_at"] = clock()
                if GRADE_ORDER[cond] > GRADE_ORDER[copy["condition_grade"]]:
                    copy["condition_grade"] = cond
            else:
                copy["status"] = "QUARANTINED"
            touch(copy)
    remaining = any(
        it["loan_status"] == "PENDING_RETURN"
        for it in DB.box_items.values()
        if it["rotation_box_id"] == b["id"]
    )
    if b["status"] == "RECEIVED" and not remaining:
        b["status"] = "INSPECTED"
    touch(b)
    return ok_object(serialize_box(b))


@bp.post("/toy-rental/rotation-boxes/<bid>/close")
def close_box(bid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    b = _get_box(bid)
    if b["status"] != "INSPECTED":
        raise invalid_state("Rotation box is not INSPECTED.")
    for f in DB.fees.values():
        if f["rotation_box_id"] == bid and f["status"] not in ("PAID", "WAIVED"):
            raise derr("ERR_FEES_OUTSTANDING", 422,
                       "Fees tied to this box are still outstanding.")
    b["status"] = "CLOSED"
    touch(b)
    sub = DB.subscriptions.get(b["subscription_id"])
    if sub is not None:
        sub["next_cycle_due_at"] = clock() + timedelta(
            days=b["plan_snapshot"]["rotation_cadence_days"])
        touch(sub)
    return ok_object(serialize_box(b))


@bp.get("/toy-rental/rotation-boxes/<bid>/fees")
def list_box_fees(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService", "OperationsManager"})
    b = _get_box(bid)
    require_ownership(role, uid, member_of_box(b))
    fees = by_seq([f for f in DB.fees.values() if f["rotation_box_id"] == bid])
    page, meta = paginate(fees)
    return ok_list([serialize_fee(f) for f in page], meta)
