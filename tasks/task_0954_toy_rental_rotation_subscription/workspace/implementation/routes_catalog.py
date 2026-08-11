"""Catalog item and physical copy routes."""
from datetime import timedelta

from flask import Blueprint

from domain import (
    SANITIZATION_MIN_HOURS,
    base_fields,
    by_seq,
    promote_for_copy,
    touch,
)
from envelope import ok_list, ok_object
from errors import domain as derr, invalid_state, not_found, validation
from serializers import (
    serialize_box_item,
    serialize_catalog_item,
    serialize_copy,
    serialize_wishlist_entry,
)
from store import DB, clock, clock_date
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
    query_filter,
)

bp = Blueprint("catalog", __name__)

STAGES = {"INFANT", "TODDLER", "PRESCHOOLER", "EARLY_SCHOOL"}
GRADES = {"NEW", "GOOD", "FAIR", "WORN"}


def _get_item(iid):
    it = DB.catalog_items.get(iid)
    if it is None:
        raise not_found("ERR_CATALOG_ITEM_NOT_FOUND", "CatalogItem id does not exist.")
    return it


def _get_copy(cid):
    c = DB.copies.get(cid)
    if c is None:
        raise not_found("ERR_COPY_NOT_FOUND", "ToyCopy id does not exist.")
    return c


@bp.post("/toy-rental/catalog-items")
def create_catalog_item():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = body()
    shape = parse_fields(data, [
        F("title", True, "str"),
        F("description", False, "str"),
        F("min_age_months", True, "int", min=0),
        F("max_age_months", True, "int", min=0),
        F("developmental_stages", True, "enum_array", values=STAGES),
        F("piece_count", True, "int", min=1),
        F("retail_value_cents", True, "int", min=1),
        F("replacement_value_cents", True, "int", min=1),
    ])
    if (
        "min_age_months" in shape.values
        and "max_age_months" in shape.values
        and shape.values["min_age_months"] > shape.values["max_age_months"]
    ):
        shape.ok = False
    finalize_shape(shape)
    it = base_fields()
    it.update({
        "title": shape.values["title"],
        "description": shape.values.get("description", ""),
        "min_age_months": shape.values["min_age_months"],
        "max_age_months": shape.values["max_age_months"],
        "developmental_stages": list(shape.values["developmental_stages"]),
        "piece_count": shape.values["piece_count"],
        "retail_value_cents": shape.values["retail_value_cents"],
        "replacement_value_cents": shape.values["replacement_value_cents"],
        "status": "ACTIVE",
    })
    DB.catalog_items[it["id"]] = it
    return ok_object(serialize_catalog_item(it), status=201)


