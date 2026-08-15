"""Collection kit + custody event endpoints."""
from flask import Blueprint, request

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_enum,
    validate_string,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import kit_out, custody_event_out
from services.common import make_record, make_audit_record, get_or_404, touch

bp = Blueprint("kits", __name__)

KIT_TYPES = {"BLOOD", "SALIVA", "TISSUE"}


def append_custody_event(kit, event_type, actor_user_id, location=None, note=None):
    return make_audit_record(db.custody_events, {
        "kit_id": kit["id"],
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "location": location,
        "note": note,
    })


@bp.route("/biobank/collection-kits", methods=["POST"])
def create_kit():
    require_roles({"ConsentCoordinator"})
    body = get_json_body()
    check_known_fields(body, {"kit_type", "expires_at"})
    require_fields(body, ["kit_type", "expires_at"])
    kit_type = validate_enum(body["kit_type"], KIT_TYPES, "kit_type")
    expires_at = parse_iso8601(body["expires_at"], "expires_at")
    kit = make_record(db.collection_kits, {
        "kit_type": kit_type,
        "donor_id": None,
        "expires_at": expires_at,
        "status": "IN_STOCK",
        "distributed_at": None,
        "returned_at": None,
    })
    return success_object(kit_out(kit), status=201)


@bp.route("/biobank/collection-kits", methods=["GET"])
def list_kits():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.collection_kits.values())
    donor_id = request.args.get("donor_id")
    status = request.args.get("status")
    if donor_id is not None:
        items = [k for k in items if k["donor_id"] == donor_id]
    if status is not None:
        items = [k for k in items if k["status"] == status]
    items.sort(key=lambda k: k["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([kit_out(k) for k in page], limit, offset, total)


@bp.route("/biobank/collection-kits/<kitId>", methods=["GET"])
def get_kit(kitId):
    require_roles(ALL_ROLES)
    kit = get_or_404(db.collection_kits, kitId, "collection kit")
    return success_object(kit_out(kit))


@bp.route("/biobank/collection-kits/<kitId>/distribute", methods=["POST"])
def distribute_kit(kitId):
    user_id, _ = require_roles({"ConsentCoordinator"})
    kit = get_or_404(db.collection_kits, kitId, "collection kit")
    body = get_json_body()
    check_known_fields(body, {"donor_id", "location", "note"})
    require_fields(body, ["donor_id"])
    donor_id = validate_string(body["donor_id"], "donor_id")
    location = body.get("location")
    note = body.get("note")
    if location is not None and not isinstance(location, str):
        raise_error("ERR_INVALID_REQUEST", "location must be a string or null")
    if note is not None and not isinstance(note, str):
        raise_error("ERR_INVALID_REQUEST", "note must be a string or null")
    # State check precedes the expiry check.
    if kit["status"] != "IN_STOCK":
        raise_error("ERR_KIT_NOT_DISTRIBUTABLE", "Kit is not IN_STOCK")
    if now() >= kit["expires_at"]:
        raise_error("ERR_KIT_EXPIRED", "Kit is expired")
    donor = db.donors.get(donor_id)
    if donor is None:
        raise_error("ERR_NOT_FOUND", f"donor not found: {donor_id}")
    kit["status"] = "DISTRIBUTED"
    kit["donor_id"] = donor_id
    kit["distributed_at"] = now()
    touch(kit)
    append_custody_event(kit, "DISTRIBUTED", user_id, location, note)
    return success_object(kit_out(kit))


@bp.route("/biobank/collection-kits/<kitId>/receive-return", methods=["POST"])
def receive_return_kit(kitId):
    user_id, _ = require_roles({"ConsentCoordinator"})
    kit = get_or_404(db.collection_kits, kitId, "collection kit")
    body = get_json_body()
    check_known_fields(body, {"location", "note"})
    location = body.get("location")
    note = body.get("note")
    if location is not None and not isinstance(location, str):
        raise_error("ERR_INVALID_REQUEST", "location must be a string or null")
    if note is not None and not isinstance(note, str):
        raise_error("ERR_INVALID_REQUEST", "note must be a string or null")
    if kit["status"] != "DISTRIBUTED":
        raise_error("ERR_KIT_NOT_RETURNED", "Kit is not DISTRIBUTED")
    if now() >= kit["expires_at"]:
        raise_error("ERR_KIT_EXPIRED", "Kit is expired")
    kit["status"] = "RETURNED"
    kit["returned_at"] = now()
    touch(kit)
    append_custody_event(kit, "RETURNED", user_id, location, note)
    return success_object(kit_out(kit))


@bp.route("/biobank/collection-kits/<id>/custody-events", methods=["GET"])
def list_custody_events(id):
    require_roles(ALL_ROLES)
    kit = get_or_404(db.collection_kits, id, "collection kit")
    limit, offset = parse_pagination()
    items = [e for e in db.custody_events.values() if e["kit_id"] == kit["id"]]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([custody_event_out(e) for e in page], limit, offset, total)
