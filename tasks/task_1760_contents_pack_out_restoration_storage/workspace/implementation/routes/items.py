"""Item endpoints: register, read, list, triage."""

from flask import Blueprint, request

from db import store
from errors import (
    validation,
    not_found,
    invalid_transition,
    item_terminal,
    duplicate_barcode,
    stale_item_version,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    optional_string,
    optional_bool,
    optional_int,
    make_common_fields,
    get_room,
    get_item,
    touch,
    job_of_item,
    items_of_room,
)
from middleware import require_roles, parse_pagination, paginate
from response import success_object, success_list
from services.recompute import recompute_room, recompute_provisional_statements_for_job, recompute_job_accrued
from services.cascade import (
    release_active_placement,
    set_item_processing,
    ensure_disposal_record,
    void_open_disposal_record,
)

bp = Blueprint("items", __name__)

ITEM_CATEGORIES = {"TEXTILE", "ELECTRONICS", "FURNITURE", "DOCUMENT", "ARTWORK", "APPLIANCE", "GENERAL"}
TRIAGEABLE_STATUSES = {"REGISTERED", "AWAITING_CLEANING", "IN_STORAGE", "AWAITING_DISPOSAL"}
TERMINAL_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}


def serialize_item(item):
    return dict(item)


@bp.route("/api/rooms/<room_id>/items", methods=["POST"])
def create_item(room_id):
    user_id, role = require_roles("InventoryTechnician")
    body = get_body()
    barcode = require_string(body, "barcode")
    description = require_string(body, "description")
    item_category = require_enum(body, "item_category", ITEM_CATEGORIES)
    declared_value_cents = require_int(body, "declared_value_cents", min_v=0)
    volume_cu_ft = require_int(body, "volume_cu_ft", min_v=1)
    photo_ref = optional_string(body, "photo_ref")
    hazmat_flag = optional_bool(body, "hazmat_flag", default=False)
    smoke_damage_flag = optional_bool(body, "smoke_damage_flag", default=False)

    room = get_room(room_id)
    job = store.jobs.get(room["job_id"])
    if job is None:
        raise not_found("PackOutJob not found")
    if job["status"] == "CLOSED":
        raise invalid_transition("Job is CLOSED")

    # duplicate barcode within parent job
    room_ids = {r["id"] for r in store.rooms.values() if r["job_id"] == job["id"]}
    for existing in store.items.values():
        if existing["room_id"] in room_ids and existing["barcode"] == barcode:
            raise duplicate_barcode()

    item = make_common_fields()
    item.update({
        "room_id": room["id"],
        "barcode": barcode,
        "description": description,
        "item_category": item_category,
        "photo_ref": photo_ref,
        "declared_value_cents": declared_value_cents,
        "volume_cu_ft": volume_cu_ft,
        "hazmat_flag": hazmat_flag,
        "smoke_damage_flag": smoke_damage_flag,
        "condition_triage": "PENDING",
        "processing_status": "REGISTERED",
        "is_high_value": declared_value_cents >= 1000000,
        "triage_count": 0,
    })
    store.items[item["id"]] = item

    # First item auto-advances job INTAKE -> ACTIVE
    if job["status"] == "INTAKE":
        job["status"] = "ACTIVE"
        touch(job)

    recompute_room(room)
    touch(room)
    return success_object(serialize_item(item), status=201)


@bp.route("/api/items", methods=["GET"])
def list_items():
    user_id, role = require_roles(
        "ProjectManager", "InventoryTechnician", "BillingClerk", "ClaimsAdjuster"
    )
    limit, offset = parse_pagination()
    room_id = request.args.get("room_id")
    items = list(store.items.values())
    if room_id is not None:
        items = [i for i in items if i["room_id"] == room_id]
    page, total = paginate([serialize_item(i) for i in items], limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/items/<item_id>", methods=["GET"])
def read_item(item_id):
    user_id, role = require_roles(
        "ProjectManager", "InventoryTechnician", "BillingClerk", "ClaimsAdjuster"
    )
    item = get_item(item_id)
    return success_object(serialize_item(item))


@bp.route("/api/items/<item_id>/triage", methods=["POST"])
def triage_item(item_id):
    user_id, role = require_roles("InventoryTechnician")
    body = get_body()
    determination = require_enum(body, "determination", {"SALVAGEABLE", "NON_SALVAGEABLE"})
    expected_item_version = require_int(body, "expected_item_version")
    item = get_item(item_id)

    # Priority 7: terminal lockdown check
    if item["processing_status"] in TERMINAL_STATUSES:
        raise item_terminal()
    # Priority 6 OCC
    if expected_item_version != item["version"]:
        raise stale_item_version()
    # Priority 7: state-legality
    if item["processing_status"] not in TRIAGEABLE_STATUSES:
        raise invalid_transition(
            f"Triage not permitted from processing_status {item['processing_status']}"
        )

    item["condition_triage"] = determination
    item["triage_count"] += 1

    if determination == "SALVAGEABLE":
        if item["processing_status"] == "AWAITING_DISPOSAL":
            void_open_disposal_record(item)
        item["processing_status"] = "AWAITING_CLEANING"
        touch(item)
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)
    else:  # NON_SALVAGEABLE
        was_in_storage = item["processing_status"] == "IN_STORAGE"
        item["processing_status"] = "AWAITING_DISPOSAL"
        touch(item)
        ensure_disposal_record(item)
        if was_in_storage:
            release_active_placement(item, "DISPOSAL")
        else:
            job = job_of_item(item)
            if job is not None:
                recompute_provisional_statements_for_job(job["id"])
                recompute_job_accrued(job)
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)

    return success_object(serialize_item(item))
