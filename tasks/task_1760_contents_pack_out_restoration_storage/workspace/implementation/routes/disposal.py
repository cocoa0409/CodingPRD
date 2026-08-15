"""DisposalRecord endpoints: fetch by item, DOCUMENT/VERIFY transitions."""

from flask import Blueprint

from db import store, format_iso
from errors import (
    validation,
    invalid_transition,
    sod,
    hazmat_manifest_required,
)
from helpers import (
    get_body,
    require_enum,
    optional_string,
    make_common_fields,
    get_item,
    get_disposal_record,
    touch,
)
from middleware import require_roles
from response import success_object, success_list
from services.recompute import recompute_room

bp = Blueprint("disposal", __name__)

DISPOSAL_METHODS = {"LANDFILL", "RECYCLE", "HAZARDOUS_WASTE", "DONATION"}
DISPOSAL_ACTIONS = {"DOCUMENT", "VERIFY"}


def serialize_record(rec):
    return dict(rec)


@bp.route("/api/items/<item_id>/disposal-record", methods=["GET"])
def get_disposal_record_for_item(item_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician")
    item = get_item(item_id)
    recs = [r for r in store.disposal_records.values()
            if r["item_id"] == item["id"] and r["status"] != "VOIDED"]
    recs.sort(key=lambda r: r["created_at"])
    data = [serialize_record(r) for r in recs[:1]]
    # array of 0-1, no pagination meta fields required (it's a non-paginated list)
    from response import success
    return success(data, status=200, response_type="array")


@bp.route("/api/disposal-records/<rec_id>/transition", methods=["POST"])
def transition_disposal(rec_id):
    user_id, role = require_roles("InventoryTechnician", "ProjectManager")
    body = get_body()
    action = require_enum(body, "action", DISPOSAL_ACTIONS)
    rec = get_disposal_record(rec_id)
    item = store.items.get(rec["item_id"])

    if action == "DOCUMENT":
        if role != "InventoryTechnician":
            from errors import forbidden_role
            raise forbidden_role("DOCUMENT requires InventoryTechnician")
        if rec["status"] != "DRAFT":
            raise invalid_transition("DisposalRecord is not DRAFT")
        disposal_method = body.get("disposal_method")
        facility_name = body.get("facility_name")
        manifest_number = body.get("manifest_number")
        photo_ref = body.get("photo_ref")
        if disposal_method is None or facility_name is None:
            raise validation("disposal_method and facility_name are required at DOCUMENT")
        if disposal_method not in DISPOSAL_METHODS:
            raise validation("Invalid disposal_method")
        if not isinstance(facility_name, str) or facility_name == "":
            raise validation("facility_name must be a non-empty string")
        if manifest_number is not None and not isinstance(manifest_number, str):
            raise validation("manifest_number must be a string")
        if photo_ref is not None and not isinstance(photo_ref, str):
            raise validation("photo_ref must be a string")
        # hazmat gate
        if item is not None and item.get("hazmat_flag"):
            if manifest_number is None or disposal_method != "HAZARDOUS_WASTE":
                raise hazmat_manifest_required()
        rec["disposal_method"] = disposal_method
        rec["facility_name"] = facility_name
        if manifest_number is not None:
            rec["manifest_number"] = manifest_number
        if photo_ref is not None:
            rec["photo_ref"] = photo_ref
        rec["documented_by_user_id"] = user_id
        rec["documented_at"] = format_iso(store.now())
        rec["status"] = "DOCUMENTED"
        touch(rec)
        return success_object(serialize_record(rec))

    # VERIFY
    if role != "ProjectManager":
        from errors import forbidden_role
        raise forbidden_role("VERIFY requires ProjectManager")
    # SoD check: priority 3 (before existence-of-target-state? No — existence first at 5)
    # SoD is priority 3 — checked before state (7). But we need rec to exist (existence at 5).
    # SoD check uses documented_by_user_id — only meaningful when record is DOCUMENTED.
    # Order: auth -> SoD -> validation -> existence -> state. SoD first.
    if rec["status"] == "DOCUMENTED" and user_id == rec["documented_by_user_id"]:
        raise sod("Verifier must differ from documenter")
    if rec["status"] != "DOCUMENTED":
        raise invalid_transition("DisposalRecord is not DOCUMENTED")
    rec["verified_by_user_id"] = user_id
    rec["status"] = "VERIFIED"
    touch(rec)
    if item is not None:
        item["processing_status"] = "DISPOSED"
        touch(item)
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)
    return success_object(serialize_record(rec))