@bp.get("/toy-rental/catalog-items")
def list_catalog_items():
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager", "PlatformAdmin"})
    items = list(DB.catalog_items.values())
    status = query_filter("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    stage = query_filter("developmental_stage")
    if stage is not None:
        items = [i for i in items if stage in i["developmental_stages"]]
    child_id = query_filter("child_id")
    if child_id is not None:
        child = DB.children.get(child_id)
        if child is None:
            raise validation("child_id does not reference an existing child profile.")
        # Rolling 30-day variant: suggestion filter only.
        rolling_age = max(0, (clock_date() - child["birthdate"]).days) // 30
        items = [
            i for i in items
            if i["min_age_months"] <= rolling_age <= i["max_age_months"]
        ]
    items = by_seq(items)
    page, meta = paginate(items)
    return ok_list([serialize_catalog_item(i) for i in page], meta)


@bp.get("/toy-rental/catalog-items/<iid>")
def get_catalog_item(iid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager", "PlatformAdmin"})
    it = _get_item(iid)
    return ok_object(serialize_catalog_item(it))


@bp.post("/toy-rental/catalog-items/<iid>/retire")
def retire_catalog_item(iid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    it = _get_item(iid)
    if it["status"] != "ACTIVE":
        raise invalid_state("Catalog item is not ACTIVE.")
    it["status"] = "RETIRED"
    touch(it)
    return ok_object(serialize_catalog_item(it))


@bp.post("/toy-rental/catalog-items/<iid>/copies")
def create_copy(iid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    it = _get_item(iid)
    data = body()
    shape = parse_fields(data, [
        F("barcode", True, "str"),
        F("condition_grade", False, "enum", values=GRADES),
    ])
    barcode = shape.values.get("barcode")
    if isinstance(barcode, str):
        for c in DB.copies.values():
            if c["barcode"] == barcode:
                raise validation("A copy with this barcode already exists.")
    finalize_shape(shape)
    c = base_fields()
    c.update({
        "catalog_item_id": iid,
        "barcode": barcode,
        "condition_grade": shape.values.get("condition_grade", "NEW"),
        "status": "AVAILABLE",
        "reserved_member_id": None,
        "sanitization_started_at": None,
        "last_sanitized_at": None,
        "sanitization_cycle_count": 0,
    })
    DB.copies[c["id"]] = c
    return ok_object(serialize_copy(c), status=201)


@bp.get("/toy-rental/catalog-items/<iid>/copies")
def list_item_copies(iid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "PlatformAdmin"})
    it = _get_item(iid)
    status = query_filter("status")
    copies = [c for c in DB.copies.values() if c["catalog_item_id"] == iid]
    if status is not None:
        copies = [c for c in copies if c["status"] == status]
    copies = by_seq(copies)
    page, meta = paginate(copies)
    return ok_list([serialize_copy(c) for c in page], meta)


@bp.get("/toy-rental/catalog-items/<iid>/wishlist-entries")
def list_item_wishlist(iid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager", "PlatformAdmin"})
    it = _get_item(iid)
    status = query_filter("status")
    entries = [e for e in DB.wishlist_entries.values() if e["catalog_item_id"] == iid]
    if status is not None:
        entries = [e for e in entries if e["status"] == status]
    entries = by_seq(entries)
    page, meta = paginate(entries)
    return ok_list([serialize_wishlist_entry(e) for e in page], meta)


@bp.get("/toy-rental/copies/<cid>")
def get_copy(cid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager", "PlatformAdmin"})
    c = _get_copy(cid)
    return ok_object(serialize_copy(c))


@bp.post("/toy-rental/copies/<cid>/complete-sanitization")
def complete_sanitization(cid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    c = _get_copy(cid)
    if c["status"] != "SANITIZING":
        raise invalid_state("Copy is not SANITIZING.")
    if clock() < c["sanitization_started_at"] + timedelta(hours=SANITIZATION_MIN_HOURS):
        raise derr("ERR_SANITIZATION_BUFFER_ACTIVE", 422,
                   "The mandatory 24-hour sanitization buffer is still active.")
    c["status"] = "AVAILABLE"
    c["last_sanitized_at"] = clock()
    c["sanitization_cycle_count"] += 1
    touch(c)
    promote_for_copy(c)
    return ok_object(serialize_copy(c))


@bp.post("/toy-rental/copies/<cid>/retire")
def retire_copy(cid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    c = _get_copy(cid)
    if c["status"] not in ("AVAILABLE", "QUARANTINED"):
        raise invalid_state("Copy is not AVAILABLE or QUARANTINED.")
    c["status"] = "RETIRED"
    touch(c)
    return ok_object(serialize_copy(c))


@bp.get("/toy-rental/copies/<cid>/wishlist-entries")
def list_copy_holds(cid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    c = _get_copy(cid)
    entries = by_seq([
        e for e in DB.wishlist_entries.values() if e["held_copy_id"] == cid
    ])
    page, meta = paginate(entries)
    return ok_list([serialize_wishlist_entry(e) for e in page], meta)


@bp.get("/toy-rental/copies/<cid>/box-items")
def list_copy_box_items(cid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    c = _get_copy(cid)
    items = by_seq([
        it for it in DB.box_items.values() if it["toy_copy_id"] == cid
    ])
    page, meta = paginate(items)
    return ok_list([serialize_box_item(it) for it in page], meta)
